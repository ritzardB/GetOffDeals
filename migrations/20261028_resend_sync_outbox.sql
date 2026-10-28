CREATE TABLE IF NOT EXISTS public.resend_sync_outbox (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    action TEXT NOT NULL
        CHECK (action IN ('add', 'unsubscribe')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            status IN ('pending', 'processing', 'done')
        ),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resend_sync_outbox_pending
    ON public.resend_sync_outbox (status, next_attempt_at);