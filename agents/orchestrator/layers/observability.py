"""Observability Layer — Trace collection, metrics recording, and failure taxonomy for the harness."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from harness.trace import TraceEvent, TraceCollector
from harness.failure import FailureCategory, FailureLog
from harness.metrics import MetricsAggregator


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
            self.metrics.record_llm_call(tokens_used // 2, tokens_used // 2)
        return event

    def trace_verification(
        self,
        iteration: int,
        operation: str,
        input_summary: str,
        output_summary: str,
        tokens_used: int = 0,
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
            self.metrics.record_llm_call(tokens_used // 2, tokens_used // 2)
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
        """Get full observability summary."""
        return {
            "metrics": self.metrics.summary(),
            "traces": self.traces.get_summary(self.session_id),
            "failures": self.failures.get_failure_categories(self.session_id),
        }

    def persist(self):
        """Persist all observability data to PostgreSQL."""
        try:
            self.traces.persist(self.session_id)
            self.failures.persist(self.session_id)
        except Exception:
            pass  # Don't let persistence failures crash the pipeline
