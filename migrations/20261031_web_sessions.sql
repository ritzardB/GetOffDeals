-- GetOffDeals PostgreSQL-backed Flask sessions
-- Local development migration
-- Creates the server-side session storage table.

BEGIN;

CREATE TABLE IF NOT EXISTS public.web_sessions (
    session_id VARCHAR(128) PRIMARY KEY,
    session_data BYTEA NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS
    idx_web_sessions_expires_at
    ON public.web_sessions (expires_at);

COMMIT;
