"""Observability MCP Server — Trace collection, failure logging, and metrics for the research harness."""

import json
import os
import time
from datetime import datetime

import psycopg2
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

PG_HOST = os.getenv("PGVECTOR_HOST", "localhost")
PG_PORT = os.getenv("PGVECTOR_PORT", "5432")
PG_DB = os.getenv("PGVECTOR_DB", "doc_research")
PG_USER = os.getenv("PGVECTOR_USER", "postgres")
PG_PASSWORD = os.getenv("PGVECTOR_PASSWORD", "postgres")

mcp = FastMCP("observability-mcp", host="0.0.0.0", port=9005, stateless_http=True)


def _get_db():
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD)


def _ensure_tables():
    """Create trace and failure tables if they don't exist."""
    conn = _get_db()
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

        CREATE TABLE IF NOT EXISTS failure_log (
            id SERIAL PRIMARY KEY,
            session_id VARCHAR(20) NOT NULL,
            iteration INTEGER,
            category VARCHAR(100),
            description TEXT,
            context TEXT,
            resolution TEXT DEFAULT '',
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_failures_session ON failure_log(session_id);
        CREATE INDEX IF NOT EXISTS idx_failures_category ON failure_log(category);
    """)
    conn.commit()
    cur.close()
    conn.close()


try:
    _ensure_tables()
except Exception:
    pass


@mcp.tool()
def record_trace(
    session_id: str,
    iteration: int,
    layer: str,
    operation: str,
    input_summary: str = "",
    output_summary: str = "",
    tokens_used: int = 0,
    latency_ms: int = 0,
    success: bool = True,
    failure_category: str = "",
) -> dict:
    """Record a trace event for a research pipeline operation."""
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO trace_events
                (session_id, iteration, layer, operation, input_summary, output_summary,
                 tokens_used, latency_ms, success, failure_category, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            session_id, iteration, layer, operation,
            input_summary[:500], output_summary[:500],
            tokens_used, latency_ms, success,
            failure_category or None,
            datetime.utcnow().isoformat(),
        ))
        trace_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return {"trace_id": trace_id, "status": "recorded"}
    except Exception as e:
        return {"trace_id": 0, "status": "error", "error": str(e)}


@mcp.tool()
def record_failure(
    session_id: str,
    iteration: int,
    category: str,
    description: str,
    context: str = "",
) -> dict:
    """Record a categorized failure event for cross-session learning."""
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO failure_log (session_id, iteration, category, description, context, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (session_id, iteration, category, description, context[:1000], datetime.utcnow().isoformat()))
        failure_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return {"failure_id": failure_id, "status": "recorded"}
    except Exception as e:
        return {"failure_id": 0, "status": "error", "error": str(e)}


@mcp.tool()
def get_metrics(session_id: str) -> dict:
    """Retrieve aggregated metrics for a research session from trace events."""
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) as total_events,
                COALESCE(SUM(tokens_used), 0) as total_tokens,
                COALESCE(SUM(latency_ms), 0) as total_latency_ms,
                COUNT(*) FILTER (WHERE NOT success) as failures,
                COUNT(DISTINCT iteration) as iterations
            FROM trace_events
            WHERE session_id = %s
        """, (session_id,))
        row = cur.fetchone()

        cur.execute("""
            SELECT layer, COUNT(*) as count
            FROM trace_events
            WHERE session_id = %s
            GROUP BY layer
        """, (session_id,))
        by_layer = {r[0]: r[1] for r in cur.fetchall()}

        cur.close()
        conn.close()

        if row:
            return {
                "session_id": session_id,
                "total_events": row[0],
                "total_tokens": row[1],
                "total_latency_ms": row[2],
                "failures": row[3],
                "iterations": row[4],
                "events_by_layer": by_layer,
            }
        return {"session_id": session_id, "total_events": 0}
    except Exception as e:
        return {"session_id": session_id, "error": str(e)}


@mcp.tool()
def get_failure_hints(session_id: str) -> dict:
    """Get improvement hints based on accumulated failures for a session."""
    HINT_MAP = {
        "insufficient_depth": "Previous iteration was too shallow. Search for more specific details and examples.",
        "missing_citations": "Ensure every claim references a source document with [Source N] notation.",
        "low_relevance": "Previous search returned low-relevance results. Try more specific query terms.",
        "hallucination": "Only include information directly supported by retrieved documents.",
        "poor_structure": "Structure the report with clear headings: Summary, Findings, Analysis, Conclusion.",
        "repetitive": "Avoid repeating information. Cover new aspects not addressed previously.",
    }
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT category FROM failure_log WHERE session_id = %s
        """, (session_id,))
        categories = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()

        hints = [HINT_MAP[cat] for cat in categories if cat in HINT_MAP]
        return {"hints": "\n".join(f"- {h}" for h in hints), "categories": categories}
    except Exception as e:
        return {"hints": "", "categories": [], "error": str(e)}


@mcp.tool()
def get_past_failure_patterns(limit: int = 50) -> list[dict]:
    """Load past failure patterns across all sessions for cross-session learning."""
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT category, COUNT(*) as count, array_agg(DISTINCT description) as descriptions
            FROM failure_log
            GROUP BY category
            ORDER BY count DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"category": r[0], "count": r[1], "examples": r[2][:3]} for r in rows]
    except Exception:
        return []


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
