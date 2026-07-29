"""MCP Client Layer — Routes tool calls through MCP servers via streamable-http transport.

MCP-based tools: vector-search, web-search, verification, observability, document.
Direct LLM tools: query rewriting, plan generation, report drafting (formerly analysis-mcp).
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Callable

import time
import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from openai import APIConnectionError, APITimeoutError, OpenAI

load_dotenv(override=True)

logger = logging.getLogger(__name__)

VECTOR_SEARCH_MCP_URL = os.getenv("VECTOR_SEARCH_MCP_URL", "http://127.0.0.1:9002")
WEB_SEARCH_MCP_URL = os.getenv("WEB_SEARCH_MCP_URL", "http://127.0.0.1:9003")
VERIFICATION_MCP_URL = os.getenv("VERIFICATION_MCP_URL", "http://127.0.0.1:9004")
OBSERVABILITY_MCP_URL = os.getenv("OBSERVABILITY_MCP_URL", "http://127.0.0.1:9005")

def _ensure_v1(url: str) -> str:
    """Append /v1 if missing — RHOAI dashboard URLs omit it."""
    if url and not url.rstrip("/").endswith("/v1"):
        return url.rstrip("/") + "/v1"
    return url


LLM_BASE_URL = _ensure_v1(os.getenv("LLM_BASE_URL", "http://localhost:8000/v1"))
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
LLM_MODEL = os.getenv("LLM_MODEL", "granite-3.3-8b-instruct")
MAAS_API_KEY = os.getenv("MAAS_API_KEY", "")
_EFFECTIVE_LLM_KEY = MAAS_API_KEY if MAAS_API_KEY else LLM_API_KEY
_MAX_TOKEN_SMALL = int(os.getenv("LLM_MAX_TOKEN_SMALL", "512"))
_MAX_TOKEN_MEDIUM = int(os.getenv("LLM_MAX_TOKEN_MEDIUM", "1024"))
_MAX_TOKEN_LARGE = int(os.getenv("LLM_MAX_TOKEN_LARGE", "4096"))
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")

_MCP_ENDPOINT = "/mcp"

SERVER_URLS = {
    "vector-search": f"{VECTOR_SEARCH_MCP_URL}{_MCP_ENDPOINT}",
    "web-search": f"{WEB_SEARCH_MCP_URL}{_MCP_ENDPOINT}",
    "verification": f"{VERIFICATION_MCP_URL}{_MCP_ENDPOINT}",
    "observability": f"{OBSERVABILITY_MCP_URL}{_MCP_ENDPOINT}",
}


# ---------------------------------------------------------------------------
# MCP transport helpers
# ---------------------------------------------------------------------------


_MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "90"))
_MCP_MAX_RETRIES = int(os.getenv("MCP_MAX_RETRIES", "2"))


async def _call_mcp_tool(server: str, tool_name: str, arguments: dict) -> Any:
    """Call a tool on a remote MCP server via streamable-http transport."""
    url = SERVER_URLS[server]
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

            # Prefer structuredContent (FastMCP returns this for typed results)
            if hasattr(result, "structuredContent") and result.structuredContent is not None:
                return result.structuredContent.get("result", result.structuredContent)

            if result.content and len(result.content) > 0:
                text = result.content[0].text
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text

            return None


def _call_mcp_sync(server: str, tool_name: str, arguments: dict) -> Any:
    """Synchronous wrapper for MCP tool calls with retry on transient failures."""
    last_err: Exception | None = None

    for attempt in range(_MCP_MAX_RETRIES + 1):
        try:
            return _run_mcp_in_new_loop(server, tool_name, arguments)
        except Exception as e:
            last_err = e
            err_str = str(e)
            is_transient = any(k in err_str for k in ("TaskGroup", "ConnectionRefused", "timeout", "ConnectError"))
            if is_transient and attempt < _MCP_MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(
                    "MCP call %s/%s attempt %d failed (%s), retrying in %ds...",
                    server, tool_name, attempt + 1, err_str[:120], wait,
                )
                time.sleep(wait)
                continue
            break

    logger.error("MCP call %s/%s failed after %d attempts: %s", server, tool_name, _MCP_MAX_RETRIES + 1, last_err)
    raise last_err  # type: ignore[misc]


def _run_mcp_in_new_loop(server: str, tool_name: str, arguments: dict) -> Any:
    """Run MCP call in a fresh event loop. Always safe from any thread."""
    import concurrent.futures

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run, asyncio.wait_for(
                    _call_mcp_tool(server, tool_name, arguments),
                    timeout=_MCP_TIMEOUT,
                )
            )
            return future.result(timeout=_MCP_TIMEOUT + 10)
    else:
        return asyncio.run(
            asyncio.wait_for(
                _call_mcp_tool(server, tool_name, arguments),
                timeout=_MCP_TIMEOUT,
            )
        )


# ---------------------------------------------------------------------------
# LLM helpers (for plan/draft/synthesis — formerly analysis-mcp)
# ---------------------------------------------------------------------------


_LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))


def _get_llm() -> OpenAI:
    http_client = None
    if not _VERIFY_SSL:
        http_client = httpx.Client(verify=False, timeout=httpx.Timeout(300.0))
    return OpenAI(
        base_url=LLM_BASE_URL,
        api_key=_EFFECTIVE_LLM_KEY,
        http_client=http_client,
        max_retries=_LLM_MAX_RETRIES,
    )


def _call_llm(messages: list[dict], max_tokens: int = 1024, temperature: float = 0.3) -> tuple[str, int]:
    """Call LLM and return (content, tokens_used) with retry on connection errors."""
    client = _get_llm()
    last_err: Exception | None = None

    for attempt in range(_LLM_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            content = response.choices[0].message.content or ""
            tokens = response.usage.total_tokens if response.usage else 0
            return content, tokens
        except (APIConnectionError, APITimeoutError) as e:
            last_err = e
            if attempt < _LLM_MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(
                    "LLM call attempt %d/%d failed (%s), retrying in %ds...",
                    attempt + 1, _LLM_MAX_RETRIES + 1, type(e).__name__, wait,
                )
                time.sleep(wait)
                continue
            break

    logger.error("LLM call failed after %d attempts: %s", _LLM_MAX_RETRIES + 1, last_err)
    raise last_err  # type: ignore[misc]


def _call_llm_streaming(
    messages: list[dict],
    max_tokens: int = 1024,
    temperature: float = 0.3,
    on_chunk: Callable[[str], None] | None = None,
) -> tuple[str, int]:
    """Call LLM with streaming, invoking *on_chunk* for each token delta.

    Returns the same ``(content, tokens_used)`` tuple as ``_call_llm``.
    ``tokens_used`` is estimated from the accumulated text when the API
    does not provide usage in streaming mode.
    """
    client = _get_llm()
    chunks: list[str] = []

    stream = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )

    tokens_used = 0
    for event in stream:
        if event.usage:
            tokens_used = event.usage.total_tokens
        if not event.choices:
            continue
        delta = event.choices[0].delta
        if delta and delta.content:
            chunks.append(delta.content)
            if on_chunk:
                on_chunk(delta.content)

    content = "".join(chunks)
    if tokens_used == 0:
        tokens_used = max(len(content) // 4, 1)
    return content, tokens_used


def _length_guidance(max_tokens: int, language_instruction: str = "") -> str:
    """Generate a length constraint instruction scaled to token budget and language.

    Korean text typically consumes ~1.8x tokens vs English for equivalent content,
    so we reduce the word budget accordingly and express it in characters.
    """
    is_korean = "한국어" in language_instruction or "Korean" in language_instruction
    safety_factor = 0.85
    usable_tokens = int(max_tokens * safety_factor)

    if is_korean:
        char_budget = int(usable_tokens * 1.2)
        return f"\n\nLENGTH CONSTRAINT: Keep your response under approximately {char_budget} characters ({usable_tokens} tokens). Be concise and prioritize depth over breadth. Truncation will occur if you exceed this limit."
    else:
        word_budget = int(usable_tokens * 0.75)
        return f"\n\nLENGTH CONSTRAINT: Keep your response under approximately {word_budget} words ({usable_tokens} tokens). Be concise and prioritize depth over breadth. Truncation will occur if you exceed this limit."


def _extract_json(text: str) -> Any:
    """Extract JSON from model output that may contain thinking tags or markdown."""
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


# ---------------------------------------------------------------------------
# Vector Search MCP tools
# ---------------------------------------------------------------------------


def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """Semantic search via vector-search-mcp server."""
    result = _call_mcp_sync("vector-search", "semantic_search", {
        "query": query,
        "top_k": top_k,
    })
    return result if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# Web Search MCP tools
# ---------------------------------------------------------------------------


def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Web search via web-search-mcp server (SearXNG)."""
    result = _call_mcp_sync("web-search", "web_search", {
        "query": query,
        "num_results": num_results,
    })
    return result if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# Analysis tools (direct LLM — no MCP)
