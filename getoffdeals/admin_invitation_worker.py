"""Process administrator-triggered newsletter invitation emails."""

import base64
import hashlib
import hmac
import logging
import os
import sqlite3

from datetime import datetime, timedelta, timezone

from getoffdeals.email_service import send_newsletter_invitation
from getoffdeals.newsletter_invitation_service import (
    create_or_reuse_invitation,
    hash_token,
)
from getoffdeals.newsletter_service import _execute

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
BATCH_SIZE = 20
PROCESSING_LEASE_MINUTES = 15
IDEMPOTENCY_WINDOW_HOURS = 23


def _now():
    return datetime.now(timezone.utc)


def _timestamp(value):
    return value.isoformat()


def _is_sqlite(conn):
    return isinstance(conn, sqlite3.Connection)


def _table(conn):
    return (
        "admin_newsletter_invitation_outbox"
        if _is_sqlite(conn)
        else "public.admin_newsletter_invitation_outbox"
    )


def _invitation_token(job):
    """Generate a stable token unique to this invitation job."""
    secret = os.getenv("FLASK_SECRET_KEY", "")

    if not secret:
        raise RuntimeError(
            "FLASK_SECRET_KEY is required for invitation generation."
        )

    message = (
        "getoffdeals-admin-newsletter-invitation:"
        f"{job['id']}:{job['user_id']}"
    ).encode("utf-8")

    digest = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()

    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _idempotency_key(job):
    return f"getoffdeals-admin-newsletter-invitation-{job['id']}"


def _claim_job(conn):
    """Claim a due job and recover abandoned processing jobs."""
    table = _table(conn)
    now = _now()
    now_text = _timestamp(now)

    stale_before = _timestamp(
        now - timedelta(minutes=PROCESSING_LEASE_MINUTES)
    )
    retry_deadline = _timestamp(
        now - timedelta(hours=IDEMPOTENCY_WINDOW_HOURS)
    )

    # Recover abandoned jobs. Do not retry beyond the provider's
    # idempotency retention window.
    _execute(
        conn,
        f"""
        UPDATE {table}
        SET status = CASE
                WHEN first_attempt_at <= %s THEN 'failed'
                ELSE 'pending'
            END,
            last_error = CASE
                WHEN first_attempt_at <= %s
                    THEN 'Delivery outcome uncertain; idempotency window expired.'
                ELSE last_error
            END,
            updated_at = %s
        WHERE status = 'processing'
          AND updated_at < %s
        """,
        (
            retry_deadline,
            retry_deadline,
            now_text,
            stale_before,
        ),
    )

    # Also close pending jobs that have passed the safe retry window.
    _execute(
        conn,
        f"""
        UPDATE {table}
        SET status = 'failed',
            last_error = %s,
            updated_at = %s
        WHERE status = 'pending'
          AND first_attempt_at <= %s
        """,
        (
            "Delivery outcome uncertain; idempotency window expired.",
            now_text,
            retry_deadline,
        ),
    )

    suffix = "" if _is_sqlite(conn) else " FOR UPDATE SKIP LOCKED"

    job = _execute(
        conn,
        f"""
        SELECT
            id,
            user_id,
            email,
            attempts,
            first_attempt_at
        FROM {table}
        WHERE status = 'pending'
          AND attempts < %s
          AND next_attempt_at <= %s
          AND (
              first_attempt_at IS NULL
              OR first_attempt_at > %s
          )
        ORDER BY created_at
        LIMIT 1{suffix}
        """,
        (MAX_ATTEMPTS, now_text, retry_deadline),
    ).fetchone()

    if not job:
        conn.commit()
        return None

    cursor = _execute(
        conn,
        f"""
        UPDATE {table}
        SET status = 'processing',
            first_attempt_at = COALESCE(first_attempt_at, %s),
            updated_at = %s
        WHERE id = %s
          AND status = 'pending'
        """,
        (now_text, now_text, job["id"]),
    )

    if cursor.rowcount != 1:
        conn.commit()
        return None

    conn.commit()
    return dict(job)


def _prepare_invitation(db_connect, job):
    """Create or reuse this job's invitation without replacing another."""
    public_base_url = os.getenv(
        "PUBLIC_BASE_URL", ""
    ).strip().rstrip("/")

    if not public_base_url.startswith("https://"):
        raise RuntimeError(
            "PUBLIC_BASE_URL must be configured with HTTPS."
        )

    token = _invitation_token(job)
    token_hash = hash_token(token)

    with db_connect() as conn:
        suffix = "" if _is_sqlite(conn) else " FOR UPDATE"

        # Serialize admin invitations for this user.
        user = _execute(
            conn,
            f"""
            SELECT id, email
            FROM {"users" if _is_sqlite(conn) else "public.users"}
            WHERE id = %s
            {suffix}
            """,
            (job["user_id"],),
        ).fetchone()

        if not user:
            return None

        # Never send an invitation to an outdated email address.
        queued_email = str(job.get("email") or "").strip()
        current_email = str(user["email"] or "").strip()

        if (
            not queued_email
            or not current_email
            or queued_email.casefold() != current_email.casefold()
        ):
            logger.warning(
                "Admin invitation skipped because account email changed: "
                "job_id=%s",
                job["id"],
            )
            return None

        # Recheck subscription eligibility immediately before sending.
        subscriber = _execute(
            conn,
            f"""
            SELECT 1
            FROM {"subscribers" if _is_sqlite(conn) else "public.subscribers"}
            WHERE LOWER(email) = LOWER(%s)
            LIMIT 1
            """,
            (user["email"],),
        ).fetchone()

        if subscriber:
            return None

        invitations_table = (
            "newsletter_invitations"
            if _is_sqlite(conn)
            else "public.newsletter_invitations"
        )

        existing = _execute(
            conn,
            f"""
            SELECT token_hash
            FROM {invitations_table}
            WHERE user_id = %s
              AND used_at IS NULL
              AND expires_at > %s
            LIMIT 1
            """,
            (job["user_id"], _timestamp(_now())),
        ).fetchone()

        if existing and existing["token_hash"] != token_hash:
            # Preserve a valid invitation created by the welcome flow
            # or another invitation job.
            return None

        invitation = create_or_reuse_invitation(
            conn,
            user_id=str(job["user_id"]),
            email=user["email"],
            token=token,
        )

    return (
        f"{public_base_url}/newsletter/join/"
        f"{invitation['token']}"
    )


