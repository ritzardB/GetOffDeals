
"""Process durable Resend contact synchronization jobs."""

import logging
import sqlite3
import uuid

from datetime import datetime, timedelta, timezone

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
    """Claim one due job and assign a unique processing lease."""
    table = _table(conn)
    now = _now()
    now_text = _timestamp(now)
    stale_before = _timestamp(
        now - timedelta(minutes=PROCESSING_LEASE_MINUTES)
    )
    lease_token = str(uuid.uuid4())

    # Recover jobs whose processing lease has expired.
    _execute(
        conn,
        f"""
        UPDATE {table}
        SET status = 'pending',
            lease_token = NULL,
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
        SET status = 'processing',
            lease_token = %s,
            updated_at = %s
        WHERE id = %s
          AND status = 'pending'
        """,
        (lease_token, now_text, job["id"]),
    )

    if cursor.rowcount != 1:
        conn.commit()
        return None

    conn.commit()

    claimed_job = dict(job)
    claimed_job["lease_token"] = lease_token

    return claimed_job


def _owns_job(conn, job):
    """Return whether this worker still owns the processing lease."""
    table = _table(conn)

    row = _execute(
        conn,
        f"""
        SELECT 1
        FROM {table}
        WHERE id = %s
          AND status = 'processing'
          AND lease_token = %s
        """,
        (job["id"], job["lease_token"]),
    ).fetchone()

    return row is not None


def _finish_job(conn, job):
    """Complete a job only if the supplied lease is still current."""
    table = _table(conn)
    now = _timestamp(_now())

    cursor = _execute(
        conn,
        f"""
        UPDATE {table}
        SET status = 'done',
            lease_token = NULL,
            last_error = NULL,
            updated_at = %s
        WHERE id = %s
          AND status = 'processing'
          AND lease_token = %s
        """,
        (now, job["id"], job["lease_token"]),
    )

    conn.commit()
    return cursor.rowcount == 1


def _retry_job(conn, job, exc):
    """Schedule a retry only if this worker still owns the lease."""
    table = _table(conn)
    attempts = job["attempts"] + 1
    now = _now()

    exhausted = attempts >= MAX_ATTEMPTS

    next_attempt = _timestamp(
        now + timedelta(minutes=min(2 ** (attempts - 1), 360))
    )

    # Store only the exception class, never email or provider response data.
    error = type(exc).__name__
    status = "failed" if exhausted else "pending"

    cursor = _execute(
        conn,
        f"""
        UPDATE {table}
        SET attempts = %s,
            status = %s,
            next_attempt_at = %s,
            last_error = %s,
            lease_token = NULL,
            updated_at = %s
        WHERE id = %s
          AND status = 'processing'
          AND lease_token = %s
        """,
        (
            attempts,
            status,
            next_attempt,
            error,
            _timestamp(now),
            job["id"],
            job["lease_token"],
        ),
    )

    conn.commit()

    # A newer worker may already own this job.
    if cursor.rowcount != 1:
        logger.info(
            "Resend sync retry ignored because lease was lost: job_id=%s",
            job["id"],
        )
        return False

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

    return True


def _current_subscriber_status(conn, email, *, for_update=False):
    """Read subscriber status, optionally locking the PostgreSQL row."""
    is_sqlite = _is_sqlite(conn)

    sql = (
        """
        SELECT status FROM subscribers
        WHERE LOWER(email) = LOWER(%s)
        """
        if is_sqlite
        else
        """
        SELECT status FROM public.subscribers
        WHERE LOWER(email) = LOWER(%s)
        """
    )

    if for_update and not is_sqlite:
        sql += " FOR UPDATE"

    row = _execute(conn, sql, (email,)).fetchone()
    return row["status"] if row else None


def process_one(db_connect):
    """Process one due job while protecting consent and lease ownership."""
    with db_connect() as conn:
        job = _claim_job(conn)

    if not job:
        return False

    try:
        # Hold the subscriber row lock while checking consent and
        # performing the corresponding Resend operation.
        with db_connect() as conn:
            current_status = _current_subscriber_status(
                conn,
                job["email"],
                for_update=True,
            )

            should_sync = False

            if job["action"] == "add":
                should_sync = current_status == "confirmed"

            elif job["action"] == "unsubscribe":
                should_sync = current_status == "unsubscribed"

            else:
                raise ValueError("Unsupported outbox action")

            if should_sync:
                # Check lease ownership immediately before the external call.
                # Use a separate connection so the subscriber transaction
                # remains open and its row lock is retained.
                with db_connect() as lease_conn:
                    still_owner = _owns_job(lease_conn, job)

                if not still_owner:
                    logger.info(
                        "Resend sync skipped because lease was lost: job_id=%s",
                        job["id"],
                    )
                    return True

                if job["action"] == "add":
                    result = add_confirmed_contact(job["email"])

                    if result == "suppressed":
                        logger.info(
                            "Resend contact remains suppressed: job_id=%s",
                            job["id"],
                        )

                elif job["action"] == "unsubscribe":
                    unsubscribe_contact(job["email"])

    except Exception as exc:
        with db_connect() as conn:
            _retry_job(conn, job, exc)

        return True

    # Completion is guarded by the original lease token.
    with db_connect() as conn:
        completed = _finish_job(conn, job)

    if not completed:
        logger.info(
            "Resend sync completion ignored because lease was lost: job_id=%s",
            job["id"],
        )

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
    from getoffdeals.database import get_connection

    count = run_batch(get_connection)
    logger.info("Resend sync worker processed %s jobs", count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
