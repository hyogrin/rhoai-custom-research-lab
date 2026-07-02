"""Prometheus custom metrics for agentic workload observability.

Follows the AgentOps Workshop pattern: define counters, histograms, and gauges
that OpenShift User Workload Monitoring scrapes via /metrics every 30 seconds.
"""

from prometheus_client import Counter, Histogram, Gauge

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["model", "direction"],
)

llm_inference_duration_seconds = Histogram(
    "llm_inference_duration_seconds",
    "LLM inference latency in seconds",
    ["model", "operation"],
)

tool_calls_total = Counter(
    "tool_calls_total",
    "Total tool/MCP calls",
    ["tool_name", "status"],
)

tool_call_duration_seconds = Histogram(
    "tool_call_duration_seconds",
    "Tool call latency in seconds",
    ["tool_name"],
)

research_sessions_total = Counter(
    "research_sessions_total",
    "Total research sessions started",
    ["status"],
)

research_iterations_total = Counter(
    "research_iterations_total",
    "Total harness iterations executed",
)

research_quality_score = Histogram(
    "research_quality_score",
    "Quality scores from verification",
    buckets=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
)

active_research_sessions = Gauge(
    "active_research_sessions",
    "Number of currently running research sessions",
)

research_failures_total = Counter(
    "research_failures_total",
    "Research failures by category",
    ["category"],
)

documents_processed_total = Counter(
    "documents_processed_total",
    "Documents ingested and processed",
    ["status"],
)
