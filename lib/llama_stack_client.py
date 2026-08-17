"""Llama Stack client — OpenAI-compatible wrapper for Files, Vector Stores, and Search.

All document ingestion and vector search operations go through this module.
Uses the OpenAI Python SDK pointing at a Llama Stack server (RHOAI 3.4).

Vector storage uses pgvector (PostgreSQL) as the backend.  Because the
embedding model does not support matryoshka representation, ingestion uses
a direct pipeline: chunk locally, embed via ``/embeddings`` (no ``dimensions``
parameter), then insert via ``/v1/vector-io/insert``.
"""

import logging
import os
import time
import uuid
from typing import Any, Callable

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

logger = logging.getLogger(__name__)

LLAMA_STACK_URL = os.getenv("LLAMA_STACK_URL", "http://localhost:8321/v1")
LLAMA_STACK_API_KEY = os.getenv("LLAMA_STACK_API_KEY", "not-needed")
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Return a singleton OpenAI client pointing at the Llama Stack server."""
    global _client
    if _client is None:
        http_client = None if _VERIFY_SSL else httpx.Client(verify=False, timeout=httpx.Timeout(300.0))
        _client = OpenAI(
            base_url=LLAMA_STACK_URL,
            api_key=LLAMA_STACK_API_KEY,
            http_client=http_client,
            max_retries=2,
            timeout=120.0,
        )
        logger.info("Llama Stack client initialized: %s", LLAMA_STACK_URL)
    return _client


def _discover_embedding_model() -> tuple[str, int]:
    """Auto-discover the first available embedding model and its dimension."""
    client = get_client()
    try:
        models = client.models.list()
        for m in models:
            meta = getattr(m, "custom_metadata", None) or {}
            if isinstance(meta, dict) and meta.get("model_type") == "embedding":
                dim = meta.get("embedding_dimension", 768)
                logger.info("Discovered embedding model: %s (dim=%d)", m.id, dim)
                return m.id, dim
    except Exception as e:
        logger.warning("Model discovery failed: %s — using defaults", e)
    default_model = os.getenv("EMBEDDING_MODEL", "granite-embedding-278m-multilingual")
    default_dim = int(os.getenv("EMBEDDING_DIMENSION", "768"))
    return default_model, default_dim


_embedding_model: str | None = None
_embedding_dimension: int | None = None


def _get_embedding_config() -> tuple[str, int]:
    """Get embedding model and dimension (cached after first call)."""
    global _embedding_model, _embedding_dimension
    if _embedding_model is None:
        _embedding_model, _embedding_dimension = _discover_embedding_model()
    return _embedding_model, _embedding_dimension


def upload_file(file_path: str, filename: str | None = None) -> str:
    """Upload a file to Llama Stack Files API. Returns the file_id.

    Args:
        file_path: Local path to the file to upload.
        filename: Display name to register with Llama Stack.
                  Defaults to os.path.basename(file_path).
    """
    client = get_client()
    display_name = filename or os.path.basename(file_path)
    with open(file_path, "rb") as f:
        file_obj = client.files.create(
            file=(display_name, f),
            purpose="assistants",
        )
    logger.info("Uploaded file %s -> %s", display_name, file_obj.id)
    return file_obj.id


def ensure_vector_store(name: str = "research-docs") -> str:
    """Create or retrieve a vector store by name. Returns vector_store_id."""
    client = get_client()
    stores = client.vector_stores.list()
    for store in stores.data:
        if store.name == name:
            logger.info("Found existing vector store: %s (%s)", name, store.id)
            return store.id

    embedding_model, embedding_dimension = _get_embedding_config()
    store = client.vector_stores.create(
        name=name,
        extra_body={
            "embedding_model": embedding_model,
            "embedding_dimension": embedding_dimension,
        },
    )
    logger.info("Created vector store: %s (%s)", name, store.id)
    return store.id


def _recreate_vector_store(old_id: str, name: str = "research-docs") -> str | None:
    """Delete a broken vector store and create a fresh one.

    Returns the new vector_store_id, or None on failure.
    """
    client = get_client()
    try:
        client.vector_stores.delete(old_id)
        logger.info("Deleted broken vector store %s", old_id)
    except Exception:
        logger.warning("Could not delete vector store %s (may already be gone)", old_id)

    try:
        embedding_model, embedding_dimension = _get_embedding_config()
        store = client.vector_stores.create(
            name=name,
            extra_body={
                "embedding_model": embedding_model,
                "embedding_dimension": embedding_dimension,
            },
        )
        logger.info("Recreated vector store: %s (%s)", name, store.id)
        return store.id
    except Exception:
        logger.exception("Failed to recreate vector store")
        return None


def _chunk_text(text: str, max_tokens: int = 800, overlap_tokens: int = 100) -> list[str]:
    """Split text into overlapping chunks sized by approximate token count.

    Uses a simple heuristic of ~4 characters per token.
    """
    chars_per_token = 4
    max_chars = max_tokens * chars_per_token
    overlap_chars = overlap_tokens * chars_per_token

    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end < len(text):
            for sep in ["\n\n", "\n", ". ", " "]:
                boundary = text.rfind(sep, start + max_chars // 2, end)
                if boundary > start:
                    end = boundary + len(sep)
                    break
        chunks.append(text[start:end].strip())
        start = end - overlap_chars
    return [c for c in chunks if c]


def _get_embeddings(
    texts: list[str],
    batch_size: int = 3,
    on_progress: Callable[[int, int], None] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> list[list[float]]:
    """Generate embeddings via the Llama Stack ``/embeddings`` endpoint.

    Calls the endpoint directly via httpx WITHOUT the ``dimensions`` parameter,
    which avoids the matryoshka error.  If a request returns 504 (embedding
    model pod cold-starting behind the OpenShift route timeout), retries
    automatically once the pod is ready.

    *on_progress(current, total)* is called after each successful batch.
    *on_status(message)* is called to report non-progress state changes
    (e.g. cold-start waiting).
    """
    base_url = LLAMA_STACK_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {LLAMA_STACK_API_KEY}", "Content-Type": "application/json"}
    model, _ = _get_embedding_config()
    all_embeddings: list[list[float]] = []
    total = len(texts)
    t0 = time.time()
    max_retries = 12

    def _post(payload: dict) -> httpx.Response:
        return httpx.post(
            f"{base_url}/embeddings",
            json=payload,
            headers=headers,
            verify=_VERIFY_SSL,
            timeout=120,
        )

    def _wait_for_model(payload: dict) -> httpx.Response:
        """Retry on 504 until the embedding model pod is ready."""
        for attempt in range(1, max_retries + 1):
            msg = f"Waiting for embedding model to start... ({attempt}/{max_retries})"
            logger.info(msg)
            if on_status:
                on_status(msg)
            time.sleep(10)
            resp = _post(payload)
            if resp.status_code != 504:
                return resp
            logger.info("Still 504 after attempt %d/%d", attempt, max_retries)
        return resp  # last 504 — will be raised below

    for i in range(0, total, batch_size):
        batch = texts[i : i + batch_size]
        payload = {"model": model, "input": batch}
        batch_t0 = time.time()

        resp = _post(payload)

        if resp.status_code == 504:
            logger.info("Embedding model cold start detected (504)")
            resp = _wait_for_model(payload)

        if resp.status_code == 400 and len(batch) > 1:
            logger.warning(
                "Batch of %d rejected (400) — retrying one at a time. Body: %s",
                len(batch), resp.text[:300],
            )
            for single in batch:
                single_resp = _post({"model": model, "input": [single]})
                if single_resp.status_code == 504:
                    single_resp = _wait_for_model({"model": model, "input": [single]})
                single_resp.raise_for_status()
                single_data = single_resp.json()["data"]
                all_embeddings.append(single_data[0]["embedding"])
            done = min(i + batch_size, total)
            batch_elapsed = time.time() - batch_t0
            if on_progress:
                on_progress(done, total)
            logger.info(
                "Embedding progress: %d/%d chunks (fallback 1-by-1 in %.1fs)",
                done, total, batch_elapsed,
            )
            continue

        if resp.status_code != 200:
            logger.error("Embedding failed (%d): %s", resp.status_code, resp.text[:300])
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        all_embeddings.extend(d["embedding"] for d in data)

        done = min(i + batch_size, total)
        batch_elapsed = time.time() - batch_t0
        if on_progress:
            on_progress(done, total)
        logger.info(
            "Embedding progress: %d/%d chunks (batch of %d in %.1fs)",
            done, total, len(batch), batch_elapsed,
        )

    total_elapsed = time.time() - t0
    logger.info("Embedding complete: %d chunks in %.1fs (%.1fs/chunk avg)",
                total, total_elapsed, total_elapsed / max(total, 1))
    return all_embeddings


def _ingest_direct(
    vector_store_id: str,
    file_id: str,
    content: str,
    filename: str,
    max_chunk_size_tokens: int = 800,
    chunk_overlap_tokens: int = 100,
    on_progress: Callable[[int, int], None] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> dict:
    """Fallback ingestion: chunk locally, embed via Llama Stack, insert via vector-io/insert."""
    model, dimension = _get_embedding_config()
    chunks = _chunk_text(content, max_chunk_size_tokens, chunk_overlap_tokens)
    if not chunks:
        logger.warning("No chunks produced for file %s", file_id)
        return {"id": file_id, "status": "failed", "file_id": file_id}

    logger.info("Direct ingestion for %s: %d chunks", filename, len(chunks))

    embeddings = _get_embeddings(chunks, on_progress=on_progress, on_status=on_status)

    insert_chunks = [
        {
            "chunk_id": str(uuid.uuid4()),
            "content": f"[source: {filename} | chunk: {idx}]\n{text}",
            "chunk_metadata": {
                "document_id": file_id,
                "filename": filename,
                "chunk_index": idx,
            },
            "embedding": emb,
            "embedding_model": model,
            "embedding_dimension": dimension,
        }
        for idx, (text, emb) in enumerate(zip(chunks, embeddings))
    ]

    base_url = LLAMA_STACK_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {LLAMA_STACK_API_KEY}", "Content-Type": "application/json"}

    batch_size = 20
    for i in range(0, len(insert_chunks), batch_size):
        batch = insert_chunks[i : i + batch_size]
        resp = httpx.post(
            f"{base_url}/vector-io/insert",
            json={"vector_store_id": vector_store_id, "chunks": batch},
            headers=headers,
            verify=_VERIFY_SSL,
            timeout=120,
        )
        if resp.status_code == 404:
            logger.warning("vector-io/insert 404 for store %s — recreating and retrying", vector_store_id)
            new_vs_id = _recreate_vector_store(vector_store_id)
            if not new_vs_id:
                return {"id": file_id, "status": "failed", "file_id": file_id}
            vector_store_id = new_vs_id
            for b in insert_chunks:
                b.setdefault("chunk_metadata", {})
            resp = httpx.post(
                f"{base_url}/vector-io/insert",
                json={"vector_store_id": vector_store_id, "chunks": batch},
                headers=headers,
                verify=_VERIFY_SSL,
                timeout=120,
            )
        if resp.status_code not in (200, 204):
            logger.error("vector-io/insert failed (batch %d): %s", i, resp.text[:300])
            return {"id": file_id, "status": "failed", "file_id": file_id}

    logger.info("Direct ingestion completed: %d chunks inserted for %s", len(chunks), filename)
    return {"id": file_id, "status": "completed", "file_id": file_id}


def ingest_file(
    vector_store_id: str,
    file_id: str,
    max_chunk_size_tokens: int = 800,
    chunk_overlap_tokens: int = 100,
    content: str = "",
    filename: str = "",
    on_progress: Callable[[int, int], None] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> dict:
    """Add a file to a vector store using the direct embedding pipeline.

    Chunks content locally, embeds via ``/embeddings`` (bypassing the
    matryoshka-incompatible ``dimensions`` parameter), and inserts via
    ``/v1/vector-io/insert``.

    The standard ``vector_stores.files.create`` path is intentionally skipped
    because the current embedding model does not support matryoshka
    representation, causing that API to always fail and potentially corrupt
    the vector store's internal state.
    """
    if not content:
        logger.warning("ingest_file called without content for %s — cannot proceed", file_id)
        return {"id": file_id, "status": "failed", "file_id": file_id}

    logger.info("Ingesting file %s into vector store %s (direct pipeline)", file_id, vector_store_id)
    return _ingest_direct(
        vector_store_id, file_id, content,
        filename or file_id,
        max_chunk_size_tokens, chunk_overlap_tokens,
        on_progress=on_progress, on_status=on_status,
    )


def search(
    vector_store_id: str,
    query: str,
    max_results: int = 5,
    filters: dict | None = None,
) -> list[dict]:
    """Search a vector store. Returns normalized result dicts."""
    client = get_client()
    kwargs: dict[str, Any] = {
        "vector_store_id": vector_store_id,
        "query": query,
        "max_num_results": max_results,
    }
    if filters:
        kwargs["filters"] = filters

    response = client.vector_stores.search(**kwargs)

    import re as _re

    source_header_pat = _re.compile(
        r"^\[source:\s*(.+?)\s*\|\s*chunk:\s*(\d+)\]\n?",
        _re.IGNORECASE,
    )

    results = []
    for item in response.data:
        content_text = ""
        if hasattr(item, "content") and item.content:
            content_parts = []
            for c in item.content:
                if hasattr(c, "text"):
                    content_parts.append(c.text)
            content_text = "\n".join(content_parts)

        file_id = getattr(item, "file_id", "") or ""
        filename = getattr(item, "filename", "") or ""
        chunk_index = 0

        m = source_header_pat.match(content_text)
        if m:
            filename = filename or m.group(1)
            chunk_index = int(m.group(2))
            content_text = content_text[m.end():]

        results.append({
            "file_id": file_id,
            "filename": filename,
            "content": content_text,
            "score": getattr(item, "score", 0.0),
            "attributes": getattr(item, "attributes", {}),
            "chunk_index": chunk_index,
        })

    return results


def list_files(vector_store_id: str) -> list[dict]:
    """List all files in a vector store, including the original filename."""
    client = get_client()
    files = client.vector_stores.files.list(vector_store_id=vector_store_id)
    result = []
    for f in files.data:
        fid = getattr(f, "file_id", f.id)
        filename = ""
        try:
            file_obj = client.files.retrieve(fid)
            filename = getattr(file_obj, "filename", "")
        except Exception:
            pass
        result.append({
            "id": f.id,
            "status": f.status,
            "file_id": fid,
            "filename": filename,
        })
    return result


def delete_file(vector_store_id: str, file_id: str) -> bool:
    """Remove a file from a vector store."""
    client = get_client()
    try:
        client.vector_stores.files.delete(
            vector_store_id=vector_store_id,
            file_id=file_id,
        )
        logger.info("Deleted file %s from vector store %s", file_id, vector_store_id)
        return True
    except Exception as e:
        logger.warning("Failed to delete file %s: %s", file_id, e)
        return False


def delete_vector_store(vector_store_id: str) -> bool:
    """Delete an entire vector store."""
    client = get_client()
    try:
        client.vector_stores.delete(vector_store_id=vector_store_id)
        logger.info("Deleted vector store %s", vector_store_id)
        return True
    except Exception as e:
        logger.warning("Failed to delete vector store %s: %s", vector_store_id, e)
        return False


def check_connectivity() -> tuple[bool, str]:
    """Verify connectivity to the Llama Stack server."""
    try:
        client = get_client()
        models = client.models.list()
        model_count = len(list(models))
        return True, f"Connected to Llama Stack ({model_count} models available)"
    except Exception as e:
        return False, f"Llama Stack unreachable: {e}"
