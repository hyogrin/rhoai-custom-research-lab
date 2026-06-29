# Phase 1: Document Processing with Docling

## Overview

[Docling](https://github.com/docling-project/docling) is an open-source document processing library developed by IBM Research, adopted by Red Hat for use in OpenShift AI pipelines. With 62,000+ GitHub stars, it is the leading open-source tool for converting complex documents into structured formats for generative AI applications.

In this lab, Docling serves as the data foundation for the harness — documents are parsed, chunked, and embedded into pgvector, where the harness's MCP tools can search and retrieve them during iterative research.

## Why Docling?

| Capability | Description |
|-----------|-------------|
| Multi-format support | PDF, DOCX, PPTX, XLSX, HTML, EPUB, images, LaTeX |
| Advanced PDF understanding | Page layout, reading order, table structure, formulas |
| OCR support | Scanned PDFs and images via Tesseract/EasyOCR |
| Semantic chunking | HybridChunker preserves document structure |
| Red Hat integration | KFP pipelines in OpenDataHub, Ray Data scaling |
| VLM support | GraniteDocling model for vision-based extraction |

## Architecture in This Lab

```
Document Upload (PDF/DOCX/PPTX)
        │
        ▼
┌─────────────────┐
│  Docling Parser  │  ← DocumentConverter
│  (Multi-format)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Hybrid Chunker   │  ← Semantic chunking with structure preservation
│ (Token-aware)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Embedding Model  │  ← Granite Embedding via RHOAI
│ (768-dim)        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ PostgreSQL +     │  ← pgvector for similarity search
│ pgvector         │
└─────────────────┘
```

## Key Concepts

### Document Conversion
Docling's `DocumentConverter` handles format detection and parsing automatically. It produces a unified `Document` object with structured content (headings, paragraphs, tables, figures).

### Semantic Chunking
The `HybridChunker` splits documents while respecting:
- Section boundaries (headings)
- Paragraph integrity
- Table completeness
- Token budget (configurable max tokens per chunk)

### pgvector Storage
Chunks are embedded using the Granite embedding model and stored in PostgreSQL with the pgvector extension, enabling cosine similarity search for RAG retrieval.

## References

- [Docling Documentation](https://docling-project.github.io/docling)
- [Red Hat Blog: Docling for Generative AI](https://www.redhat.com/en/blog/docling-missing-document-processing-companion-generative-ai)
- [OpenDataHub Docling Pipeline](https://github.com/opendatahub-io/data-processing/tree/stable/kubeflow-pipelines/docling-standard)
- [Red Hat Blog: Ray Data + Docling](https://www.redhat.com/en/blog/breaking-rag-bottleneck-scalable-document-processing-ray-data-and-docling)
