"""Tool Layer — MCP client connections for doc, search, and analysis tools."""

import json
import logging
import os
import re
from typing import Any

import httpx as _httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

DOC_MCP_URL = os.getenv("DOC_MCP_URL", "http://localhost:9001")
SEARCH_MCP_URL = os.getenv("SEARCH_MCP_URL", "http://localhost:9002")
ANALYSIS_MCP_URL = os.getenv("ANALYSIS_MCP_URL", "http://localhost:9003")

PG_HOST = os.getenv("PGVECTOR_HOST", "localhost")
PG_PORT = os.getenv("PGVECTOR_PORT", "5432")
PG_DB = os.getenv("PGVECTOR_DB", "doc_research")
PG_USER = os.getenv("PGVECTOR_USER", "postgres")
PG_PASSWORD = os.getenv("PGVECTOR_PASSWORD", "postgres")

EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://localhost:8000/v1")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "not-needed")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "granite-embedding-278m-multilingual")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
LLM_MODEL = os.getenv("LLM_MODEL", "granite-3.3-8b-instruct")
MAAS_API_KEY = os.getenv("MAAS_API_KEY", "")
_EFFECTIVE_LLM_KEY = MAAS_API_KEY if MAAS_API_KEY else LLM_API_KEY
_MAX_TOKEN_SMALL = int(os.getenv("LLM_MAX_TOKEN_SMALL", "512"))
_MAX_TOKEN_MEDIUM = int(os.getenv("LLM_MAX_TOKEN_MEDIUM", "1024"))
_MAX_TOKEN_LARGE = int(os.getenv("LLM_MAX_TOKEN_LARGE", "4096"))
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")

_THINKING_EXTRA_BODY: dict = {"chat_template_kwargs": {"enable_thinking": False}}

import threading as _threading
import time as _time

_llm_lock = _threading.Lock()
_last_llm_call: float = 0.0
_MIN_CALL_INTERVAL = 1.0


def _rate_limit():
    """Enforce minimum interval between LLM calls to avoid MaaS rate limiting."""
    global _last_llm_call
    with _llm_lock:
        now = _time.time()
        elapsed = now - _last_llm_call
        if elapsed < _MIN_CALL_INTERVAL:
            _time.sleep(_MIN_CALL_INTERVAL - elapsed)
        _last_llm_call = _time.time()


