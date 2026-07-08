"""Research tools: MCP client wrappers for search and analysis servers."""

import asyncio
import json
import logging
import os

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv()

logger = logging.getLogger(__name__)

SEARCH_MCP_URL = os.getenv("SEARCH_MCP_URL", "http://127.0.0.1:9002")
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


def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """Search pgvector for semantically similar document chunks via search-mcp."""
    result = _call_sync(
        f"{SEARCH_MCP_URL}{_MCP_ENDPOINT}",
        "semantic_search",
        {"query": query, "top_k": top_k},
    )
    return result if isinstance(result, list) else []


def rewrite_query(query: str) -> list[str]:
    """Rewrite a query into multiple search-optimized sub-queries via analysis-mcp."""
    result = _call_sync(
        f"{ANALYSIS_MCP_URL}{_MCP_ENDPOINT}",
        "rewrite_query",
        {"query": query},
    )
    if isinstance(result, dict):
        return result.get("queries", [query])
    return [query]


def synthesize_context(query: str, passages: list[dict]) -> dict:
    """Synthesize retrieved passages via analysis-mcp."""
    result = _call_sync(
        f"{ANALYSIS_MCP_URL}{_MCP_ENDPOINT}",
        "synthesize_context",
        {"query": query, "passages": passages},
    )
    if isinstance(result, dict):
        return result
    return {"synthesis": "Synthesis unavailable.", "citations": []}
