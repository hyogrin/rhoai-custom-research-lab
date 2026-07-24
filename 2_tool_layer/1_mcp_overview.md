# Tool Layer: MCP Servers

## Overview

The Tool Layer provides the foundational capabilities that the research harness uses to interact with external systems. Instead of embedding tool logic directly into agents, we expose **infrastructure tools** as **Model Context Protocol (MCP) servers** — standardized, independently deployable services. LLM-powered analysis (query rewriting, drafting, planning) is handled directly by agents via prompt calls to reduce unnecessary overhead.

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
│ AGENTS.md Harness Controller                                    │
│ (connects to MCP servers as tools in the inner loop)            │
│ (LLM analysis/drafting via direct prompt calls)                 │
│ (document ingestion via backend API — Docling direct)           │
└───┬──────────────┬──────────────┬──────────────────────────────┘
    │              │              │
┌───▼──────────┐ ┌▼──────────────┐ ┌▼────────────────┐
│vector-search-│ │verification-  │ │observability-   │
│mcp (pgvector)│ │mcp (QA)       │ │mcp (trace)      │
└──────────────┘ └───────────────┘ └─────────────────┘
    │
┌───▼──────────┐
│web-search-mcp│
│(SearXNG)     │
└──────────────┘
```

## MCP Servers in This Lab

### 1. Vector Search MCP (`mcp_servers/vector_search_mcp/`)
- **Port**: 9002
- **Purpose**: Semantic search over ingested document chunks
- **Tools**: `semantic_search`, `search_by_document`, `get_chunk_context`
- **Backend**: Embedding model → pgvector similarity queries

### 2. Web Search MCP (`mcp_servers/web_search_mcp/`)
- **Port**: 9003
- **Purpose**: Web search via SearXNG for real-time information
- **Tools**: `web_search`
- **Backend**: SearXNG instance (deployed via compose.yml)

### 3. Verification MCP (`mcp_servers/verification_mcp/`)
- **Port**: 9004
- **Purpose**: Quality assessment after each research iteration
- **Tools**: `quality_score`, `validate_citations`, `fact_check`, `llm_as_judge`, `run_verification`
- **Backend**: LLM inference + rule-based checks

### 4. Observability MCP (`mcp_servers/observability_mcp/`)
- **Port**: 9005
- **Purpose**: Trace collection, failure memory, cost tracking
- **Tools**: `record_trace`, `record_failure`, `get_metrics`, `get_failure_hints`, `get_past_failure_patterns`
- **Backend**: PostgreSQL for persistence

## What About Analysis/Drafting?

Query rewriting, context synthesis, research planning, and report drafting are performed as **direct LLM calls** within the agents themselves (Researcher, Writer, Orchestrator). This avoids the overhead of MCP round-trips for operations that are purely LLM prompt calls with no external system integration.

## MCP Protocol Basics

MCP uses a simple JSON-RPC interface over streamable HTTP:

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
