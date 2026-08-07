"""Unit tests for mcp_servers/vector_search_mcp/server.py."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

try:
    import sqlite_vec
    from sqlite_vec import serialize_float32

    _test_conn = sqlite3.connect(":memory:")
    _test_conn.enable_load_extension(True)
    sqlite_vec.load(_test_conn)
    _test_conn.close()
    _HAS_VEC = True
except (AttributeError, OSError, Exception):
    _HAS_VEC = False

needs_vec = pytest.mark.skipif(not _HAS_VEC, reason="sqlite-vec extension not loadable")


def _make_test_db():
    """Create an in-memory SQLite DB with sqlite-vec for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    conn.executescript("""
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            name TEXT,
            object_store_path TEXT
        );
        CREATE TABLE document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            document_name TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT DEFAULT '{}'
        );
        CREATE VIRTUAL TABLE vec_chunks USING vec0(
            chunk_id INTEGER PRIMARY KEY,
            embedding float[384]
        );
    """)
    return conn


def _make_simple_db():
    """Create an in-memory SQLite DB without vec extension (for non-vector tests)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            name TEXT,
            object_store_path TEXT
        );
        CREATE TABLE document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            document_name TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT DEFAULT '{}'
        );
    """)
    return conn


def _insert_chunk(conn, doc_id, doc_name, chunk_idx, content, embedding, metadata="{}", source_url=None):
    """Insert a chunk with its vector into the test DB."""
    if source_url is not None:
        conn.execute(
            "INSERT OR IGNORE INTO documents (id, name, object_store_path) VALUES (?, ?, ?)",
            (doc_id, doc_name, source_url),
        )
    conn.execute(
        "INSERT INTO document_chunks (document_id, document_name, chunk_index, content, metadata) VALUES (?, ?, ?, ?, ?)",
        (doc_id, doc_name, chunk_idx, content, metadata),
    )
    chunk_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
        (chunk_id, serialize_float32(embedding)),
    )
    conn.commit()
    return chunk_id


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
def test_db():
    """Provide a test SQLite DB with sample data."""
    if not _HAS_VEC:
        pytest.skip("sqlite-vec extension not loadable")
    conn = _make_test_db()

    _insert_chunk(conn, "doc-001", "research.pdf", 3, "Machine learning overview",
                  [0.1] * 384, '{"section": "intro"}',
                  "http://localhost:8000/documents/doc-001/research.pdf")
    _insert_chunk(conn, "doc-001", "research.pdf", 4, "Deep learning methods",
                  [0.12] * 384, '{"section": "methods"}',
                  "http://localhost:8000/documents/doc-001/research.pdf")

    with patch("mcp_servers.vector_search_mcp.server.get_connection", return_value=conn):
        yield conn

    conn.close()


@needs_vec
class TestSemanticSearch:
    def test_returns_results_with_expected_schema(self, mock_embedding, test_db):
        from mcp_servers.vector_search_mcp.server import semantic_search

        results = semantic_search("machine learning", top_k=5, min_similarity=0.0)

        assert len(results) == 2
        for result in results:
            assert "id" in result
            assert "document_id" in result
            assert "document_name" in result
            assert "chunk_index" in result
            assert "content" in result
            assert "metadata" in result
            assert "similarity" in result
            assert "source_url" in result
            assert isinstance(result["similarity"], float)

    def test_source_url_populated_from_documents_table(self, mock_embedding, test_db):
        from mcp_servers.vector_search_mcp.server import semantic_search

        results = semantic_search("test", min_similarity=0.0)

        assert results[0]["source_url"].startswith("http://localhost")

    def test_filters_results_below_min_similarity(self, mock_embedding):
        conn = _make_test_db()
        # Store embedding orthogonal to mock query ([0.1]*384) so similarity is low
        far_embedding = [0.0] * 192 + [1.0] * 192
        _insert_chunk(conn, "doc-001", "report.pdf", 0, "Far content", far_embedding)

        with patch("mcp_servers.vector_search_mcp.server.get_connection", return_value=conn):
            from mcp_servers.vector_search_mcp.server import semantic_search

            results = semantic_search("query", min_similarity=0.99)

            assert results == []
        conn.close()

    def test_null_metadata_becomes_empty_dict(self, mock_embedding):
        conn = _make_test_db()
        _insert_chunk(conn, "doc-001", "report.pdf", 0, "Content", [0.1] * 384)

        with patch("mcp_servers.vector_search_mcp.server.get_connection", return_value=conn):
            from mcp_servers.vector_search_mcp.server import semantic_search

            results = semantic_search("query", min_similarity=0.0)

            assert results[0]["metadata"] == {}
        conn.close()

    def test_source_url_empty_when_no_document_record(self, mock_embedding):
        conn = _make_test_db()
        conn.execute(
            "INSERT INTO document_chunks (document_id, document_name, chunk_index, content) VALUES (?, ?, ?, ?)",
            ("doc-no-meta", "paper.pdf", 0, "Content"),
        )
        chunk_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
            (chunk_id, serialize_float32([0.1] * 384)),
        )
        conn.commit()

        with patch("mcp_servers.vector_search_mcp.server.get_connection", return_value=conn):
            from mcp_servers.vector_search_mcp.server import semantic_search

            results = semantic_search("test", min_similarity=0.0)

            assert results[0]["source_url"] == ""
        conn.close()