def _finish_job(conn, job_id, message_id):
    table = _table(conn)
    now = _timestamp(_now())

    _execute(
        conn,
        f"""
        UPDATE {table}
        SET status = 'sent',
            resend_message_id = %s,
            sent_at = %s,
            last_error = NULL,
            updated_at = %s
        WHERE id = %s
          AND status = 'processing'
        """,
        (message_id, now, now, job_id),
    )

    conn.commit()


def _skip_job(conn, job_id, reason):
    table = _table(conn)
    now = _timestamp(_now())

    _execute(
        conn,
        f"""
        UPDATE {table}
        SET status = 'skipped',
            last_error = %s,
            updated_at = %s
        WHERE id = %s
          AND status = 'processing'
        """,
        (reason, now, job_id),
    )

    conn.commit()


def _retry_job(conn, job, exc):
    """Retry safely within the provider's idempotency window."""
    table = _table(conn)
    attempts = job["attempts"] + 1
    now = _now()

    first_attempt = job.get("first_attempt_at")

    if isinstance(first_attempt, str):
        first_attempt = datetime.fromisoformat(first_attempt)

    if first_attempt and first_attempt.tzinfo is None:
        first_attempt = first_attempt.replace(tzinfo=timezone.utc)

    deadline_passed = (
        first_attempt is not None
        and now >= first_attempt + timedelta(
            hours=IDEMPOTENCY_WINDOW_HOURS
        )
    )

    exhausted = attempts >= MAX_ATTEMPTS or deadline_passed

    next_attempt = _timestamp(
        now + timedelta(minutes=min(2 ** (attempts - 1), 360))
    )

    status = "failed" if exhausted else "pending"

    error = type(exc).__name__

    if deadline_passed:
        error = "Delivery outcome uncertain; idempotency window expired."
    elif exhausted:
        error = f"Retry limit reached: {error}"

    _execute(
        conn,
        f"""
        UPDATE {table}
        SET attempts = %s,
            status = %s,
            next_attempt_at = %s,
            last_error = %s,
            updated_at = %s
        WHERE id = %s
          AND status = 'processing'
        """,
        (
            attempts,
            status,
            next_attempt,
            error,
            _timestamp(now),
            job["id"],
        ),
    )

    conn.commit()

    if exhausted:
        logger.error(
            "Admin invitation job failed: job_id=%s attempts=%s",
            job["id"],
            attempts,
        )
    else:
        logger.warning(
            "Admin invitation job scheduled for retry: "
            "job_id=%s attempt=%s",
            job["id"],
            attempts,
        )


def process_one(db_connect):
    """Process one administrator invitation delivery job."""
    with db_connect() as conn:
        job = _claim_job(conn)

    if not job:
        return False

    try:
        invitation_url = _prepare_invitation(db_connect, job)

        if not invitation_url:
            with db_connect() as conn:
                _skip_job(
                    conn,
                    job["id"],
                    "User is subscribed, unavailable, or already has an active invitation.",
                )
            return True

        result = send_newsletter_invitation(
            to_email=job["email"],
            invitation_url=invitation_url,
            idempotency_key=_idempotency_key(job),
        )

        message_id = (
            result.get("id")
            if isinstance(result, dict)
            else getattr(result, "id", None)
        )

        if not isinstance(message_id, str) or not message_id.strip():
            raise RuntimeError(
                "Resend did not return a valid message ID."
            )

        with db_connect() as conn:
            _finish_job(conn, job["id"], message_id.strip())

    except Exception as exc:
        logger.exception(
            "Admin newsletter invitation delivery failed: job_id=%s",
            job["id"],
        )

        with db_connect() as conn:
            _retry_job(conn, job, exc)

    return True


def run_batch(db_connect, limit=BATCH_SIZE):
    """Process up to limit invitation jobs."""
    processed = 0

    for _ in range(limit):
        if not process_one(db_connect):
            break
        processed += 1

    return processed


def main():
    from getoffdeals.database import get_connection

    count = run_batch(get_connection)

    logger.info(
        "Admin invitation worker processed %s jobs",
        count,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
