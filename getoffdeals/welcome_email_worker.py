
"""Process durable GetOffDeals welcome email jobs."""

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from getoffdeals.email_service import send_welcome_email
from getoffdeals.newsletter_invitation_service import (
    create_or_reuse_invitation,
)
import base64
import hashlib
import hmac
from getoffdeals.newsletter_service import _execute

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
BATCH_SIZE = 20
PROCESSING_LEASE_MINUTES = 15


def _invitation_token(job):
    """Generate a stable, secret-derived token for one welcome job."""
    secret = os.getenv("FLASK_SECRET_KEY", "")

    if not secret:
        raise RuntimeError(
            "FLASK_SECRET_KEY is required for invitation generation."
        )

    message = (
        f"getoffdeals-newsletter-invitation:"
        f"{job['id']}:{job['user_id']}"
    ).encode("utf-8")

    digest = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()

    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _is_sqlite(conn):
    return isinstance(conn, sqlite3.Connection)


def _table(conn):
    return (
        "welcome_email_outbox"
        if _is_sqlite(conn)
        else "public.welcome_email_outbox"
    )


def _now():
    return datetime.now(timezone.utc)


def _timestamp(value):
    return value.isoformat()


def _claim_job(conn):
    """Claim one due welcome email job, recovering stale leases."""
    table = _table(conn)
    now = _now()
    now_text = _timestamp(now)

    stale_before = _timestamp(
        now - timedelta(minutes=PROCESSING_LEASE_MINUTES)
    )

    _execute(
        conn,
        f"""
        UPDATE {table}
        SET status = 'pending',
            updated_at = %s
        WHERE status = 'processing'
          AND updated_at < %s
        """,
        (now_text, stale_before),
    )

    suffix = "" if _is_sqlite(conn) else " FOR UPDATE SKIP LOCKED"

    job = _execute(
        conn,
        f"""
        SELECT id, user_id, email, first_name, attempts
        FROM {table}
        WHERE status = 'pending'
          AND attempts < %s
          AND next_attempt_at <= %s
        ORDER BY created_at
        LIMIT 1{suffix}
        """,
        (MAX_ATTEMPTS, now_text),
    ).fetchone()

    if not job:
        conn.commit()
        return None

    cursor = _execute(
        conn,
        f"""
        UPDATE {table}
        SET status = 'processing',
            updated_at = %s
        WHERE id = %s
          AND status = 'pending'
        """,
        (now_text, job["id"]),
    )

    if cursor.rowcount != 1:
        conn.commit()
        return None

    conn.commit()
    return dict(job)



def _create_subscription_invitation(db_connect, job):
    """Create or reuse a stable newsletter invitation."""
    public_base_url = os.getenv(
        "PUBLIC_BASE_URL", ""
    ).strip().rstrip("/")

    if not public_base_url.startswith("https://"):
        raise RuntimeError(
            "PUBLIC_BASE_URL must be configured with HTTPS."
        )

    token = _invitation_token(job)

    with db_connect() as conn:
        invitation = create_or_reuse_invitation(
            conn,
            user_id=str(job["user_id"]),
            email=job["email"],
            token=token,
        )

    return (
        f"{public_base_url}/newsletter/join/"
        f"{invitation['token']}"
    )


def _finish_job(conn, job_id, message_id):
    """Mark a welcome email as successfully sent."""
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
        """,
        (message_id, now, now, job_id),
    )

    conn.commit()


def _retry_job(conn, job, exc):
    """Schedule a failed email for retry or mark it permanently failed."""
    table = _table(conn)
    attempts = job["attempts"] + 1
    now = _now()

    exhausted = attempts >= MAX_ATTEMPTS

    next_attempt = _timestamp(
        now + timedelta(minutes=min(2 ** (attempts - 1), 360))
    )

    error = type(exc).__name__
    status = "failed" if exhausted else "pending"

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
            "Welcome email job exhausted retries: "
            "job_id=%s attempts=%s",
            job["id"],
            attempts,
        )
    else:
        logger.warning(
            "Welcome email job scheduled for retry: "
            "job_id=%s attempt=%s",
            job["id"],
            attempts,
        )


def process_one(db_connect):
    """Process one due welcome email job."""
    with db_connect() as conn:
        job = _claim_job(conn)

    if not job:
        return False

    try:
        subscribe_url = _create_subscription_invitation(
            db_connect,
            job,
        )

        result = send_welcome_email(
            to_email=job["email"],
            first_name=job["first_name"],
            subscribe_url=subscribe_url,
        )

        message_id = (
            result.get("id")
            if isinstance(result, dict)
            else None
        )

        with db_connect() as conn:
            _finish_job(conn, job["id"], message_id)

    except Exception as exc:
        logger.exception(
            "Welcome email delivery failed: job_id=%s",
            job["id"],
        )

        with db_connect() as conn:
            _retry_job(conn, job, exc)

    return True


def run_batch(db_connect, limit=BATCH_SIZE):
    """Process up to limit welcome email jobs."""
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
        "Welcome email worker processed %s jobs",
        count,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
