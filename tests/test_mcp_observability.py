"""Unit tests for mcp_servers/observability_mcp/server.py."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_obs_db():
    """Mock the database connection for observability MCP server."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("mcp_servers.observability_mcp.server._get_db", return_value=mock_conn):
        yield {"connection": mock_conn, "cursor": mock_cursor}


class TestRecordTrace:
    def test_stores_trace_data(self, mock_obs_db):
        mock_obs_db["cursor"].fetchone.return_value = (42,)

        from mcp_servers.observability_mcp.server import record_trace

        result = record_trace(
            session_id="sess-001",
            iteration=1,
            layer="execute",
            operation="semantic_search",
            input_summary="Query about AI",
            output_summary="5 results found",
            tokens_used=0,
            latency_ms=150,
            success=True,
        )

        assert result["status"] == "recorded"
        assert result["trace_id"] == 42
        mock_obs_db["cursor"].execute.assert_called_once()
        mock_obs_db["connection"].commit.assert_called_once()

    def test_handles_db_error_gracefully(self, mock_obs_db):
        mock_obs_db["cursor"].execute.side_effect = Exception("DB connection lost")

        from mcp_servers.observability_mcp.server import record_trace

        result = record_trace(
            session_id="sess-001",
            iteration=1,
            layer="execute",
            operation="search",
        )

        assert result["status"] == "error"
        assert "error" in result

    def test_truncates_long_summaries(self, mock_obs_db):
        mock_obs_db["cursor"].fetchone.return_value = (1,)

        from mcp_servers.observability_mcp.server import record_trace

        long_text = "x" * 1000
        record_trace(
            session_id="sess-001",
            iteration=1,
            layer="execute",
            operation="search",
            input_summary=long_text,
            output_summary=long_text,
        )

        call_args = mock_obs_db["cursor"].execute.call_args[0][1]
        assert len(call_args[4]) <= 500
        assert len(call_args[5]) <= 500


class TestGetMetrics:
    def test_returns_valid_metrics(self, mock_obs_db):
        mock_obs_db["cursor"].fetchone.return_value = (15, 3000, 4500, 2, 3)
        mock_obs_db["cursor"].fetchall.return_value = [
            ("execute", 8),
            ("verify", 4),
            ("observe", 3),
        ]

        from mcp_servers.observability_mcp.server import get_metrics

        result = get_metrics("sess-001")

        assert result["session_id"] == "sess-001"
        assert result["total_events"] == 15
        assert result["total_tokens"] == 3000
        assert result["total_latency_ms"] == 4500
        assert result["failures"] == 2
        assert result["iterations"] == 3
        assert result["events_by_layer"]["execute"] == 8
        assert result["events_by_layer"]["verify"] == 4

    def test_returns_zero_metrics_for_unknown_session(self, mock_obs_db):
        mock_obs_db["cursor"].fetchone.return_value = None
        mock_obs_db["cursor"].fetchall.return_value = []

        from mcp_servers.observability_mcp.server import get_metrics

        result = get_metrics("nonexistent-session")

        assert result["session_id"] == "nonexistent-session"
        assert result["total_events"] == 0

    def test_handles_db_error(self, mock_obs_db):
        mock_obs_db["cursor"].execute.side_effect = Exception("Connection refused")

        from mcp_servers.observability_mcp.server import get_metrics

        result = get_metrics("sess-001")

        assert "error" in result


class TestGetFailureHints:
    def test_returns_hints_for_known_categories(self, mock_obs_db):
        mock_obs_db["cursor"].fetchall.return_value = [
            ("insufficient_depth",),
            ("missing_citations",),
        ]

        from mcp_servers.observability_mcp.server import get_failure_hints

        result = get_failure_hints("sess-001")

        assert "hints" in result
        assert "categories" in result
        assert "insufficient_depth" in result["categories"]
        assert "missing_citations" in result["categories"]
        assert "shallow" in result["hints"].lower() or "depth" in result["hints"].lower()
        assert "citation" in result["hints"].lower() or "source" in result["hints"].lower()

    def test_returns_empty_hints_for_no_failures(self, mock_obs_db):
        mock_obs_db["cursor"].fetchall.return_value = []

        from mcp_servers.observability_mcp.server import get_failure_hints

        result = get_failure_hints("sess-clean")

        assert result["hints"] == ""
        assert result["categories"] == []

    def test_handles_db_error(self, mock_obs_db):
        mock_obs_db["cursor"].execute.side_effect = Exception("Timeout")

        from mcp_servers.observability_mcp.server import get_failure_hints

        result = get_failure_hints("sess-001")

        assert result["hints"] == ""
        assert result["categories"] == []
        assert "error" in result


class TestRecordFailure:
    def test_stores_failure_record(self, mock_obs_db):
        mock_obs_db["cursor"].fetchone.return_value = (7,)

        from mcp_servers.observability_mcp.server import record_failure

        result = record_failure(
            session_id="sess-001",
            iteration=2,
            category="insufficient_depth",
            description="Report lacks detailed analysis",
            context="Draft was only 200 words",
        )

        assert result["status"] == "recorded"
        assert result["failure_id"] == 7
        mock_obs_db["connection"].commit.assert_called_once()
