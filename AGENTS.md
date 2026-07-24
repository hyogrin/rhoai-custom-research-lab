# RHOAI Custom Deep Research Lab

A research system that performs custom deep research on uploaded documents using
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
│   rewrite queries    (vector-search,   citation check   │
│   load context        web-search)      fact check       │
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
| `vector-search-mcp` | 9002 | `semantic_search`, `search_by_document`, `get_chunk_context` | Execute |
| `web-search-mcp` | 9003 | `web_search` | Execute |
| `verification-mcp` | 9004 | `quality_score`, `validate_citations`, `fact_check`, `llm_as_judge`, `run_verification` | Verify |
| `observability-mcp` | 9005 | `record_trace`, `record_failure`, `get_metrics`, `get_failure_hints`, `get_past_failure_patterns` | Reflect |

Document ingestion (Docling → embedding → pgvector) is handled directly by the backend API — no MCP indirection needed.
Query rewriting, context synthesis, research planning, and report drafting are performed as direct LLM calls within the orchestrator (no MCP overhead for pure prompt operations).

### MCP Transport

- **Protocol**: Streamable HTTP (`FastMCP` with `stateless_http=True`)
- **Endpoint convention**: `http://<server>:<port>/mcp/`
- **Client**: `mcp.client.streamable_http.streamablehttp_client` via `agents/orchestrator/layers/mcp_client.py`

## Project Structure

```
0_setup/                  — Environment and model setup
1_document_processing/    — Docling + pgvector (data foundation)
2_tool_layer/             — MCP tool servers (vector-search, web-search, verification, observability)
3_harness_engineering/    — AGENTS.md concept + iterative inner loop + long transaction
4_agent_orchestration/    — LangGraph orchestrator + system integration
5_deployment/             — OpenShift deployment with Helm
6_evaluation/             — Quality and performance evaluation
```

## Running the System

### Local Development

```bash
cp sample.env .env        # Configure model endpoints
uv sync                   # Install dependencies
make dev-up               # Start PostgreSQL+pgvector, MinIO, SearXNG
make backend-start        # Start backend + auto-start all 4 MCP servers
make frontend-start       # Start Chainlit UI (separate terminal)
```

### Running a Research Query

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "Your research query", "quality_threshold": 7.0, "max_iterations": 3}'
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
- Do not wrap pure LLM prompt calls in MCP — use MCP only for tools with external system integration
- Do not use fixed iteration counts — use quality thresholds for termination
- Do not discard accumulated context between iterations
