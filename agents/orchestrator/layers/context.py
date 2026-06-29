"""Context Layer — Gathers context from agent configs, past failures, and accumulated research."""

import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def gather_context(state: dict) -> dict:
    """Gather context for the current iteration.

    Combines:
    - Past failure hints (from previous iterations or sessions)
    - Accumulated context from prior iterations
    - Agent configuration context
    """
    context_parts = []

    # Include failure hints so the planner avoids past mistakes
    if state.get("failure_hints"):
        context_parts.append(f"## Past Issues to Avoid\n{state['failure_hints']}")

    # Summarize accumulated context from previous iterations
    accumulated = state.get("accumulated_context", [])
    if accumulated:
        recent = accumulated[-10:]  # Last 10 context items
        context_summary = "\n".join(
            f"- [{c.get('source', 'unknown')}] {c.get('content', '')[:200]}"
            for c in recent
        )
        context_parts.append(f"## Previously Gathered Context\n{context_summary}")

    # If there's a previous draft, summarize what's been written
    if state.get("current_draft"):
        draft_preview = state["current_draft"][:500]
        context_parts.append(f"## Current Draft Preview\n{draft_preview}...")

    # Iteration context
    context_parts.append(
        f"## Session Info\n"
        f"- Iteration: {state.get('iteration', 0)}/{state.get('max_iterations', 5)}\n"
        f"- Quality score: {state.get('quality_score', 0.0)}/{state.get('quality_threshold', 7.0)}\n"
        f"- Status: {state.get('status', 'unknown')}"
    )

    return {
        "context_summary": "\n\n".join(context_parts),
        "iteration": state.get("iteration", 0),
        "has_prior_context": len(accumulated) > 0,
    }


def load_past_failure_memory() -> str:
    """Load failure patterns from past sessions (if available)."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("PGVECTOR_HOST", "localhost"),
            port=os.getenv("PGVECTOR_PORT", "5432"),
            dbname=os.getenv("PGVECTOR_DB", "doc_research"),
            user=os.getenv("PGVECTOR_USER", "postgres"),
            password=os.getenv("PGVECTOR_PASSWORD", "postgres"),
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT category, COUNT(*) as cnt
            FROM failure_log
            WHERE timestamp > NOW() - INTERVAL '7 days'
            GROUP BY category
            ORDER BY cnt DESC
            LIMIT 5
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if rows:
            hints = [f"- {r[0]} (occurred {r[1]} times recently)" for r in rows]
            return "Common failure patterns to watch for:\n" + "\n".join(hints)
    except Exception:
        pass
    return ""
