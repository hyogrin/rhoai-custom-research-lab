"""Research Writer Agent — Generates structured research reports with citations."""

import os

from a2a.types import Message
from a2a.utils.message import get_message_text
from kagenti_adk.server import Server
from kagenti_adk.server.context import RunContext
from kagenti_adk.a2a.types import AgentMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict

from tools import generate_report, format_citations


class WriterState(TypedDict):
    query: str
    context: str
    instructions: str
    report: str
    citations: str


def plan_node(state: WriterState) -> WriterState:
    """Plan the report structure based on the query and context."""
    from tools import plan_report_structure
    plan = plan_report_structure(state["query"], state["context"])
    return {**state, "instructions": plan}


def write_node(state: WriterState) -> WriterState:
    """Generate the research report."""
    report = generate_report(state["query"], state["context"], state["instructions"])
    return {**state, "report": report}


def cite_node(state: WriterState) -> WriterState:
    """Add properly formatted citations to the report."""
    citations = format_citations(state["context"])
    return {**state, "citations": citations}


def build_graph():
    graph = StateGraph(WriterState)
    graph.add_node("plan", plan_node)
    graph.add_node("write", write_node)
    graph.add_node("cite", cite_node)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "write")
    graph.add_edge("write", "cite")
    graph.add_edge("cite", END)
    return graph.compile()


writer_graph = build_graph()

server = Server()


@server.agent()
async def research_writer(input: Message, context: RunContext):
    """Generate comprehensive research reports with structured citations."""
    text = get_message_text(input)

    result = await writer_graph.ainvoke({
        "query": text,
        "context": context.get("research_context", text) if hasattr(context, "get") else text,
        "instructions": "",
        "report": "",
        "citations": "",
    })

    output = result["report"]
    if result["citations"]:
        output += f"\n\n---\n\n## References\n\n{result['citations']}"

    yield AgentMessage(text=output)


def run():
    port = int(os.getenv("WRITER_PORT", "8103"))
    server.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    run()
