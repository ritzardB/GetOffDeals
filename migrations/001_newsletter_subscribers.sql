
-- GetOffDeals newsletter subscribers
-- PostgreSQL migration 001
-- Creates a separate newsletter table; leaves existing tables untouched.

BEGIN;

CREATE TABLE IF NOT EXISTS public.subscribers (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email TEXT NOT NULL,
    consent BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'confirmed', 'unsubscribed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consent_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,
    confirmation_token_hash TEXT,
    confirmation_expires_at TIMESTAMPTZ,
    unsubscribe_token_hash TEXT,
    unsubscribed_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS
    idx_subscribers_email_lower
    ON public.subscribers (LOWER(email));

CREATE UNIQUE INDEX IF NOT EXISTS
    idx_subscribers_confirmation_token
    ON public.subscribers (confirmation_token_hash)
    WHERE confirmation_token_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS
    idx_subscribers_unsubscribe_token
    ON public.subscribers (unsubscribe_token_hash)
    WHERE unsubscribe_token_hash IS NOT NULL;

COMMIT;
