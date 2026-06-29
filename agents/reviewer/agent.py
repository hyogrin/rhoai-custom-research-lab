"""Research Reviewer Agent — Quality validation and scoring."""

import os

from a2a.types import Message
from a2a.utils.message import get_message_text
from kagenti_adk.server import Server
from kagenti_adk.server.context import RunContext
from kagenti_adk.a2a.types import AgentMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict

from tools import score_quality, validate_citations, generate_feedback


class ReviewState(TypedDict):
    report: str
    quality_score: float
    citation_valid: bool
    feedback: str
    approved: bool


def quality_node(state: ReviewState) -> ReviewState:
    """Score the overall quality of the research report."""
    score = score_quality(state["report"])
    return {**state, "quality_score": score}


def citation_node(state: ReviewState) -> ReviewState:
    """Validate that citations are properly referenced."""
    valid = validate_citations(state["report"])
    return {**state, "citation_valid": valid}


def feedback_node(state: ReviewState) -> ReviewState:
    """Generate improvement feedback if needed."""
    approved = state["quality_score"] >= 7.0 and state["citation_valid"]
    feedback = ""
    if not approved:
        feedback = generate_feedback(state["report"], state["quality_score"], state["citation_valid"])
    return {**state, "feedback": feedback, "approved": approved}


def build_graph():
    graph = StateGraph(ReviewState)
    graph.add_node("quality", quality_node)
    graph.add_node("citations", citation_node)
    graph.add_node("feedback", feedback_node)
    graph.set_entry_point("quality")
    graph.add_edge("quality", "citations")
    graph.add_edge("citations", "feedback")
    graph.add_edge("feedback", END)
    return graph.compile()


review_graph = build_graph()

server = Server()


@server.agent()
async def research_reviewer(input: Message, context: RunContext):
    """Review research reports for quality, accuracy, and citation integrity."""
    report = get_message_text(input)

    result = await review_graph.ainvoke({
        "report": report,
        "quality_score": 0.0,
        "citation_valid": False,
        "feedback": "",
        "approved": False,
    })

    review_result = {
        "approved": result["approved"],
        "quality_score": result["quality_score"],
        "citation_valid": result["citation_valid"],
        "feedback": result["feedback"],
    }

    status = "APPROVED" if result["approved"] else "NEEDS REVISION"
    response = (
        f"## Review Result: {status}\n\n"
        f"- **Quality Score**: {result['quality_score']}/10\n"
        f"- **Citations Valid**: {'Yes' if result['citation_valid'] else 'No'}\n"
    )
    if result["feedback"]:
        response += f"\n### Feedback\n\n{result['feedback']}"

    yield AgentMessage(text=response)


def run():
    port = int(os.getenv("REVIEWER_PORT", "8104"))
    server.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    run()
