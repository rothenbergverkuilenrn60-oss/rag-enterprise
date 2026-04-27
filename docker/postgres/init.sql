-- pgvector extension + RLS setup for EnterpriseRAG
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- RLS: app sets this per-connection before any query
-- SET app.current_tenant = 'tenant_id';
