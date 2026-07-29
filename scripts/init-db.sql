-- =============================================================================
-- SQLite + sqlite-vec schema for the RHOAI Custom Deep Research Lab
-- =============================================================================

-- Documents metadata table
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    file_type TEXT,
    file_size INTEGER,
    chunk_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    object_store_path TEXT,
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Document chunks table (metadata only — embeddings live in vec_chunks)
CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    document_name TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks (document_id);

-- vec0 virtual table for vector similarity search
-- Linked to document_chunks via chunk_id = document_chunks.id
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding float[768]
);

-- =============================================================================
-- Harness Tables (Research Sessions, Traces, Failures)
-- =============================================================================

-- Research sessions (long transaction state)
CREATE TABLE IF NOT EXISTS research_sessions (
    session_id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    iteration INTEGER DEFAULT 0,
    status TEXT DEFAULT 'initialized',
    quality_score REAL DEFAULT 0.0,
    state TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON research_sessions(status);

-- Trace events (observability)
CREATE TABLE IF NOT EXISTS trace_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    iteration INTEGER,
    layer TEXT,
    operation TEXT,
    input_summary TEXT,
    output_summary TEXT,
    tokens_used INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    success INTEGER DEFAULT 1,
    failure_category TEXT,
    metadata TEXT DEFAULT '{}',
    timestamp TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_traces_session ON trace_events(session_id);

-- Failure log (cross-session learning)
CREATE TABLE IF NOT EXISTS failure_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    iteration INTEGER,
    category TEXT,
    description TEXT,
    context TEXT,
    resolution TEXT DEFAULT '',
    timestamp TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_failures_session ON failure_log(session_id);
CREATE INDEX IF NOT EXISTS idx_failures_category ON failure_log(category);
