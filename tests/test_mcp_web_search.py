"""Unit tests for mcp_servers/web_search_mcp/server.py."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_httpx_client():
    """Mock httpx.Client to simulate SearXNG responses."""
    with patch("mcp_servers.web_search_mcp.server.httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        yield mock_client


class TestWebSearch:
    def test_returns_results_with_title_url_content(self, mock_httpx_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"title": "ML Guide", "url": "https://example.com/ml", "content": "Machine learning intro"},
                {"title": "AI News", "url": "https://example.com/ai", "content": "Latest AI developments"},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_httpx_client.get.return_value = mock_response

        from mcp_servers.web_search_mcp.server import web_search

        results = web_search("machine learning", num_results=5)

        assert len(results) == 2
        for result in results:
            assert "title" in result
            assert "url" in result
            assert "content" in result
        assert results[0]["title"] == "ML Guide"
        assert results[0]["url"] == "https://example.com/ml"
        assert results[0]["content"] == "Machine learning intro"

    def test_respects_num_results_limit(self, mock_httpx_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"title": f"Result {i}", "url": f"https://example.com/{i}", "content": f"Content {i}"}
                for i in range(10)
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_httpx_client.get.return_value = mock_response

        from mcp_servers.web_search_mcp.server import web_search

        results = web_search("test query", num_results=3)

        assert len(results) == 3

    def test_empty_query_returns_empty_list(self, mock_httpx_client):
        mock_httpx_client.get.side_effect = Exception("Bad request")

        from mcp_servers.web_search_mcp.server import web_search

        results = web_search("")

        assert results == []

    def test_handles_network_error_gracefully(self, mock_httpx_client):
        mock_httpx_client.get.side_effect = Exception("Connection refused")

        from mcp_servers.web_search_mcp.server import web_search

        results = web_search("some query")

        assert results == []

    def test_handles_empty_results_from_searxng(self, mock_httpx_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()
        mock_httpx_client.get.return_value = mock_response

        from mcp_servers.web_search_mcp.server import web_search

        results = web_search("obscure topic")

        assert results == []

    def test_handles_missing_fields_gracefully(self, mock_httpx_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"title": "Partial result"},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_httpx_client.get.return_value = mock_response

        from mcp_servers.web_search_mcp.server import web_search

        results = web_search("partial data")

        assert len(results) == 1
        assert results[0]["title"] == "Partial result"
        assert results[0]["url"] == ""
        assert results[0]["content"] == ""
