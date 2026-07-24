# Phase 6: Evaluation

## Overview

Evaluate the multi-agent document research system across three dimensions:
observability (are we seeing what happens?), tracing (can we debug why?), and
evaluation (is the quality good enough?). Each dimension maps to a dedicated
notebook with hands-on setup and visual results in RHOAI dashboards.

## What You Will Learn

```
2_observability  →  3_tracing_mlflow  →  4_agent_evaluation  →  5_evaluation_pipeline
   Grafana            MLflow UI            MLflow GenAI            KFP on RHOAI
   LokiStack          autolog tracing      Prompt Registry         Scheduled eval
   Prometheus         span trees           Scorers + Judge         Pipeline runs
```

## Notebooks

| # | Notebook | Focus | Where You See Results |
|---|----------|-------|-----------------------|
| 2 | `2_observability.ipynb` | Prometheus metrics, Grafana dashboards, LokiStack log queries | OpenShift Console, Grafana UI |
| 3 | `3_tracing_mlflow.ipynb` | MLflow autolog tracing, span trees, harness trace events | MLflow UI Traces tab |
| 4 | `4_agent_evaluation.ipynb` | Prompt Registry, GenAI datasets, custom + LLM-as-Judge scorers | MLflow UI Evaluation tab |
| 5 | `5_evaluation_pipeline.ipynb` | Kubeflow Pipeline for automated evaluation on RHOAI | RHOAI Data Science Pipelines |

## Evaluation Dimensions

### 1. Research Quality

| Metric | Description | Target |
|--------|-------------|--------|
| Relevance | Are retrieved passages relevant to the query? | > 0.7 avg similarity |
| Completeness | Does the report cover all aspects of the question? | 8+/10 coverage score |
| Accuracy | Are claims supported by source citations? | > 90% citation validity |
| Coherence | Is the report well-structured and readable? | 7+/10 quality score |

### 2. Pipeline Performance

| Metric | Description | Target |
|--------|-------------|--------|
| End-to-end latency | Total time from query to report | < 60s |
| Ingestion throughput | Documents processed per minute | > 5 docs/min |
| Retrieval latency | Time for semantic search (p95) | < 500ms |
| MCP tool call | MCP round-trip time | < 200ms |

### 3. Cost Efficiency

| Metric | Description |
|--------|-------------|
| Token usage | Total tokens consumed per research query |
| LLM calls | Number of inference calls per pipeline run |
| Agent utilization | % time each agent is active vs idle |

## MLflow Integration

Track experiments using MLflow on RHOAI:
- **Tracing**: Zero-code autolog captures every LLM call, tool invocation, and agent decision
- **Prompt Registry**: Version and track evaluation prompts, link traces to prompt versions
- **GenAI Datasets**: Persistent, versioned test datasets on the MLflow server
- **Scorers**: Deterministic checks (fast) + LLM-as-Judge (comprehensive)
- **Evaluation Runs**: Compare metrics across configurations in the MLflow UI

## Evaluation Methodology

1. **Set up observability**: Verify Grafana, LokiStack, and Prometheus metrics (notebook 2)
2. **Inspect traces**: Explore MLflow autolog traces and harness trace events (notebook 3)
3. **Run evaluation**: Register prompts, create datasets, run scorers (notebook 4)
4. **Automate with pipelines**: Package evaluation as a KFP pipeline on RHOAI (notebook 5)
