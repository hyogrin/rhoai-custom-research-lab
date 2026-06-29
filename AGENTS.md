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

All capabilities are exposed as MCP servers for standardized, independent access:

| MCP Server | Tools | Harness Phase |
|------------|-------|---------------|
| `doc-mcp` | `ingest_document`, `get_document_status`, `list_documents` | Execute |
| `search-mcp` | `semantic_search`, `search_by_document`, `get_chunk_context` | Execute |
| `analysis-mcp` | `rewrite_query`, `synthesize_context`, `generate_research_plan`, `draft_report` | Plan + Execute |
| `verification-mcp` | `quality_score`, `validate_citations`, `fact_check`, `llm_as_judge` | Verify |
| `observability-mcp` | `record_trace`, `record_failure`, `get_metrics`, `get_failure_hints` | Reflect |

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
make agents-start         # Start all 5 agents
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
