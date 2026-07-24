"""API tests for backend/api.py using FastAPI TestClient."""

import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_backend_deps():
    """Patch backend dependencies to avoid starting MCP servers and DB connections."""
    patches = [
        patch("backend.api._start_mcp_servers"),
        patch("backend.api._stop_mcp_servers"),
        patch("backend.api.session_mgr", new_callable=MagicMock),
        patch("backend.api.Instrumentator"),
        patch("backend.api.init_mlflow"),
    ]
    started = [p.start() for p in patches]
    yield started
    for p in patches:
        p.stop()


@pytest.fixture
def client(mock_backend_deps):
    """Create a FastAPI TestClient with mocked dependencies."""
    from backend.api import app

    with TestClient(app) as c:
        yield c


class TestHealthEndpoint:
    def test_returns_200(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestResearchEndpoint:
    def test_post_research_returns_streaming_response(self, client, mock_backend_deps):
        session_mgr = mock_backend_deps[2]
        session_mgr.save = MagicMock()

        with patch("backend.api.orchestrator_graph") as mock_graph:
            async def mock_stream(*args, **kwargs):
                yield {"normalize": {"session_id": "test-123", "iteration": 1, "status": "planning", "failure_hints": ""}}
                yield {"finalize": {"final_output": "Research complete", "total_cost": 0.0, "status": "complete"}}

            mock_graph.astream = mock_stream

            response = client.post(
                "/research",
                json={
                    "query": "What is AI?",
                    "quality_threshold": 7.0,
                    "max_iterations": 2,
                },
            )

            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")

    def test_post_research_requires_query(self, client):
        response = client.post("/research", json={})

        assert response.status_code == 422


class TestUploadEndpoint:
    def test_upload_files_returns_upload_id(self, client, mock_backend_deps):
        file_content = b"Sample document content for testing"
        files = [("files", ("test_doc.txt", BytesIO(file_content), "text/plain"))]

        with patch("backend.api._process_documents_background"):
            response = client.post("/upload", files=files)

        assert response.status_code == 200
        data = response.json()
        assert "upload_id" in data
        assert data["status"] == "processing"
        assert "test_doc.txt" in data["files"]

    def test_upload_multiple_files(self, client, mock_backend_deps):
        files = [
            ("files", ("doc1.pdf", BytesIO(b"PDF content"), "application/pdf")),
            ("files", ("doc2.txt", BytesIO(b"Text content"), "text/plain")),
        ]

        with patch("backend.api._process_documents_background"):
            response = client.post("/upload", files=files)

        assert response.status_code == 200
        data = response.json()
        assert len(data["files"]) == 2


class TestSessionStatusEndpoint:
    def test_returns_session_progress(self, client, mock_backend_deps):
        session_mgr = mock_backend_deps[2]
        session_mgr.get_progress.return_value = {
            "session_id": "sess-001",
            "status": "researching",
            "iteration": 2,
            "max_iterations": 3,
            "quality_score": 6.5,
        }

        response = client.get("/sessions/sess-001/status")

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "sess-001"
        assert data["status"] == "researching"
        assert data["iteration"] == 2

    def test_returns_404_for_unknown_session(self, client, mock_backend_deps):
        session_mgr = mock_backend_deps[2]
        session_mgr.get_progress.return_value = None

        response = client.get("/sessions/nonexistent/status")

        assert response.status_code == 404
