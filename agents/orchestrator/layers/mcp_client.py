"""MCP Client Layer — Routes tool calls through MCP servers via streamable-http transport.

Replaces direct function calls in tools.py with MCP protocol-based calls to
remote servers. Provides the same function signatures for backward compatibility.
"""

import asyncio
import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv()

logger = logging.getLogger(__name__)

DOC_MCP_URL = os.getenv("DOC_MCP_URL", "http://127.0.0.1:9001")
SEARCH_MCP_URL = os.getenv("SEARCH_MCP_URL", "http://127.0.0.1:9002")
ANALYSIS_MCP_URL = os.getenv("ANALYSIS_MCP_URL", "http://127.0.0.1:9003")
VERIFICATION_MCP_URL = os.getenv("VERIFICATION_MCP_URL", "http://127.0.0.1:9004")
OBSERVABILITY_MCP_URL = os.getenv("OBSERVABILITY_MCP_URL", "http://127.0.0.1:9005")

_MCP_ENDPOINT = "/mcp"

SERVER_URLS = {
    "doc": f"{DOC_MCP_URL}{_MCP_ENDPOINT}",
    "search": f"{SEARCH_MCP_URL}{_MCP_ENDPOINT}",
    "analysis": f"{ANALYSIS_MCP_URL}{_MCP_ENDPOINT}",
    "verification": f"{VERIFICATION_MCP_URL}{_MCP_ENDPOINT}",
    "observability": f"{OBSERVABILITY_MCP_URL}{_MCP_ENDPOINT}",
}


async def _call_mcp_tool(server: str, tool_name: str, arguments: dict) -> Any:
    """Call a tool on a remote MCP server via streamable-http transport."""
    url = SERVER_URLS[server]
    async with streamablehttp_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            if result.content and len(result.content) > 0:
                text = result.content[0].text
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
            return None


def _call_mcp_sync(server: str, tool_name: str, arguments: dict) -> Any:
    """Synchronous wrapper for MCP tool calls. Thread-safe."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run, _call_mcp_tool(server, tool_name, arguments)
            )
            return future.result(timeout=120)
    else:
        return asyncio.run(_call_mcp_tool(server, tool_name, arguments))


# ---------------------------------------------------------------------------
# Search MCP tools
# ---------------------------------------------------------------------------


def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """Semantic search via search-mcp server."""
    result = _call_mcp_sync("search", "semantic_search", {
        "query": query,
        "top_k": top_k,
    })
    return result if isinstance(result, list) else []


def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Web search via search-mcp server (SearXNG)."""
    result = _call_mcp_sync("search", "web_search", {
        "query": query,
        "num_results": num_results,
    })
    return result if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# Analysis MCP tools
# ---------------------------------------------------------------------------


def rewrite_query(query: str) -> list[str]:
    """Rewrite query into sub-queries via analysis-mcp server."""
    result = _call_mcp_sync("analysis", "rewrite_query", {"query": query})
    if isinstance(result, dict):
        return result.get("queries", [query])
    return [query]


def synthesize_context(query: str, passages: list[dict]) -> dict:
    """Synthesize passages via analysis-mcp server."""
    result = _call_mcp_sync("analysis", "synthesize_context", {
        "query": query,
        "passages": passages,
    })
    if isinstance(result, dict):
        return result
    return {"synthesis": "Synthesis unavailable.", "citations": [], "tokens_used": 0}


def generate_plan(
    query: str,
    iteration: int,
    failure_hints: str,
    existing_context: str,
    enable_web_search: bool = False,
) -> dict:
    """Generate research plan via analysis-mcp server."""
    result = _call_mcp_sync("analysis", "generate_research_plan", {
        "query": query,
        "iteration": iteration,
        "failure_hints": failure_hints,
        "existing_context": existing_context,
    })
    if isinstance(result, dict):
        return result
    return {"plan": [{"action": "search", "query": query, "purpose": "Direct search"}], "tokens_used": 0}


def generate_sectioned_plan(
    query: str,
    iteration: int,
    failure_hints: str,
    existing_context: str,
    language_instruction: str = "",
    enable_web_search: bool = False,
) -> dict:
    """Generate sectioned plan via analysis-mcp server."""
    result = _call_mcp_sync("analysis", "generate_sectioned_plan", {
        "query": query,
        "iteration": iteration,
        "failure_hints": failure_hints,
        "existing_context": existing_context,
        "language_instruction": language_instruction,
        "enable_web_search": enable_web_search,
    })
    if isinstance(result, dict):
        return result
    return {
        "sub_topics": [{"title": "Research Report", "queries": [query], "purpose": "Comprehensive analysis"}],
        "summary_query": query,
        "tokens_used": 0,
    }


def draft_report(
    query: str,
    context: str,
    plan: str,
    previous_draft: str = "",
    improvement_hints: str = "",
    language_instruction: str = "",
) -> dict:
    """Draft report via analysis-mcp server."""
    result = _call_mcp_sync("analysis", "draft_report", {
        "query": query,
        "context": context,
        "plan": plan,
        "previous_draft": previous_draft,
        "improvement_hints": improvement_hints,
    })
    if isinstance(result, dict):
        return result
    return {"draft": "Report generation failed.", "tokens_used": 0}


def draft_section(
    query: str,
    sub_topic: dict,
    search_context: list[dict],
    previous_content: str = "",
    improvement_hints: str = "",
    language_instruction: str = "",
) -> dict:
    """Draft a single report section via analysis-mcp server."""
    result = _call_mcp_sync("analysis", "draft_section", {
        "query": query,
        "sub_topic_title": sub_topic.get("title", "Section"),
        "sub_topic_purpose": sub_topic.get("purpose", ""),
        "search_context": search_context,
        "previous_content": previous_content,
        "improvement_hints": improvement_hints,
        "language_instruction": language_instruction,
    })
    if isinstance(result, dict):
        return result
    return {"content": f"## {sub_topic.get('title', 'Section')}\n\nSection generation failed.", "tokens_used": 0}


def assemble_report(
    sections: list[dict],
    section_order: list[str],
    query: str,
    language_instruction: str = "",
) -> dict:
    """Assemble full report via analysis-mcp server."""
    result = _call_mcp_sync("analysis", "assemble_report", {
        "sections": sections,
        "section_order": section_order,
        "query": query,
        "language_instruction": language_instruction,
    })
    if isinstance(result, dict):
        return result
    return {"draft": "No sections were generated.", "tokens_used": 0}


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
    """Score each section and return failing section titles.

    Uses the verification-mcp quality_score tool per section.
    """
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


# ---------------------------------------------------------------------------
# Document MCP tools
# ---------------------------------------------------------------------------


def ingest_document(file_path: str) -> dict:
    """Ingest document via doc-mcp server."""
    result = _call_mcp_sync("doc", "ingest_document", {"file_path": file_path})
    if isinstance(result, dict):
        return result
    return {"document_id": "", "status": "error", "error": "MCP call failed"}


def get_document_status(document_id: str) -> dict:
    """Get document status via doc-mcp server."""
    result = _call_mcp_sync("doc", "get_document_status", {"document_id": document_id})
    if isinstance(result, dict):
        return result
    return {"error": "MCP call failed"}


def list_documents() -> list[dict]:
    """List documents via doc-mcp server."""
    result = _call_mcp_sync("doc", "list_documents", {})
    return result if isinstance(result, list) else []
