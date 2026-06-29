"""Research session state management with PostgreSQL persistence.

Falls back to in-memory storage when PostgreSQL is unavailable,
allowing local development without running dev-up containers.
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras

    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False


@dataclass
class ResearchSession:
    """Long-transaction state for an iterative deep research session."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    query: str = ""
    iteration: int = 0
    max_iterations: int = 5
    quality_threshold: float = 7.0

    # Evolving state — grows across iterations
    research_plan: list[dict] = field(default_factory=list)
    accumulated_context: list[dict] = field(default_factory=list)
    current_draft: str = ""

    # Verification results per iteration
    verification_history: list[dict] = field(default_factory=list)

    # Observability
    traces: list[dict] = field(default_factory=list)
    total_tokens: int = 0
    total_cost: float = 0.0
    failure_log: list[dict] = field(default_factory=list)

    # Sectioned report (used when SECTIONED_REPORT=true)
    report_sections: list[dict] = field(default_factory=list)
    section_order: list[str] = field(default_factory=list)
    failing_sections: list[str] = field(default_factory=list)

    # Control
    status: str = "initialized"  # initialized|planning|researching|writing|verifying|complete|failed
    quality_score: float = 0.0

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def should_iterate(self) -> bool:
        """Determine if another iteration is needed."""
        if self.status in ("complete", "failed"):
            return False
        if self.iteration >= self.max_iterations:
            return False
        if self.quality_score >= self.quality_threshold:
            return False
        return True

    def advance_iteration(self):
        """Move to next iteration."""
        self.iteration += 1
        self.updated_at = datetime.utcnow().isoformat()

    def mark_complete(self):
        self.status = "complete"
        self.updated_at = datetime.utcnow().isoformat()

    def mark_failed(self, reason: str):
        self.status = "failed"
        self.failure_log.append({
            "iteration": self.iteration,
            "category": "session_failure",
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.updated_at = datetime.utcnow().isoformat()

    def add_context(self, source: str, content: str, metadata: dict | None = None):
        """Accumulate context from research iterations."""
        self.accumulated_context.append({
            "iteration": self.iteration,
            "source": source,
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow().isoformat(),
        })

    def add_verification(self, result: dict):
        """Record a verification result."""
        self.verification_history.append({
            "iteration": self.iteration,
            **result,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def to_dict(self) -> dict:
        return asdict(self)

    def get_progress(self) -> dict:
        """Return structured progress for frontend status display."""
        return {
            "session_id": self.session_id,
            "query": self.query,
            "status": self.status,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "quality_score": self.quality_score,
            "quality_threshold": self.quality_threshold,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "verification_history": self.verification_history,
            "has_draft": bool(self.current_draft),
            "draft_length": len(self.current_draft),
            "context_count": len(self.accumulated_context),
            "failure_count": len(self.failure_log),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchSession":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SessionManager:
    """Persist and retrieve research sessions.

    Uses PostgreSQL when available, falls back to in-memory dict otherwise.
    """

    def __init__(self, connection_string: str | None = None):
        self._conn_str = connection_string or self._build_conn_str()
        self._use_db = False
        self._memory: dict[str, ResearchSession] = {}
        self._try_connect()

    @staticmethod
    def _build_conn_str() -> str:
        return (
            f"host={os.getenv('PGVECTOR_HOST', 'localhost')} "
            f"port={os.getenv('PGVECTOR_PORT', '5432')} "
            f"dbname={os.getenv('PGVECTOR_DB', 'doc_research')} "
            f"user={os.getenv('PGVECTOR_USER', 'postgres')} "
            f"password={os.getenv('PGVECTOR_PASSWORD', 'postgres')}"
        )

    def _try_connect(self):
        """Probe PostgreSQL; fall back to in-memory if unavailable."""
        if not _HAS_PSYCOPG2:
            logger.info("psycopg2 not installed — using in-memory session storage")
            return
        try:
            conn = psycopg2.connect(self._conn_str, connect_timeout=3)
            conn.close()
            self._use_db = True
            logger.info("Connected to PostgreSQL for session storage")
        except Exception as e:
            logger.warning("PostgreSQL unavailable (%s) — using in-memory session storage", e)

    def _get_conn(self):
        return psycopg2.connect(self._conn_str)

    def ensure_table(self):
        """Create the sessions table if it doesn't exist."""
        if not self._use_db:
            return
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS research_sessions (
                session_id VARCHAR(20) PRIMARY KEY,
                query TEXT NOT NULL,
                iteration INTEGER DEFAULT 0,
                status VARCHAR(50) DEFAULT 'initialized',
                quality_score REAL DEFAULT 0.0,
                state JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_status ON research_sessions(status);
        """)
        conn.commit()
        cur.close()
        conn.close()

    def save(self, session: ResearchSession):
        """Upsert a research session."""
        if not self._use_db:
            self._memory[session.session_id] = session
            return
        conn = self._get_conn()
        cur = conn.cursor()
        state_json = json.dumps(session.to_dict())
        cur.execute("""
            INSERT INTO research_sessions (session_id, query, iteration, status, quality_score, state, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW())
            ON CONFLICT (session_id) DO UPDATE SET
                iteration = EXCLUDED.iteration,
                status = EXCLUDED.status,
                quality_score = EXCLUDED.quality_score,
                state = EXCLUDED.state,
                updated_at = NOW()
        """, (session.session_id, session.query, session.iteration,
              session.status, session.quality_score, state_json))
        conn.commit()
        cur.close()
        conn.close()

    def load(self, session_id: str) -> ResearchSession | None:
        """Load a session by ID."""
        if not self._use_db:
            return self._memory.get(session_id)
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT state FROM research_sessions WHERE session_id = %s", (session_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return ResearchSession.from_dict(row[0])
        return None

    def get_progress(self, session_id: str) -> dict | None:
        """Get progress summary for a session without loading full state."""
        if not self._use_db:
            session = self._memory.get(session_id)
            return session.get_progress() if session else None
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT session_id, query, iteration, status, quality_score, state, created_at, updated_at "
            "FROM research_sessions WHERE session_id = %s",
            (session_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        session = ResearchSession.from_dict(row[5])
        return session.get_progress()

    def list_sessions(self, status: str | None = None, limit: int = 20) -> list[dict]:
        """List recent sessions."""
        if not self._use_db:
            sessions = list(self._memory.values())
            if status:
                sessions = [s for s in sessions if s.status == status]
            sessions.sort(key=lambda s: s.updated_at, reverse=True)
            return [
                {"session_id": s.session_id, "query": s.query, "iteration": s.iteration,
                 "status": s.status, "quality_score": s.quality_score, "created_at": s.created_at}
                for s in sessions[:limit]
            ]
        conn = self._get_conn()
        cur = conn.cursor()
        if status:
            cur.execute(
                "SELECT session_id, query, iteration, status, quality_score, created_at "
                "FROM research_sessions WHERE status = %s ORDER BY updated_at DESC LIMIT %s",
                (status, limit),
            )
        else:
            cur.execute(
                "SELECT session_id, query, iteration, status, quality_score, created_at "
                "FROM research_sessions ORDER BY updated_at DESC LIMIT %s",
                (limit,),
            )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"session_id": r[0], "query": r[1], "iteration": r[2],
             "status": r[3], "quality_score": r[4], "created_at": str(r[5])}
            for r in rows
        ]
