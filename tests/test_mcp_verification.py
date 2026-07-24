"""Unit tests for mcp_servers/verification_mcp/server.py."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_verification_llm():
    """Patch the LLM used by verification MCP server."""
    with patch("mcp_servers.verification_mcp.server._call_llm") as mock_call:
        yield mock_call


class TestQualityScore:
    def test_returns_score_between_1_and_10(self, mock_verification_llm):
        mock_verification_llm.return_value = (
            '{"completeness": 8, "accuracy": 7, "clarity": 8, "structure": 7, "overall": 7.5, "feedback": "Well structured"}',
            200,
        )

        from mcp_servers.verification_mcp.server import quality_score

        result = quality_score("A research draft about AI.", "What is AI?")

        assert "overall" in result
        assert 1 <= result["overall"] <= 10
        assert "completeness" in result
        assert "accuracy" in result
        assert "clarity" in result
        assert "structure" in result
        assert "feedback" in result
        assert "tokens_used" in result

    def test_returns_default_scores_on_llm_failure(self, mock_verification_llm):
        mock_verification_llm.return_value = ("", 0)

        from mcp_servers.verification_mcp.server import quality_score

        result = quality_score("draft", "query")

        assert result["overall"] == 5
        assert result["completeness"] == 5
        assert result["feedback"] == "Unable to evaluate"

    def test_handles_malformed_json_from_llm(self, mock_verification_llm):
        mock_verification_llm.return_value = ("This is not JSON at all", 50)

        from mcp_servers.verification_mcp.server import quality_score

        result = quality_score("draft", "query")

        assert result["overall"] == 5
        assert result["tokens_used"] == 50


class TestRunVerification:
    def test_returns_passed_when_quality_sufficient(self, mock_verification_llm):
        # run_verification calls: validate_citations (no LLM), quality_score, llm_as_judge, fact_check
        responses = [
            ('{"completeness": 8, "accuracy": 8, "clarity": 8, "structure": 8, "overall": 8, "feedback": "Excellent"}', 100),
            ('{"relevance": 2, "depth": 2, "evidence": 2, "clarity": 2, "completeness": 2, "total": 10, "verdict": "pass", "reasoning": "Good", "improvements": []}', 100),
            ('{"supported_claims": 5, "unsupported_claims": 0, "hallucinations": [], "passed": true}', 50),
        ]
        mock_verification_llm.side_effect = responses

        from mcp_servers.verification_mcp.server import run_verification

        context = [{"content": "Source document content"}]
        result = run_verification(
            draft="Research report with [Source 1] citation.",
            query="What is AI?",
            context=context,
            iteration=1,
        )

        assert result["passed"] is True
        assert result["quality_score"] >= 7
        assert "quality_details" in result
        assert "citation_check" in result
        assert "fact_check" in result
        assert "improvements" in result
        assert "tokens_used" in result

    def test_returns_failed_with_improvements(self, mock_verification_llm):
        responses = [
            ('{"completeness": 3, "accuracy": 4, "clarity": 3, "structure": 3, "overall": 3, "feedback": "Too shallow"}', 100),
            ('{"relevance": 1, "depth": 0, "evidence": 0, "clarity": 1, "completeness": 0, "total": 2, "verdict": "fail", "reasoning": "Lacks depth", "improvements": ["Add more detail", "Include citations"]}', 100),
            ('{"supported_claims": 1, "unsupported_claims": 3, "hallucinations": ["Claim X"], "passed": false}', 50),
        ]
        mock_verification_llm.side_effect = responses

        from mcp_servers.verification_mcp.server import run_verification

        result = run_verification(
            draft="Short draft without sources.",
            query="Comprehensive analysis of AI",
            context=[{"content": "source"}],
            iteration=1,
        )

        assert result["passed"] is False
        assert len(result["improvements"]) > 0
        assert result["tokens_used"] > 0

    def test_skips_fact_check_when_disabled(self, mock_verification_llm):
        responses = [
            ('{"completeness": 7, "accuracy": 7, "clarity": 7, "structure": 7, "overall": 7, "feedback": "OK"}', 100),
            ('{"relevance": 2, "depth": 1, "evidence": 2, "clarity": 2, "completeness": 1, "total": 8, "verdict": "pass", "reasoning": "Solid", "improvements": []}', 100),
        ]
        mock_verification_llm.side_effect = responses

        from mcp_servers.verification_mcp.server import run_verification

        result = run_verification(
            draft="Draft with [Source 1].",
            query="query",
            context=[{"content": "ctx"}],
            iteration=1,
            enable_fact_check=False,
        )

        assert result["fact_check"]["passed"] is True
        assert result["fact_check"]["tokens_used"] == 0


class TestValidateCitations:
    def test_detects_valid_citations(self):
        from mcp_servers.verification_mcp.server import validate_citations

        result = validate_citations("Report uses [Source 1] and [Source 2] evidence.", num_sources=3)

        assert 1 in result["valid_citations"]
        assert 2 in result["valid_citations"]
        assert result["passed"] is True

    def test_detects_invalid_citations(self):
        from mcp_servers.verification_mcp.server import validate_citations

        result = validate_citations("Claims from [Source 5] are interesting.", num_sources=2)

        assert 5 in result["invalid_citations"]
        assert result["passed"] is False

    def test_no_citations_fails(self):
        from mcp_servers.verification_mcp.server import validate_citations

        result = validate_citations("A draft with no citations at all.", num_sources=3)

        assert result["has_citations"] is False
        assert result["passed"] is False
