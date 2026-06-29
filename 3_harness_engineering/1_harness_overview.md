# Harness Engineering: AGENTS.md + Iterative Research

## Overview

The Execution Layer is the core of the deep research system. It replaces the old linear pipeline with a **harness-controlled iterative loop** that evolves research quality through multiple passes.

## AGENTS.md: The Harness Definition

[AGENTS.md](https://github.com/agentsmd/agents.md) is an open format that gives AI coding agents project-specific instructions. Place it in the project root and every agent (Cursor, Claude Code, OpenCode) reads it automatically.

The `AGENTS.md` file *is* the harness — it defines the plan-execute-verify-reflect cycle scoped to this project's conventions:

```
┌─────────────────────────────────────────────────────────┐
│             AGENTS.md  Harness  (inner loop)            │
│                                                         │
│   1. Plan        ─→  2. Execute   ─→  3. Verify        │
│   read AGENTS.md     use MCP tools     quality checks   │
│   search context     (doc, search,     (scoring, judge, │
│                       analysis)         citations)      │
│        ↑                                   │            │
│        └──── 4. Reflect (observe) ─────────┘            │
│               (trace, failure memory,                   │
│                cost tracking)                           │
└─────────────────────────────────────────────────────────┘
```

Each MCP tool maps to a phase in the inner loop — the harness orchestrator calls them in sequence, iterating until the quality threshold is met.

## From Linear to Iterative

### Before (Linear Pipeline)
```
plan → ingest → research → write → review → finalize (END)
```
- Single pass, no learning
- Review always goes to finalize
- No quality threshold

### After (Iterative Harness)
```
normalize → plan → execute → verify → observe
                ↑                         │
                └──── iterate (if score < threshold)
```
- Multiple iterations refine the output
- Verification provides structured feedback
- Observability enables learning from failures

## The Long Transaction Pattern

Each research session is a **long transaction** — a stateful process that:

1. **Maintains session state** across iterations (accumulated context, drafts, scores)
2. **Learns from failures** within the session (failure hints improve next iteration)
3. **Persists progress** to PostgreSQL (resumable, auditable)
4. **Terminates on quality** (not on step count)

## Research Session State

```python
class ResearchState(TypedDict):
    session_id: str
    query: str
    iteration: int           # Current pass number
    max_iterations: int      # Safety limit
    quality_threshold: float # Target score (e.g., 7.0/10)
    
    research_plan: list[dict]       # Generated per iteration
    accumulated_context: list[dict] # Grows across iterations
    current_draft: str              # Evolves each iteration
    
    verification_history: list[dict]  # All past checks
    quality_score: float              # Latest score
    failure_hints: str                # Guides next iteration
```

## Iteration Flow Example

```
Iteration 1: Broad search → initial draft → score 4/10 (too shallow)
    └── Failure: "insufficient_depth" logged
    └── Hint: "Search for more specific details and examples"

Iteration 2: Targeted search on weak areas → expanded draft → score 6/10
    └── Failure: "missing_citations" logged
    └── Hint: "Ensure every claim references a source"

Iteration 3: Citation-focused search → cited draft → score 8/10 → PASS
    └── Success: session complete
```

## Graph Nodes

| Node | Layer | Purpose |
|------|-------|---------|
| `normalize` | Input | Parse query, initialize session |
| `plan` | Context + Tool | Gather context, generate plan |
| `execute` | Tool + Execution | Search, retrieve, synthesize, draft |
| `verify` | Verification | Quality, citations, facts, judge |
| `observe` | Observability | Record metrics, determine next step |
| `iterate` | Control | Advance iteration counter |
| `finalize` | Output | Produce final report with metadata |

## Lab Exercises

1. **Research Agents** (notebook 2) — Build Researcher + Writer as A2A agents
2. **Iterative Orchestrator** (notebook 3) — Implement the harness controller
3. **Long Transaction** (notebook 4) — Session state management and iteration
