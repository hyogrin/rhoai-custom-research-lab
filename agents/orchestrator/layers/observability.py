"""Observability Layer — Trace collection, metrics recording, and failure taxonomy for the harness."""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from harness.trace import TraceEvent, TraceCollector
from harness.failure import FailureCategory, FailureLog
from harness.metrics import MetricsAggregator

logger = logging.getLogger(__name__)


class HarnessObserver:
    """Unified observability for the harness controller.

    Combines trace collection, metrics aggregation, and failure logging
    into a single interface used by all layer nodes.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.traces = TraceCollector()
        self.failures = FailureLog()
        self.metrics = MetricsAggregator(session_id=session_id)

    def start_iteration(self, iteration: int):
        """Begin a new iteration for metrics tracking."""
        self.metrics.start_iteration(iteration)

    def end_iteration(self, quality_score: float, passed: bool):
        """Finalize the current iteration."""
        self.metrics.end_iteration(quality_score, passed)

    def trace_tool_call(
        self,
        iteration: int,
        operation: str,
        input_summary: str,
        output_summary: str,
        tokens_used: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        success: bool = True,
        failure_category: str | None = None,
    ) -> TraceEvent:
        """Record a tool layer operation."""
        event = TraceEvent(
            session_id=self.session_id,
            iteration=iteration,
            layer="tool",
            operation=operation,
            input_summary=input_summary,
            output_summary=output_summary,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            success=success,
            failure_category=failure_category,
        )
        self.traces.record(event)
        if tokens_used:
            in_tok = input_tokens or tokens_used // 2
            out_tok = output_tokens or tokens_used - in_tok
            self.metrics.record_llm_call(in_tok, out_tok)
        self._increment_prometheus_metrics(operation, tokens_used, latency_ms, success)
        return event

    def trace_verification(
        self,
        iteration: int,
        operation: str,
        input_summary: str,
        output_summary: str,
        tokens_used: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        success: bool = True,
    ) -> TraceEvent:
        """Record a verification layer operation."""
        event = TraceEvent(
            session_id=self.session_id,
            iteration=iteration,
            layer="verification",
            operation=operation,
            input_summary=input_summary,
            output_summary=output_summary,
            tokens_used=tokens_used,
            success=success,
        )
        self.traces.record(event)
        if tokens_used:
            in_tok = input_tokens or tokens_used // 2
            out_tok = output_tokens or tokens_used - in_tok
            self.metrics.record_llm_call(in_tok, out_tok)
        self._increment_prometheus_metrics(operation, tokens_used, 0, success)
        return event

    def trace_context(self, iteration: int, operation: str, summary: str) -> TraceEvent:
        """Record a context layer operation."""
        event = TraceEvent(
            session_id=self.session_id,
            iteration=iteration,
            layer="context",
            operation=operation,
            input_summary="",
            output_summary=summary[:500],
        )
        self.traces.record(event)
        return event

    def record_failure(self, iteration: int, category: FailureCategory, description: str, context: str = ""):
        """Log a failure for learning."""
        self.failures.record(self.session_id, iteration, category, description, context)

    def get_improvement_hints(self) -> str:
        """Get hints based on accumulated failures."""
        return self.failures.get_improvement_hints(self.session_id)

    def get_summary(self) -> dict:
        """Get full observability summary including cost estimate."""
        metrics_summary = self.metrics.summary()
        return {
            "metrics": metrics_summary,
            "traces": self.traces.get_summary(self.session_id),
            "failures": self.failures.get_failure_categories(self.session_id),
            "total_cost": metrics_summary.get("total_cost", 0.0),
        }

    def persist(self):
        """Persist all observability data to PostgreSQL."""
        try:
            self.traces.persist(self.session_id)
            self.failures.persist(self.session_id)
        except Exception:
            logger.debug("Observability persistence failed", exc_info=True)

    def _increment_prometheus_metrics(
        self, operation: str, tokens_used: int, latency_ms: int, success: bool
    ):
        """Increment Prometheus metrics (no-op if prometheus_client unavailable)."""
        try:
            from backend.metrics import (
                llm_tokens_total,
                llm_inference_duration_seconds,
                tool_calls_total,
                tool_call_duration_seconds,
                research_iterations_total,
            )

            model = os.getenv("LLM_MODEL", "unknown")

            if tokens_used:
                llm_tokens_total.labels(model=model, direction="total").inc(tokens_used)
                llm_inference_duration_seconds.labels(
                    model=model, operation=operation
                ).observe(latency_ms / 1000 if latency_ms else 0)

            status = "success" if success else "error"
            tool_calls_total.labels(tool_name=operation, status=status).inc()
            if latency_ms:
                tool_call_duration_seconds.labels(tool_name=operation).observe(
                    latency_ms / 1000
                )
        except ImportError:
            pass
