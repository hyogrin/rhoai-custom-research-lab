"""Trace event recording for the research harness."""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

import psycopg2
from dotenv import load_dotenv

load_dotenv()


@dataclass
class TraceEvent:
    """A single observable event in the research pipeline."""

    session_id: str
    iteration: int
    layer: str  # context | tool | execution | verification | observability
    operation: str  # e.g. "semantic_search", "llm_call", "quality_check"
    input_summary: str = ""
    output_summary: str = ""
    tokens_used: int = 0
    latency_ms: int = 0
    success: bool = True
    failure_category: str | None = None
    metadata: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class TraceCollector:
    """Collects and persists trace events for a research session."""

    def __init__(self):
        self._events: list[TraceEvent] = []
        self._start_times: dict[str, float] = {}

    def start_span(self, span_id: str):
        """Start timing a span."""
        self._start_times[span_id] = time.time()

    def end_span(
        self,
        span_id: str,
        session_id: str,
        iteration: int,
        layer: str,
        operation: str,
        input_summary: str = "",
        output_summary: str = "",
        tokens_used: int = 0,
        success: bool = True,
        failure_category: str | None = None,
        metadata: dict | None = None,
    ) -> TraceEvent:
        """End a span and record the trace event."""
        start = self._start_times.pop(span_id, time.time())
        latency_ms = int((time.time() - start) * 1000)

        event = TraceEvent(
            session_id=session_id,
            iteration=iteration,
            layer=layer,
            operation=operation,
            input_summary=input_summary[:500],
            output_summary=output_summary[:500],
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            success=success,
            failure_category=failure_category,
            metadata=metadata or {},
        )
        self._events.append(event)
        return event

    def record(self, event: TraceEvent):
        """Directly record a trace event."""
        self._events.append(event)

    def get_events(self, session_id: str | None = None) -> list[TraceEvent]:
        """Get collected events, optionally filtered by session."""
        if session_id:
            return [e for e in self._events if e.session_id == session_id]
        return list(self._events)

    def get_summary(self, session_id: str) -> dict:
        """Summarize traces for a session."""
        events = self.get_events(session_id)
        if not events:
            return {"total_events": 0}

        total_tokens = sum(e.tokens_used for e in events)
        total_latency = sum(e.latency_ms for e in events)
        failures = [e for e in events if not e.success]
        by_layer = {}
        for e in events:
            by_layer.setdefault(e.layer, []).append(e)

        return {
            "total_events": len(events),
            "total_tokens": total_tokens,
            "total_latency_ms": total_latency,
            "failures": len(failures),
            "failure_categories": list(set(e.failure_category for e in failures if e.failure_category)),
            "events_by_layer": {k: len(v) for k, v in by_layer.items()},
        }

    def persist(self, session_id: str):
        """Save trace events to PostgreSQL."""
        events = self.get_events(session_id)
        if not events:
            return

        conn = psycopg2.connect(
            host=os.getenv("PGVECTOR_HOST", "localhost"),
            port=os.getenv("PGVECTOR_PORT", "5432"),
            dbname=os.getenv("PGVECTOR_DB", "doc_research"),
            user=os.getenv("PGVECTOR_USER", "postgres"),
            password=os.getenv("PGVECTOR_PASSWORD", "postgres"),
        )
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS trace_events (
                id SERIAL PRIMARY KEY,
                session_id VARCHAR(20) NOT NULL,
                iteration INTEGER,
                layer VARCHAR(50),
                operation VARCHAR(100),
                input_summary TEXT,
                output_summary TEXT,
                tokens_used INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                success BOOLEAN DEFAULT TRUE,
                failure_category VARCHAR(100),
                metadata JSONB DEFAULT '{}',
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_traces_session ON trace_events(session_id);
        """)

        for event in events:
            cur.execute("""
                INSERT INTO trace_events
                    (session_id, iteration, layer, operation, input_summary, output_summary,
                     tokens_used, latency_ms, success, failure_category, metadata, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            """, (
                event.session_id, event.iteration, event.layer, event.operation,
                event.input_summary, event.output_summary, event.tokens_used,
                event.latency_ms, event.success, event.failure_category,
                json.dumps(event.metadata), event.timestamp,
            ))

        conn.commit()
        cur.close()
        conn.close()