# ---------------------------------------------------------------------------


def rewrite_query(query: str) -> list[str]:
    """Rewrite query into sub-queries via direct LLM call."""
    content, _ = _call_llm(
        [
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
        max_tokens=_MAX_TOKEN_SMALL,
    )
    if content:
        parsed = _extract_json(content)
        if isinstance(parsed, list):
            return [query] + parsed[:3]
    return [query]


def classify_intent(query: str) -> dict:
    """Classify query intent: 'research' or 'casual'."""
    content, tokens = _call_llm(
        [
            {
                "role": "system",
                "content": (
                    "You are a query intent classifier. Classify the user's message into one of two categories:\n"
                    "- \"research\": The user wants in-depth research, analysis, or information retrieval on a topic.\n"
                    "- \"casual\": The user is making a greeting, small talk, asking a simple non-research question, "
                    "or the message is too short/vague to be a research query.\n\n"
                    "Return ONLY a JSON object: {\"intent\": \"research\" or \"casual\", \"reason\": \"brief explanation\"}\n"
                    "When in doubt, classify as \"research\"."
                ),
            },
            {"role": "user", "content": query},
        ],
        max_tokens=64,
        temperature=0.0,
    )
    if content:
        parsed = _extract_json(content)
        if isinstance(parsed, dict) and parsed.get("intent") in ("research", "casual"):
            return {**parsed, "tokens_used": tokens}
    return {"intent": "research", "reason": "default", "tokens_used": tokens}


def direct_response(query: str, language_instruction: str = "") -> dict:
    """Generate a direct conversational response (no research pipeline)."""
    lang_hint = f"\n{language_instruction}" if language_instruction else ""
    content, tokens = _call_llm(
        [
            {
                "role": "system",
                "content": (
                    "You are a friendly research assistant. The user sent a casual message "
                    "(greeting, simple question, or small talk). Respond naturally and briefly. "
                    "If they seem to want research help, suggest they ask a specific research question."
                    f"{lang_hint}"
                ),
            },
            {"role": "user", "content": query},
        ],
        max_tokens=_MAX_TOKEN_SMALL,
        temperature=0.7,
    )
    return {"response": content, "tokens_used": tokens}


def synthesize_context(query: str, passages: list[dict]) -> dict:
    """Synthesize passages via direct LLM call."""
    if not passages:
        return {"synthesis": "No relevant documents found.", "citations": [], "tokens_used": 0}

    context_parts = []
    for i, p in enumerate(passages):
        context_parts.append(
            f"[Source {i+1}: {p.get('document_name', 'unknown')}, chunk {p.get('chunk_index', 0)}]\n{p.get('content', '')}"
        )
    context = "\n\n".join(context_parts)

    content, tokens = _call_llm(
        [
            {
                "role": "system",
                "content": (
                    "You are a research analyst. Synthesize the provided document excerpts "
                    "to answer the user's question. Be comprehensive and accurate. "
                    "Reference sources by their [Source N] identifiers."
                ),
            },
            {"role": "user", "content": f"Question: {query}\n\nDocuments:\n{context}"},
        ],
        max_tokens=_MAX_TOKEN_LARGE,
        temperature=0.2,
    )

    citations = [
        {"document": p.get("document_name", ""), "chunk_index": p.get("chunk_index", 0), "similarity": p.get("similarity", 0)}
        for p in passages
    ]
    return {"synthesis": content, "citations": citations, "tokens_used": tokens}


def generate_plan(
    query: str,
    iteration: int,
    failure_hints: str,
    existing_context: str,
    enable_web_search: bool = False,
) -> dict:
    """Generate research plan via direct LLM call."""
    context_info = ""
    if existing_context:
        context_info = f"\n\nContext gathered so far:\n{existing_context[:2000]}"
    failure_info = ""
    if failure_hints:
        failure_info = f"\n\nPrevious issues to avoid:\n{failure_hints}"

    content, tokens = _call_llm(
        [
            {
                "role": "system",
                "content": (
                    "You are a research planner. Create a structured research plan as a JSON array of steps. "
                    "Each step should have: 'action' (search|analyze|compare|validate), "
                    "'query' (specific search or analysis query), 'purpose' (why this step). "
                    f"This is iteration {iteration}."
                    f"{failure_info}{context_info}"
                ),
            },
            {"role": "user", "content": query},
        ],
        max_tokens=_MAX_TOKEN_MEDIUM,
    )
    if content:
        parsed = _extract_json(content)
        if isinstance(parsed, list):
            return {"plan": parsed, "tokens_used": tokens}
    return {"plan": [{"action": "search", "query": query, "purpose": "Direct search"}], "tokens_used": tokens}


def generate_sectioned_plan(
    query: str,
    iteration: int,
    failure_hints: str,
    existing_context: str,
    language_instruction: str = "",
    enable_web_search: bool = False,
) -> dict:
    """Decompose a research query into 1-3 sub-topics via direct LLM call."""
    web_note = ""
    if enable_web_search:
        web_note = (
            "- You may include web search queries prefixed with 'web:' for topics that "
            "benefit from up-to-date web information\n"
        )
    system_content = (
        "You are a research planner. Given a research question, decompose it into "
        "sub-topics for a structured report. "
        "Choose the MINIMUM number of sections needed:\n"
        "- Pros/cons, comparisons, simple factual questions: strictly 1-2 sections (e.g. 'Advantages' and 'Disadvantages')\n"
        "- Moderate multi-faceted topics: 2-3 sections\n"
        "- Complex broad research requiring deep analysis: 3-5 sections\n\n"
        "IMPORTANT: Fewer sections is better. Do NOT create separate sections for 'introduction', "
        "'overview', 'background', or 'conclusion' — integrate them into the main topic sections.\n\n"
        "Return ONLY a JSON object (no other text) with this shape:\n"
        '{"sub_topics": [{"section_number": 1, "title": "...", "queries": ["search query 1", "..."], "purpose": "..."}, '
        '{"section_number": 2, "title": "...", "queries": [...], "purpose": "..."}], '
        '"summary_query": "one-line summary of the full research"}\n\n'
        "Rules:\n"
        "- Each sub_topic MUST have section_number (starting from 1), title, 1-3 search queries, and a purpose\n"
        "- Return sub_topics in ascending section_number order\n"
        "- Use ONLY as many sections as the query genuinely requires — do NOT pad with unnecessary sections\n"
        "- Sub-topics should cover the question comprehensively without overlap\n"
        f"{web_note}"
        f"- This is iteration {iteration}. Adjust the plan based on any hints below."
    )
    if failure_hints:
        system_content += f"\n\nAvoid these past issues:\n{failure_hints[:500]}"
    if existing_context:
        system_content += f"\n\nContext gathered so far:\n{existing_context[:800]}"
    if language_instruction:
        system_content += f"\n\n{language_instruction}"

    content, tokens = _call_llm(
        [
            {"role": "system", "content": system_content},
            {"role": "user", "content": query},
        ],
        max_tokens=_MAX_TOKEN_MEDIUM,
    )
    def _sort_by_section_number(topics: list[dict]) -> list[dict]:
        return sorted(topics, key=lambda t: t.get("section_number", 99))

    if content:
        parsed = _extract_json(content)
        if isinstance(parsed, dict) and "sub_topics" in parsed:
            sub_topics = _sort_by_section_number(parsed["sub_topics"])
            return {"sub_topics": sub_topics, "summary_query": parsed.get("summary_query", query), "tokens_used": tokens}
        if isinstance(parsed, list):
            sub_topics = [item for item in parsed if isinstance(item, dict) and "title" in item]
            if sub_topics:
                return {"sub_topics": _sort_by_section_number(sub_topics), "summary_query": query, "tokens_used": tokens}
    return {
        "sub_topics": [{"section_number": 1, "title": "Research Report", "queries": [query], "purpose": "Comprehensive analysis"}],
        "summary_query": query,
        "tokens_used": tokens,
    }


def draft_report(
    query: str,
    context: str,
    plan: str,
    previous_draft: str = "",
    improvement_hints: str = "",
    language_instruction: str = "",
) -> dict:
    """Draft report via direct LLM call."""
    system_prompt = (
        "You are a research report writer. Write a comprehensive, well-structured research report "
        "based on the provided context and research plan. Include citations as [Source N]. "
        "Structure: Executive Summary, Key Findings, Detailed Analysis, Conclusion."
    )
    system_prompt += _length_guidance(_MAX_TOKEN_LARGE, language_instruction)
    if language_instruction:
        system_prompt += f"\n\n{language_instruction}"

    user_content = f"Research Question: {query}\n\nResearch Plan:\n{plan}\n\nContext:\n{context[:4000]}"
    if previous_draft:
        user_content += f"\n\nPrevious Draft (improve upon this):\n{previous_draft[:2000]}"
    if improvement_hints:
        user_content += f"\n\nSpecific improvements needed:\n{improvement_hints}"

    content, tokens = _call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=_MAX_TOKEN_LARGE,
    )
    return {"draft": content, "tokens_used": tokens}


