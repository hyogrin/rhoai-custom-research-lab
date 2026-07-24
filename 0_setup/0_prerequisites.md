# Phase 0: Prerequisites

## What This Lab Does

Build a **custom deep research system using harness engineering** on Red Hat OpenShift AI that:
1. Accepts document uploads (PDF, DOCX, PPTX, XLSX)
2. Parses them with Docling and stores semantic chunks in pgvector
3. Performs iterative deep research using a LangGraph orchestrator with MCP tools
4. Delivers comprehensive analytical reports with citations

The system uses **LangGraph** for orchestration, **MCP (Model Context Protocol)** for tool standardization, and **AGENTS.md for harness engineering** to define the iterative plan-execute-verify-reflect loop.

## Required Access

- [ ] Red Hat OpenShift cluster (4.17+) with admin access
- [ ] OpenShift AI (RHOAI) 3.4+ installed
- [ ] **LLM and embedding models already deployed** (or any OpenAI-compatible endpoint)

> **Note:** This lab assumes models are pre-deployed. Fill in `LLM_BASE_URL` and `EMBEDDING_BASE_URL` in your `.env` before starting. The setup notebook verifies connectivity only — it does not deploy models.

## Required Tools (Local Machine)

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | `brew install python@3.11` or system package |
| uv | 0.4+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| oc CLI | 4.14+ | [Download](https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/) |
| Podman | 4+ | `brew install podman` or system package |
| Git | 2.x | System package |

## Optional (for local development without cluster)

For running the full system locally without an OpenShift cluster:
- Podman Compose (for PostgreSQL + MinIO + SearXNG containers)
- A local LLM server (e.g., LM Studio, Ollama) with OpenAI-compatible API

## Environment Setup

```bash
# 1. Clone the repository
git clone https://github.com/hyogrin/rhoai-custom-research-lab.git
cd rhoai-custom-research-lab

# 2. Create environment file
cp sample.env .env

# 3. Install Python dependencies
uv sync

# 4. Start local services (PostgreSQL+pgvector, MinIO, SearXNG)
make dev-up

# 5. Begin with Phase 0 notebooks
```

## Network Requirements

If running on a cluster, ensure:
- Outbound access to container registries (quay.io, registry.redhat.io)
- Route access for service endpoints
- Internal service communication between pods

## Next Step

Proceed to `1_environment_setup.ipynb` to verify your cluster and deploy models.
