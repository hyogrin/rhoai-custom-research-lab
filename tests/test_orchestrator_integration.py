"""Integration tests for agents/orchestrator/agent.py."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_mcp_functions():
    """Patch all MCP client functions at the point of use in the orchestrator module."""
    patches = {
        "semantic_search": patch(
            "agents.orchestrator.agent.semantic_search",
            return_value=[
                {"document_id": "doc-1", "document_name": "paper.pdf", "chunk_index": 0, "content": "AI research findings", "similarity": 0.9},
            ],
        ),
        "web_search": patch(
            "agents.orchestrator.agent.web_search",
            return_value=[
                {"title": "AI Overview", "url": "https://example.com/ai", "content": "AI is transforming the world"},
            ],
        ),
        "synthesize_context": patch(
            "agents.orchestrator.agent.synthesize_context",
            return_value={"synthesis": "AI research synthesis", "citations": [], "tokens_used": 100},
        ),
        "generate_plan": patch(
            "agents.orchestrator.agent.generate_plan",
            return_value={
                "plan": [{"action": "search", "query": "AI fundamentals", "purpose": "Basic research"}],
                "tokens_used": 50,
            },
        ),
        "generate_sectioned_plan": patch(
            "agents.orchestrator.agent.generate_sectioned_plan",
            return_value={
                "sub_topics": [{"title": "Overview", "queries": ["AI overview"], "purpose": "Introduction"}],
                "tokens_used": 50,
            },
        ),
        "draft_report": patch(
            "agents.orchestrator.agent.draft_report",
            return_value={"draft": "# Research Report\n\nAI is important [Source 1].", "tokens_used": 200},
        ),
        "draft_section": patch(
            "agents.orchestrator.agent.draft_section",
            return_value={"content": "## Overview\n\nAI section content", "tokens_used": 150},
        ),
        "assemble_report": patch(
            "agents.orchestrator.agent.assemble_report",
            return_value={"draft": "# Executive Summary\n\nFull report assembled.", "tokens_used": 100},
        ),
        "run_verification": patch(
            "agents.orchestrator.agent.run_verification",
            return_value={
                "quality_score": 8,
                "quality_details": {"completeness": 8, "accuracy": 8, "clarity": 8, "structure": 8},
                "citation_check": {"passed": True},
                "fact_check": {"passed": True},
                "judge_verdict": {"verdict": "pass", "total": 8},
                "passed": True,
                "improvements": [],
                "tokens_used": 150,
            },
        ),
        "verify_sections": patch(
            "agents.orchestrator.agent.verify_sections",
            return_value=[],
        ),
    }

    started = {}
    for name, p in patches.items():
        started[name] = p.start()

    yield started

    for p in patches.values():
        p.stop()


@pytest.fixture
def mock_session_manager():
    """Patch SessionManager to avoid real DB calls."""
    with patch("agents.orchestrator.agent.SessionManager") as mock_cls:
        mock_mgr = MagicMock()
        mock_cls.return_value = mock_mgr
        yield mock_mgr


@pytest.fixture
def mock_observer():
    """Patch HarnessObserver to avoid real observability calls."""
    with patch("agents.orchestrator.agent.HarnessObserver") as mock_cls:
        mock_obs = MagicMock()
        mock_obs.get_improvement_hints.return_value = ""
        mock_obs.get_summary.return_value = {"metrics": {}, "total_cost": 0.0}
        mock_cls.return_value = mock_obs
        yield mock_obs


@pytest.fixture
def mock_checkpoint():
    """Patch checkpoint_session to avoid DB writes."""
    with patch("agents.orchestrator.agent.checkpoint_session"):
        yield


@pytest.fixture
def mock_failure_memory():
    """Patch load_past_failure_memory."""
    with patch("agents.orchestrator.agent.load_past_failure_memory", return_value=""):
        yield


class TestBuildGraph:
    def test_returns_compiled_graph(self, mock_session_manager, mock_checkpoint, mock_failure_memory):
        from agents.orchestrator.agent import build_graph

        graph = build_graph()

        assert graph is not None
        assert hasattr(graph, "invoke")
        assert hasattr(graph, "astream")

    def test_graph_has_expected_nodes(self, mock_session_manager, mock_checkpoint, mock_failure_memory):
        from agents.orchestrator.agent import build_graph

        graph = build_graph()

        node_names = set(graph.nodes.keys())
        expected = {"normalize", "plan", "execute", "verify", "observe", "iterate", "finalize", "__start__"}
        assert expected.issubset(node_names)


class TestShouldIterate:
    def test_finalizes_when_quality_above_threshold(self):
        from agents.orchestrator.agent import should_iterate

        state = {"quality_score": 8.0, "quality_threshold": 7.0, "iteration": 1, "max_iterations": 3}
        result = should_iterate(state)

        assert result == "finalize"

    def test_finalizes_when_max_iterations_reached(self):
        from agents.orchestrator.agent import should_iterate

        state = {"quality_score": 4.0, "quality_threshold": 7.0, "iteration": 3, "max_iterations": 3}
        result = should_iterate(state)

        assert result == "finalize"

    def test_continues_when_below_threshold_and_iterations_remain(self):
        from agents.orchestrator.agent import should_iterate

        state = {"quality_score": 5.0, "quality_threshold": 7.0, "iteration": 1, "max_iterations": 3}
        result = should_iterate(state)

        assert result == "plan"

    def test_uses_default_threshold(self):
        from agents.orchestrator.agent import should_iterate

        state = {"quality_score": 7.0, "iteration": 1, "max_iterations": 5}
        result = should_iterate(state)

        assert result == "finalize"

    def test_uses_default_max_iterations(self):
        from agents.orchestrator.agent import should_iterate

        state = {"quality_score": 3.0, "quality_threshold": 7.0, "iteration": 5}
        result = should_iterate(state)

        assert result == "finalize"


class TestGraphInvocation:
    @pytest.mark.asyncio
    async def test_graph_runs_to_completion(
        self, mock_mcp_functions, mock_observer, mock_checkpoint, mock_failure_memory
    ):
        from agents.orchestrator.agent import build_graph

        graph = build_graph()

        initial_state = {
            "session_id": "test-001",
            "query": "What is machine learning?",
            "file_path": "",
            "has_document": False,
            "iteration": 0,
            "max_iterations": 1,
            "quality_threshold": 5.0,
            "research_plan": [],
            "accumulated_context": [],
            "current_draft": "",
            "verification_result": {},
            "verification_history": [],
            "quality_score": 0.0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "failure_hints": "",
            "enable_web_search": True,
            "enable_planning": True,
            "enable_fact_check": True,
            "enable_parallel": False,
            "enable_sectioned": False,
            "report_sections": [],
            "section_order": [],
            "failing_sections": [],
            "status": "normalizing",
            "final_output": "",
            "error": "",
            "language_instruction": "",
        }

        result = await graph.ainvoke(initial_state)

        assert result["status"] == "complete"
        assert result["final_output"] != ""
        assert result["iteration"] >= 1