def _format_source_entry(idx: int, ctx: dict) -> str:
    """Format a single context entry for LLM prompt, including source URL if available."""
    name = ctx.get("document_name", ctx.get("source", "unknown"))
    metadata = ctx.get("metadata") or {}
    url = metadata.get("source_url", "")
    header = f"[Source {idx+1}: {name}]"
    if url and url.startswith("http"):
        header = f"[Source {idx+1}: {name}]({url})"
    return f"{header}\n{ctx.get('content', '')[:400]}"


def draft_section(
    query: str,
    sub_topic: dict,
    search_context: list[dict],
    previous_content: str = "",
    improvement_hints: str = "",
    language_instruction: str = "",
    stream_callback: Callable[[str], None] | None = None,
) -> dict:
    """Draft a single report section via direct LLM call.

    If *stream_callback* is provided, tokens are streamed to the caller
    in real-time via ``_call_llm_streaming``.
    """
    sub_topic_title = sub_topic.get("title", "Section")
    sub_topic_purpose = sub_topic.get("purpose", "")

    system_prompt = (
        f'You are a research report writer. Write the section titled "{sub_topic_title}" '
        f"for a larger research report.\n"
        f"Purpose of this section: {sub_topic_purpose}\n\n"
        "Guidelines:\n"
        "- Write ONLY this section (do not include executive summary or conclusion for the whole report)\n"
        "- Start with a ## heading matching the section title\n"
        "- Include citations as [Source N] referencing the provided context\n"
        "- Be thorough but focused on this sub-topic only\n"
        "- Use clear structure with sub-headings (###) if needed"
    )
    system_prompt += _length_guidance(_MAX_TOKEN_LARGE, language_instruction)
    if language_instruction:
        system_prompt += f"\n\n{language_instruction}"

    context_text = "\n\n".join(
        _format_source_entry(i, c) for i, c in enumerate(search_context[:4])
    )

    user_content = f"Research Question: {query}\n\nSection: {sub_topic_title}\n\nContext:\n{context_text}"
    if previous_content:
        user_content += f"\n\nPrevious version (improve upon):\n{previous_content[:800]}"
    if improvement_hints:
        user_content += f"\n\nImprovements needed:\n{improvement_hints[:300]}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    if stream_callback:
        content, tokens = _call_llm_streaming(
            messages, max_tokens=_MAX_TOKEN_LARGE, on_chunk=stream_callback,
        )
    else:
        content, tokens = _call_llm(messages, max_tokens=_MAX_TOKEN_LARGE)

    if content.strip():
        return {"content": content, "tokens_used": tokens}
    return {"content": f"## {sub_topic_title}\n\nSection generation failed.", "tokens_used": 0}


