
"""Process durable Resend contact synchronization jobs."""

import logging
from datetime import datetime, timedelta, timezone

import sqlite3

from getoffdeals.newsletter_service import _execute
from getoffdeals.resend_contacts import (
    ResendContactsError,
    add_confirmed_contact,
    unsubscribe_contact,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
BATCH_SIZE = 20
PROCESSING_LEASE_MINUTES = 15


def _is_sqlite(conn):
    return isinstance(conn, sqlite3.Connection)


def _table(conn):
    return (
        "resend_sync_outbox"
        if _is_sqlite(conn)
        else "public.resend_sync_outbox"
    )


def _now():
    return datetime.now(timezone.utc)


def _timestamp(value):
    return value.isoformat()


def _claim_job(conn):
    """Claim one due job, reclaiming stale worker leases."""
    table = _table(conn)
    now = _now()
    now_text = _timestamp(now)
    stale_before = _timestamp(
        now - timedelta(minutes=PROCESSING_LEASE_MINUTES)
    )

    # Recover jobs left processing after a worker crash.
    _execute(
        conn,
        f"""
        UPDATE {table}
        SET status = 'pending', updated_at = %s
        WHERE status = 'processing'
          AND updated_at < %s
        """,
        (now_text, stale_before),
    )

    suffix = "" if _is_sqlite(conn) else " FOR UPDATE SKIP LOCKED"
    job = _execute(
        conn,
        f"""
        SELECT id, email, action, attempts
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
        SET status = 'processing', updated_at = %s
        WHERE id = %s AND status = 'pending'
        """,
        (now_text, job["id"]),
    )

    if cursor.rowcount != 1:
        conn.commit()
        return None

    conn.commit()
    return dict(job)


def _finish_job(conn, job_id):
    table = _table(conn)
    now = _timestamp(_now())

    _execute(
        conn,
        f"""
        UPDATE {table}
        SET status = 'done',
            last_error = NULL,
            updated_at = %s
        WHERE id = %s
        """,
        (now, job_id),
    )
    conn.commit()


def _retry_job(conn, job, exc):
    table = _table(conn)
    attempts = job["attempts"] + 1
    now = _now()

    # Mark the job permanently failed after MAX_ATTEMPTS.
    exhausted = attempts >= MAX_ATTEMPTS
    next_attempt = _timestamp(
        now + timedelta(minutes=min(2 ** (attempts - 1), 360))
    )

    # Never persist email addresses or provider response bodies.
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
            "Resend sync job exhausted retries: job_id=%s attempts=%s",
            job["id"],
            attempts,
        )
    else:
        logger.warning(
            "Resend sync job scheduled for retry: job_id=%s attempt=%s",
            job["id"],
            attempts,
        )

def _current_subscriber_status(conn, email):
    sql = (
        """
        SELECT status FROM subscribers
        WHERE LOWER(email) = LOWER(%s)
        """
        if _is_sqlite(conn)
        else
        """
        SELECT status FROM public.subscribers
        WHERE LOWER(email) = LOWER(%s)
        """
    )

    row = _execute(conn, sql, (email,)).fetchone()
    return row["status"] if row else None


def process_one(db_connect):
    """Process one due job. Pass newsletter_db_connect as db_connect."""
    with db_connect() as conn:
        job = _claim_job(conn)

    if not job:
        return False

    try:
        # Recheck consent immediately before calling Resend.
        with db_connect() as conn:
            current_status = _current_subscriber_status(
                conn, job["email"]
            )

        if job["action"] == "add":
            if current_status != "confirmed":
                # Do not add pending or unsubscribed subscribers.
                with db_connect() as conn:
                    _finish_job(conn, job["id"])
                return True

            result = add_confirmed_contact(job["email"])

            if result == "suppressed":
                # Resend already has an unsubscribe suppression.
                logger.info(
                    "Resend contact remains suppressed: job_id=%s",
                    job["id"],
                )

        elif job["action"] == "unsubscribe":
            if current_status != "unsubscribed":
                # Do not apply a stale unsubscribe to a currently
                # confirmed subscriber.
                with db_connect() as conn:
                    _finish_job(conn, job["id"])
                return True

            unsubscribe_contact(job["email"])

        else:
            raise ValueError("Unsupported outbox action")

    except ResendContactsError as exc:
        with db_connect() as conn:
            _retry_job(conn, job, exc)
        return True

    with db_connect() as conn:
        _finish_job(conn, job["id"])

    return True


def run_batch(db_connect, limit=BATCH_SIZE):
    """Process up to limit jobs; return the number processed."""
    processed = 0

    for _ in range(limit):
        if not process_one(db_connect):
            break
        processed += 1

    return processed


def main():
    # Import here to avoid a module-level app/worker import cycle.
    from app import newsletter_db_connect

    count = run_batch(newsletter_db_connect)
    logger.info("Resend sync worker processed %s jobs", count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
