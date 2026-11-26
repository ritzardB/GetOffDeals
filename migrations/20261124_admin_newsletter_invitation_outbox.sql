-- Durable queue for administrator-triggered newsletter invitations.
-- This migration has already been applied to production Supabase.
-- Do not rerun manually against an existing production database.

BEGIN;

CREATE TABLE IF NOT EXISTS public.admin_newsletter_invitation_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL
        REFERENCES public.users(id) ON DELETE CASCADE,

    email TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            status IN (
                'pending',
                'processing',
                'sent',
                'failed',
                'skipped'
            )
        ),

    attempts INTEGER NOT NULL DEFAULT 0
        CHECK (attempts >= 0),

    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    resend_message_id TEXT,
    last_error TEXT,

    first_attempt_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ
);

-- Only one pending or processing admin invitation per user.
CREATE UNIQUE INDEX IF NOT EXISTS
    idx_admin_newsletter_invitation_one_active
ON public.admin_newsletter_invitation_outbox (user_id)
WHERE status IN ('pending', 'processing');

-- Efficient retrieval of due jobs.
CREATE INDEX IF NOT EXISTS
    idx_admin_newsletter_invitation_pending
ON public.admin_newsletter_invitation_outbox (
    status,
    next_attempt_at,
    created_at
)
WHERE status IN ('pending', 'processing');

ALTER TABLE public.admin_newsletter_invitation_outbox
    ENABLE ROW LEVEL SECURITY;

COMMIT;
