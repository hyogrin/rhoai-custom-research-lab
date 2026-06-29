-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Document chunks table for RAG
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(255) NOT NULL,
    document_name VARCHAR(500) NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding vector(768),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for vector similarity search
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Index for document lookups
CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON document_chunks (document_id);

-- Documents metadata table
CREATE TABLE IF NOT EXISTS documents (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    file_type VARCHAR(50),
    file_size BIGINT,
    chunk_count INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'pending',
    object_store_path VARCHAR(1000),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================================================
-- Harness Tables (Research Sessions, Traces, Failures)
-- =============================================================================

-- Research sessions (long transaction state)
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

-- Trace events (observability)
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

-- Failure log (cross-session learning)
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
