"""Shared database module — local PostgreSQL for harness state only.

All modules import `get_connection()` from here instead of managing DB connections directly.
This connects to the LOCAL PostgreSQL instance (POSTGRES_URL in .env) for:
  - LangGraph checkpointing
  - Research sessions, trace events, failure log
  - Chat history

Vector storage (pgvector) is handled separately by Llama Stack on the cluster
and is NOT accessed through this module.
"""

import logging
import os

import psycopg
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgresql://research:research@localhost:5432/research_db",
)

_HARNESS_DDL = """
CREATE TABLE IF NOT EXISTS research_sessions (
    session_id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    iteration INTEGER DEFAULT 0,
    status TEXT DEFAULT 'initialized',
    quality_score REAL DEFAULT 0.0,
    state JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON research_sessions(status);

CREATE TABLE IF NOT EXISTS trace_events (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    iteration INTEGER,
    layer TEXT,
    operation TEXT,
    input_summary TEXT,
    output_summary TEXT,
    tokens_used INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    success BOOLEAN DEFAULT TRUE,
    failure_category TEXT,
    metadata JSONB DEFAULT '{}',
    timestamp TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_traces_session ON trace_events(session_id);

CREATE TABLE IF NOT EXISTS failure_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    iteration INTEGER,
    category TEXT,
    description TEXT,
    context TEXT,
    resolution TEXT DEFAULT '',
    timestamp TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_failures_session ON failure_log(session_id);
CREATE INDEX IF NOT EXISTS idx_failures_category ON failure_log(category);
"""


def get_connection() -> psycopg.Connection:
    """Return a PostgreSQL connection with autocommit off and dict-like row factory."""
    conn = psycopg.connect(POSTGRES_URL, row_factory=psycopg.rows.dict_row)
    return conn


def init_db():
    """Ensure harness tables exist in PostgreSQL."""
    conn = get_connection()
    conn.execute(_HARNESS_DDL)
    conn.commit()
    conn.close()
