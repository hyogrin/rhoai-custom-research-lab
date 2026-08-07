"""Tests for the Claim-Evidence Graph artifact branch.

Covers routing, permission gate, sandbox execution, artifact verification,
and SSE event ordering. Uses FakeOpenShellExecutor for all sandbox operations.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from agents.orchestrator.graph import (
    route_after_review,
    route_artifact,
    route_after_permission,
    artifact_router_node,
    artifact_plan_node,
    permission_gate_node,
    sandbox_execute_node,
    artifact_verify_node,
)
from agents.orchestrator.artifact_planner import (
    _validate_spec,
    _sanitize_label,
    plan_claim_evidence_graph,
)
from harness.execution import FakeOpenShellExecutor, set_executor


# --- Fixtures ---


@pytest.fixture(autouse=True)
def reset_executor():
    """Reset the global executor before each test."""
    from harness.execution.openshell_executor import _executor_instance
    import harness.execution.openshell_executor as mod
    mod._executor_instance = None
    yield
    mod._executor_instance = None


@pytest.fixture
def fake_executor():
    """Inject a FakeOpenShellExecutor."""
    executor = FakeOpenShellExecutor()
    set_executor(executor)
    return executor


@pytest.fixture
def base_state():
    """Minimal state for artifact branch tests."""
    return {
        "session_id": "test-sess",
        "query": "Test query",
        "iteration": 1,
        "max_iterations": 3,
        "quality_score": 8.0,
        "quality_threshold": 7.0,
        "status": "finalizing",
        "enable_claim_evidence_graph": True,
        "current_draft": "# Report\n\nClaim: AI improves efficiency [Source 1].",
        "accumulated_context": [
            {"source": "doc1", "content": "AI context", "metadata": {"title": "Doc1", "url": "http://example.com/1"}},
            {"source": "doc2", "content": "More context", "metadata": {"title": "Doc2", "url": "http://example.com/2"}},
        ],
        "verification_result": {"summary": "Good quality"},
        "artifact_status": "",
        "artifact_execution_id": "",
        "claim_evidence_spec": {},
        "execution_permission_request": {},
        "execution_permission_decision": "",
        "sandbox_id": "",
        "sandbox_status": "",
        "sandbox_error": "",
        "claim_evidence_artifact": {},
        "artifact_verification": {},
    }


@pytest.fixture
def valid_spec():
    return {
        "title": "Test Graph",
        "summary": "Test summary",
        "nodes": [
            {"id": "claim-1", "type": "claim", "label": "AI improves efficiency", "confidence": 0.85, "citation_ids": ["1"]},
            {"id": "evidence-1", "type": "evidence", "label": "Study shows 40% improvement", "source_id": "1", "source_title": "Doc1", "source_url": "http://example.com/1"},
        ],
        "edges": [
            {"source": "evidence-1", "target": "claim-1", "relation": "supports"},
        ],
    }


# --- Routing Tests ---


class TestRouting:
    def test_toggle_disabled_routes_to_finalize(self, base_state):
        """When graph toggle is off, artifact_router routes to finalize."""
        base_state["enable_claim_evidence_graph"] = False
        result = route_artifact(base_state)
        assert result == "finalize"

    def test_toggle_enabled_routes_to_artifact_plan(self, base_state):
        """When graph toggle is on, artifact_router routes to artifact_plan."""
        base_state["enable_claim_evidence_graph"] = True
        result = route_artifact(base_state)
        assert result == "artifact_plan"

    def test_user_continues_routes_to_iterate(self, base_state):
        """When user continues, route_after_review routes to iterate."""
        base_state["status"] = "planning"
        result = route_after_review(base_state)
        assert result == "iterate"

    def test_accept_routes_to_artifact_router(self, base_state):
        """When user accepts (finalizing), route_after_review routes to artifact_router."""
        base_state["status"] = "finalizing"
        result = route_after_review(base_state)
        assert result == "artifact_router"

    def test_artifact_router_disabled(self, base_state):
        """artifact_router_node returns disabled status when toggle is off."""
        base_state["enable_claim_evidence_graph"] = False
        writer = MagicMock()
        result = artifact_router_node(base_state, writer)
        assert result["artifact_status"] == "disabled"

    def test_artifact_router_enabled(self, base_state):
        """artifact_router_node returns planning status when toggle is on."""
        writer = MagicMock()
        result = artifact_router_node(base_state, writer)
        assert result["artifact_status"] == "planning"


# --- Permission Tests ---


class TestPermission:
    def test_approval_routes_to_sandbox(self, base_state):
        """When approved, route_after_permission routes to sandbox_execute."""
        base_state["execution_permission_decision"] = "approved"
        result = route_after_permission(base_state)
        assert result == "sandbox_execute"

    def test_denial_routes_to_finalize(self, base_state):
        """When denied, route_after_permission routes to finalize."""
        base_state["execution_permission_decision"] = "denied"
        result = route_after_permission(base_state)
        assert result == "finalize"

    def test_auto_approve_when_disabled(self, base_state, monkeypatch):
        """When OPENSHELL_REQUIRE_APPROVAL=false, auto-approve."""
        monkeypatch.setenv("OPENSHELL_REQUIRE_APPROVAL", "false")
        base_state["execution_permission_request"] = {"type": "execution_permission"}
        base_state["artifact_execution_id"] = "exec-test"
        writer = MagicMock()
        result = permission_gate_node(base_state, writer)
        assert result["execution_permission_decision"] == "approved"


# --- Execution Tests ---


class TestExecution:
    def test_successful_execution(self, base_state, fake_executor, valid_spec):
        """Successful sandbox execution produces artifact."""
        base_state["claim_evidence_spec"] = valid_spec
        base_state["artifact_execution_id"] = "exec-test"
        writer = MagicMock()
        result = sandbox_execute_node(base_state, writer)
        assert result["sandbox_status"] == "completed"
        assert result["artifact_status"] == "created"
        assert result["claim_evidence_artifact"]["format"] == "svg"
        assert fake_executor.deleted_sandboxes  # cleanup ran

    def test_execution_failure(self, base_state, valid_spec):
        """Failed execution emits failure status."""
        failing_executor = FakeOpenShellExecutor(fail_on_execute=True)
        set_executor(failing_executor)
        base_state["claim_evidence_spec"] = valid_spec
        base_state["artifact_execution_id"] = "exec-test"
        writer = MagicMock()
        result = sandbox_execute_node(base_state, writer)
        assert result["sandbox_status"] == "failed"
        assert result["artifact_status"] == "failed"

    def test_sandbox_cleanup_on_failure(self, base_state, valid_spec):
        """Sandbox is deleted even when execution fails."""
        failing_executor = FakeOpenShellExecutor(fail_on_execute=True)
        set_executor(failing_executor)
        base_state["claim_evidence_spec"] = valid_spec
        base_state["artifact_execution_id"] = "exec-test"
        writer = MagicMock()
        sandbox_execute_node(base_state, writer)
        assert len(failing_executor.deleted_sandboxes) > 0


# --- Verification Tests ---


class TestVerification:
    def test_valid_svg_passes(self, base_state):
        """Valid SVG artifact passes verification."""
        base_state["claim_evidence_artifact"] = {
            "svg_data": '<svg xmlns="http://www.w3.org/2000/svg"><text>Test</text></svg>',
            "artifact_id": "art-1",
        }
        base_state["claim_evidence_spec"] = {
            "nodes": [{"id": "e1", "type": "evidence", "label": "test", "source_id": "1"}],
        }
        base_state["sandbox_status"] = "completed"
        base_state["artifact_execution_id"] = "exec-test"
        writer = MagicMock()
        result = artifact_verify_node(base_state, writer)
        assert result["artifact_verification"]["passed"] is True
        assert result["artifact_status"] == "completed"

    def test_svg_with_script_fails(self, base_state):
        """SVG containing script tags fails verification."""
        base_state["claim_evidence_artifact"] = {
            "svg_data": '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            "artifact_id": "art-1",
        }
        base_state["claim_evidence_spec"] = {"nodes": []}
        base_state["sandbox_status"] = "completed"
        base_state["artifact_execution_id"] = "exec-test"
        writer = MagicMock()
        result = artifact_verify_node(base_state, writer)
        assert result["artifact_verification"]["passed"] is False
        assert result["artifact_verification"]["checks"]["no_scripts"] is False

    def test_svg_with_external_urls_fails(self, base_state):
        """SVG with external URLs fails verification."""
        base_state["claim_evidence_artifact"] = {
            "svg_data": '<svg xmlns="http://www.w3.org/2000/svg"><image href="http://evil.com/img.png"/></svg>',
            "artifact_id": "art-1",
        }
        base_state["claim_evidence_spec"] = {"nodes": []}
        base_state["sandbox_status"] = "completed"
        base_state["artifact_execution_id"] = "exec-test"
        writer = MagicMock()
        result = artifact_verify_node(base_state, writer)
        assert result["artifact_verification"]["passed"] is False
        assert result["artifact_verification"]["checks"]["no_external_resources"] is False

    def test_empty_svg_fails(self, base_state):
        """Empty SVG fails verification."""
        base_state["claim_evidence_artifact"] = {"svg_data": "", "artifact_id": "art-1"}
        base_state["claim_evidence_spec"] = {"nodes": []}
        base_state["sandbox_status"] = "completed"
        base_state["artifact_execution_id"] = "exec-test"
        writer = MagicMock()
        result = artifact_verify_node(base_state, writer)
        assert result["artifact_verification"]["passed"] is False
        assert result["artifact_verification"]["checks"]["file_exists"] is False


# --- Planner / Schema Tests ---


class TestPlanner:
    def test_validate_spec_valid(self, valid_spec):
        """Valid spec passes validation."""
        errors = _validate_spec(valid_spec, {"1", "2"})
        assert errors == []

    def test_validate_spec_unknown_source(self, valid_spec):
        """Unknown source_id is flagged."""
        errors = _validate_spec(valid_spec, {"99"})
        assert any("unknown source_id" in e for e in errors)

    def test_validate_spec_too_many_claims(self):
        """More than 12 claims is rejected."""
        spec = {
            "nodes": [{"id": f"claim-{i}", "type": "claim", "label": f"Claim {i}", "confidence": 0.5} for i in range(15)],
            "edges": [],
        }
        errors = _validate_spec(spec, set())
        assert any("Too many claims" in e for e in errors)

    def test_sanitize_label_strips_html(self):
        """Labels with HTML are sanitized."""
        result = _sanitize_label("<b>Bold</b> text &amp; more")
        assert "<b>" not in result
        assert "Bold text & more" == result

    def test_sanitize_label_truncates(self):
        """Long labels are truncated."""
        long_label = "x" * 500
        result = _sanitize_label(long_label)
        assert len(result) <= 300


# --- SSE Event Tests ---


class TestSSEEvents:
    def test_successful_event_order(self, base_state, fake_executor, valid_spec):
        """Successful flow emits events in correct order."""
        base_state["claim_evidence_spec"] = valid_spec
        base_state["artifact_execution_id"] = "exec-test"

        events: list[str] = []
        def capture_writer(payload):
            events.append(payload.get("progress", ""))

        # artifact_plan_node
        with patch("agents.orchestrator.artifact_planner.plan_claim_evidence_graph") as mock_plan:
            mock_plan.return_value = {"spec": valid_spec, "errors": [], "tokens_used": 100}
            result = artifact_plan_node(base_state, capture_writer)
            assert "artifact_planning" in events
            assert "execution_proposed" in events

        events.clear()
        # sandbox_execute_node
        base_state.update(result)
        result2 = sandbox_execute_node(base_state, capture_writer)
        assert "sandbox_scheduled" in events
        assert "sandbox_running" in events
        assert "artifact_created" in events

        events.clear()
        # artifact_verify_node
        base_state.update(result2)
        artifact_verify_node(base_state, capture_writer)
        assert "artifact_verifying" in events
        assert "execution_completed" in events

    def test_denial_event_order(self, base_state, monkeypatch):
        """Denied permission emits execution_denied."""
        monkeypatch.setenv("OPENSHELL_REQUIRE_APPROVAL", "true")
        base_state["execution_permission_request"] = {"type": "execution_permission", "permissions": {}}
        base_state["artifact_execution_id"] = "exec-test"

        events: list[str] = []
        def capture_writer(payload):
            events.append(payload.get("progress", ""))

        with patch("agents.orchestrator.graph.interrupt") as mock_interrupt:
            mock_interrupt.return_value = "__execution_deny__"
            result = permission_gate_node(base_state, capture_writer)

        assert "permission_required" in events
        assert "execution_denied" in events
        assert result["execution_permission_decision"] == "denied"

    def test_failure_event_order(self, base_state, valid_spec):
        """Failed execution emits execution_failed."""
        failing_executor = FakeOpenShellExecutor(fail_on_execute=True)
        set_executor(failing_executor)
        base_state["claim_evidence_spec"] = valid_spec
        base_state["artifact_execution_id"] = "exec-test"

        events: list[str] = []
        def capture_writer(payload):
            events.append(payload.get("progress", ""))

        sandbox_execute_node(base_state, capture_writer)
        assert "sandbox_scheduled" in events
        assert "sandbox_running" in events
        assert "execution_failed" in events
