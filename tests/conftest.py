"""Shared pytest fixtures for the RHOAI research lab test suite."""

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    """Set environment variables for testing — mock LLM, PG, and MCP URLs."""
    env_vars = {
        "LLM_BASE_URL": "http://localhost:8000/v1",
        "LLM_API_KEY": "test-key",
        "LLM_MODEL": "test-model",
        "MAAS_API_KEY": "",
        "EMBEDDING_BASE_URL": "http://localhost:8000/v1",
        "EMBEDDING_API_KEY": "test-key",
        "EMBEDDING_MODEL": "test-embedding-model",
        "PGVECTOR_HOST": "localhost",
        "PGVECTOR_PORT": "5432",
        "PGVECTOR_DB": "test_db",
        "PGVECTOR_USER": "test_user",
        "PGVECTOR_PASSWORD": "test_pass",
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
    """Patch psycopg2.connect to return a mock database connection."""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = (1,)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("psycopg2.connect", return_value=mock_conn) as mock_connect:
        yield {
            "connect": mock_connect,
            "connection": mock_conn,
            "cursor": mock_cursor,
        }
