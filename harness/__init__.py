"""Harness — Shared utilities for the iterative deep research framework."""

from harness.session import ResearchSession, SessionManager
from harness.trace import TraceEvent, TraceCollector
from harness.failure import FailureCategory, FailureLog
from harness.metrics import MetricsAggregator

__all__ = [
    "ResearchSession",
    "SessionManager",
    "TraceEvent",
    "TraceCollector",
    "FailureCategory",
    "FailureLog",
    "MetricsAggregator",
]