def _extract_json(text: str) -> Any:
    """Extract JSON from model output that may contain thinking/markdown."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    md_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if md_match:
        text = md_match.group(1).strip()
    bracket = text.find("[")
    brace = text.find("{")
    if bracket == -1 and brace == -1:
        return None
    start = min(x for x in (bracket, brace) if x >= 0)
    text = text[start:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for end in range(len(text), 0, -1):
        try:
            return json.loads(text[:end])
        except json.JSONDecodeError:
            continue
    return None


def _llm_client() -> OpenAI:
    """Create a fresh OpenAI client. Caller should call client.close() when done."""
    http_client = None
    if not _VERIFY_SSL:
        http_client = _httpx.Client(verify=False, timeout=_httpx.Timeout(120.0))
    return OpenAI(
        base_url=LLM_BASE_URL,
        api_key=_EFFECTIVE_LLM_KEY,
        http_client=http_client,
        max_retries=0,
        timeout=120.0,
    )


def _call_llm_with_retry(messages: list[dict], max_tokens: int, temperature: float = 0.3, attempts: int = 3) -> tuple[str, int]:
    """Call LLM with retry and inter-attempt delay. Returns (content, tokens_used)."""
    for attempt in range(attempts):
        if attempt > 0:
            _time.sleep(5 + 3 * attempt)
            logger.info("LLM retry attempt %d/%d after delay", attempt + 1, attempts)
        _rate_limit()
        client = _llm_client()
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=_THINKING_EXTRA_BODY,
            )
            content = response.choices[0].message.content or ""
            tokens = response.usage.total_tokens if response.usage else 0
            return content, tokens
        except Exception as e:
            cause = getattr(e, "__cause__", None)
            logger.warning(
                "LLM call attempt %d/%d failed (max_tokens=%d): %s | cause: %s",
                attempt + 1, attempts, max_tokens, e, cause,
            )
        finally:
            client.close()
    return "", 0


def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """Execute semantic search against pgvector via direct connection."""
    import psycopg2
    import time as _time

    truncated_query = query[:1500]
    embedding = None

    for attempt in range(4):
        if attempt > 0:
            delay = 3 * attempt
            logger.info("semantic_search embedding retry %d/4 (wait %ds)", attempt + 1, delay)
            _time.sleep(delay)
        try:
            embed_http = None if _VERIFY_SSL else _httpx.Client(verify=False, timeout=_httpx.Timeout(30.0))
            client = OpenAI(base_url=EMBEDDING_BASE_URL, api_key=EMBEDDING_API_KEY, http_client=embed_http)
            response = client.embeddings.create(input=[truncated_query], model=EMBEDDING_MODEL)
            embedding = response.data[0].embedding
            client.close()
            break
        except Exception as e:
            logger.warning("semantic_search embedding attempt %d failed: %s", attempt + 1, str(e)[:200])
            if attempt == 3:
                logger.error("semantic_search embedding failed after 4 attempts")
                return []

    if embedding is None:
        return []

    conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD)
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


def rewrite_query(query: str) -> list[str]:
    """Rewrite a query into multiple search-optimized sub-queries."""
    content, _ = _call_llm_with_retry(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a search query optimizer. Given a research question, "
                    "generate 3 diverse search queries that would help find relevant information. "
                    "Return ONLY a JSON array of strings. No explanation."
                ),
            },
            {"role": "user", "content": query},
        ],
        max_tokens=_MAX_TOKEN_SMALL,
        attempts=2,
    )
    if content:
        parsed = _extract_json(content)
        if isinstance(parsed, list):
            return [query] + [str(q) for q in parsed[:3]]
    return [query]


def synthesize_context(query: str, passages: list[dict]) -> dict:
    """Synthesize retrieved passages into a coherent summary."""
    if not passages:
        return {"synthesis": "No relevant documents found.", "citations": [], "tokens_used": 0}

    context_parts = []
    for i, p in enumerate(passages):
        context_parts.append(
            f"[Source {i+1}: {p.get('document_name', 'unknown')}, chunk {p.get('chunk_index', 0)}]\n{p.get('content', '')}"
        )
    context = "\n\n".join(context_parts)

    content, tokens = _call_llm_with_retry(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a research analyst. Synthesize the provided document excerpts "
                    "to answer the user's question. Be comprehensive and accurate. "
                    "Reference sources by their [Source N] identifiers. Keep your response concise."
                ),
            },
            {"role": "user", "content": f"Question: {query}\n\nDocuments:\n{context[:1500]}"},
        ],
        max_tokens=_MAX_TOKEN_SMALL,
        temperature=0.2,
    )
    return {
        "synthesis": content if content else "Synthesis unavailable.",
        "citations": [
            {"document": p.get("document_name", ""), "chunk_index": p.get("chunk_index", 0), "similarity": p.get("similarity", 0)}
            for p in passages
        ],
        "tokens_used": tokens,
    }


def generate_plan(query: str, iteration: int, failure_hints: str, existing_context: str) -> dict:
    """Generate a structured research plan."""
    system_content = (
        "You are a research planner. Return ONLY a JSON array (no other text). "
        "Each element: {\"action\": \"search|analyze|compare|validate\", \"query\": \"...\", \"purpose\": \"...\"}. "
        f"This is iteration {iteration}. Generate 2-3 steps."
    )
    if failure_hints:
        system_content += f"\n\nAvoid these past issues:\n{failure_hints[:500]}"
    if existing_context:
        system_content += f"\n\nContext gathered so far:\n{existing_context[:800]}"

    content, tokens = _call_llm_with_retry(
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": query},
        ],
        max_tokens=_MAX_TOKEN_SMALL,
    )
    if content:
        parsed = _extract_json(content)
        if isinstance(parsed, list):
            return {"plan": parsed, "tokens_used": tokens}
    return {"plan": [{"action": "search", "query": query, "purpose": "Direct search"}], "tokens_used": tokens}


def draft_report(query: str, context: str, plan: str, previous_draft: str = "", improvement_hints: str = "", language_instruction: str = "") -> dict:
    """Draft a research report."""
    system_prompt = (
        "You are a research report writer. Write a well-structured research report. "
        "Include citations as [Source N]. "
        "Structure: Executive Summary, Key Findings, Detailed Analysis, Conclusion. "
        "Be concise but comprehensive."
    )
    if language_instruction:
        system_prompt += f"\n\n{language_instruction}"

    user_content = f"Research Question: {query}\n\nResearch Plan:\n{plan[:500]}\n\nContext:\n{context[:2000]}"
    if previous_draft:
        user_content += f"\n\nPrevious Draft (improve upon):\n{previous_draft[:1000]}"
    if improvement_hints:
        user_content += f"\n\nImprovements needed:\n{improvement_hints[:300]}"

    content, tokens = _call_llm_with_retry(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=_MAX_TOKEN_LARGE,
        attempts=3,
    )
    if content.strip():
        return {"draft": content, "tokens_used": tokens}
    return {"draft": "Report generation failed after retries. Please try again.", "tokens_used": 0}
