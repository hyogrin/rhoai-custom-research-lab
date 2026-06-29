# Tool Layer: MCP Servers

## Overview

The Tool Layer provides the foundational capabilities that the research harness uses to interact with external systems. Instead of embedding tool logic directly into agents, we expose tools as **Model Context Protocol (MCP) servers** — standardized, independently deployable services that any agent can connect to.

## Why MCP?

| Benefit | Description |
|---------|-------------|
| **Decoupling** | Tools evolve independently of agent logic |
| **Reusability** | Multiple agents share the same tool servers |
| **Testability** | Each MCP server can be tested in isolation |
| **Discoverability** | Standard protocol for tool enumeration |
| **Scalability** | Scale tools independently based on load |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│           AGENTS.md Harness Controller                          │
│      (connects to MCP servers as tools in the inner loop)      │
└───┬──────────┬──────────┬──────────────┬──────────────┬────────┘
    │          │          │              │              │
┌───▼───┐ ┌───▼────┐ ┌───▼────────┐ ┌───▼──────────┐ ┌▼────────────┐
│doc-mcp│ │search- │ │analysis-   │ │verification- │ │observability-│
│(Docling)│ │mcp    │ │mcp (LLM)  │ │mcp (QA)     │ │mcp (trace)  │
└───────┘ │(pgvec) │ └────────────┘ └─────────────┘ └─────────────┘
          └────────┘
```

## MCP Servers in This Lab

### 1. Document MCP (`mcp_servers/doc_mcp/`)
- **Purpose**: Parse and ingest documents using Docling
- **Tools**: `ingest_document`, `get_document_status`, `list_documents`
- **Backend**: Docling → embedding model → PostgreSQL/pgvector

### 2. Search MCP (`mcp_servers/search_mcp/`)
- **Purpose**: Semantic search over ingested document chunks
- **Tools**: `semantic_search`, `search_by_document`, `get_chunk_context`
- **Backend**: Embedding model → pgvector similarity queries

### 3. Analysis MCP (`mcp_servers/analysis_mcp/`)
- **Purpose**: LLM-powered analysis, synthesis, planning, and writing
- **Tools**: `rewrite_query`, `synthesize_context`, `generate_research_plan`, `draft_report`
- **Backend**: LLM inference endpoint (vLLM on RHOAI)

### 4. Verification MCP (`agents/orchestrator/layers/verification.py`)
- **Purpose**: Quality assessment after each research iteration
- **Tools**: `quality_score`, `validate_citations`, `fact_check`, `llm_as_judge`
- **Backend**: LLM inference + rule-based checks

### 5. Observability MCP (`harness/`)
- **Purpose**: Trace collection, failure memory, cost tracking
- **Tools**: `record_trace`, `record_failure`, `get_metrics`, `get_failure_hints`
- **Backend**: PostgreSQL for persistence, in-memory for active sessions

## MCP Protocol Basics

MCP uses a simple JSON-RPC interface:

```json
// List available tools
{"jsonrpc": "2.0", "method": "tools/list", "id": 1}

// Call a tool
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "id": 2,
  "params": {
    "name": "semantic_search",
    "arguments": {"query": "machine learning", "top_k": 5}
  }
}
```

## Lab Exercises

1. **Build MCP Servers** (notebook 2) — Core MCP server implementations
2. **Test MCP Tools** (notebook 3) — Verify each tool independently
3. **Web Search MCP** (notebook 4) — Optional: Add SearXNG for web search
4. **Verification MCP** (notebook 5) — Quality checks as MCP tools
5. **LLM-as-Judge** (notebook 6) — Rubric-based judgment
6. **Threshold Tuning** (notebook 7) — Quality/cost balance
7. **Trace Collection** (notebook 8) — Operation tracing
8. **Failure Memory** (notebook 9) — Cross-session learning
9. **Dashboard** (notebook 10) — Metrics visualization
