"""Analysis MCP Server — LLM-powered analysis and synthesis tools."""

import json
import os

import httpx
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
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

app = Server("analysis-mcp")


def _get_llm() -> OpenAI:
    return OpenAI(base_url=LLM_BASE_URL, api_key=_EFFECTIVE_LLM_KEY, http_client=_HTTP_CLIENT)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="rewrite_query",
            description="Rewrite a research query into multiple search-optimized sub-queries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Original research query"},
                    "num_variants": {"type": "integer", "description": "Number of sub-queries to generate", "default": 3},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="synthesize_context",
            description="Synthesize retrieved passages into a coherent context summary with citations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Original research question"},
                    "passages": {
                        "type": "array",
                        "description": "Retrieved document passages",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "document_name": {"type": "string"},
                                "chunk_index": {"type": "integer"},
                                "similarity": {"type": "number"},
                            },
                        },
                    },
                },
                "required": ["query", "passages"],
            },
        ),
        Tool(
            name="generate_research_plan",
            description="Generate a structured research plan from a query, considering past failures.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Research query"},
                    "iteration": {"type": "integer", "description": "Current iteration number", "default": 1},
                    "failure_hints": {"type": "string", "description": "Hints from past failures to avoid", "default": ""},
                    "existing_context": {"type": "string", "description": "Context accumulated so far", "default": ""},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="draft_report",
            description="Draft a research report from accumulated context and research plan.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Original research question"},
                    "context": {"type": "string", "description": "Accumulated research context"},
                    "plan": {"type": "string", "description": "Research plan being followed"},
                    "previous_draft": {"type": "string", "description": "Previous draft to improve upon", "default": ""},
                    "improvement_hints": {"type": "string", "description": "Specific areas to improve", "default": ""},
                },
                "required": ["query", "context", "plan"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "rewrite_query":
        result = _rewrite_query(arguments["query"], arguments.get("num_variants", 3))
    elif name == "synthesize_context":
        result = _synthesize_context(arguments["query"], arguments["passages"])
    elif name == "generate_research_plan":
        result = _generate_research_plan(
            arguments["query"],
            arguments.get("iteration", 1),
            arguments.get("failure_hints", ""),
            arguments.get("existing_context", ""),
        )
    elif name == "draft_report":
        result = _draft_report(
            arguments["query"],
            arguments["context"],
            arguments["plan"],
            arguments.get("previous_draft", ""),
            arguments.get("improvement_hints", ""),
        )
    else:
        result = {"error": f"Unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(result, default=str))]


def _rewrite_query(query: str, num_variants: int = 3) -> dict:
    client = _get_llm()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
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
        temperature=0.3,
        max_tokens=_MAX_TOKEN_SMALL,
    )

    content = response.choices[0].message.content
    tokens = response.usage.total_tokens if response.usage else 0

    try:
        queries = json.loads(content)
        if isinstance(queries, list):
            return {"queries": [query] + queries[:num_variants], "tokens_used": tokens}
    except (json.JSONDecodeError, IndexError):
        pass
    return {"queries": [query], "tokens_used": tokens}


def _synthesize_context(query: str, passages: list[dict]) -> dict:
    if not passages:
        return {"synthesis": "No relevant documents found.", "citations": [], "tokens_used": 0}

    context_parts = []
    for i, p in enumerate(passages):
        context_parts.append(
            f"[Source {i+1}: {p.get('document_name', 'unknown')}, chunk {p.get('chunk_index', 0)}]\n{p.get('content', '')}"
        )
    context = "\n\n".join(context_parts)

    client = _get_llm()
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
            {"role": "user", "content": f"Question: {query}\n\nDocuments:\n{context}"},
        ],
        temperature=0.2,
        max_tokens=_MAX_TOKEN_LARGE,
    )

    tokens = response.usage.total_tokens if response.usage else 0
    synthesis = response.choices[0].message.content
    citations = [
        {"document": p.get("document_name", ""), "chunk_index": p.get("chunk_index", 0), "similarity": p.get("similarity", 0)}
        for p in passages
    ]

    return {"synthesis": synthesis, "citations": citations, "tokens_used": tokens}


def _generate_research_plan(query: str, iteration: int, failure_hints: str, existing_context: str) -> dict:
    context_info = ""
    if existing_context:
        context_info = f"\n\nContext gathered so far:\n{existing_context[:2000]}"
    failure_info = ""
    if failure_hints:
        failure_info = f"\n\nPrevious issues to avoid:\n{failure_hints}"

    client = _get_llm()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
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
        temperature=0.3,
        max_tokens=_MAX_TOKEN_MEDIUM,
    )

    content = response.choices[0].message.content
    tokens = response.usage.total_tokens if response.usage else 0

    try:
        plan = json.loads(content)
        if isinstance(plan, list):
            return {"plan": plan, "tokens_used": tokens}
    except (json.JSONDecodeError, IndexError):
        pass

    return {
        "plan": [{"action": "search", "query": query, "purpose": "Direct search for the question"}],
        "tokens_used": tokens,
    }


def _draft_report(query: str, context: str, plan: str, previous_draft: str, improvement_hints: str) -> dict:
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

    client = _get_llm()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
        max_tokens=_MAX_TOKEN_LARGE,
    )

    tokens = response.usage.total_tokens if response.usage else 0
    return {"draft": response.choices[0].message.content, "tokens_used": tokens}


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
