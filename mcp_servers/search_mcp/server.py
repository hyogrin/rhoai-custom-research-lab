"""Search MCP Server — pgvector semantic search tools."""

import json
import os
from typing import Any

import httpx
import psycopg2
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
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

app = Server("search-mcp")


def _get_db():
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD)


def _get_embedding(text: str) -> list[float]:
    client = OpenAI(base_url=EMBEDDING_BASE_URL, api_key=EMBEDDING_API_KEY, http_client=_HTTP_CLIENT)
    response = client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
    return response.data[0].embedding


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="semantic_search",
            description="Search for semantically similar document chunks using pgvector.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query text"},
                    "top_k": {"type": "integer", "description": "Number of results to return", "default": 5},
                    "min_similarity": {"type": "number", "description": "Minimum similarity threshold (0-1)", "default": 0.3},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_by_document",
            description="Search within a specific document by document_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query text"},
                    "document_id": {"type": "string", "description": "Target document ID"},
                    "top_k": {"type": "integer", "description": "Number of results", "default": 5},
                },
                "required": ["query", "document_id"],
            },
        ),
        Tool(
            name="get_chunk_context",
            description="Get surrounding chunks for a given chunk to provide broader context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "Document ID"},
                    "chunk_index": {"type": "integer", "description": "Center chunk index"},
                    "window": {"type": "integer", "description": "Number of chunks before/after", "default": 2},
                },
                "required": ["document_id", "chunk_index"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "semantic_search":
        result = _semantic_search(
            arguments["query"],
            arguments.get("top_k", 5),
            arguments.get("min_similarity", 0.3),
        )
    elif name == "search_by_document":
        result = _search_by_document(
            arguments["query"],
            arguments["document_id"],
            arguments.get("top_k", 5),
        )
    elif name == "get_chunk_context":
        result = _get_chunk_context(
            arguments["document_id"],
            arguments["chunk_index"],
            arguments.get("window", 2),
        )
    else:
        result = {"error": f"Unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(result, default=str))]


def _semantic_search(query: str, top_k: int = 5, min_similarity: float = 0.3) -> list[dict]:
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


def _search_by_document(query: str, document_id: str, top_k: int = 5) -> list[dict]:
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


def _get_chunk_context(document_id: str, chunk_index: int, window: int = 2) -> list[dict]:
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


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
