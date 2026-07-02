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
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8888")

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


_searxng_available: bool | None = None
_searxng_checked_at: float = 0.0
_SEARXNG_RETRY_INTERVAL = 60.0


def _check_searxng() -> bool:
    """Probe SearXNG with TTL-based caching. Retries after 60s on failure."""
    global _searxng_available, _searxng_checked_at
    now = _time.time()
    if _searxng_available is not None:
        if _searxng_available or (now - _searxng_checked_at < _SEARXNG_RETRY_INTERVAL):
            return _searxng_available
    _searxng_checked_at = now
    verify = not SEARXNG_URL.startswith("https://") or _VERIFY_SSL
    try:
        client = _httpx.Client(verify=verify, timeout=_httpx.Timeout(5.0))
        resp = client.get(f"{SEARXNG_URL}/search", params={"q": "test", "format": "json"})
        client.close()
        _searxng_available = resp.status_code == 200
    except Exception:
        _searxng_available = False
    if not _searxng_available:
        logger.warning("SearXNG not available at %s — will retry in %ds", SEARXNG_URL, int(_SEARXNG_RETRY_INTERVAL))
    else:
        logger.info("SearXNG available at %s", SEARXNG_URL)
    return _searxng_available


def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Search the web via SearXNG. Returns list of {title, url, content}.

    Gracefully returns empty list if SearXNG is unavailable.
    """
    if not _check_searxng():
        return []
    try:
        verify = not SEARXNG_URL.startswith("https://") or _VERIFY_SSL
        client = _httpx.Client(
            verify=verify,
            timeout=_httpx.Timeout(15.0),
        )
        resp = client.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "engines": "google,duckduckgo"},
        )
        client.close()
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("results", [])[:num_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
            })
        return results
    except Exception as e:
        logger.warning("Web search failed: %s", e)
        return []


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


def generate_plan(query: str, iteration: int, failure_hints: str, existing_context: str, enable_web_search: bool = False) -> dict:
    """Generate a structured research plan."""
    actions = "search|analyze|compare|validate"
    if enable_web_search:
        actions += "|web_search"
    system_content = (
        "You are a research planner. Return ONLY a JSON array (no other text). "
        f"Each element: {{\"action\": \"{actions}\", \"query\": \"...\", \"purpose\": \"...\"}}. "
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


def generate_sectioned_plan(query: str, iteration: int, failure_hints: str, existing_context: str, language_instruction: str = "", enable_web_search: bool = False) -> dict:
    """Decompose a research query into 2-5 sub-topics, each with search queries.

    Returns a dict with 'sub_topics' (list) and 'tokens_used' (int).
    The plan is compatible with per-section writing in execute_sections().
    """
    web_note = ""
    if enable_web_search:
        web_note = (
            "- You may include web search queries prefixed with 'web:' for topics that "
            "benefit from up-to-date web information\n"
        )
    system_content = (
        "You are a research planner. Given a research question, decompose it into "
        "2-5 sub-topics for a structured report. "
        "Return ONLY a JSON object (no other text) with this shape:\n"
        '{"sub_topics": [{"title": "...", "queries": ["search query 1", "..."], "purpose": "..."}], '
        '"summary_query": "one-line summary of the full research"}\n\n'
        "Rules:\n"
        "- Each sub_topic has a clear title, 1-3 search queries, and a purpose\n"
        "- Sub-topics should cover the question comprehensively without overlap\n"
        "- Order sub-topics logically (background first, analysis later)\n"
        f"{web_note}"
        f"- This is iteration {iteration}. Adjust the plan based on any hints below."
    )
    if failure_hints:
        system_content += f"\n\nAvoid these past issues:\n{failure_hints[:500]}"
    if existing_context:
        system_content += f"\n\nContext gathered so far:\n{existing_context[:800]}"
    if language_instruction:
        system_content += f"\n\n{language_instruction}"

    content, tokens = _call_llm_with_retry(
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": query},
        ],
        max_tokens=_MAX_TOKEN_MEDIUM,
    )
    if content:
        parsed = _extract_json(content)
        if isinstance(parsed, dict) and "sub_topics" in parsed:
            return {"sub_topics": parsed["sub_topics"], "summary_query": parsed.get("summary_query", query), "tokens_used": tokens}
        if isinstance(parsed, list):
            sub_topics = []
            for item in parsed:
                if isinstance(item, dict) and "title" in item:
                    sub_topics.append(item)
            if sub_topics:
                return {"sub_topics": sub_topics, "summary_query": query, "tokens_used": tokens}
    return {
        "sub_topics": [{"title": "Research Report", "queries": [query], "purpose": "Comprehensive analysis"}],
        "summary_query": query,
        "tokens_used": tokens,
    }


def draft_section(query: str, sub_topic: dict, search_context: list[dict], previous_content: str = "", improvement_hints: str = "", language_instruction: str = "") -> dict:
    """Draft a single report section for one sub-topic.

    Similar to draft_report() but scoped to one section with its own context.
    """
    title = sub_topic.get("title", "Section")
    purpose = sub_topic.get("purpose", "")

    system_prompt = (
        f"You are a research report writer. Write the section titled \"{title}\" "
        f"for a larger research report.\n"
        f"Purpose of this section: {purpose}\n\n"
        "Guidelines:\n"
        "- Write ONLY this section (do not include executive summary or conclusion for the whole report)\n"
        "- Start with a ## heading matching the section title\n"
        "- Include citations as [Source N] referencing the provided context\n"
        "- Be thorough but focused on this sub-topic only\n"
        "- Use clear structure with sub-headings (###) if needed"
    )
    if language_instruction:
        system_prompt += f"\n\n{language_instruction}"

    context_text = "\n\n".join(
        f"[Source {i+1}: {c.get('document_name', c.get('source', 'unknown'))}]\n{c.get('content', '')[:600]}"
        for i, c in enumerate(search_context[:8])
    )

    user_content = f"Research Question: {query}\n\nSection: {title}\n\nContext:\n{context_text}"
    if previous_content:
        user_content += f"\n\nPrevious version (improve upon):\n{previous_content[:800]}"
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
        return {"content": content, "tokens_used": tokens}
    return {"content": f"## {title}\n\nSection generation failed.", "tokens_used": 0}


def assemble_report(sections: list[dict], section_order: list[str], query: str, language_instruction: str = "") -> dict:
    """Concatenate completed sections into a full report with an executive summary.

    Generates a brief executive summary via LLM, then appends all sections in order.
    """
    ordered_contents = []
    for title in section_order:
        section = next((s for s in sections if s.get("sub_topic") == title), None)
        if section and section.get("content"):
            ordered_contents.append(section["content"])

    if not ordered_contents:
        return {"draft": "No sections were generated.", "tokens_used": 0}

    body = "\n\n".join(ordered_contents)

    system_prompt = (
        "You are a research report editor. Given the section contents below, "
        "write ONLY a brief Executive Summary (3-5 sentences) that synthesizes "
        "the key findings across all sections. Do NOT repeat the sections."
    )
    if language_instruction:
        system_prompt += f"\n\n{language_instruction}"

    summary_content, tokens = _call_llm_with_retry(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Research Question: {query}\n\nSections:\n{body[:3000]}"},
        ],
        max_tokens=_MAX_TOKEN_MEDIUM,
        attempts=2,
    )

    if summary_content.strip():
        full_report = f"# Executive Summary\n\n{summary_content}\n\n{body}"
    else:
        full_report = body

    return {"draft": full_report, "tokens_used": tokens}


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
