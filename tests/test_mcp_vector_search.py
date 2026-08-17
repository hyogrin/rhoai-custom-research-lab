"""Unit tests for mcp_servers/vector_search_mcp/server.py (Llama Stack proxy)."""

from unittest.mock import MagicMock, patch

import pytest


def _make_search_result(file_id="file-001", filename="research.md", content="ML overview", score=0.85):
    """Create a mock search result dict matching llama_stack_client.search() output."""
    return {
        "file_id": file_id,
        "filename": filename,
        "content": content,
        "score": score,
        "attributes": {},
    }


@pytest.fixture
def mock_llama_search():
    """Mock the Llama Stack client search and ensure_vector_store functions."""
    with patch("mcp_servers.vector_search_mcp.server.ensure_vector_store", return_value="vs-test-123") as mock_evs, \
         patch("mcp_servers.vector_search_mcp.server.search") as mock_search, \
         patch("mcp_servers.vector_search_mcp.server.list_files") as mock_list:
        yield {
            "ensure_vector_store": mock_evs,
            "search": mock_search,
            "list_files": mock_list,
        }


class TestSemanticSearch:
    def test_returns_results_with_expected_schema(self, mock_llama_search):
        mock_llama_search["search"].return_value = [
            _make_search_result("file-001", "research.md", "Machine learning overview", 0.92),
            _make_search_result("file-002", "paper.md", "Deep learning methods", 0.87),
        ]

        from mcp_servers.vector_search_mcp.server import semantic_search

        results = semantic_search("machine learning", top_k=5, min_similarity=0.0)

        assert len(results) == 2
        for result in results:
            assert "file_id" in result
            assert "document_name" in result
            assert "content" in result
            assert "similarity" in result
            assert isinstance(result["similarity"], float)

    def test_filters_results_below_min_similarity(self, mock_llama_search):
        mock_llama_search["search"].return_value = [
            _make_search_result(score=0.92),
            _make_search_result(score=0.3),
        ]

        from mcp_servers.vector_search_mcp.server import semantic_search

        results = semantic_search("query", min_similarity=0.5)

        assert len(results) == 1
        assert results[0]["similarity"] >= 0.5

    def test_returns_empty_when_all_below_threshold(self, mock_llama_search):
        mock_llama_search["search"].return_value = [
            _make_search_result(score=0.1),
            _make_search_result(score=0.2),
        ]

        from mcp_servers.vector_search_mcp.server import semantic_search

        results = semantic_search("query", min_similarity=0.99)

        assert results == []

    def test_calls_llama_stack_with_correct_params(self, mock_llama_search):
        mock_llama_search["search"].return_value = []

        from mcp_servers.vector_search_mcp.server import semantic_search

        semantic_search("test query", top_k=3)

        mock_llama_search["search"].assert_called_once_with("vs-test-123", "test query", max_results=3)


class TestSearchByDocument:
    def test_passes_filename_filter(self, mock_llama_search):
        mock_llama_search["search"].return_value = [
            _make_search_result("file-abc", "paper.md", "Specific doc content", 0.88),
        ]

        from mcp_servers.vector_search_mcp.server import search_by_document

        results = search_by_document("findings", document_name="paper.md", top_k=5)

        assert len(results) == 1
        assert results[0]["document_name"] == "paper.md"
        mock_llama_search["search"].assert_called_once()
        call_kwargs = mock_llama_search["search"].call_args
        assert call_kwargs[1]["filters"]["key"] == "filename"
        assert call_kwargs[1]["filters"]["value"] == "paper.md"


class TestGetChunkContext:
    def test_returns_context_chunks(self, mock_llama_search):
        mock_llama_search["search"].return_value = [
            _make_search_result(content=f"Chunk {i} content", score=0.8 - i * 0.1)
            for i in range(3)
        ]

        from mcp_servers.vector_search_mcp.server import get_chunk_context

        results = get_chunk_context(document_name="paper.md", query="methods", window=3)

        assert len(results) == 3
        for r in results:
            assert "content" in r
            assert "score" in r
