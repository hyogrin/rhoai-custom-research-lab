"""Document processing tools using Docling and pgvector."""

import hashlib
import logging
import os
import re
from typing import Any

import httpx
import psycopg2
import psycopg2.extras
from docling.document_converter import DocumentConverter
from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

load_dotenv()

PG_HOST = os.getenv("PGVECTOR_HOST", "localhost")
PG_PORT = os.getenv("PGVECTOR_PORT", "5432")
PG_DB = os.getenv("PGVECTOR_DB", "doc_research")
PG_USER = os.getenv("PGVECTOR_USER", "postgres")
PG_PASSWORD = os.getenv("PGVECTOR_PASSWORD", "postgres")

EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://localhost:8000/v1")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "not-needed")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "granite-embedding-278m-multilingual")
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")
_HTTP_CLIENT = None if _VERIFY_SSL else httpx.Client(verify=False, timeout=httpx.Timeout(300.0))


def get_db_connection():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )


_EMBED_MAX_CHARS = 1500  # ~375 tokens; keeps request small for gateway timeout


def _truncate_for_embedding(text: str) -> str:
    """Truncate text to fit within embedding model limits."""
    if len(text) <= _EMBED_MAX_CHARS:
        return text
    return text[:_EMBED_MAX_CHARS]


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Get embeddings from the RHOAI model serving endpoint with retry.

    Truncates each text and sends one at a time to avoid gateway timeouts.
    """
    import time

    truncated = [_truncate_for_embedding(t) for t in texts]

    client = OpenAI(
        base_url=EMBEDDING_BASE_URL,
        api_key=EMBEDDING_API_KEY,
        http_client=_HTTP_CLIENT,
        max_retries=0,
        timeout=30.0,
    )

    all_embeddings: list[list[float]] = []
    for i, text in enumerate(truncated):
        for attempt in range(4):
            if attempt > 0:
                delay = 3 * attempt
                logger.info("Embedding retry %d/4 for text %d/%d (wait %ds)", attempt + 1, i + 1, len(truncated), delay)
                time.sleep(delay)
            try:
                response = client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
                all_embeddings.append(response.data[0].embedding)
                break
            except Exception as e:
                logger.warning("Embedding attempt %d for text %d failed: %s", attempt + 1, i + 1, str(e)[:200])
                if attempt == 3:
                    raise RuntimeError(f"Embedding failed after 4 attempts for text {i+1}/{len(truncated)}")

    return all_embeddings


CHUNK_MAX_CHARS = int(os.getenv("CHUNK_MAX_CHARS", "3000"))  # ~750 tokens

_SEMANTIC_SEPARATORS = [
    "\n\n## ",
    "\n\n### ",
    "\n\n---\n",
    "\n\n\n",
    "\n\n",
    ".\n",
    ". ",
    "! ",
    "? ",
    "\n- ",
    "\n* ",
    "\n",
    " ",
]


def _split_oversized(text: str, heading: str, max_chars: int) -> list[dict]:
    """Split text that exceeds max_chars using semantic separators (iterative)."""
    if len(text) <= max_chars:
        return [{"text": text, "metadata": {"heading": heading}}]

    # Try each separator in priority order
    for sep in _SEMANTIC_SEPARATORS:
        if sep not in text:
            continue

        # Split the entire text by this separator into all parts
        parts = text.split(sep)
        if len(parts) < 2:
            continue

        # Merge parts into chunks that fit within max_chars
        chunks: list[dict] = []
        current = ""
        for i, part in enumerate(parts):
            candidate = (current + sep + part) if current else part
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current.strip():
                    chunks.append({"text": current.strip(), "metadata": {"heading": heading}})
                current = part

        if current.strip():
            chunks.append({"text": current.strip(), "metadata": {"heading": heading}})

        if len(chunks) > 1:
            return chunks

    # Fallback: hard split at word boundary
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            for i in range(end, max(start + max_chars // 2, start), -1):
                if text[i] in " .,;:!?\n":
                    end = i + 1
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({"text": chunk, "metadata": {"heading": heading}})
        start = end
    return chunks if chunks else [{"text": text.strip(), "metadata": {"heading": heading}}]


def semantic_chunk_document(doc) -> list[dict]:
    """Split a Docling document by markdown heading hierarchy (H1 > H2).

    Strategy:
    1. Convert to markdown (preserves heading structure)
    2. Split at H1/H2 boundaries (large/medium category)
    3. Enforce CHUNK_MAX_CHARS — oversized chunks are recursively split
       using semantic separators (paragraph, sentence, list boundaries)
    4. Each chunk retains its parent H1 heading for retrieval context

    Returns list of dicts: [{"text": ..., "metadata": {"heading": ...}}]
    """
    md_content = doc.export_to_markdown()
    if not md_content or not md_content.strip():
        return [{"text": md_content.strip(), "metadata": {}}] if md_content else []

    lines = md_content.split("\n")
    sections: list[dict] = []
    current_h1 = ""
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if re.match(r"^#\s+", stripped):
            if current_lines:
                sections.append({"h1": current_h1, "lines": current_lines})
            current_h1 = stripped
            current_lines = [line]
        elif re.match(r"^##\s+", stripped) and not current_h1:
            if current_lines:
                sections.append({"h1": "", "lines": current_lines})
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append({"h1": current_h1, "lines": current_lines})

    raw_chunks: list[dict] = []
    for section in sections:
        h1 = section["h1"]
        content_lines = section["lines"]

        h2_positions = [i for i, l in enumerate(content_lines) if re.match(r"^##\s+", l.strip())]

        if len(h2_positions) >= 2:
            before_first_h2 = "\n".join(content_lines[:h2_positions[0]]).strip()
            if before_first_h2 and before_first_h2 != h1:
                raw_chunks.append({"text": before_first_h2, "metadata": {"heading": h1}})

            for j, h2_pos in enumerate(h2_positions):
                end = h2_positions[j + 1] if j + 1 < len(h2_positions) else len(content_lines)
                sub_lines = content_lines[h2_pos:end]
                chunk_text = (h1 + "\n" + "\n".join(sub_lines)).strip() if h1 else "\n".join(sub_lines).strip()
                if chunk_text:
                    heading = sub_lines[0].strip() if sub_lines else h1
                    raw_chunks.append({"text": chunk_text, "metadata": {"heading": heading, "parent": h1}})
        else:
            chunk_text = "\n".join(content_lines).strip()
            if chunk_text:
                raw_chunks.append({"text": chunk_text, "metadata": {"heading": h1 or ""}})

    if not raw_chunks and md_content.strip():
        raw_chunks = [{"text": md_content.strip(), "metadata": {}}]

    # Enforce max size: split oversized chunks recursively
    final_chunks: list[dict] = []
    for chunk in raw_chunks:
        if len(chunk["text"]) <= CHUNK_MAX_CHARS:
            final_chunks.append(chunk)
        else:
            heading = chunk["metadata"].get("heading", "")
            split_results = _split_oversized(chunk["text"], heading, CHUNK_MAX_CHARS)
            final_chunks.extend(split_results)

    logger.info(
        "Semantic chunking: %d sections → %d heading chunks → %d final chunks (max %d chars)",
        len(sections), len(raw_chunks), len(final_chunks), CHUNK_MAX_CHARS,
    )
    return final_chunks


def ingest_document(file_path: str) -> dict[str, Any]:
    """Parse a document with Docling, semantic-chunk it, embed, and store in pgvector."""
    try:
        converter = DocumentConverter()
        result = converter.convert(file_path)
        doc = result.document

        chunks = semantic_chunk_document(doc)

        if not chunks:
            return {"document_id": "", "status": "error", "chunk_count": 0, "error": "No chunks produced"}

        document_id = hashlib.sha256(file_path.encode()).hexdigest()[:16]
        document_name = os.path.basename(file_path)

        batch_size = 10
        all_embeddings = []
        chunk_texts = [c["text"] for c in chunks]
        for i in range(0, len(chunk_texts), batch_size):
            batch = chunk_texts[i : i + batch_size]
            embeddings = get_embeddings(batch)
            all_embeddings.extend(embeddings)

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """INSERT INTO documents (id, name, file_type, chunk_count, status, object_store_path)
               VALUES (%s, %s, %s, %s, 'completed', %s)
               ON CONFLICT (id) DO UPDATE SET
                   chunk_count = EXCLUDED.chunk_count,
                   status = EXCLUDED.status,
                   updated_at = NOW()""",
            (document_id, document_name, os.path.splitext(file_path)[1], len(chunks), file_path),
        )

        cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))

        for idx, (chunk, embedding) in enumerate(zip(chunks, all_embeddings)):
            metadata = chunk.get("metadata", {})
            cur.execute(
                """INSERT INTO document_chunks (document_id, document_name, chunk_index, content, metadata, embedding)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s::vector)""",
                (
                    document_id,
                    document_name,
                    idx,
                    chunk["text"],
                    psycopg2.extras.Json(metadata) if metadata else "{}",
                    str(embedding),
                ),
            )

        conn.commit()
        cur.close()
        conn.close()

        return {"document_id": document_id, "status": "completed", "chunk_count": len(chunks)}

    except Exception as e:
        return {"document_id": "", "status": "error", "chunk_count": 0, "error": str(e)}


def get_document_status(document_id: str) -> str:
    """Get the processing status of a document."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT status, chunk_count FROM documents WHERE id = %s", (document_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return f"status={row[0]}, chunks={row[1]}"
        return "not found"
    except Exception as e:
        return f"error: {e}"
