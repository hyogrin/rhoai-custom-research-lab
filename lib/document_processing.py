"""Document processing — Docling parse + Llama Stack ingestion.

Docling converts uploaded files to Markdown.
Llama Stack handles chunking, embedding, and vector storage.
"""

import hashlib
import logging
import os
import sys
import tempfile
from typing import Any

from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.llama_stack_client import (
    ensure_vector_store,
    ingest_file,
    upload_file,
)


def parse_to_markdown(file_path: str) -> str:
    """Parse a document with Docling and return Markdown content."""
    converter = DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.DOCX,
            InputFormat.PPTX,
            InputFormat.MD,
            InputFormat.HTML,
        ]
    )
    result = converter.convert(file_path)
    md_content = result.document.export_to_markdown()
    logger.info("Docling parsed %s -> %d chars of markdown", os.path.basename(file_path), len(md_content))
    return md_content


def ingest_document(file_path: str, vector_store_name: str = "research-docs") -> dict[str, Any]:
    """Parse a document with Docling, upload to Llama Stack, and ingest into vector store.

    Flow: Docling parse -> .md temp file -> Llama Stack Files API -> Vector Store ingestion
    """
    try:
        md_content = parse_to_markdown(file_path)
        if not md_content or not md_content.strip():
            return {"document_id": "", "status": "error", "chunk_count": 0, "error": "No content after parsing"}

        document_name = os.path.basename(file_path)
        document_id = hashlib.sha256(file_path.encode()).hexdigest()[:16]

        md_filename = os.path.splitext(document_name)[0] + ".md"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", prefix=md_filename + "_", delete=False) as tmp:
            tmp.write(md_content)
            tmp_path = tmp.name

        try:
            file_id = upload_file(tmp_path, filename=md_filename)
            vector_store_id = ensure_vector_store(vector_store_name)
            result = ingest_file(vector_store_id, file_id)
        finally:
            os.unlink(tmp_path)

        return {
            "document_id": document_id,
            "file_id": file_id,
            "vector_store_id": vector_store_id,
            "status": result.get("status", "unknown"),
            "document_name": document_name,
        }

    except Exception as e:
        logger.error("Document ingestion failed for %s: %s", file_path, e)
        return {"document_id": "", "status": "error", "error": str(e)}
