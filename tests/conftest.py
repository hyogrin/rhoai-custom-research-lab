"""Shared pytest fixtures for the RHOAI research lab test suite."""

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def env_setup(monkeypatch, tmp_path):
    """Set environment variables for testing — mock LLM, Llama Stack, and MCP URLs."""
    env_vars = {
        "LLM_BASE_URL": "http://localhost:8000/v1",
        "LLM_API_KEY": "test-key",
        "LLM_MODEL": "test-model",
        "MAAS_API_KEY": "",
        "LLAMA_STACK_URL": "http://localhost:8321/v1",
        "LLAMA_STACK_API_KEY": "test-key",
        "POSTGRES_URL": "postgresql://test:test@localhost:5432/test_db",
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
            data=[MagicMock(embedding=[0.1] * 768)]
        )
        mock_openai.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_llama_stack():
    """Mock the Llama Stack client module for testing."""
    with patch("lib.llama_stack_client.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        yield mock_client