def assemble_report(
    sections: list[dict],
    section_order: list[str],
    query: str,
    language_instruction: str = "",
) -> dict:
    """Concatenate completed sections and append a citation reference list.

    No LLM call — sections are already drafted individually, so we only
    need to join them and collect ``[Source N]`` references into a footer.
    """
    import re

    ordered_contents = []
    for title in section_order:
        section = next((s for s in sections if s.get("sub_topic") == title), None)
        if section and section.get("content"):
            ordered_contents.append(section["content"])

    if not ordered_contents:
        return {"draft": "No sections were generated.", "tokens_used": 0}

    body = "\n\n".join(ordered_contents)

    ref_numbers = sorted(set(int(m) for m in re.findall(r"\[Source\s+(\d+)\]", body)))

    all_contexts: list[dict] = []
    for sec in sections:
        all_contexts.extend(sec.get("search_context") or [])

    if ref_numbers and all_contexts:
        lines = ["\n\n---\n\n**References**\n"]
        for n in ref_numbers:
            if n < len(all_contexts):
                ctx = all_contexts[n]
                src = ctx.get("source", f"Source {n}")
                preview = ctx.get("content", "")[:120].replace("\n", " ")
                lines.append(f"- **[Source {n}]** {src}: {preview}")
            else:
                lines.append(f"- **[Source {n}]** (reference)")
        body += "\n".join(lines)

    return {"draft": body, "tokens_used": 0}


