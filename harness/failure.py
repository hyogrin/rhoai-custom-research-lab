"""Failure taxonomy and learning for the research harness."""

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import get_connection


class FailureCategory(str, Enum):
    """Taxonomy of research failure types."""

    # Content quality failures
    INSUFFICIENT_DEPTH = "insufficient_depth"
    MISSING_CITATIONS = "missing_citations"
    HALLUCINATION = "hallucination"
    OFF_TOPIC = "off_topic"
    REPETITIVE = "repetitive"
    POOR_STRUCTURE = "poor_structure"

    # Retrieval failures
    LOW_RELEVANCE = "low_relevance"
    NO_RESULTS = "no_results"
    WRONG_CONTEXT = "wrong_context"

    # System failures
    TIMEOUT = "timeout"
    AGENT_ERROR = "agent_error"
    MCP_ERROR = "mcp_error"
    LLM_ERROR = "llm_error"
    TOKEN_LIMIT = "token_limit"

    # Verification failures
    QUALITY_BELOW_THRESHOLD = "quality_below_threshold"
    CITATION_INVALID = "citation_invalid"
    FACT_CHECK_FAILED = "fact_check_failed"


@dataclass
class FailureEntry:
    """A recorded failure with context for learning."""

    session_id: str
    iteration: int
    category: FailureCategory
    description: str
    context: str = ""
    resolution: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class FailureLog:
    """Manages failure records and provides learning from past failures."""

    def __init__(self):
        self._entries: list[FailureEntry] = []

    def record(
        self,
        session_id: str,
        iteration: int,
        category: FailureCategory,
        description: str,
        context: str = "",
    ) -> FailureEntry:
        """Record a failure event."""
        entry = FailureEntry(
            session_id=session_id,
            iteration=iteration,
            category=category,
            description=description,
            context=context[:1000],
        )
        self._entries.append(entry)
        return entry

    def get_failures(self, session_id: str) -> list[FailureEntry]:
        return [e for e in self._entries if e.session_id == session_id]

    def get_failure_categories(self, session_id: str) -> list[str]:
        """Get unique failure categories for a session — used by planner to avoid repeats."""
        return list(set(e.category.value for e in self.get_failures(session_id)))

    def get_improvement_hints(self, session_id: str) -> str:
        """Generate improvement hints based on accumulated failures."""
        failures = self.get_failures(session_id)
        if not failures:
            return ""

        hints = []
        categories = self.get_failure_categories(session_id)

        if FailureCategory.INSUFFICIENT_DEPTH.value in categories:
            hints.append("Previous iteration was too shallow. Search for more specific details and examples.")
        if FailureCategory.MISSING_CITATIONS.value in categories:
            hints.append("Ensure every claim references a source document with [Source N] notation.")
        if FailureCategory.LOW_RELEVANCE.value in categories:
            hints.append("Previous search returned low-relevance results. Try more specific query terms.")
        if FailureCategory.HALLUCINATION.value in categories:
            hints.append("Only include information directly supported by retrieved documents.")
        if FailureCategory.POOR_STRUCTURE.value in categories:
            hints.append("Structure the report with clear headings: Summary, Findings, Analysis, Conclusion.")
        if FailureCategory.REPETITIVE.value in categories:
            hints.append("Avoid repeating information. Cover new aspects not addressed previously.")

        return "\n".join(f"- {h}" for h in hints)

    def persist(self, session_id: str):
        """Save failures to SQLite for cross-session learning."""
        entries = self.get_failures(session_id)
        if not entries:
            return

        conn = get_connection()

        for entry in entries:
            conn.execute(
                """INSERT INTO failure_log (session_id, iteration, category, description, context, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (entry.session_id, entry.iteration, entry.category.value,
                 entry.description, entry.context, entry.timestamp),
            )

        conn.commit()
        conn.close()

    def load_past_failures(self, limit: int = 50) -> list[dict]:
        """Load past failure patterns for cross-session learning."""
        try:
            conn = get_connection()
            rows = conn.execute(
                """SELECT category, COUNT(*) as count,
                          GROUP_CONCAT(DISTINCT description) as descriptions
                FROM failure_log
                GROUP BY category
                ORDER BY count DESC
                LIMIT ?""",
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
