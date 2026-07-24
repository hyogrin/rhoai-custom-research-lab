---
name: harness-engineering
description: |
  Design and implement harness-driven multi-agent research systems using the
  AGENTS.md open format and the plan-execute-verify-reflect inner loop.

  Use when:
  - Creating or editing AGENTS.md files for agent-aware projects
  - Designing iterative plan-execute-verify-reflect loops
  - Building MCP tools that serve as harness components (verification, observability)
  - Configuring quality thresholds, iteration limits, or failure categories
  - Implementing the long transaction pattern for stateful research sessions
  - Discussing harness engineering concepts or architecture
---

# Harness Engineering

## What Is Harness Engineering?

Harness engineering is the practice of turning a generic AI coding agent into a
**project-aware** one by providing structured instructions via an `AGENTS.md` file.
The `AGENTS.md` file *is* the harness — it defines the inner loop that every agent
follows when working on the project.

## The Inner Loop

```
┌─────────────────────────────────────────────────────────┐
│             AGENTS.md  Harness  (inner loop)            │
│                                                         │
│   1. Plan        ─→  2. Execute   ─→  3. Verify        │
│   read AGENTS.md     follow            Code Sandbox     │
│   search codebase    conventions       run & test       │
│        ↑                                   │            │
│        └──── 4. Reflect (fix failures) ────┘            │
└─────────────────────────────────────────────────────────┘
```

### Phase 1: Plan

The agent reads `AGENTS.md`, searches the codebase for context, and formulates a
strategy. In a research harness, this includes generating a research plan with
specific search queries and analysis steps.

### Phase 2: Execute

The agent follows the plan using available tools. In the research harness, these
are MCP tools: document ingestion, semantic search, context synthesis, report drafting.

### Phase 3: Verify

The agent validates its work against quality criteria. In the research harness, this
includes quality scoring, citation validation, fact checking, and LLM-as-judge
evaluation.

### Phase 4: Reflect

If verification fails, the agent analyzes what went wrong, categorizes the failure,
and feeds improvement hints back into the next planning phase.

## AGENTS.md Structure

Place `AGENTS.md` in the project root. Every compatible agent (Cursor, Claude Code,
OpenCode) reads it automatically. Key sections:

```markdown
# Project Name

## Overview
What this project does and how agents should approach it.

## Architecture
System components, data flow, key abstractions.

## Conventions
Code style, file organization, naming patterns.

## Tools Available
MCP servers, CLI commands, APIs the agent can use.

## Testing & Verification
How to run tests, what quality bar to meet.

## Common Pitfalls
Known issues, anti-patterns, things to avoid.
```

Reference: [AGENTS.md specification](https://github.com/agentsmd/agents.md)

## MCP Tools as Harness Components

Instead of embedding tool logic directly into agents, expose capabilities as
**Model Context Protocol (MCP) servers**. Each layer of the harness maps to one
or more MCP tools:

| Harness Phase | Tools | Purpose |
|---------------|-------|---------|
| Plan | Direct LLM calls | Generate research plans, rewrite queries |
| Execute | `vector-search-mcp`, `web-search-mcp` | Semantic search, web search |
| Execute | Direct LLM calls | Synthesize context, draft reports |
| Verify | `verification-mcp` | Quality scoring, citation check, fact check, LLM-as-judge |
| Reflect | `observability-mcp` | Trace collection, failure memory, metrics |

Benefits of MCP-based tools:
- **Decoupling**: Tools evolve independently of agent logic
- **Reusability**: Multiple agents share the same tool servers
- **Testability**: Each MCP server can be tested in isolation
- **Discoverability**: Standard protocol for tool enumeration

## Quality Threshold Conventions

The quality threshold determines when research output is "good enough" to stop iterating:

| Threshold | Typical Iterations | Use Case |
|-----------|-------------------|----------|
| 5.0 (Low) | 1-2 | Quick, exploratory research |
| 7.0 (Medium) | 2-3 | Balanced quality/cost (recommended default) |
| 9.0 (High) | 3-5 | Exhaustive, publication-quality research |

### Verification Components

1. **Quality Scorer** (LLM-based): Scores completeness, accuracy, clarity, structure (1-10 each)
2. **Citation Validator** (rule-based): Verifies `[Source N]` references exist in context
3. **Fact Checker** (LLM cross-reference): Confirms claims are supported by sources
4. **LLM-as-Judge** (rubric-based): 5 criteria scored 0-2 each (relevance, depth, evidence, clarity, completeness)

### Failure Categories

| Category | Types |
|----------|-------|
| Content | `insufficient_depth`, `missing_citations`, `hallucination`, `off_topic`, `repetitive`, `poor_structure` |
| Retrieval | `low_relevance`, `no_results`, `wrong_context` |
| System | `timeout`, `agent_error`, `mcp_error`, `llm_error`, `token_limit` |
| Verification | `quality_below_threshold`, `citation_invalid`, `fact_check_failed` |

## Long Transaction Pattern

Each research session is a **long transaction** — a stateful process that:

1. **Maintains session state** across iterations (accumulated context, drafts, scores)
2. **Learns from failures** within the session (failure hints improve next iteration)
3. **Persists progress** to a database (resumable, auditable)
4. **Terminates on quality** (not on step count)

### Session State Shape

```python
class ResearchState(TypedDict):
    session_id: str
    query: str
    iteration: int
    max_iterations: int
    quality_threshold: float
    research_plan: list[dict]
    accumulated_context: list[dict]
    current_draft: str
    verification_history: list[dict]
    quality_score: float
    failure_hints: str
```

### Iteration Example

```
Iteration 1: Broad search → initial draft → score 4/10 (too shallow)
    └── Failure: "insufficient_depth" → Hint: "Search for specific details"

Iteration 2: Targeted search → expanded draft → score 6/10
    └── Failure: "missing_citations" → Hint: "Ensure every claim references a source"

Iteration 3: Citation-focused → cited draft → score 8/10 → PASS
```

## Graph Nodes (LangGraph Implementation)

| Node | Phase | Purpose |
|------|-------|---------|
| `normalize` | Input | Parse query, initialize session |
| `plan` | Plan | Gather context, generate research plan |
| `execute` | Execute | Search, retrieve, synthesize, draft |
| `verify` | Verify | Quality, citations, facts, judge |
| `observe` | Reflect | Record metrics, categorize failures |
| `iterate` | Control | Advance iteration counter |
| `finalize` | Output | Produce final report with metadata |

## Anti-Patterns

1. **Never skip verification** — always run quality checks before declaring completion.
2. **Never ignore failure hints** — the planner must incorporate hints from previous iterations.
3. **Never hardcode iteration counts** — use quality thresholds for termination.
4. **Never discard accumulated context** — context grows across iterations.
5. **Never embed tool logic in agents** — expose tools via MCP for reusability.
