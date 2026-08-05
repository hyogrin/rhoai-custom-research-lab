-- =============================================================================
-- PostgreSQL + pgvector schema for the RHOAI Custom Deep Research Lab
-- =============================================================================
-- Run this ONCE on a fresh database:
--   psql $POSTGRES_URL -f scripts/init-postgres.sql
--
-- LangGraph checkpointer tables are auto-created by AsyncPostgresSaver.setup()
-- and are NOT included here (they are managed by the langgraph library).
-- =============================================================================

-- Enable pgvector extension (requires superuser or CREATE privilege)
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- Document Storage
-- =============================================================================

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    file_type TEXT,
    file_size INTEGER,
    chunk_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    object_store_path TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_name TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- =============================================================================
-- Harness Tables (Research Sessions, Traces, Failures)
-- =============================================================================

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

-- =============================================================================
-- Chat History (replaces Chainlit SQLite data layer)
-- =============================================================================

CREATE TABLE IF NOT EXISTS chat_threads (
    id TEXT PRIMARY KEY,
    title TEXT,
    user_id TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_threads_user ON chat_threads(user_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL,  -- 'user' | 'assistant' | 'system'
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON chat_messages(thread_id);
