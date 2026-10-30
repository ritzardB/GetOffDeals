
"""Database operations for GetOffDeals invitation campaigns."""

import logging
from uuid import UUID

from getoffdeals.database import get_connection
from getoffdeals.invitations import normalize_email, validate_email

logger = logging.getLogger(__name__)


def record_consented_contact(
    email,
    consent_source,
    consent_evidence,
    consented_at,
):
    """Insert or update a contact only when explicit consent is documented.

    Existing revoked contacts remain revoked. Re-consent must be handled
    through a separate, auditable workflow.
    """
    normalized = normalize_email(email)

    if not validate_email(normalized):
        raise ValueError("Enter a valid email address.")

    if not isinstance(consent_source, str) or not consent_source.strip():
        raise ValueError("A consent source is required.")

    if not isinstance(consent_evidence, str) or not consent_evidence.strip():
        raise ValueError("Consent evidence is required.")

    if consented_at is None:
        raise ValueError("A consent timestamp is required.")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.invitation_contacts (
                    email,
                    email_normalized,
                    consent_status,
                    consented_at,
                    consent_source,
                    consent_evidence
                )
                VALUES (%s, %s, 'consented', %s, %s, %s)
                ON CONFLICT (email_normalized) DO UPDATE
                SET
                    email = EXCLUDED.email,
                    updated_at = NOW()
                WHERE public.invitation_contacts.consent_status <> 'revoked'
                RETURNING id, email_normalized, consent_status
                """,
                (
                    email.strip(),
                    normalized,
                    consented_at,
                    consent_source.strip(),
                    consent_evidence.strip(),
                ),
            )
            return cur.fetchone()


def create_campaign(name, created_by_user_id):
    """Create a draft campaign for a valid authenticated admin UUID."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Campaign name is required.")

    try:
        user_id = str(UUID(str(created_by_user_id)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A valid administrator user ID is required.") from None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.invitation_campaigns (
                    name, created_by_user_id
                )
                VALUES (%s, %s)
                RETURNING id, name, status, created_at
                """,
                (name.strip(), user_id),
            )
            return cur.fetchone()


def list_eligible_contacts(contact_ids=None):
    """Return only explicitly consented, non-unsubscribed contacts.

    If contact_ids is supplied, only those contact UUIDs are considered.
    This function does not send email.
    """
    params = []
    id_filter = ""

    if contact_ids is not None:
        normalized_ids = []
        for raw_id in contact_ids:
            try:
                normalized_ids.append(str(UUID(str(raw_id))))
            except (ValueError, TypeError, AttributeError):
                continue

        if not normalized_ids:
            return []

        id_filter = "AND c.id = ANY(%s::uuid[])"
        params.append(normalized_ids)

    query = f"""
        SELECT c.id, c.email, c.email_normalized
        FROM public.invitation_contacts AS c
        WHERE c.consent_status = 'consented'
          AND c.consented_at IS NOT NULL
          AND NULLIF(TRIM(c.consent_source), '') IS NOT NULL
          AND NULLIF(TRIM(c.consent_evidence), '') IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM public.invitation_unsubscribes AS u
              WHERE u.contact_id = c.id
          )
          {id_filter}
        ORDER BY c.created_at, c.id
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def create_unsubscribe_token(contact_id, token_hash, expires_at=None):
    """Persist a hash for a generated unsubscribe token.

    The raw token must never be passed to this function or stored.
    """
    try:
        contact_uuid = str(UUID(str(contact_id)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid contact ID.") from None

    if not isinstance(token_hash, str) or len(token_hash) != 64:
        raise ValueError("Invalid unsubscribe token hash.")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.invitation_unsubscribe_tokens (
                    contact_id, token_hash, expires_at
                )
                VALUES (%s, %s, %s)
                RETURNING id, contact_id, created_at, expires_at
                """,
                (contact_uuid, token_hash, expires_at),
            )
            return cur.fetchone()


def add_campaign_recipients(campaign_id, contact_ids):
    """Add eligible contacts to a draft campaign without sending email."""
    try:
        campaign_uuid = str(UUID(str(campaign_id)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid campaign ID.") from None

    eligible = list_eligible_contacts(contact_ids)
    eligible_ids = [str(contact["id"]) for contact in eligible]

    if not eligible_ids:
        return 0

    inserted = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status
                FROM public.invitation_campaigns
                WHERE id = %s
                FOR UPDATE
                """,
                (campaign_uuid,),
            )
            campaign = cur.fetchone()

            if campaign is None:
                raise ValueError("Campaign not found.")

            if campaign["status"] != "draft":
                raise ValueError("Recipients can only be added to a draft campaign.")

            for contact_id in eligible_ids:
                cur.execute(
                    """
                    INSERT INTO public.invitation_messages (
                        campaign_id, contact_id
                    )
                    VALUES (%s, %s)
                    ON CONFLICT (campaign_id, contact_id) DO NOTHING
                    RETURNING id
                    """,
                    (campaign_uuid, contact_id),
                )
                if cur.fetchone():
                    inserted += 1

    return inserted


def get_campaign_summary(campaign_id):
    """Return campaign metadata and counts by message status."""
    try:
        campaign_uuid = str(UUID(str(campaign_id)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid campaign ID.") from None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, status, created_at, started_at, completed_at
                FROM public.invitation_campaigns
                WHERE id = %s
                """,
                (campaign_uuid,),
            )
            campaign = cur.fetchone()

            if campaign is None:
                return None

            cur.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM public.invitation_messages
                WHERE campaign_id = %s
                GROUP BY status
                """,
                (campaign_uuid,),
            )
            counts = {
                row["status"]: row["count"]
                for row in cur.fetchall()
            }

    return {"campaign": campaign, "message_counts": counts}


def start_campaign(campaign_id):
    """Move a draft campaign to sending, exactly once."""
    try:
        campaign_uuid = str(UUID(str(campaign_id)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid campaign ID.") from None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.invitation_campaigns
                SET status = 'sending',
                    started_at = COALESCE(started_at, NOW())
                WHERE id = %s AND status = 'draft'
                RETURNING id, status, started_at
                """,
                (campaign_uuid,),
            )
            return cur.fetchone()


def claim_next_campaign_message(campaign_id):
    """Atomically claim one pending message for a sending campaign.

    The claim is committed when the database connection context exits.
    No email is sent by this function.
    """
    try:
        campaign_uuid = str(UUID(str(campaign_id)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid campaign ID.") from None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM public.invitation_messages
                WHERE campaign_id = %s
                  AND status = 'pending'
                ORDER BY created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (campaign_uuid,),
            )
            message = cur.fetchone()

            if message is None:
                return None

            cur.execute(
                """
                UPDATE public.invitation_messages
                SET status = 'sending',
                    updated_at = NOW()
                WHERE id = %s
                  AND status = 'pending'
                RETURNING id, campaign_id, contact_id
                """,
                (message["id"],),
            )
            return cur.fetchone()


def mark_message_suppressed(message_id):
    """Mark a claimed message as suppressed without sending it."""
    try:
        message_uuid = str(UUID(str(message_id)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid message ID.") from None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.invitation_messages
                SET status = 'suppressed',
                    updated_at = NOW()
                WHERE id = %s AND status = 'sending'
                RETURNING id, status
                """,
                (message_uuid,),
            )
            return cur.fetchone()


def finish_campaign_if_complete(campaign_id):
    """Complete a campaign only when no messages remain unresolved."""
    try:
        campaign_uuid = str(UUID(str(campaign_id)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid campaign ID.") from None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('pending', 'sending'))
                        AS unresolved,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed
                FROM public.invitation_messages
                WHERE campaign_id = %s
                """,
                (campaign_uuid,),
            )
            counts = cur.fetchone()

            if counts["unresolved"] > 0:
                return None

            status = (
                "completed_with_errors"
                if counts["failed"] > 0
                else "completed"
            )

            cur.execute(
                """
                UPDATE public.invitation_campaigns
                SET status = %s,
                    completed_at = NOW()
                WHERE id = %s AND status = 'sending'
                RETURNING id, status, completed_at
                """,
                (status, campaign_uuid),
            )
            return cur.fetchone()


def unsubscribe_contact(token):
    """Validate an unsubscribe token and record the opt-out atomically.

    The raw token is never stored. A valid token can be used only once.
    """
    import hashlib

    if not isinstance(token, str) or not token or len(token) > 200:
        return False

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock the token and contact while checking and recording the opt-out.
            cur.execute(
                """
                SELECT t.id AS token_id, t.contact_id
                FROM public.invitation_unsubscribe_tokens AS t
                JOIN public.invitation_contacts AS c
                  ON c.id = t.contact_id
                WHERE t.token_hash = %s
                  AND t.used_at IS NULL
                  AND t.revoked_at IS NULL
                  AND (t.expires_at IS NULL OR t.expires_at > NOW())
                FOR UPDATE OF t, c
                """,
                (token_hash,),
            )
            row = cur.fetchone()

            if row is None:
                return False

            cur.execute(
                """
                INSERT INTO public.invitation_unsubscribes (contact_id)
                VALUES (%s)
                ON CONFLICT (contact_id) DO NOTHING
                """,
                (row["contact_id"],),
            )

            cur.execute(
                """
                UPDATE public.invitation_contacts
                SET consent_status = 'revoked',
                    updated_at = NOW()
                WHERE id = %s
                """,
                (row["contact_id"],),
            )

            cur.execute(
                """
                UPDATE public.invitation_unsubscribe_tokens
                SET used_at = NOW()
                WHERE id = %s
                """,
                (row["token_id"],),
            )

            # Invalidate any other outstanding tokens for this contact.
            cur.execute(
                """
                UPDATE public.invitation_unsubscribe_tokens
                SET revoked_at = NOW()
                WHERE contact_id = %s
                  AND id <> %s
                  AND used_at IS NULL
                  AND revoked_at IS NULL
                """,
                (row["contact_id"], row["token_id"]),
            )

    return True
