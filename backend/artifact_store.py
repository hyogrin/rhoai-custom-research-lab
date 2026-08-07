"""Artifact storage abstraction.

Stores generated artifacts (SVGs, metadata) using local file storage.
"""

import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "artifacts")


class ArtifactStore:
    """Store and retrieve generated artifacts."""

    def __init__(self):
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    def save(self, artifact_id: str, data: bytes, content_type: str = "image/svg+xml") -> str:
        """Save artifact data, return a URL path for retrieval."""
        if not artifact_id:
            artifact_id = f"artifact-{uuid.uuid4().hex[:8]}"

        local_path = Path(ARTIFACTS_DIR) / artifact_id
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        return f"/artifacts/{artifact_id}"

    def get(self, artifact_id: str) -> bytes | None:
        """Retrieve artifact data by ID."""
        local_path = Path(ARTIFACTS_DIR) / artifact_id
        if local_path.exists():
            return local_path.read_bytes()
        return None

    def get_url(self, artifact_id: str) -> str:
        """Get the URL path for an artifact."""
        return f"/artifacts/{artifact_id}"
