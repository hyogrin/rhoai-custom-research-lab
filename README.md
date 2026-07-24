# RHOAI Custom Deep Research Lab

A hands-on lab for building **custom deep research systems** using **harness engineering** on **Red Hat OpenShift AI (RHOAI)**. Upload documents, perform iterative deep research through a quality-driven feedback loop, and receive comprehensive analytical reports.

## Architecture

```mermaid
flowchart TB
    subgraph UI ["User Interface"]
        Browser(("Browser"))
        Chainlit["Chainlit Frontend\n:7860"]
        Backend["FastAPI Backend\n:8000\n(SSE Streaming)"]
    end

    subgraph Orchestrator ["LangGraph Orchestrator"]
        Graph["StateGraph\n(harness controller)"]
        MCPClient["MCP Client Layer"]
        Context["Context Layer"]
        Observability["Observability Layer"]
    end

    subgraph Harness ["AGENTS.md Harness — Iterative Inner Loop"]
        direction LR
        Plan["1. Plan\ngenerate plan\nrewrite queries"]
        Execute["2. Execute\nuse MCP tools\n(search, draft)"]
        Verify["3. Verify\nquality scoring\ncitation + fact check"]
        Reflect["4. Reflect\nfailure memory\ncost tracking"]
        Plan --> Execute --> Verify --> Reflect
        Reflect -- "score < threshold" --> Plan
    end

    subgraph MCP ["MCP Tool Layer · FastMCP · Streamable HTTP"]
        VectorMCP["vector-search-mcp\n:9002\nsemantic search"]
        WebMCP["web-search-mcp\n:9003\nweb search (SearXNG)"]
        VerifMCP["verification-mcp\n:9004\nscore, cite, fact-check"]
        ObsMCP["observability-mcp\n:9005\ntrace, failure, metrics"]
    end

    subgraph Infra ["Infrastructure"]
        PG[("PostgreSQL\n+ pgvector")]
        MinIO[("MinIO\nObject Storage")]
        vLLM["RHOAI vLLM\nModel Serving"]
    end

    Browser -- "HTTP" --> Chainlit
    Chainlit -- "REST + SSE" --> Backend
    Backend -- "auto-start\nsubprocess" --> MCP
    Backend -- "invoke graph" --> Graph
    Backend -- "Docling direct" --> PG
    Backend -- "file store" --> MinIO
    Graph -.-> Harness
    MCPClient -- "MCP\nstreamable-http" --> MCP
    VectorMCP --> PG
    WebMCP & VerifMCP --> vLLM
    VectorMCP --> vLLM
```

### Harness Inner Loop Detail

```
    ┌──────────┐     ┌──────────┐     ┌──────────┐
    │  1.Plan  │────▶│2.Execute │────▶│ 3.Verify │
    │ generate │     │ MCP tool │     │ quality  │
    │  plan    │     │ calls    │     │ scoring  │
    └──────────┘     └──────────┘     └─────┬────┘
         ▲                                  │
         │           ┌──────────┐           │
         └───────────│4.Reflect │◀──────────┘
        score <      │ failure  │
        threshold    │ memory   │
                     └──────────┘
    Iterations stop when score >= QUALITY_THRESHOLD or MAX_ITERATIONS reached.
```

## Key Technologies

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Harness Engineering | AGENTS.md | Project-specific agent instructions, inner loop definition |
| Orchestration | LangGraph | Stateful graph-based harness controller |
| Tool Protocol | MCP (Model Context Protocol) | Standardized tool exposure via FastMCP + streamable-http |
| Document Intelligence | Docling | PDF/DOCX/PPTX parsing, table extraction, OCR |
| Vector Store | PostgreSQL + pgvector | Semantic search over document embeddings |
| Object Storage | MinIO | Document file storage |
| Model Serving | RHOAI vLLM | LLM and embedding inference |
| Web UI | Chainlit + FastAPI | Interactive research with real-time SSE progress |

## Lab Flow

