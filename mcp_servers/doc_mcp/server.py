"""Document MCP Server — Docling-based document parsing, chunking, and ingestion."""

import hashlib
import os
from typing import Any

import httpx
import psycopg2
import psycopg2.extras
from docling.document_converter import DocumentConverter
from docling.chunking import HybridChunker
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

mcp = FastMCP("doc-mcp", host="0.0.0.0", port=9001, stateless_http=True)


def _get_db():
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD)


def _get_embeddings(texts: list[str]) -> list[list[float]]:
    client = OpenAI(base_url=EMBEDDING_BASE_URL, api_key=EMBEDDING_API_KEY, http_client=_HTTP_CLIENT)
    response = client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
    return [item.embedding for item in response.data]


@mcp.tool()
def ingest_document(file_path: str) -> dict[str, Any]:
    """Parse a document with Docling, chunk it, generate embeddings, and store in pgvector."""
    try:
        converter = DocumentConverter()
        result = converter.convert(file_path)
        doc = result.document

        chunker = HybridChunker(tokenizer="sentence-transformers/all-MiniLM-L6-v2")
        chunks = list(chunker.chunk(doc))

        if not chunks:
            return {"document_id": "", "status": "error", "chunk_count": 0, "error": "No chunks produced"}

        document_id = hashlib.sha256(file_path.encode()).hexdigest()[:16]
        document_name = os.path.basename(file_path)

        batch_size = 32
        all_embeddings = []
        chunk_texts = [chunk.text for chunk in chunks]
        for i in range(0, len(chunk_texts), batch_size):
            batch = chunk_texts[i:i + batch_size]
            embeddings = _get_embeddings(batch)
            all_embeddings.extend(embeddings)

        conn = _get_db()
        cur = conn.cursor()

        cur.execute(
            """INSERT INTO documents (id, name, file_type, chunk_count, status, object_store_path)
               VALUES (%s, %s, %s, %s, 'completed', %s)
               ON CONFLICT (id) DO UPDATE SET
                   chunk_count = EXCLUDED.chunk_count, status = EXCLUDED.status, updated_at = NOW()""",
            (document_id, document_name, os.path.splitext(file_path)[1], len(chunks), file_path),
        )

        cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))

        for idx, (chunk, embedding) in enumerate(zip(chunks, all_embeddings)):
            metadata = {}
            if hasattr(chunk, "meta") and chunk.meta:
                metadata = {"headings": getattr(chunk.meta, "headings", []), "page": getattr(chunk.meta, "page", None)}

            cur.execute(
                """INSERT INTO document_chunks (document_id, document_name, chunk_index, content, metadata, embedding)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s::vector)""",
                (document_id, document_name, idx, chunk.text, psycopg2.extras.Json(metadata), str(embedding)),
            )

        conn.commit()
        cur.close()
        conn.close()

        return {"document_id": document_id, "status": "completed", "chunk_count": len(chunks)}
    except Exception as e:
        return {"document_id": "", "status": "error", "chunk_count": 0, "error": str(e)}


@mcp.tool()
def get_document_status(document_id: str) -> dict:
    """Check the processing status of a document by its ID."""
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name, status, chunk_count FROM documents WHERE id = %s", (document_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {"document_id": row[0], "name": row[1], "status": row[2], "chunk_count": row[3]}
        return {"error": "Document not found"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_documents() -> list[dict]:
    """List all ingested documents with their status and chunk counts."""
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name, file_type, chunk_count, status FROM documents ORDER BY updated_at DESC LIMIT 50")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"id": r[0], "name": r[1], "file_type": r[2], "chunk_count": r[3], "status": r[4]} for r in rows]
    except Exception as e:
        return [{"error": str(e)}]


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
