
"""Database-compatible newsletter subscription helpers."""

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone


CONFIRMATION_TTL_HOURS = 24


def generate_token():
    """Return a random token and its SHA-256 hash."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token):
    """Hash a token before database lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def confirmation_expiry():
    """Return an ISO-8601 UTC expiry timestamp."""
    return (
        datetime.now(timezone.utc)
        + timedelta(hours=CONFIRMATION_TTL_HOURS)
    ).isoformat()


def token_is_expired(expires_at):
    """Check whether a timestamp is expired."""
    try:
        if isinstance(expires_at, str):
            expiry = datetime.fromisoformat(expires_at)
        elif isinstance(expires_at, datetime):
            expiry = expires_at
        else:
            return True

        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        return datetime.now(timezone.utc) >= expiry
    except (TypeError, ValueError):
        return True


def utc_now():
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _execute(conn, sql, params=()):
    """Execute SQL with placeholders compatible with SQLite and psycopg."""
    if isinstance(conn, sqlite3.Connection):
        sql = sql.replace("%s", "?")
    return conn.execute(sql, params)


def prepare_subscription(conn, email):
    """Create or refresh a pending subscription after consent."""
    row = _execute(
        conn,
        """
        SELECT * FROM public.subscribers
        WHERE LOWER(email) = LOWER(%s)
        """ if not isinstance(conn, sqlite3.Connection) else """
        SELECT * FROM subscribers
        WHERE LOWER(email) = LOWER(%s)
        """,
        (email,),
    ).fetchone()

    if row and row["status"] == "confirmed":
        return {"status": "already_confirmed"}

    if row and row["status"] == "unsubscribed":
        return {"status": "already_unsubscribed"}

    confirmation_token, confirmation_hash = generate_token()
    unsubscribe_token, unsubscribe_hash = generate_token()
    now = utc_now()
    expires = confirmation_expiry()

    if row:
        _execute(
            conn,
            """
            UPDATE subscribers
            SET consent = TRUE,
                consent_at = %s,
                status = 'pending',
                confirmed_at = NULL,
                confirmation_token_hash = %s,
                confirmation_expires_at = %s,
                unsubscribe_token_hash = %s,
                unsubscribed_at = NULL
            WHERE id = %s
            """,
            (now, confirmation_hash, expires, unsubscribe_hash, row["id"]),
        )
    else:
        _execute(
            conn,
            """
            INSERT INTO subscribers (
                email, consent, status, consent_at,
                confirmation_token_hash, confirmation_expires_at,
                unsubscribe_token_hash
            )
            VALUES (%s, TRUE, 'pending', %s, %s, %s, %s)
            """,
            (email, now, confirmation_hash, expires, unsubscribe_hash),
        )

    return {
        "status": "pending",
        "confirmation_token": confirmation_token,
        "unsubscribe_token": unsubscribe_token,
    }


def get_confirmation_email(conn, token):
    """Return the email associated with a confirmation token."""
    token_hash = hash_token(token)
    row = _execute(
        conn,
        """
        SELECT email
        FROM subscribers
        WHERE confirmation_token_hash = %s
        """,
        (token_hash,),
    ).fetchone()
    return row["email"] if row else None


def get_unsubscribe_email(conn, token):
    """Return the email associated with an unsubscribe token."""
    token_hash = hash_token(token)
    row = _execute(
        conn,
        """
        SELECT email
        FROM subscribers
        WHERE unsubscribe_token_hash = %s
        """,
        (token_hash,),
    ).fetchone()
    return row["email"] if row else None


def confirm_subscription(conn, token):
    """Confirm a subscription using a valid, unexpired token."""
    row = _execute(
        conn,
        """
        SELECT id, email, status, confirmation_expires_at
        FROM subscribers
        WHERE confirmation_token_hash = %s
        """,
        (hash_token(token),),
    ).fetchone()

    if not row or row["status"] != "pending":
        return False

    if token_is_expired(row["confirmation_expires_at"]):
        return False

    cursor = _execute(
        conn,
        """
        UPDATE subscribers
        SET status = 'confirmed',
            confirmed_at = %s,
            confirmation_token_hash = NULL,
            confirmation_expires_at = NULL
        WHERE id = %s
          AND status = 'pending'
        """,
        (utc_now(), row["id"]),
    )

    if cursor.rowcount != 1:
        return False

    enqueue_resend_sync(conn, row["email"], "add")
    return True


def unsubscribe_subscription(conn, token):
    """Unsubscribe and queue Resend suppression atomically."""
    row = _execute(
        conn,
        """
        SELECT id, email
        FROM subscribers
        WHERE unsubscribe_token_hash = %s
          AND status = 'confirmed'
        """,
        (hash_token(token),),
    ).fetchone()

    if not row:
        return False

    _execute(
        conn,
        """
        UPDATE subscribers
        SET status = 'unsubscribed',
            consent = FALSE,
            unsubscribed_at = %s,
            unsubscribe_token_hash = NULL,
            confirmation_token_hash = NULL,
            confirmation_expires_at = NULL
        WHERE id = %s
          AND status = 'confirmed'
        """,
        (utc_now(), row["id"]),
    )

    enqueue_resend_sync(conn, row["email"], "unsubscribe")
    return True


def get_confirmation_email(conn, token):
    token_hash = hash_token(token)
    row = _execute(
        conn,
        """
        SELECT email
        FROM subscribers
        WHERE confirmation_token_hash = %s
        """,
        (token_hash,),
    ).fetchone()

    return row["email"] if row else None


def get_unsubscribe_email(conn, token):
    token_hash = hash_token(token)
    row = _execute(
        conn,
        """
        SELECT email
        FROM subscribers
        WHERE unsubscribe_token_hash = %s
        """,
        (token_hash,),
    ).fetchone()

    return row["email"] if row else None


def enqueue_resend_sync(conn, email, action):
    """Queue a Resend sync task in the current DB transaction."""
    if action not in {"add", "unsubscribe"}:
        raise ValueError("Unsupported Resend sync action.")

    table = (
        "resend_sync_outbox"
        if isinstance(conn, sqlite3.Connection)
        else "public.resend_sync_outbox"
    )

    now = utc_now()
    job_id = secrets.token_urlsafe(18)

    _execute(
        conn,
        f"""
        INSERT INTO {table} (
            id, email, action, status, attempts,
            next_attempt_at, created_at, updated_at
        )
        VALUES (%s, %s, %s, 'pending', 0, %s, %s, %s)
        """,
        (job_id, email, action, now, now, now),
    )

    return job_id
