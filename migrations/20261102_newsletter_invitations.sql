
-- GetOffDeals secure newsletter subscription invitations.
-- Apply locally first. Do not apply to production yet.

BEGIN;

CREATE TABLE IF NOT EXISTS public.newsletter_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL
        REFERENCES public.users(id) ON DELETE CASCADE,

    email TEXT NOT NULL,

    token_hash TEXT NOT NULL UNIQUE,

    expires_at TIMESTAMPTZ NOT NULL,

    used_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- A user should have only one active invitation at a time.
CREATE UNIQUE INDEX IF NOT EXISTS
    idx_newsletter_invitations_one_active_per_user
ON public.newsletter_invitations (user_id)
WHERE used_at IS NULL;

-- Efficient lookup of valid, unused invitations.
CREATE INDEX IF NOT EXISTS
    idx_newsletter_invitations_valid
ON public.newsletter_invitations (token_hash, expires_at)
WHERE used_at IS NULL;

COMMIT;
