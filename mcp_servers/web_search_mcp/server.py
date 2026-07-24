"""Web Search MCP Server — SearXNG-based web search tool."""

import os

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8888")
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")

mcp = FastMCP("web-search-mcp", host="0.0.0.0", port=9003, stateless_http=True)


@mcp.tool()
def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Search the web via SearXNG. Returns list of {title, url, content}."""
    try:
        verify = not SEARXNG_URL.startswith("https://") or _VERIFY_SSL
        client = httpx.Client(verify=verify, timeout=httpx.Timeout(15.0))
        resp = client.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "engines": "google,duckduckgo"},
        )
        client.close()
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in data.get("results", [])[:num_results]
        ]
    except Exception:
        return []


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
