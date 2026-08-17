"""MinIO object store client for document file persistence."""

import logging
import os
from urllib.parse import quote

from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error

load_dotenv()

logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "documents")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() in ("true", "1", "yes")

_client: Minio | None = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
        if not _client.bucket_exists(MINIO_BUCKET):
            _client.make_bucket(MINIO_BUCKET)
            logger.info("Created MinIO bucket: %s", MINIO_BUCKET)
    return _client


def upload_document(local_path: str, document_id: str) -> str:
    """Upload a document to MinIO and return the object store path.

    Returns the S3 object key (e.g., "abc123/paper.pdf").
    """
    client = get_minio_client()
    filename = os.path.basename(local_path)
    object_key = f"{document_id}/{filename}"

    client.fput_object(
        MINIO_BUCKET,
        object_key,
        local_path,
        content_type=_guess_content_type(filename),
    )
    logger.info("Uploaded %s to MinIO: %s/%s", filename, MINIO_BUCKET, object_key)
    return object_key


def get_document_url(object_key: str) -> str:
    """Build a direct access URL for a stored document."""
    protocol = "https" if MINIO_SECURE else "http"
    encoded_key = quote(object_key, safe="/")
    return f"{protocol}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{encoded_key}"


def get_presigned_url(object_key: str, expires_hours: int = 24) -> str:
    """Generate a time-limited presigned URL for document download."""
    from datetime import timedelta

    client = get_minio_client()
    url = client.presigned_get_object(
        MINIO_BUCKET,
        object_key,
        expires=timedelta(hours=expires_hours),
    )
    return url


def _guess_content_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".html": "text/html",
    }
    return types.get(ext, "application/octet-stream")