# ---------------------------------------------------------------------------
# Verification MCP tools
# ---------------------------------------------------------------------------


def run_verification(
    draft: str,
    query: str,
    context: list[dict],
    iteration: int,
    enable_fact_check: bool = True,
    enable_parallel: bool = True,
) -> dict:
    """Run verification via verification-mcp server."""
    result = _call_mcp_sync("verification", "run_verification", {
        "draft": draft,
        "query": query,
        "context": context,
        "iteration": iteration,
        "enable_fact_check": enable_fact_check,
    })
    if isinstance(result, dict):
        return result
    return {
        "quality_score": 5,
        "quality_details": {},
        "citation_check": {"passed": True},
        "fact_check": {"passed": True},
        "judge_verdict": {"verdict": "fail", "total": 5},
        "passed": False,
        "improvements": ["Verification unavailable"],
        "tokens_used": 0,
    }


def quality_score(draft: str, query: str) -> dict:
    """Score quality via verification-mcp server."""
    result = _call_mcp_sync("verification", "quality_score", {
        "draft": draft,
        "query": query,
    })
    if isinstance(result, dict):
        return result
    return {"overall": 5, "tokens_used": 0}


def verify_sections(
    report_sections: list[dict],
    query: str,
    quality_threshold: float = 7.0,
    enable_parallel: bool = True,
) -> list[str]:
    """Score each section and return failing section titles."""
    section_threshold = quality_threshold * 0.8
    failing: list[str] = []

    for section in report_sections:
        if not section.get("content") or section.get("status") == "passed":
            continue
        sub_topic = section.get("sub_topic", "")
        scores = quality_score(section["content"], f"{query} — section: {sub_topic}")
        section_score = scores.get("overall", 5)
        section["score"] = section_score
        if section_score >= section_threshold:
            section["status"] = "passed"
        else:
            section["status"] = "needs_rewrite"
            failing.append(sub_topic)

    return failing