@needs_vec
class TestSearchByDocument:
    def test_filters_by_document_id(self, mock_embedding):
        conn = _make_test_db()
        _insert_chunk(conn, "doc-abc", "paper.pdf", 2, "Specific doc content",
                      [0.1] * 384, '{"page": 3}',
                      "http://localhost:8000/documents/doc-abc/paper.pdf")
        _insert_chunk(conn, "doc-xyz", "other.pdf", 0, "Other doc", [0.15] * 384)

        with patch("mcp_servers.vector_search_mcp.server.get_connection", return_value=conn):
            from mcp_servers.vector_search_mcp.server import search_by_document

            results = search_by_document("findings", document_id="doc-abc", top_k=5)

            assert len(results) == 1
            assert results[0]["document_id"] == "doc-abc"
            assert results[0]["source_url"] == "http://localhost:8000/documents/doc-abc/paper.pdf"
        conn.close()


class TestGetChunkContext:
    def test_returns_surrounding_chunks(self):
        conn = _make_simple_db()
        for i in range(3, 6):
            conn.execute(
                "INSERT INTO document_chunks (document_id, document_name, chunk_index, content) VALUES (?, ?, ?, ?)",
                ("doc-001", "paper.pdf", i, f"Chunk {i} content"),
            )
        conn.commit()

        with patch("mcp_servers.vector_search_mcp.server.get_connection", return_value=conn):
            from mcp_servers.vector_search_mcp.server import get_chunk_context

            results = get_chunk_context(document_id="doc-001", chunk_index=4, window=1)

            assert len(results) == 3
            assert results[0]["chunk_index"] == 3
            assert results[1]["chunk_index"] == 4
            assert results[2]["chunk_index"] == 5
        conn.close()

    def test_marks_center_chunk(self):
        conn = _make_simple_db()
        for i in range(2, 5):
            conn.execute(
                "INSERT INTO document_chunks (document_id, document_name, chunk_index, content) VALUES (?, ?, ?, ?)",
                ("doc-001", "paper.pdf", i, f"Chunk {i}"),
            )
        conn.commit()

        with patch("mcp_servers.vector_search_mcp.server.get_connection", return_value=conn):
            from mcp_servers.vector_search_mcp.server import get_chunk_context

            results = get_chunk_context(document_id="doc-001", chunk_index=3, window=1)

            assert results[0]["is_center"] is False
            assert results[1]["is_center"] is True
            assert results[2]["is_center"] is False
        conn.close()

    def test_null_metadata_becomes_empty_dict(self):
        conn = _make_simple_db()
        conn.execute(
            "INSERT INTO document_chunks (document_id, document_name, chunk_index, content) VALUES (?, ?, ?, ?)",
            ("doc-001", "paper.pdf", 4, "Content here"),
        )
        conn.commit()

        with patch("mcp_servers.vector_search_mcp.server.get_connection", return_value=conn):
            from mcp_servers.vector_search_mcp.server import get_chunk_context

            results = get_chunk_context(document_id="doc-001", chunk_index=4)

            assert results[0]["metadata"] == {}
        conn.close()
