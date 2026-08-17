"""Vector Search MCP Server — Llama Stack vector store search proxy."""

import logging
import os
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(override=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from lib.llama_stack_client import (
    ensure_vector_store,
    list_files,
    search,
)

logger = logging.getLogger(__name__)

VECTOR_STORE_NAME = os.getenv("VECTOR_STORE_NAME", "research-docs")

mcp = FastMCP("vector-search-mcp", host="0.0.0.0", port=9002, stateless_http=True)


def _get_vector_store_id() -> str:
    """Lazily resolve the vector store ID."""
    return ensure_vector_store(VECTOR_STORE_NAME)


@mcp.tool()
def semantic_search(query: str, top_k: int = 5, min_similarity: float = 0.0) -> list[dict]:
    """Search for semantically similar document chunks via Llama Stack.

    Returns chunks with content, score, and source file metadata.
    """
    vector_store_id = _get_vector_store_id()
    results = search(vector_store_id, query, max_results=top_k)

    filtered = []
    for r in results:
        score = r.get("score", 0.0)
        if score < min_similarity:
            continue
        filtered.append({
            "file_id": r.get("file_id", ""),
            "document_name": r.get("filename", "") or "unknown",
            "content": r.get("content", ""),
            "similarity": round(score, 4),
            "chunk_index": r.get("chunk_index", 0),
            "attributes": r.get("attributes", {}),
        })

    return filtered


@mcp.tool()
def search_by_document(query: str, document_name: str, top_k: int = 5) -> list[dict]:
    """Search within a specific document by filename.

    Returns chunks with content, score, and source file metadata.
    """
    vector_store_id = _get_vector_store_id()
    filters = {
        "type": "eq",
        "key": "filename",
        "value": document_name,
    }
    results = search(vector_store_id, query, max_results=top_k, filters=filters)

    return [
        {
            "file_id": r.get("file_id", ""),
            "document_name": r.get("filename", "") or "unknown",
            "content": r.get("content", ""),
            "similarity": round(r.get("score", 0.0), 4),
            "chunk_index": r.get("chunk_index", 0),
            "attributes": r.get("attributes", {}),
        }
        for r in results
    ]


@mcp.tool()
def get_chunk_context(document_name: str, query: str = "", window: int = 5) -> list[dict]:
    """Get chunks from a specific document for broader context.

    Uses a broad search within the document to retrieve surrounding context.
    Falls back to listing document chunks if no query is provided.
    """
    vector_store_id = _get_vector_store_id()
    search_query = query or document_name
    filters = {
        "type": "eq",
        "key": "filename",
        "value": document_name,
    }
    results = search(vector_store_id, search_query, max_results=window, filters=filters)

    return [
        {
            "content": r.get("content", ""),
            "score": round(r.get("score", 0.0), 4),
            "file_id": r.get("file_id", ""),
        }
        for r in results
    ]


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
