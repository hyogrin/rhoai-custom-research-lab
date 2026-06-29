# Phase 6: Evaluation

## Overview

Evaluate the multi-agent document research system across three dimensions: research quality, pipeline performance, and cost efficiency.

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
| Agent communication | A2A round-trip time | < 200ms |

### 3. Cost Efficiency

| Metric | Description |
|--------|-------------|
| Token usage | Total tokens consumed per research query |
| LLM calls | Number of inference calls per pipeline run |
| Agent utilization | % time each agent is active vs idle |

## Evaluation Methodology

1. **Prepare test corpus**: 10+ diverse documents (research papers, reports, manuals)
2. **Define test queries**: 20+ research questions with expected answers
3. **Run pipeline**: Execute each query through the full multi-agent pipeline
4. **Measure metrics**: Collect latency, quality scores, and token usage
5. **Compare patterns**: Evaluate with/without review loop, different chunk sizes

## MLflow Integration

Track experiments using MLflow on RHOAI:
- Log metrics per query (latency, scores, tokens)
- Compare across configurations
- Visualize quality vs cost tradeoffs
