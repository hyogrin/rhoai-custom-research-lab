"""Artifact storage abstraction.

Stores generated artifacts (SVGs, metadata) and serves them via URL.
Falls back to local file storage when MinIO is not configured.
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
        self._use_minio = False
        self._minio_client = None
        self._bucket = "artifacts"
        self._try_minio()

    def _try_minio(self):
        endpoint = os.environ.get("MINIO_ENDPOINT", "")
        if not endpoint:
            logger.info("MinIO not configured — using local artifact storage")
            os.makedirs(ARTIFACTS_DIR, exist_ok=True)
            return
        try:
            from minio import Minio
            self._minio_client = Minio(
                endpoint,
                access_key=os.environ.get("MINIO_ACCESS_KEY", ""),
                secret_key=os.environ.get("MINIO_SECRET_KEY", ""),
                secure=os.environ.get("MINIO_SECURE", "false").lower() == "true",
            )
            if not self._minio_client.bucket_exists(self._bucket):
                self._minio_client.make_bucket(self._bucket)
            self._use_minio = True
            logger.info("Using MinIO for artifact storage")
        except Exception as e:
            logger.warning("MinIO unavailable (%s) — using local storage", e)
            os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    def save(self, artifact_id: str, data: bytes, content_type: str = "image/svg+xml") -> str:
        """Save artifact data, return a URL path for retrieval."""
        if not artifact_id:
            artifact_id = f"artifact-{uuid.uuid4().hex[:8]}"

        if self._use_minio and self._minio_client:
            import io
            self._minio_client.put_object(
                self._bucket,
                artifact_id,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return f"/artifacts/{artifact_id}"

        local_path = Path(ARTIFACTS_DIR) / artifact_id
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        return f"/artifacts/{artifact_id}"

    def get(self, artifact_id: str) -> bytes | None:
        """Retrieve artifact data by ID."""
        if self._use_minio and self._minio_client:
            try:
                response = self._minio_client.get_object(self._bucket, artifact_id)
                return response.read()
            except Exception:
                return None
            finally:
                if 'response' in locals():
                    response.close()
                    response.release_conn()

        local_path = Path(ARTIFACTS_DIR) / artifact_id
        if local_path.exists():
            return local_path.read_bytes()
        return None

    def get_url(self, artifact_id: str) -> str:
        """Get the URL path for an artifact."""
        return f"/artifacts/{artifact_id}"