| Phase | Folder | Focus | Key Outcome |
|-------|--------|-------|-------------|
| **0** | `0_setup/` | Environment & model setup | Cluster ready, model endpoints verified |
| **1** | `1_document_processing/` | Docling + pgvector | Documents parsed, chunked, embedded |
| **2** | `2_tool_layer/` | MCP tool servers | All MCP tools built and tested (vector-search, web-search, verification, observability) |
| **3** | `3_harness_engineering/` | AGENTS.md + inner loop | Iterative harness with quality-driven research |
| **4** | `4_agent_orchestration/` | LangGraph system integration | Full pipeline wired and tested end-to-end |
| **5** | `5_deployment/` | OpenShift deployment | System running on cluster via Helm |
| **6** | `6_evaluation/` | Quality & performance | Research quality metrics validated |

## Quick Start

1. Clone this repo:

```bash
git clone https://github.com/hyogrin/rhoai-custom-research-lab.git
cd rhoai-custom-research-lab
```

2. Configure environment:

```bash
cp sample.env .env
# Edit .env with your model endpoints (LLM_BASE_URL, EMBEDDING_BASE_URL)
# Models must be pre-deployed on RHOAI or any OpenAI-compatible endpoint
```

3. Install Python dependencies:

```bash
uv sync
```

4. Start local services:

```bash
make dev-up   # PostgreSQL+pgvector, MinIO, SearXNG
```

5. Follow phases 0–6 in order.

## Running the UI

The project includes a web UI (Chainlit frontend + FastAPI backend) for interactive document research with real-time progress streaming.

```mermaid
flowchart LR
    A["make dev-up"] --> B["make backend-start"]
    B --> C["make frontend-start"]
    B -. "auto-starts\n4 MCP servers\nas subprocesses" .-> D["MCP :9002-9005"]
```

1. Start infrastructure (only once):

```bash
make dev-up          # PostgreSQL+pgvector, MinIO, SearXNG
```

2. Start the backend API (auto-starts all 4 MCP servers):

```bash
make backend-start   # FastAPI :8000 + MCP :9002-9005
```

3. Start the frontend (in a separate terminal):

```bash
make frontend-start  # Chainlit on port 7860
```

4. Open http://localhost:7860 in your browser.

The UI supports:
- **Document upload** — PDF and text files via drag-and-drop
- **Real-time progress** — SSE-streamed harness phases (Plan, Execute, Verify, Reflect) shown as collapsible steps with iteration counter and quality score
- **Session persistence** — Long-running research survives connection drops; resume from the last checkpoint via PostgreSQL-backed session state
- **Configurable harness** — Adjust quality threshold and max iterations from the settings panel

To stop everything:

```bash
make ui-stop         # Stops backend + frontend + MCP servers
```

## System Ports

| Service | Port | Protocol | Description |
|---------|------|----------|-------------|
| Chainlit Frontend | 7860 | HTTP | Web UI |
| FastAPI Backend | 8000 | HTTP + SSE | API server (auto-starts MCP subprocesses, Docling direct ingest) |
| vector-search-mcp | 9002 | MCP (streamable-http) | Semantic search over pgvector |
| web-search-mcp | 9003 | MCP (streamable-http) | Web search via SearXNG |
| verification-mcp | 9004 | MCP (streamable-http) | Quality score, citation/fact check |
| observability-mcp | 9005 | MCP (streamable-http) | Traces, failures, metrics |

## Prerequisites

| Component | Version | Purpose |
|-----------|---------|---------|
| Red Hat OpenShift | 4.17+ | Container platform |
| OpenShift AI (RHOAI) | 3.4+ | Model serving (vLLM) |
| Python | 3.11+ | Lab notebooks and agent code |
| uv | 0.4+ | Python package manager |
| Podman | 4+ | Container builds (optional) |

## References

- [AGENTS.md](https://github.com/agentsmd/agents.md) — Open format for AI agent instructions
- [LangGraph](https://langchain-ai.github.io/langgraph/) — Stateful graph-based agent framework
- [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) — Tool protocol standard
- [Docling](https://github.com/docling-project/docling) — Document intelligence
- [FastMCP](https://github.com/jlowin/fastmcp) — Python MCP server framework
