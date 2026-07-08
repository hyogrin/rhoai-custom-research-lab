# RHOAI Custom Deep Research Lab

A multi-agent system that performs custom deep research on uploaded documents using
harness engineering — an iterative plan-execute-verify-reflect loop that evolves
research quality through multiple passes.

## Architecture

```
User Query + Documents
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│             AGENTS.md  Harness  (inner loop)            │
│                                                         │
│   1. Plan        ─→  2. Execute   ─→  3. Verify        │
│   generate plan      use MCP tools     quality scoring  │
│   rewrite queries    (doc, search,     citation check   │
│   load context        analysis)        fact check       │
│        ↑                                   │            │
│        └──── 4. Reflect (fix failures) ────┘            │
│              trace collection                           │
│              failure memory                             │
│              cost tracking                              │
└─────────────────────────────────────────────────────────┘
```

## Conventions

### Quality Threshold

- Default: `QUALITY_THRESHOLD=7.0` in `.env`
- Range: 1-10 (LLM-as-Judge rubric)
- Iterations stop when score >= threshold or `MAX_ITERATIONS` reached

### Iteration Limits

- Default: `MAX_ITERATIONS=3` in `.env`
- Each iteration accumulates context — never discard previous findings

### Failure Categories

| Category | Types |
|----------|-------|
| Content | `insufficient_depth`, `missing_citations`, `hallucination` |
| Retrieval | `low_relevance`, `no_results` |
| System | `timeout`, `token_limit` |
| Verification | `quality_below_threshold`, `citation_invalid` |

## MCP Tools Available

All capabilities are exposed as FastMCP servers with **streamable-http** transport
for standardized, network-accessible, horizontally scalable access:

| MCP Server | Port | Tools | Harness Phase |
|------------|------|-------|---------------|
| `doc-mcp` | 9001 | `ingest_document`, `get_document_status`, `list_documents` | Execute |
| `search-mcp` | 9002 | `semantic_search`, `search_by_document`, `get_chunk_context`, `web_search` | Execute |
| `analysis-mcp` | 9003 | `rewrite_query`, `synthesize_context`, `generate_research_plan`, `draft_report`, `generate_sectioned_plan`, `draft_section`, `assemble_report` | Plan + Execute |
| `verification-mcp` | 9004 | `quality_score`, `validate_citations`, `fact_check`, `llm_as_judge`, `run_verification` | Verify |
| `observability-mcp` | 9005 | `record_trace`, `record_failure`, `get_metrics`, `get_failure_hints`, `get_past_failure_patterns` | Reflect |

### MCP Transport

- **Protocol**: Streamable HTTP (`FastMCP` with `stateless_http=True`)
- **Endpoint convention**: `http://<server>:<port>/mcp/`
- **Client**: `mcp.client.streamable_http.streamablehttp_client` via `agents/orchestrator/layers/mcp_client.py`
- **Feature flag**: `USE_MCP=true` in `.env` (set to `false` for legacy direct-call mode)

## Project Structure

```
0_setup/                  — Environment and model setup
1_document_processing/    — Docling + pgvector (data foundation)
2_tool_layer/             — All MCP tools (doc, search, analysis, verification, observability)
3_harness_engineering/    — AGENTS.md concept + iterative inner loop + long transaction
4_agent_orchestration/    — Kagenti + LangGraph + A2A multi-agent orchestration
5_deployment/             — OpenShift + Kagenti deployment
6_evaluation/             — Quality and performance evaluation
```

## Running the System

### Local Development

```bash
cp sample.env .env        # Configure model endpoints
uv sync                   # Install dependencies
make dev-up               # Start PostgreSQL+pgvector, MinIO
make backend-start        # Start backend + auto-start all 5 MCP servers
make frontend-start       # Start Chainlit UI (separate terminal)
```

### Running a Research Query

```bash
curl -X POST http://localhost:8100 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"message/send","id":"1",
       "params":{"message":{"role":"user","parts":[{"kind":"text","text":"Your research query"}]}}}'
```

### Testing

```bash
make test                 # Run all tests
make lint                 # Lint Python code
```

## Code Conventions

- **Language**: All code, comments, markdown — English only
- **Notebooks**: One action per cell, markdown before each code cell, status emoji output
- **Idempotent**: Every notebook cell safe to re-run
- **`.env` state**: Auto-detect values on first run, skip on subsequent runs
- **Numbered headings**: Sequential within each notebook (`## 1.`, `## 2.`, ...)

## Common Pitfalls

- Do not hardcode cluster-specific values — derive from `oc` commands or `.env`
- Do not skip `.env` updates after creating resources
- Do not embed tool logic directly in agents — expose via MCP servers
- Do not use fixed iteration counts — use quality thresholds for termination
- Do not discard accumulated context between iterations
