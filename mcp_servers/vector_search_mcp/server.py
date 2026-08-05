"""Vector Search MCP Server — sqlite-vec semantic search tools."""

import json
import os
import sys

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from openai import OpenAI
from sqlite_vec import serialize_float32

load_dotenv(override=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from db import get_connection


def _ensure_v1(url: str) -> str:
    """Append /v1 if missing — RHOAI dashboard URLs omit it."""
    if url and not url.rstrip("/").endswith("/v1"):
        return url.rstrip("/") + "/v1"
    return url


EMBEDDING_BASE_URL = _ensure_v1(os.getenv("EMBEDDING_BASE_URL", "http://localhost:8000/v1"))
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "not-needed")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "granite-embedding-278m-multilingual")
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")
_HTTP_CLIENT = None if _VERIFY_SSL else httpx.Client(verify=False, timeout=httpx.Timeout(300.0))

mcp = FastMCP("vector-search-mcp", host="0.0.0.0", port=9002, stateless_http=True)


def _get_embedding(text: str) -> list[float]:
    client = OpenAI(base_url=EMBEDDING_BASE_URL, api_key=EMBEDDING_API_KEY, http_client=_HTTP_CLIENT)
    response = client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
    return response.data[0].embedding


@mcp.tool()
def semantic_search(query: str, top_k: int = 5, min_similarity: float = 0.0) -> list[dict]:
    """Search for semantically similar document chunks using sqlite-vec.

    Returns chunks with source_url linking to the original document in object storage.
    """
    embedding = _get_embedding(query)
    conn = get_connection()

    rows = conn.execute(
        """SELECT vc.chunk_id, vc.distance,
                  dc.document_id, dc.document_name, dc.chunk_index, dc.content, dc.metadata,
                  d.object_store_path
           FROM vec_chunks vc
           JOIN document_chunks dc ON dc.id = vc.chunk_id
           LEFT JOIN documents d ON dc.document_id = d.id
           WHERE vc.embedding MATCH ? AND vc.k = ?
           ORDER BY vc.distance""",
        (serialize_float32(embedding), top_k),
    ).fetchall()

    results = []
    for row in rows:
        dist = float(row["distance"])
        similarity = 1.0 / (1.0 + dist)
        if similarity < min_similarity:
            continue
        meta = row["metadata"]
        results.append({
            "id": row["chunk_id"],
            "document_id": row["document_id"],
            "document_name": row["document_name"],
            "chunk_index": row["chunk_index"],
            "content": row["content"],
            "metadata": json.loads(meta) if meta else {},
            "similarity": round(similarity, 4),
            "source_url": row["object_store_path"] or "",
        })

    conn.close()
    return results


@mcp.tool()
def search_by_document(query: str, document_id: str, top_k: int = 5) -> list[dict]:
    """Search within a specific document by document_id.

    Returns chunks with source_url linking to the original document in object storage.
    """
    embedding = _get_embedding(query)
    conn = get_connection()

    rows = conn.execute(
        """SELECT sub.chunk_id, sub.distance,
                  dc.document_id, dc.document_name, dc.chunk_index, dc.content, dc.metadata,
                  d.object_store_path
           FROM (
               SELECT chunk_id, distance
               FROM vec_chunks
               WHERE embedding MATCH ? AND k = ?
               ORDER BY distance
           ) sub
           JOIN document_chunks dc ON dc.id = sub.chunk_id
           LEFT JOIN documents d ON dc.document_id = d.id
           WHERE dc.document_id = ?
           ORDER BY sub.distance""",
        (serialize_float32(embedding), top_k * 10, document_id),
    ).fetchall()

    results = []
    for row in rows:
        dist = float(row["distance"])
        similarity = 1.0 / (1.0 + dist)
        meta = row["metadata"]
        results.append({
            "id": row["chunk_id"],
            "document_id": row["document_id"],
            "document_name": row["document_name"],
            "chunk_index": row["chunk_index"],
            "content": row["content"],
            "metadata": json.loads(meta) if meta else {},
            "similarity": round(similarity, 4),
            "source_url": row["object_store_path"] or "",
        })

    conn.close()
    return results


@mcp.tool()
def get_chunk_context(document_id: str, chunk_index: int, window: int = 2) -> list[dict]:
    """Get surrounding chunks for a given chunk to provide broader context."""
    conn = get_connection()

    rows = conn.execute(
        """SELECT chunk_index, content, metadata
           FROM document_chunks
           WHERE document_id = ? AND chunk_index BETWEEN ? AND ?
           ORDER BY chunk_index""",
        (document_id, chunk_index - window, chunk_index + window),
    ).fetchall()

    results = []
    for row in rows:
        meta = row["metadata"]
        results.append({
            "chunk_index": row["chunk_index"],
            "content": row["content"],
            "metadata": json.loads(meta) if meta else {},
            "is_center": row["chunk_index"] == chunk_index,
        })

    conn.close()
    return results


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
