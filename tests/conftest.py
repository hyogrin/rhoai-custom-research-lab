"""Shared pytest fixtures for the RHOAI research lab test suite."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def env_setup(monkeypatch, tmp_path):
    """Set environment variables for testing — mock LLM, SQLite, and MCP URLs."""
    db_path = str(tmp_path / "test_research.db")
    env_vars = {
        "LLM_BASE_URL": "http://localhost:8000/v1",
        "LLM_API_KEY": "test-key",
        "LLM_MODEL": "test-model",
        "MAAS_API_KEY": "",
        "EMBEDDING_BASE_URL": "http://localhost:8000/v1",
        "EMBEDDING_API_KEY": "test-key",
        "EMBEDDING_MODEL": "test-embedding-model",
        "SQLITE_DB_PATH": db_path,
        "VECTOR_SEARCH_MCP_URL": "http://localhost:9002",
        "WEB_SEARCH_MCP_URL": "http://localhost:9003",
        "VERIFICATION_MCP_URL": "http://localhost:9004",
        "OBSERVABILITY_MCP_URL": "http://localhost:9005",
        "SEARXNG_URL": "http://localhost:8888",
        "VERIFY_SSL": "false",
        "QUALITY_THRESHOLD": "7.0",
        "MAX_ITERATIONS": "3",
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def mock_llm_response():
    """Patch OpenAI client to return canned responses."""
    mock_choice = MagicMock()
    mock_choice.message.content = '{"overall": 7, "completeness": 7, "accuracy": 8, "clarity": 7, "structure": 7, "feedback": "Good report"}'

    mock_usage = MagicMock()
    mock_usage.total_tokens = 150

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    with patch("openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1] * 384)]
        )
        mock_openai.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_db_connection():
    """Provide a real in-memory SQLite connection for testing.

    Loads sqlite-vec if available; skips vec0 tables otherwise.
    """
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        init_sql = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "init-db.sql")
        with open(init_sql) as f:
            conn.executescript(f.read())
    except (AttributeError, OSError, Exception):
        pass

    yield conn
    conn.close()
