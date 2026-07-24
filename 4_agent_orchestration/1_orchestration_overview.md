# Phase 4: LangGraph System Integration

## Overview

This phase integrates all components into a working research system: the **LangGraph orchestrator** drives the harness loop, calling **MCP servers** for tool execution and using the **harness library** for session persistence, tracing, and failure memory. The **FastAPI backend** ties everything together with SSE streaming to the Chainlit frontend.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Backend (:8000)                                     │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  LangGraph StateGraph (orchestrator)                   │  │
│  │                                                        │  │
│  │  normalize → plan → execute → verify → observe         │  │
│  │       ↑                                    │           │  │
│  │       └──── iterate (if score < threshold) ┘           │  │
│  │                    │                                    │  │
│  │                finalize (when done)                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                          │                                    │
│              ┌───────────┼───────────┐                       │
│              ▼           ▼           ▼                        │
│     MCP Client    Context Layer   Observability              │
│     (mcp_client.py) (context.py)  (harness/)                 │
└──────────────┬───────────────────────────────────────────────┘
               │ streamable-http
    ┌──────────┼──────────┬──────────┬──────────┐
    ▼          ▼          ▼          ▼          │
 vector-   web-search  verification  observability
 search    -mcp :9003  -mcp :9004   -mcp :9005
 -mcp :9002
```

## Key Modules

| Module | Path | Purpose |
|--------|------|---------|
| Orchestrator Graph | `agents/orchestrator/agent.py` | LangGraph harness controller (7 nodes) |
| Research State | `agents/orchestrator/state.py` | TypedDict for long-transaction state |
| MCP Client | `agents/orchestrator/layers/mcp_client.py` | Calls 4 MCP servers + direct LLM for planning/drafting |
| Context Layer | `agents/orchestrator/layers/context.py` | Gathers iteration context + past failure memory |
| Observability | `agents/orchestrator/layers/observability.py` | HarnessObserver wrapping trace/failure/metrics |
| Session Manager | `harness/session.py` | PostgreSQL-persisted research sessions |
| Backend API | `backend/api.py` | FastAPI with SSE streaming, file upload, MCP subprocess management |

## Graph Nodes

| Node | LangGraph Function | What It Does |
|------|-------------------|--------------|
| `normalize` | Initialize session, load past failure memory |
| `plan` | Generate research plan (sectioned or flat) via LLM |
| `execute` | Run searches (MCP), draft report sections (LLM) |
| `verify` | Score quality, check citations/facts (verification-mcp) |
| `observe` | Record traces, compile failure hints for next iteration |
| `iterate` | Advance iteration counter (conditional edge from observe) |
| `finalize` | Assemble final report with metadata |

## Data Flow

1. Frontend sends `POST /research` with query + settings
2. Backend creates SSE stream, invokes `orchestrator_graph.ainvoke()`
3. Graph iterates: plan → execute → verify → observe → (iterate or finalize)
4. Each node checkpoints state to PostgreSQL via `SessionManager`
5. Backend emits SSE events mapping each node to UI steps
6. Final output streamed as `content` event with the research report

## Lab Exercises

| Notebook | Focus |
|----------|-------|
| `2_langgraph_orchestrator.ipynb` | Graph structure walkthrough + single query execution |
| `3_end_to_end_test.ipynb` | Full pipeline: upload document → research → verify quality |
