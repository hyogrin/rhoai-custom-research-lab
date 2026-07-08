"""Search MCP Server — pgvector semantic search tools."""

import os

import httpx
import psycopg2
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from openai import OpenAI

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

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8888")

mcp = FastMCP("search-mcp", host="0.0.0.0", port=9002, stateless_http=True)


def _get_db():
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD)


def _get_embedding(text: str) -> list[float]:
    client = OpenAI(base_url=EMBEDDING_BASE_URL, api_key=EMBEDDING_API_KEY, http_client=_HTTP_CLIENT)
    response = client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
    return response.data[0].embedding


@mcp.tool()
def semantic_search(query: str, top_k: int = 5, min_similarity: float = 0.3) -> list[dict]:
    """Search for semantically similar document chunks using pgvector."""
    embedding = _get_embedding(query)
    conn = _get_db()
    cur = conn.cursor()

    cur.execute(
        """SELECT id, document_id, document_name, chunk_index, content, metadata,
                  1 - (embedding <=> %s::vector) as similarity
           FROM document_chunks
           WHERE 1 - (embedding <=> %s::vector) >= %s
           ORDER BY embedding <=> %s::vector
           LIMIT %s""",
        (str(embedding), str(embedding), min_similarity, str(embedding), top_k),
    )

    results = []
    for row in cur.fetchall():
        results.append({
            "id": row[0],
            "document_id": row[1],
            "document_name": row[2],
            "chunk_index": row[3],
            "content": row[4],
            "metadata": row[5] if row[5] else {},
            "similarity": round(float(row[6]), 4),
        })

    cur.close()
    conn.close()
    return results


@mcp.tool()
def search_by_document(query: str, document_id: str, top_k: int = 5) -> list[dict]:
    """Search within a specific document by document_id."""
    embedding = _get_embedding(query)
    conn = _get_db()
    cur = conn.cursor()

    cur.execute(
        """SELECT id, document_id, document_name, chunk_index, content, metadata,
                  1 - (embedding <=> %s::vector) as similarity
           FROM document_chunks
           WHERE document_id = %s
           ORDER BY embedding <=> %s::vector
           LIMIT %s""",
        (str(embedding), document_id, str(embedding), top_k),
    )

    results = []
    for row in cur.fetchall():
        results.append({
            "id": row[0],
            "document_id": row[1],
            "document_name": row[2],
            "chunk_index": row[3],
            "content": row[4],
            "metadata": row[5] if row[5] else {},
            "similarity": round(float(row[6]), 4),
        })

    cur.close()
    conn.close()
    return results


@mcp.tool()
def get_chunk_context(document_id: str, chunk_index: int, window: int = 2) -> list[dict]:
    """Get surrounding chunks for a given chunk to provide broader context."""
    conn = _get_db()
    cur = conn.cursor()

    cur.execute(
        """SELECT chunk_index, content, metadata
           FROM document_chunks
           WHERE document_id = %s AND chunk_index BETWEEN %s AND %s
           ORDER BY chunk_index""",
        (document_id, chunk_index - window, chunk_index + window),
    )

    results = []
    for row in cur.fetchall():
        results.append({
            "chunk_index": row[0],
            "content": row[1],
            "metadata": row[2] if row[2] else {},
            "is_center": row[0] == chunk_index,
        })

    cur.close()
    conn.close()
    return results


@mcp.tool()
def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Search the web via SearXNG. Returns list of {title, url, content}."""
    try:
        verify = not SEARXNG_URL.startswith("https://") or _VERIFY_SSL
        client = httpx.Client(verify=verify, timeout=httpx.Timeout(15.0))
        resp = client.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "engines": "google,duckduckgo"},
        )
        client.close()
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in data.get("results", [])[:num_results]
        ]
    except Exception:
        return []


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
