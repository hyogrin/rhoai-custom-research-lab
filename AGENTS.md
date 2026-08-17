# RHOAI Custom Deep Research Lab

A research system that performs custom deep research on uploaded documents using
harness engineering — an iterative plan-execute-verify-reflect loop that evolves
research quality through multiple passes.

This file (`AGENTS.md`) is the **LangGraph inner loop definition** — it specifies
the orchestrator's behavior, MCP tool contracts, quality thresholds, and iteration
semantics. The actual harness implementation lives in `agents/orchestrator/graph.py`.

## Architecture

```
User Query + Documents
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│        LangGraph Orchestrator — Iterative Harness       │
│     (inner loop defined in AGENTS.md specification)     │
│                                                         │
│   1. Plan        ─→  2. Execute   ─→  3. Verify        │
│   generate plan      MCP tools:       LLM-as-Judge     │
│   rewrite queries    · vector-search  quality scoring   │
│   section planning   · web-search     citation check    │
│        ↑                                   │            │
│        └──── 4. Reflect (fix failures) ────┘            │
│              dynamic web-search expansion               │
│              failure hints for next iteration            │
│              quality threshold check                    │
└─────────────────────────────────────────────────────────┘
        │ (accept or max_iterations)
        ▼
┌─────────────────────────────────────────────────────────┐
│              Finalize + Citation Resolution              │
│                                                         │
│   [[cite:SRC_ID]] → [N](#cite-N) (deterministic)       │
│   Source registry → numbered References section         │
└─────────────────────────────────────────────────────────┘
        │ (optional, if enabled)
        ▼
┌─────────────────────────────────────────────────────────┐
│     Optional Claim-Evidence Graph (artifact branch)     │
│                                                         │
│   artifact_router → artifact_plan → permission_gate     │
│                                          │              │
│                         ┌────────────────┤              │
│                         ▼ (approved)     ▼ (denied)     │
│                   sandbox_execute      finalize          │
│                         │                               │
│                         ▼                               │
│                   artifact_verify → finalize             │
│                                                         │
│   Execution: NVIDIA OpenShell (policy-controlled)       │
│   Renderer: trusted Python script (networkx SVG)        │
│   Network: deny-all (Landlock enforced)                 │
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

Active MCP servers (FastMCP, **streamable-http** transport):

| MCP Server | Port | Tools | Harness Phase |
|------------|------|-------|---------------|
| `vector-search-mcp` | 9002 | `semantic_search`, `search_by_document`, `get_chunk_context` | Execute |
| `web-search-mcp` | 9003 | `web_search` (SearXNG + DuckDuckGo fallback) | Execute |
| `verification-mcp` | 9004 | `quality_score`, `validate_citations`, `fact_check`, `llm_as_judge`, `run_verification` | Verify |

The `observability-mcp` (port 9005) server is started but currently unused — observability
is handled in-process by `HarnessObserver` (`agents/orchestrator/layers/observability.py`).

Document ingestion (Docling parse → Llama Stack Files API → Vector Store) is handled
directly by the backend API — no MCP indirection needed. Llama Stack handles chunking,
embedding, and vector storage.
Query rewriting, context synthesis, research planning, and report drafting are performed as direct LLM calls within the orchestrator (no MCP overhead for pure prompt operations).

### MCP Transport

- **Protocol**: Streamable HTTP (`FastMCP` with `stateless_http=True`)
- **Endpoint convention**: `http://<server>:<port>/mcp/`
- **Client**: `mcp.client.streamable_http.streamable_http_client` via `agents/orchestrator/layers/tools.py`

## Project Structure

```
0_setup/                  — Environment and model setup
1_document_processing/    — Docling parse + Llama Stack ingestion (data foundation)
2_tool_layer/             — MCP tool servers (vector-search proxy, web-search, verification)
3_harness_engineering/    — Iterative inner loop concept + long transaction pattern
4_agent_orchestration/    — LangGraph orchestrator + system integration
5_deployment/             — OpenShift deployment with Helm
6_evaluation/             — Quality and performance evaluation
```

## Claim-Evidence Graph (Optional Artifact)

After the user accepts a research report, the system can optionally generate a
Claim-Evidence Graph — a visual SVG showing key claims and their supporting or
contradicting evidence.

### How It Works

1. **Toggle**: Enabled via `enableClaimEvidenceGraph` in Research Settings (default: off)
2. **Planning**: LLM extracts claims and evidence from the report as structured JSON
3. **Permission Gate**: User must approve sandbox execution (HITL interrupt)
4. **Sandbox Execution**: Trusted renderer runs inside an NVIDIA OpenShell sandbox
5. **Verification**: SVG is validated (no scripts, no external URLs, valid XML)
6. **Display**: Graph is shown below the research report in the UI

### Security Model

- Sandbox runs with **deny-all network** policy (Landlock enforced)
- Only a trusted, repository-controlled renderer executes
- LLM generates structured JSON only — never executable code
- Execution permissions are managed separately from research settings

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENSHELL_RENDERER_IMAGE` | (required) | Container image with Python + networkx + matplotlib |
| `OPENSHELL_WORKSPACE` | `default` | OpenShell workspace |
| `OPENSHELL_CPU` | `500m` | CPU limit |
| `OPENSHELL_MEMORY` | `512Mi` | Memory limit |
| `OPENSHELL_TIMEOUT_SECONDS` | `60` | Execution timeout |
| `OPENSHELL_POLICY_PATH` | `config/openshell/claim-evidence-policy.yaml` | Security policy |
| `OPENSHELL_REQUIRE_APPROVAL` | `true` | Whether to interrupt for user approval |
| `ARTIFACT_PLAN_TIMEOUT` | `120` | Claim-evidence planning LLM timeout (seconds) |
| `OPENSHELL_GATEWAY_URL` | `http://127.0.0.1:8080` | Gateway endpoint (must match SDK config) |

