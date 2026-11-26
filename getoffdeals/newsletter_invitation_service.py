
"""Secure, single-use newsletter invitation management."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from getoffdeals.newsletter_service import _execute


INVITATION_TTL_HOURS = 24


def _is_sqlite(conn):
    import sqlite3
    return isinstance(conn, sqlite3.Connection)


def _table(conn):
    return (
        "newsletter_invitations"
        if _is_sqlite(conn)
        else "public.newsletter_invitations"
    )


def _now():
    return datetime.now(timezone.utc)


def _timestamp(value):
    return value.isoformat()


def hash_token(token):
    """Return the SHA-256 hash of an invitation token."""
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def get_invitation_email(conn, token):
    """Return the email for a valid invitation without consuming it."""
    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        return None

    token_hash = hash_token(token)
    table = _table(conn)
    now = _timestamp(_now())

    row = _execute(
        conn,
        f"""
        SELECT email
        FROM {table}
        WHERE token_hash = %s
          AND used_at IS NULL
          AND expires_at > %s
        """,
        (token_hash, now),
    ).fetchone()

    return row["email"] if row else None


def create_invitation(conn, user_id, email):
    """
    Create a new invitation and return its plaintext token.

    Only the token hash is stored in the database.
    Any previous unused invitation for this user is invalidated.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("A valid user ID is required.")

    if not isinstance(email, str) or not email.strip():
        raise ValueError("A valid email address is required.")

    email = email.strip().lower()

    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)

    now = _now()
    expires_at = now + timedelta(hours=INVITATION_TTL_HOURS)

    table = _table(conn)

    # Invalidate any previous unused invitation for this user.
    # This also handles expired invitations.
    _execute(
        conn,
        f"""
        DELETE FROM {table}
        WHERE user_id = %s
          AND used_at IS NULL
        """,
        (user_id,),
    )

    _execute(
        conn,
        f"""
        INSERT INTO {table} (
            user_id,
            email,
            token_hash,
            expires_at,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            user_id,
            email,
            token_hash,
            _timestamp(expires_at),
            _timestamp(now),
        ),
    )

    return {
        "token": token,
        "expires_at": _timestamp(expires_at),
    }


def create_or_reuse_invitation(conn, user_id, email, token):
    """
    Reuse a valid invitation token across welcome-email retries.

    The caller supplies a deterministic, securely generated token.
    Only its hash is stored in the database.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("A valid user ID is required.")

    if not isinstance(email, str) or not email.strip():
        raise ValueError("A valid email address is required.")

    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        raise ValueError("A valid invitation token is required.")

    email = email.strip().lower()
    token_hash = hash_token(token)
    table = _table(conn)
    now = _now()
    now_text = _timestamp(now)

    existing = _execute(
        conn,
        f"""
        SELECT token_hash, expires_at, used_at
        FROM {table}
        WHERE user_id = %s
          AND used_at IS NULL
        """,
        (user_id,),
    ).fetchone()

    if existing and existing["token_hash"] == token_hash:
        if existing["expires_at"] > now_text:
            return {
                "token": token,
                "expires_at": existing["expires_at"],
            }

        # The same invitation expired. Replace it with a fresh expiry.
        _execute(
            conn,
            f"""
            DELETE FROM {table}
            WHERE user_id = %s
              AND token_hash = %s
              AND used_at IS NULL
            """,
            (user_id, token_hash),
        )

    elif existing:
        _execute(
            conn,
            f"""
            DELETE FROM {table}
            WHERE user_id = %s
              AND used_at IS NULL
            """,
            (user_id,),
        )

    # Never recreate an invitation that has already been consumed.
    used = _execute(
        conn,
        f"""
        SELECT 1
        FROM {table}
        WHERE token_hash = %s
          AND used_at IS NOT NULL
        """,
        (token_hash,),
    ).fetchone()

    if used:
        raise ValueError("This invitation has already been consumed.")

    expires_at = now + timedelta(hours=INVITATION_TTL_HOURS)

    _execute(
        conn,
        f"""
        INSERT INTO {table} (
            user_id, email, token_hash, expires_at, created_at
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            user_id,
            email,
            token_hash,
            _timestamp(expires_at),
            now_text,
        ),
    )

    return {
        "token": token,
        "expires_at": _timestamp(expires_at),
    }



def consume_invitation(conn, token):
    """
    Consume a valid invitation exactly once.

    Returns the associated email on success, otherwise None.
    """
    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        return None

    token_hash = hash_token(token)
    table = _table(conn)

    now = _timestamp(_now())

    row = _execute(
        conn,
        f"""
        SELECT email
        FROM {table}
        WHERE token_hash = %s
          AND used_at IS NULL
          AND expires_at > %s
        """,
        (token_hash, now),
    ).fetchone()

    if not row:
        return None

    cursor = _execute(
        conn,
        f"""
        UPDATE {table}
        SET used_at = %s
        WHERE token_hash = %s
          AND used_at IS NULL
          AND expires_at > %s
        """,
        (now, token_hash, now),
    )

    if cursor.rowcount != 1:
        return None

    return row["email"]


def restore_invitation(conn, token):
    """
    Restore a consumed invitation after confirmation-email delivery fails.

    The invitation must still be within its original expiry period.
    Returns True if the invitation was restored.
    """
    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        return False

    token_hash = hash_token(token)
    table = _table(conn)
    now = _timestamp(_now())

    cursor = _execute(
        conn,
        f"""
        UPDATE {table}
        SET used_at = NULL
        WHERE token_hash = %s
          AND used_at IS NOT NULL
          AND expires_at > %s
        """,
        (token_hash, now),
    )

    return cursor.rowcount == 1
