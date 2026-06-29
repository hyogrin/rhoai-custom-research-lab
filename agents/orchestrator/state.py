"""Research session state definition for the iterative harness controller."""

from typing import TypedDict


class ResearchState(TypedDict):
    """LangGraph state for the iterative harness-controlled research pipeline.

    This replaces the old linear OrchestratorState with a versioned,
    iteration-aware state that supports the long transaction pattern.
    """

    # Input
    session_id: str
    query: str
    file_path: str
    has_document: bool

    # Iteration control
    iteration: int
    max_iterations: int
    quality_threshold: float
    language_instruction: str

    # Evolving research state
    research_plan: list[dict]
    accumulated_context: list[dict]
    current_draft: str

    # Verification
    verification_result: dict
    verification_history: list[dict]
    quality_score: float

    # Observability
    total_tokens: int
    total_cost: float
    failure_hints: str

    # Control flow
    status: str  # normalizing|planning|researching|writing|verifying|observing|complete|failed
    final_output: str
    error: str
