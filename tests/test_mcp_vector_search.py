"""Unit tests for mcp_servers/vector_search_mcp/server.py."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_embedding():
    """Mock the OpenAI embedding call."""
    mock_data = MagicMock()
    mock_data.embedding = [0.1] * 384

    mock_response = MagicMock()
    mock_response.data = [mock_data]

    with patch("mcp_servers.vector_search_mcp.server.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = mock_response
        mock_openai.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_db():
    """Mock the database connection for vector search."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("mcp_servers.vector_search_mcp.server._get_db", return_value=mock_conn):
        yield {"connection": mock_conn, "cursor": mock_cursor}


class TestSemanticSearch:
    def test_returns_results_with_expected_schema(self, mock_embedding, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            (1, "doc-001", "research.pdf", 3, "Machine learning overview", {"section": "intro"}, 0.87),
            (2, "doc-001", "research.pdf", 4, "Deep learning methods", {"section": "methods"}, 0.82),
        ]

        from mcp_servers.vector_search_mcp.server import semantic_search

        results = semantic_search("machine learning", top_k=5, min_similarity=0.3)

        assert len(results) == 2
        for result in results:
            assert "id" in result
            assert "document_id" in result
            assert "document_name" in result
            assert "chunk_index" in result
            assert "content" in result
            assert "metadata" in result
            assert "similarity" in result
            assert isinstance(result["similarity"], float)

    def test_returns_empty_list_when_no_matches(self, mock_embedding, mock_db):
        mock_db["cursor"].fetchall.return_value = []

        from mcp_servers.vector_search_mcp.server import semantic_search

        results = semantic_search("nonexistent topic", top_k=5, min_similarity=0.9)

        assert results == []

    def test_similarity_is_rounded(self, mock_embedding, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            (1, "doc-001", "report.pdf", 0, "Some content", None, 0.876543),
        ]

        from mcp_servers.vector_search_mcp.server import semantic_search

        results = semantic_search("test query")

        assert results[0]["similarity"] == 0.8765

    def test_null_metadata_becomes_empty_dict(self, mock_embedding, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            (1, "doc-001", "report.pdf", 0, "Content", None, 0.9),
        ]

        from mcp_servers.vector_search_mcp.server import semantic_search

        results = semantic_search("query")

        assert results[0]["metadata"] == {}


class TestSearchByDocument:
    def test_filters_by_document_id(self, mock_embedding, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            (5, "doc-abc", "paper.pdf", 2, "Specific doc content", {"page": 3}, 0.91),
        ]

        from mcp_servers.vector_search_mcp.server import search_by_document

        results = search_by_document("findings", document_id="doc-abc", top_k=5)

        assert len(results) == 1
        assert results[0]["document_id"] == "doc-abc"
        assert results[0]["content"] == "Specific doc content"

        call_args = mock_db["cursor"].execute.call_args
        sql_params = call_args[0][1]
        assert "doc-abc" in sql_params

    def test_returns_results_with_expected_schema(self, mock_embedding, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            (10, "doc-xyz", "thesis.pdf", 7, "Results section", {"heading": "Results"}, 0.85),
        ]

        from mcp_servers.vector_search_mcp.server import search_by_document

        results = search_by_document("results", document_id="doc-xyz")

        result = results[0]
        assert "id" in result
        assert "document_id" in result
        assert "document_name" in result
        assert "chunk_index" in result
        assert "content" in result
        assert "metadata" in result
        assert "similarity" in result


class TestGetChunkContext:
    def test_returns_surrounding_chunks(self, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            (3, "Previous chunk content", {"page": 2}),
            (4, "Current chunk content", {"page": 2}),
            (5, "Next chunk content", {"page": 3}),
        ]

        from mcp_servers.vector_search_mcp.server import get_chunk_context

        results = get_chunk_context(document_id="doc-001", chunk_index=4, window=1)

        assert len(results) == 3
        assert results[0]["chunk_index"] == 3
        assert results[1]["chunk_index"] == 4
        assert results[2]["chunk_index"] == 5

    def test_marks_center_chunk(self, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            (2, "Chunk 2", None),
            (3, "Chunk 3", None),
            (4, "Chunk 4", None),
        ]

        from mcp_servers.vector_search_mcp.server import get_chunk_context

        results = get_chunk_context(document_id="doc-001", chunk_index=3, window=1)

        assert results[0]["is_center"] is False
        assert results[1]["is_center"] is True
        assert results[2]["is_center"] is False

    def test_uses_window_parameter(self, mock_db):
        mock_db["cursor"].fetchall.return_value = []

        from mcp_servers.vector_search_mcp.server import get_chunk_context

        get_chunk_context(document_id="doc-001", chunk_index=5, window=3)

        call_args = mock_db["cursor"].execute.call_args[0][1]
        assert call_args == ("doc-001", 2, 8)

    def test_null_metadata_becomes_empty_dict(self, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            (4, "Content here", None),
        ]

        from mcp_servers.vector_search_mcp.server import get_chunk_context

        results = get_chunk_context(document_id="doc-001", chunk_index=4)

        assert results[0]["metadata"] == {}
