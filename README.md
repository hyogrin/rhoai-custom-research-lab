# RHOAI Custom Deep Research Lab

A hands-on lab for building **custom deep research systems** using **multi-agent harness engineering** on **Red Hat OpenShift AI (RHOAI)**. Upload documents, perform iterative deep research through collaborative AI agents with quality-driven feedback loops, and receive comprehensive analytical reports.

## Architecture

```
User Query + Documents
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  AGENTS.md Harness (Iterative Inner Loop)               │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Orchestrator (LangGraph + A2A + Kagenti)        │   │
│  │  Plan → Execute → Verify → Reflect (iterate)    │   │
│  └──────┬──────────┬──────────┬──────────┬──────────┘   │
│         │          │          │          │               │
│    ┌────▼───┐ ┌────▼───┐ ┌───▼────┐ ┌───▼────┐         │
│    │Doc Proc│ │Research│ │ Writer │ │Reviewer│         │
│    │(Docling)│ │(RAG)  │ │(Report)│ │(QA)   │         │
│    └────┬───┘ └────┬───┘ └────────┘ └────────┘         │
│         │          │                                    │
│  ┌──────▼──────────▼──────────────────────────────┐     │
│  │  MCP Tool Layer                                │     │
│  │  doc-mcp │ search-mcp │ analysis-mcp           │     │
│  │  verification-mcp │ observability-mcp          │     │
│  └────────────────────────────────────────────────┘     │
│         │          │                                    │
│    ┌────▼──────────▼────┐  ┌──────────────────┐        │
│    │ PostgreSQL+pgvector │  │ vLLM Model Serve │        │
│    └────────────────────┘  └──────────────────┘        │
└─────────────────────────────────────────────────────────┘
```

## Key Technologies

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Harness Engineering | AGENTS.md | Project-specific agent instructions, inner loop definition |
| Agent Control Plane | Kagenti | K8s-native agent lifecycle, identity, discovery |
| Agent Framework | LangGraph | Stateful graph-based agent logic |
| Inter-agent Protocol | A2A (Agent-to-Agent) | Standardized agent communication (JSON-RPC 2.0) |
| Tool Protocol | MCP (Model Context Protocol) | Standardized tool exposure (doc, search, analysis, verification, observability) |
| Document Intelligence | Docling | PDF/DOCX/PPTX parsing, table extraction, OCR |
| Vector Store | PostgreSQL + pgvector | Semantic search over document embeddings |
| Model Serving | RHOAI vLLM | LLM and embedding inference |

## Lab Flow

| Phase | Folder | Focus | Key Outcome |
|-------|--------|-------|-------------|
| **0** | `0_setup/` | Environment & model setup | Cluster ready, model endpoints verified |
| **1** | `1_document_processing/` | Docling + pgvector | Documents parsed, chunked, embedded |
| **2** | `2_tool_layer/` | MCP tool servers | All MCP tools built and tested (doc, search, analysis, verification, observability) |
| **3** | `3_harness_engineering/` | AGENTS.md + inner loop | Iterative harness with quality-driven research |
| **4** | `4_agent_orchestration/` | Kagenti + A2A orchestration | Multi-agent pipeline with harness integration |
| **5** | `5_deployment/` | OpenShift deployment | Agents running on cluster via Kagenti |
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
make dev-up   # PostgreSQL+pgvector, MinIO
```

5. Follow phases 0–6 in order.

## Running the UI

The project includes a web UI (Chainlit frontend + FastAPI backend) for interactive document research with real-time progress streaming.

1. Start the backend API:

```bash
make backend-start   # FastAPI on port 8000
```

2. Start the frontend (in a separate terminal):

```bash
make frontend-start  # Chainlit on port 7860
```

3. Or start everything together:

```bash
make ui-start        # backend + frontend
```

4. Open http://localhost:7860 in your browser.

The UI supports:
- **Document upload** — PDF and text files via drag-and-drop
- **Real-time progress** — SSE-streamed harness phases (Plan, Execute, Verify, Reflect) shown as collapsible steps with iteration counter and quality score
- **Session persistence** — Long-running research survives connection drops; resume from the last checkpoint via PostgreSQL-backed session state
- **Configurable harness** — Adjust quality threshold and max iterations from the settings panel

To stop the UI:

```bash
make ui-stop
```

## Prerequisites

| Component | Version | Purpose |
|-----------|---------|---------|
| Red Hat OpenShift | 4.17+ | Container platform |
| OpenShift AI (RHOAI) | 3.4+ | Model serving (vLLM) |
| Kagenti | v0.2+ | Agent control plane |
| Python | 3.11+ | Lab notebooks and agent code |
| uv | 0.4+ | Python package manager |
| Podman | 4+ | Container builds (optional) |

## References

- [AGENTS.md](https://github.com/agentsmd/agents.md) — Open format for AI agent instructions
- [Kagenti ADK](https://github.com/kagenti/adk) — Agent Development Kit
- [Kagenti Platform](https://github.com/kagenti/kagenti) — K8s control plane
- [Docling](https://github.com/docling-project/docling) — Document intelligence
- [A2A Protocol](https://google.github.io/A2A) — Agent-to-Agent standard
