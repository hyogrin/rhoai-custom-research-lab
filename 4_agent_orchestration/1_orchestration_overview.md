# Agent Orchestration: Kagenti + LangGraph + A2A

## Overview

This phase builds individual AI agents and connects them into a coordinated multi-agent system. Each agent uses **LangGraph** for stateful logic, wrapped with **Kagenti ADK** for production deployment, and connected via the **A2A (Agent-to-Agent) protocol** for inter-agent communication. The Orchestrator agent acts as a supervisor, discovering sub-agents and delegating tasks dynamically.

## Technology Stack

### Kagenti
[Kagenti](https://github.com/kagenti/kagenti) is a Kubernetes-native control plane for AI agents developed by Red Hat. It provides:
- **Component CRD**: Deploy agents as K8s resources
- **SPIFFE/SPIRE identity**: Automatic mTLS and workload identity
- **A2A discovery**: Agents discover each other via AgentCard
- **Framework-neutral**: Works with LangGraph, CrewAI, BeeAI, etc.

### Kagenti ADK
The [Agent Development Kit](https://github.com/kagenti/adk) provides:
- **Python SDK**: `@server.agent()` decorator for A2A compliance
- **CLI**: Scaffold, run locally, deploy to cluster
- **Built-in services**: LLM proxy, pgvector, Docling, Keycloak, Phoenix

### LangGraph
[LangGraph](https://github.com/langchain-ai/langgraph) provides graph-based agent orchestration:
- **StateGraph**: Define workflows as directed graphs
- **Nodes**: Processing steps (LLM calls, tool execution, logic)
- **Edges**: Control flow between nodes (conditional routing)
- **Compile**: Produces an executable graph with `ainvoke()`

### A2A Protocol
The [Agent-to-Agent protocol](https://google.github.io/A2A) (Linux Foundation) standardizes agent communication:
- **AgentCard**: JSON metadata at `/.well-known/agent-card.json`
- **JSON-RPC 2.0**: Standard request/response over HTTPS
- **AgentSkills**: Declared capabilities for discovery
- **Task lifecycle**: Submit, monitor, complete

## Agent Pattern

Each agent in this lab follows:

```
┌────────────────────────────────────────┐
│  Kagenti ADK Server                     │
│  ┌──────────────────────────────────┐  │
│  │  @server.agent() decorator       │  │
│  │  ┌────────────────────────────┐  │  │
│  │  │  LangGraph StateGraph      │  │  │
│  │  │  ┌─────┐  ┌─────┐  ┌───┐  │  │  │
│  │  │  │Node1├──►Node2├──►END│  │  │  │
│  │  │  └─────┘  └─────┘  └───┘  │  │  │
│  │  └────────────────────────────┘  │  │
│  └──────────────────────────────────┘  │
│                                        │
│  Exposes:                              │
│  - /.well-known/agent-card.json (A2A) │
│  - JSON-RPC endpoint (A2A messages)    │
│  - Health/readiness probes             │
└────────────────────────────────────────┘
```

## Agents in This Lab

| Agent | Port | Role | Key Tools |
|-------|------|------|-----------|
| Orchestrator | 8100 | Plan + delegate via A2A | a2a_discover, a2a_send_message |
| Document Processor | 8101 | Docling parse + embed | ingest_document, get_status |
| Research Analyst | 8102 | RAG + synthesis | semantic_search, rewrite_query |
| Research Writer | 8103 | Report generation | generate_report, format_citations |
| Research Reviewer | 8104 | Quality validation | score_quality, validate_citations |

## Orchestration Pattern: Supervisor via A2A

Unlike traditional multi-agent patterns that share memory or use direct function calls, this lab uses **A2A protocol** for all inter-agent communication:

```
┌──────────────────────────────────────────────────────┐
│  Orchestrator (Supervisor)                           │
│                                                      │
│  1. Receive user query                               │
│  2. Plan research strategy (LLM)                     │
│  3. Discover agents via AgentCard                    │
│  4. Delegate tasks via A2A JSON-RPC                  │
│  5. Collect results                                  │
│  6. Synthesize final output                          │
└──────┬────────┬────────┬────────┬────────────────────┘
       │        │        │        │
  A2A  │   A2A  │   A2A  │   A2A  │
       ▼        ▼        ▼        ▼
┌──────────┐ ┌──────┐ ┌──────┐ ┌────────┐
│Doc Proc  │ │Resear│ │Writer│ │Reviewer│
│(Docling) │ │(RAG) │ │      │ │        │
└──────────┘ └──────┘ └──────┘ └────────┘
```

## A2A Communication Flow

### 1. Agent Discovery
Each agent publishes an AgentCard at `/.well-known/agent-card.json`:

```json
{
  "name": "research-analyst",
  "description": "Search and synthesize document context",
  "url": "http://researcher:8102",
  "version": "1.0.0",
  "capabilities": {"streaming": true},
  "skills": [
    {"id": "semantic-search", "name": "Semantic Search", "tags": ["rag"]},
    {"id": "context-synthesis", "name": "Context Synthesis", "tags": ["analysis"]}
  ]
}
```

### 2. Task Delegation (JSON-RPC 2.0)
The orchestrator sends tasks via standard A2A messages:

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": "task-001",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "Search for information about..."}]
    }
  }
}
```

### 3. Response Collection
Agents respond with artifacts containing their output:

```json
{
  "jsonrpc": "2.0",
  "id": "task-001",
  "result": {
    "artifacts": [{
      "parts": [{"kind": "text", "text": "Research findings..."}]
    }]
  }
}
```

## Harness Integration

The orchestrator runs the plan-execute-verify-reflect cycle defined in `AGENTS.md`, delegating to sub-agents via A2A during the execute phase:

| Harness Phase | Orchestrator Action | Sub-agents Involved |
|---------------|--------------------|--------------------|
| **Plan** | Generate research plan, rewrite queries | — (internal LLM call) |
| **Execute** | Delegate search, synthesis, writing via A2A | Researcher, Writer, Doc Processor |
| **Verify** | Request quality review via A2A | Reviewer |
| **Reflect** | Record traces, update failure memory | — (internal observability) |

Each iteration through the harness loop may invoke different sub-agents depending on the failure hints from the previous iteration. For example, if verification identifies "missing_citations," the next execute phase targets the Researcher for additional evidence retrieval.

## References

- [Kagenti ADK Docs](https://github.com/kagenti/adk/blob/main/docs/stable/agent-development/overview)
- [How Kagenti ADK simplifies production AI agent management](https://developers.redhat.com/articles/2026/05/04/how-kagenti-adk-simplifies-production-ai-agent-management)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [A2A Protocol Specification](https://google.github.io/A2A)
- [LangGraph + A2A Example](https://github.com/5enxia/langgraph-multiagent-with-a2a)
