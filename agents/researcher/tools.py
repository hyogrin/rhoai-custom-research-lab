"""Research tools: semantic search, query rewriting, and context synthesis."""

import json
import os
from typing import Any

import httpx
import psycopg2
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PG_HOST = os.getenv("PGVECTOR_HOST", "localhost")
PG_PORT = os.getenv("PGVECTOR_PORT", "5432")
PG_DB = os.getenv("PGVECTOR_DB", "doc_research")
PG_USER = os.getenv("PGVECTOR_USER", "postgres")
PG_PASSWORD = os.getenv("PGVECTOR_PASSWORD", "postgres")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
LLM_MODEL = os.getenv("LLM_MODEL", "granite-3.3-8b-instruct")
MAAS_API_KEY = os.getenv("MAAS_API_KEY", "")
_EFFECTIVE_LLM_KEY = MAAS_API_KEY if MAAS_API_KEY else LLM_API_KEY
_MAX_TOKEN_SMALL = int(os.getenv("LLM_MAX_TOKEN_SMALL", "512"))
_MAX_TOKEN_LARGE = int(os.getenv("LLM_MAX_TOKEN_LARGE", "4096"))
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")
_HTTP_CLIENT = None if _VERIFY_SSL else httpx.Client(verify=False, timeout=httpx.Timeout(300.0))

EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://localhost:8000/v1")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "not-needed")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "granite-embedding-278m-multilingual")


def get_db_connection():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD
    )


def get_embedding(text: str) -> list[float]:
    """Get embedding for a single text."""
    client = OpenAI(base_url=EMBEDDING_BASE_URL, api_key=EMBEDDING_API_KEY, http_client=_HTTP_CLIENT)
    response = client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
    return response.data[0].embedding


def get_llm_client() -> OpenAI:
    return OpenAI(base_url=LLM_BASE_URL, api_key=_EFFECTIVE_LLM_KEY, http_client=_HTTP_CLIENT)


def semantic_search(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Search pgvector for semantically similar document chunks."""
    embedding = get_embedding(query)
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """SELECT id, document_id, document_name, chunk_index, content, metadata,
                  1 - (embedding <=> %s::vector) as similarity
           FROM document_chunks
           ORDER BY embedding <=> %s::vector
           LIMIT %s""",
        (str(embedding), str(embedding), top_k),
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
            "similarity": float(row[6]),
        })

    cur.close()
    conn.close()
    return results


def rewrite_query(query: str) -> list[str]:
    """Rewrite a query into multiple search-optimized sub-queries."""
    client = get_llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a search query optimizer. Given a research question, "
                    "generate 3 diverse search queries that would help find relevant information. "
                    "Return ONLY a JSON array of strings, no explanation."
                ),
            },
            {"role": "user", "content": query},
        ],
        temperature=0.3,
        max_tokens=_MAX_TOKEN_SMALL,
    )
    try:
        queries = json.loads(response.choices[0].message.content)
        if isinstance(queries, list):
            return [query] + queries[:3]
    except (json.JSONDecodeError, IndexError):
        pass
    return [query]


def synthesize_context(query: str, passages: list[dict]) -> dict[str, Any]:
    """Synthesize retrieved passages into a coherent context summary with citations."""
    if not passages:
        return {"synthesis": "No relevant documents found.", "citations": []}

    context_parts = []
    for i, p in enumerate(passages):
        context_parts.append(f"[Source {i+1}: {p['document_name']}, chunk {p['chunk_index']}]\n{p['content']}")

    context = "\n\n".join(context_parts)

    client = get_llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a research analyst. Synthesize the provided document excerpts "
                    "to answer the user's question. Be comprehensive and accurate. "
                    "Reference sources by their [Source N] identifiers."
                ),
            },
            {
                "role": "user",
                "content": f"Question: {query}\n\nDocuments:\n{context}",
            },
        ],
        temperature=0.2,
        max_tokens=_MAX_TOKEN_LARGE,
    )

    synthesis = response.choices[0].message.content

    citations = [
        {"document": p["document_name"], "chunk_index": p["chunk_index"], "similarity": p["similarity"]}
        for p in passages
    ]

    return {"synthesis": synthesis, "citations": citations}