# ---------------------------------------------------------------------------
# Observability MCP tools
# ---------------------------------------------------------------------------


def record_trace(
    session_id: str,
    iteration: int,
    layer: str,
    operation: str,
    input_summary: str = "",
    output_summary: str = "",
    tokens_used: int = 0,
    latency_ms: int = 0,
    success: bool = True,
    failure_category: str = "",
) -> dict:
    """Record trace via observability-mcp server."""
    try:
        result = _call_mcp_sync("observability", "record_trace", {
            "session_id": session_id,
            "iteration": iteration,
            "layer": layer,
            "operation": operation,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "tokens_used": tokens_used,
            "latency_ms": latency_ms,
            "success": success,
            "failure_category": failure_category,
        })
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def record_failure(
    session_id: str,
    iteration: int,
    category: str,
    description: str,
    context: str = "",
) -> dict:
    """Record failure via observability-mcp server."""
    try:
        result = _call_mcp_sync("observability", "record_failure", {
            "session_id": session_id,
            "iteration": iteration,
            "category": category,
            "description": description,
            "context": context,
        })
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def get_failure_hints(session_id: str) -> str:
    """Get failure hints via observability-mcp server."""
    try:
        result = _call_mcp_sync("observability", "get_failure_hints", {
            "session_id": session_id,
        })
        if isinstance(result, dict):
            return result.get("hints", "")
        return ""
    except Exception:
        return ""


def get_metrics(session_id: str) -> dict:
    """Get metrics via observability-mcp server."""
    try:
        result = _call_mcp_sync("observability", "get_metrics", {
            "session_id": session_id,
        })
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


