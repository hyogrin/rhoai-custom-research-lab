"""Analysis MCP Server — LLM-powered analysis and synthesis tools."""

import json
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from openai import OpenAI

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
LLM_MODEL = os.getenv("LLM_MODEL", "granite-3.3-8b-instruct")
MAAS_API_KEY = os.getenv("MAAS_API_KEY", "")
_EFFECTIVE_LLM_KEY = MAAS_API_KEY if MAAS_API_KEY else LLM_API_KEY
_MAX_TOKEN_SMALL = int(os.getenv("LLM_MAX_TOKEN_SMALL", "512"))
_MAX_TOKEN_MEDIUM = int(os.getenv("LLM_MAX_TOKEN_MEDIUM", "1024"))
_MAX_TOKEN_LARGE = int(os.getenv("LLM_MAX_TOKEN_LARGE", "4096"))
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")
_HTTP_CLIENT = None if _VERIFY_SSL else httpx.Client(verify=False, timeout=httpx.Timeout(300.0))

mcp = FastMCP("analysis-mcp", host="0.0.0.0", port=9003, stateless_http=True)


def _get_llm() -> OpenAI:
    return OpenAI(base_url=LLM_BASE_URL, api_key=_EFFECTIVE_LLM_KEY, http_client=_HTTP_CLIENT)


def _call_llm(messages: list[dict], max_tokens: int, temperature: float = 0.3) -> tuple[str, int]:
    """Call the LLM and return (content, tokens_used)."""
    client = _get_llm()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content or ""
    tokens = response.usage.total_tokens if response.usage else 0
    return content, tokens


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
# Existing tools (converted from manual dispatch to @mcp.tool)
# ---------------------------------------------------------------------------


@mcp.tool()
def rewrite_query(query: str, num_variants: int = 3) -> dict:
    """Rewrite a research query into multiple search-optimized sub-queries."""
    content, tokens = _call_llm(
        [
            {
                "role": "system",
                "content": (
                    f"You are a search query optimizer. Given a research question, "
                    f"generate {num_variants} diverse search queries that would help find relevant information. "
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
            return {"queries": [query] + parsed[:num_variants], "tokens_used": tokens}
    return {"queries": [query], "tokens_used": tokens}


@mcp.tool()
def synthesize_context(query: str, passages: list[dict]) -> dict:
    """Synthesize retrieved passages into a coherent context summary with citations."""
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


@mcp.tool()
def generate_research_plan(
    query: str,
    iteration: int = 1,
    failure_hints: str = "",
    existing_context: str = "",
) -> dict:
    """Generate a structured research plan from a query, considering past failures."""
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

    return {
        "plan": [{"action": "search", "query": query, "purpose": "Direct search for the question"}],
        "tokens_used": tokens,
    }


@mcp.tool()
def draft_report(
    query: str,
    context: str,
    plan: str,
    previous_draft: str = "",
    improvement_hints: str = "",
) -> dict:
    """Draft a research report from accumulated context and research plan."""
    system_prompt = (
        "You are a research report writer. Write a comprehensive, well-structured research report "
        "based on the provided context and research plan. Include citations as [Source N]. "
        "Structure: Executive Summary, Key Findings, Detailed Analysis, Conclusion."
    )

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


# ---------------------------------------------------------------------------
# New tools (ported from agents/orchestrator/layers/tools.py)
# ---------------------------------------------------------------------------


@mcp.tool()
def generate_sectioned_plan(
    query: str,
    iteration: int = 1,
    failure_hints: str = "",
    existing_context: str = "",
    language_instruction: str = "",
    enable_web_search: bool = False,
) -> dict:
    """Decompose a research query into 2-5 sub-topics, each with search queries."""
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

    content, tokens = _call_llm(
        [
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
            sub_topics = [item for item in parsed if isinstance(item, dict) and "title" in item]
            if sub_topics:
                return {"sub_topics": sub_topics, "summary_query": query, "tokens_used": tokens}
    return {
        "sub_topics": [{"title": "Research Report", "queries": [query], "purpose": "Comprehensive analysis"}],
        "summary_query": query,
        "tokens_used": tokens,
    }


@mcp.tool()
def draft_section(
    query: str,
    sub_topic_title: str,
    sub_topic_purpose: str = "",
    search_context: list[dict] = [],
    previous_content: str = "",
    improvement_hints: str = "",
    language_instruction: str = "",
) -> dict:
    """Draft a single report section for one sub-topic."""
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
    if language_instruction:
        system_prompt += f"\n\n{language_instruction}"

    context_text = "\n\n".join(
        f"[Source {i+1}: {c.get('document_name', c.get('source', 'unknown'))}]\n{c.get('content', '')[:600]}"
        for i, c in enumerate(search_context[:8])
    )

    user_content = f"Research Question: {query}\n\nSection: {sub_topic_title}\n\nContext:\n{context_text}"
    if previous_content:
        user_content += f"\n\nPrevious version (improve upon):\n{previous_content[:800]}"
    if improvement_hints:
        user_content += f"\n\nImprovements needed:\n{improvement_hints[:300]}"

    content, tokens = _call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=_MAX_TOKEN_LARGE,
    )
    if content.strip():
        return {"content": content, "tokens_used": tokens}
    return {"content": f"## {sub_topic_title}\n\nSection generation failed.", "tokens_used": 0}


@mcp.tool()
def assemble_report(
    sections: list[dict],
    section_order: list[str],
    query: str,
    language_instruction: str = "",
) -> dict:
    """Concatenate completed sections into a full report with an executive summary."""
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

    summary_content, tokens = _call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Research Question: {query}\n\nSections:\n{body[:3000]}"},
        ],
        max_tokens=_MAX_TOKEN_MEDIUM,
    )

    if summary_content.strip():
        full_report = f"# Executive Summary\n\n{summary_content}\n\n{body}"
    else:
        full_report = body

    return {"draft": full_report, "tokens_used": tokens}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