### Connectivity

The `openshell` CLI and Python SDK connect via gRPC to the endpoint stored in
`~/.config/openshell/gateways/<name>/metadata.json` (written by `openshell gateway add`).
For cluster-based gateways (ClusterIP service, no Route), a port-forward is required:

```bash
oc port-forward svc/openshell 8080:8080 -n openshell
```

`make setup` handles port-forwarding and gateway registration automatically when
OpenShell is detected on the cluster.

### SSE Events

The artifact branch emits these progress events visible in step history:

```
artifact_planning → execution_proposed → permission_required →
permission_approved → sandbox_scheduled → sandbox_running →
artifact_created → artifact_verifying → execution_completed
```

### Testing

```bash
uv run pytest tests/test_artifact_graph.py -v   # Unit tests (mocked OpenShell)
RUN_OPENSHELL_INTEGRATION_TESTS=true uv run pytest tests/test_openshell_integration.py  # Integration (requires gateway)
```

## Running the System

### Local Development

```bash
cp sample.env .env        # Configure model endpoints
make setup                # Install Python deps + provision PostgreSQL (auto-detects cluster vs local)
cd frontend-next && npm install && cd ..  # Install frontend dependencies
make backend-start        # Start backend + auto-start all 4 MCP servers
make frontend-start       # Start Next.js UI (separate terminal)
```

`make setup` runs `uv sync` + `scripts/setup.sh` which:
- Auto-detects if you're on a cluster (`oc whoami`) or local Docker
- Provisions PostgreSQL for harness state (sessions, traces, failures, LangGraph checkpointing)
- Updates `.env` with `POSTGRES_URL`
- Checks for OpenShell availability (admin prerequisite, not installed here)

Document storage and vector search are handled by **Llama Stack** (RHOAI 3.4), not PostgreSQL.
Configure `LLAMA_STACK_URL` and `LLAMA_STACK_API_KEY` in `.env`.

For advanced use:
```bash
./scripts/setup-postgres.sh     # PostgreSQL only (standalone)
./scripts/setup.sh --connect-only    # Port-forward to existing cluster PostgreSQL
```

### Prerequisites (Admin)

| Component | Scope | Provisioned by |
|-----------|-------|----------------|
| Llama Stack (RHOAI 3.4) | Cluster-shared | LlamaStackDistribution CR (RHOAI operator) |
| PostgreSQL | Lab-owned | `make setup` (automatic) |
| Agent Sandbox CRDs | Cluster-shared | `./scripts/install-openshell.sh` (cluster-admin) |
| OpenShell gateway | Cluster-shared | `./scripts/install-openshell.sh` (cluster-admin) |

OpenShell is only required for the optional Claim-Evidence Graph feature.
The core research workflow works without it.

**Install (cluster-admin, one-time):**
```bash
./scripts/install-openshell.sh                    # Install CRDs + gateway (TP defaults)
./scripts/install-openshell.sh -v 0.0.99          # Specific chart version
./scripts/install-openshell.sh --status            # Verify installation
```

The script installs two components:
1. **Agent Sandbox CRDs** (`kubernetes-sigs/agent-sandbox`) — Kubernetes-native sandbox API
2. **OpenShell gateway** (NVIDIA Helm chart) — sandbox lifecycle manager

> **TP (Technology Preview):** TLS is disabled and unauthenticated client access is
> enabled for lab convenience. For production, configure OIDC authentication
> (see `helm show values oci://ghcr.io/nvidia/openshell/helm-chart`, `server.oidc.*`).

**Developer workstation setup (after admin install):**
```bash
openshell gateway add http://127.0.0.1:8080 --name cluster-forward --local
oc port-forward svc/openshell 8080:8080 -n openshell   # required for ClusterIP gateways
openshell sandbox list                                   # verify connectivity
```

`make setup` automatically detects and port-forwards OpenShell when available.

### Frontend-Backend Protocol

The frontend communicates with the backend using the **AG-UI (Agent-User Interaction)
protocol** over SSE. The `ag-ui-langgraph` adapter exposes the orchestrator graph at
`/agent`, translating LangGraph stream events into AG-UI events:

- `TEXT_MESSAGE_START/CONTENT/END` — streaming research output
- `TOOL_CALL_START/ARGS/END` — MCP tool invocations
- `THINKING_START/CONTENT/END` — reasoning visibility
- `STATE_SNAPSHOT` — full state synchronization
- `RUN_FINISHED(outcome="interrupted")` — human-in-the-loop pause

The legacy `/research` SSE endpoint is preserved for backward compatibility with notebooks.

### Human-in-the-Loop

When `MAX_ITERATIONS` is reached without meeting the quality threshold, the graph
pauses at a `human_review` interrupt node. The AG-UI protocol surfaces this as a
`RUN_FINISHED` event with `outcome: "interrupted"`. The frontend renders a review
component showing quality score, iteration info, and improvement suggestions.
The user can accept the result or trigger additional iterations.

### Persistence

- **PostgreSQL checkpointer** (`AsyncPostgresSaver`) — LangGraph graph state persistence
- **PostgreSQL harness state** — research sessions, trace events, failure log
- **Llama Stack vector store** — document embeddings and semantic search
- **Thread management** — `GET/POST/DELETE /threads` endpoints for chat history

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
