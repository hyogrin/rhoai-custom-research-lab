"""Reviewer tools: MCP client wrappers for verification server."""

import asyncio
import json
import logging
import os

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv()

logger = logging.getLogger(__name__)

VERIFICATION_MCP_URL = os.getenv("VERIFICATION_MCP_URL", "http://127.0.0.1:9004")
_MCP_ENDPOINT = "/mcp"


async def _call_mcp_tool(url: str, tool_name: str, arguments: dict):
    """Call a tool on a remote MCP server via streamable-http."""
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            if result.content and len(result.content) > 0:
                try:
                    return json.loads(result.content[0].text)
                except (json.JSONDecodeError, TypeError):
                    return result.content[0].text
            return None


def _call_sync(url: str, tool_name: str, arguments: dict):
    """Synchronous wrapper for MCP tool calls."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _call_mcp_tool(url, tool_name, arguments))
            return future.result(timeout=120)
    else:
        return asyncio.run(_call_mcp_tool(url, tool_name, arguments))


def score_quality(report: str) -> float:
    """Score quality via verification-mcp."""
    result = _call_sync(
        f"{VERIFICATION_MCP_URL}{_MCP_ENDPOINT}",
        "quality_score",
        {"draft": report, "query": "Evaluate this research report"},
    )
    if isinstance(result, dict):
        return float(result.get("overall", 5.0))
    return 5.0


def validate_citations(report: str) -> bool:
    """Validate citations via verification-mcp."""
    result = _call_sync(
        f"{VERIFICATION_MCP_URL}{_MCP_ENDPOINT}",
        "validate_citations",
        {"draft": report, "num_sources": 10},
    )
    if isinstance(result, dict):
        return result.get("passed", False)
    return True


def generate_feedback(report: str, quality_score: float, citation_valid: bool) -> str:
    """Generate feedback via verification-mcp (llm_as_judge)."""
    result = _call_sync(
        f"{VERIFICATION_MCP_URL}{_MCP_ENDPOINT}",
        "llm_as_judge",
        {"draft": report, "query": "Evaluate and provide improvement suggestions"},
    )
    if isinstance(result, dict):
        reasoning = result.get("reasoning", "")
        improvements = result.get("improvements", [])
        return f"{reasoning}\n\nImprovements:\n" + "\n".join(f"- {imp}" for imp in improvements)
    return str(result) if result else "No feedback available."
