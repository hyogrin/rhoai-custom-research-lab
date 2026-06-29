"""Document Processor Agent — Docling-based document ingestion."""

import os

from a2a.types import Message
from a2a.utils.message import get_message_text
from kagenti_adk.server import Server
from kagenti_adk.server.context import RunContext
from kagenti_adk.a2a.types import AgentMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict

from tools import ingest_document, get_document_status


class DocProcessorState(TypedDict):
    file_path: str
    document_id: str
    status: str
    chunk_count: int
    error: str


def parse_node(state: DocProcessorState) -> DocProcessorState:
    """Parse document with Docling and store chunks in pgvector."""
    result = ingest_document(state["file_path"])
    return {
        **state,
        "document_id": result["document_id"],
        "status": result["status"],
        "chunk_count": result["chunk_count"],
        "error": result.get("error", ""),
    }


def build_graph():
    graph = StateGraph(DocProcessorState)
    graph.add_node("parse", parse_node)
    graph.set_entry_point("parse")
    graph.add_edge("parse", END)
    return graph.compile()


processing_graph = build_graph()

server = Server()


@server.agent()
async def doc_processor(input: Message, context: RunContext):
    """Ingest documents using Docling, chunk semantically, and embed into pgvector."""
    text = get_message_text(input)

    if text.startswith("status:"):
        doc_id = text.replace("status:", "").strip()
        status = get_document_status(doc_id)
        yield AgentMessage(text=f"Document {doc_id}: {status}")
        return

    result = await processing_graph.ainvoke({
        "file_path": text.strip(),
        "document_id": "",
        "status": "pending",
        "chunk_count": 0,
        "error": "",
    })

    if result["error"]:
        yield AgentMessage(text=f"Error processing document: {result['error']}")
    else:
        yield AgentMessage(
            text=f"Document ingested successfully. ID: {result['document_id']}, "
                 f"Chunks: {result['chunk_count']}"
        )


def run():
    port = int(os.getenv("DOC_PROCESSOR_PORT", "8101"))
    server.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    run()
