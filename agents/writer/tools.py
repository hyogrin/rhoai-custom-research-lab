"""Writer tools: MCP client wrappers for analysis server."""

import asyncio
import json
import logging
import os

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv()

logger = logging.getLogger(__name__)

ANALYSIS_MCP_URL = os.getenv("ANALYSIS_MCP_URL", "http://127.0.0.1:9003")
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


def plan_report_structure(query: str, context: str) -> str:
    """Plan report structure via analysis-mcp (generate_research_plan)."""
    result = _call_sync(
        f"{ANALYSIS_MCP_URL}{_MCP_ENDPOINT}",
        "generate_research_plan",
        {"query": query, "existing_context": context},
    )
    if isinstance(result, dict):
        plan = result.get("plan", [])
        return "\n".join(f"{i+1}. {s.get('query', '')}" for i, s in enumerate(plan))
    return str(result) if result else ""


def generate_report(query: str, context: str, instructions: str) -> str:
    """Generate a report via analysis-mcp (draft_report)."""
    result = _call_sync(
        f"{ANALYSIS_MCP_URL}{_MCP_ENDPOINT}",
        "draft_report",
        {"query": query, "context": context, "plan": instructions},
    )
    if isinstance(result, dict):
        return result.get("draft", "")
    return str(result) if result else ""


def format_citations(context: str) -> str:
    """Format citations via analysis-mcp (synthesize_context)."""
    result = _call_sync(
        f"{ANALYSIS_MCP_URL}{_MCP_ENDPOINT}",
        "synthesize_context",
        {"query": "Extract and format source references", "passages": [{"content": context[:3000], "document_name": "sources", "chunk_index": 0, "similarity": 1.0}]},
    )
    if isinstance(result, dict):
        return result.get("synthesis", "")
    return str(result) if result else ""
