"""PostgreSQL schema for GetOffDeals email invitations.

Run explicitly with:
    python -m getoffdeals.invitation_schema

This module is not executed automatically when the Flask app starts.
"""

from getoffdeals.database import get_connection


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS public.invitation_contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    email_normalized TEXT NOT NULL UNIQUE,
    consent_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (consent_status IN ('pending', 'consented', 'revoked')),
    consented_at TIMESTAMPTZ,
    consent_source TEXT,
    consent_evidence TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT invitation_consent_evidence_required CHECK (
        consent_status <> 'consented'
        OR (
            consented_at IS NOT NULL
            AND consent_source IS NOT NULL
            AND LENGTH(TRIM(consent_source)) > 0
            AND consent_evidence IS NOT NULL
            AND LENGTH(TRIM(consent_evidence)) > 0
        )
    )
);

CREATE TABLE IF NOT EXISTS public.invitation_campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN (
            'draft', 'sending', 'completed', 'completed_with_errors',
            'failed', 'cancelled'
        )),
    created_by_user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.invitation_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL
        REFERENCES public.invitation_campaigns(id) ON DELETE RESTRICT,
    contact_id UUID NOT NULL
        REFERENCES public.invitation_contacts(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'sending', 'sent', 'failed', 'suppressed'
        )),
    provider_message_id TEXT,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campaign_id, contact_id)
);

CREATE TABLE IF NOT EXISTS public.invitation_unsubscribe_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID NOT NULL
        REFERENCES public.invitation_contacts(id) ON DELETE RESTRICT,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_invitation_unsubscribe_tokens_contact
    ON public.invitation_unsubscribe_tokens (contact_id);

CREATE TABLE IF NOT EXISTS public.invitation_unsubscribes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID NOT NULL UNIQUE
        REFERENCES public.invitation_contacts(id) ON DELETE RESTRICT,
    reason TEXT,
    unsubscribed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE INDEX IF NOT EXISTS idx_invitation_campaigns_created_at
    ON public.invitation_campaigns (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_invitation_messages_campaign_status
    ON public.invitation_messages (campaign_id, status);

CREATE INDEX IF NOT EXISTS idx_invitation_messages_contact
    ON public.invitation_messages (contact_id);
"""


def ensure_invitation_schema():
    """Create invitation tables and indexes if they do not exist."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)


def main():
    ensure_invitation_schema()
    print("GetOffDeals invitation schema initialized successfully.")


if __name__ == "__main__":
    main()
