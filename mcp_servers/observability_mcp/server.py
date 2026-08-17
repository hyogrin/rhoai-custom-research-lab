"""Observability MCP Server — Trace collection, failure logging, and metrics for the research harness."""

import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(override=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from db import get_connection, init_db

mcp = FastMCP("observability-mcp", host="0.0.0.0", port=9005, stateless_http=True)

try:
    init_db()
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
        conn = get_connection()
        cur = conn.execute(
            """INSERT INTO trace_events
                (session_id, iteration, layer, operation, input_summary, output_summary,
                 tokens_used, latency_ms, success, failure_category, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id""",
            (
                session_id, iteration, layer, operation,
                input_summary[:500], output_summary[:500],
                tokens_used, latency_ms, success,
                failure_category or None,
                datetime.utcnow().isoformat(),
            ),
        )
        row = cur.fetchone()
        trace_id = row["id"] if row else 0
        conn.commit()
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
        conn = get_connection()
        cur = conn.execute(
            """INSERT INTO failure_log (session_id, iteration, category, description, context, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id""",
            (session_id, iteration, category, description, context[:1000],
             datetime.utcnow().isoformat()),
        )
        row = cur.fetchone()
        failure_id = row["id"] if row else 0
        conn.commit()
        conn.close()
        return {"failure_id": failure_id, "status": "recorded"}
    except Exception as e:
        return {"failure_id": 0, "status": "error", "error": str(e)}


@mcp.tool()
def get_metrics(session_id: str) -> dict:
    """Retrieve aggregated metrics for a research session from trace events."""
    try:
        conn = get_connection()
        row = conn.execute(
            """SELECT
                COUNT(*) as total_events,
                COALESCE(SUM(tokens_used), 0) as total_tokens,
                COALESCE(SUM(latency_ms), 0) as total_latency_ms,
                SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failures,
                COUNT(DISTINCT iteration) as iterations
            FROM trace_events
            WHERE session_id = %s""",
            (session_id,),
        ).fetchone()

        by_layer = {
            r["layer"]: r["count"]
            for r in conn.execute(
                """SELECT layer, COUNT(*) as count
                FROM trace_events
                WHERE session_id = %s
                GROUP BY layer""",
                (session_id,),
            ).fetchall()
        }

        conn.close()

        if row:
            return {
                "session_id": session_id,
                "total_events": row["total_events"],
                "total_tokens": row["total_tokens"],
                "total_latency_ms": row["total_latency_ms"],
                "failures": row["failures"],
                "iterations": row["iterations"],
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
        conn = get_connection()
        rows = conn.execute(
            "SELECT DISTINCT category FROM failure_log WHERE session_id = %s",
            (session_id,),
        ).fetchall()
        conn.close()

        categories = [r["category"] for r in rows]
        hints = [HINT_MAP[cat] for cat in categories if cat in HINT_MAP]
        return {"hints": "\n".join(f"- {h}" for h in hints), "categories": categories}
    except Exception as e:
        return {"hints": "", "categories": [], "error": str(e)}


@mcp.tool()
def get_past_failure_patterns(limit: int = 50) -> list[dict]:
    """Load past failure patterns across all sessions for cross-session learning."""
    try:
        conn = get_connection()
        rows = conn.execute(
            """SELECT category, COUNT(*) as count,
                      STRING_AGG(DISTINCT description, ',') as descriptions
            FROM failure_log
            GROUP BY category
            ORDER BY count DESC
            LIMIT %s""",
            (limit,),
        ).fetchall()
        conn.close()
        return [
            {
                "category": r["category"],
                "count": r["count"],
                "examples": r["descriptions"].split(",")[:3] if r["descriptions"] else [],
            }
            for r in rows
        ]
    except Exception:
        return []


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
