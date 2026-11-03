-- GetOffDeals transactional welcome email queue.
-- Apply locally first; do not apply to production yet.

BEGIN;

CREATE TABLE IF NOT EXISTS public.welcome_email_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL UNIQUE
        REFERENCES public.users(id) ON DELETE CASCADE,

    email TEXT NOT NULL,
    first_name TEXT NOT NULL DEFAULT '',

    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            status IN ('pending', 'processing', 'sent', 'failed')
        ),

    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    resend_message_id TEXT,
    last_error TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_welcome_email_outbox_pending
    ON public.welcome_email_outbox (status, next_attempt_at)
    WHERE status IN ('pending', 'processing');

ALTER TABLE public.welcome_email_outbox
    ENABLE ROW LEVEL SECURITY;

COMMIT;