"""Research Analyst Agent — RAG-based document research with pgvector."""

import os

from a2a.types import Message
from a2a.utils.message import get_message_text
from kagenti_adk.server import Server
from kagenti_adk.server.context import RunContext
from kagenti_adk.a2a.types import AgentMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict

from tools import semantic_search, rewrite_query, synthesize_context


class ResearchState(TypedDict):
    original_query: str
    rewritten_queries: list[str]
    retrieved_passages: list[dict]
    synthesis: str
    citations: list[dict]


def rewrite_node(state: ResearchState) -> ResearchState:
    """Rewrite the query into multiple search-optimized sub-queries."""
    queries = rewrite_query(state["original_query"])
    return {**state, "rewritten_queries": queries}


def search_node(state: ResearchState) -> ResearchState:
    """Search pgvector for relevant passages across all sub-queries."""
    all_passages = []
    seen_ids = set()
    for query in state["rewritten_queries"]:
        results = semantic_search(query, top_k=5)
        for r in results:
            if r["id"] not in seen_ids:
                all_passages.append(r)
                seen_ids.add(r["id"])
    return {**state, "retrieved_passages": all_passages}


def synthesize_node(state: ResearchState) -> ResearchState:
    """Synthesize retrieved passages into a coherent context summary."""
    result = synthesize_context(state["original_query"], state["retrieved_passages"])
    return {
        **state,
        "synthesis": result["synthesis"],
        "citations": result["citations"],
    }


def build_graph():
    graph = StateGraph(ResearchState)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("search", search_node)
    graph.add_node("synthesize", synthesize_node)
    graph.set_entry_point("rewrite")
    graph.add_edge("rewrite", "search")
    graph.add_edge("search", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


research_graph = build_graph()

server = Server()


@server.agent()
async def research_analyst(input: Message, context: RunContext):
    """Search indexed documents and synthesize relevant context with citations."""
    query = get_message_text(input)

    result = await research_graph.ainvoke({
        "original_query": query,
        "rewritten_queries": [],
        "retrieved_passages": [],
        "synthesis": "",
        "citations": [],
    })

    response_text = result["synthesis"]
    if result["citations"]:
        response_text += "\n\n**Sources:**\n"
        for i, cite in enumerate(result["citations"], 1):
            response_text += f"{i}. {cite['document']} (chunk {cite['chunk_index']})\n"

    yield AgentMessage(text=response_text)


def run():
    port = int(os.getenv("RESEARCHER_PORT", "8102"))
    server.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    run()
