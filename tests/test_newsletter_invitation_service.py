
import sqlite3

import pytest

from getoffdeals.newsletter_invitation_service import (
    create_invitation,
    consume_invitation,
    hash_token,
)


@pytest.fixture
def invitation_db(tmp_path):
    path = tmp_path / "invitation-test.sqlite3"

    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE newsletter_invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                email TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    yield conn

    conn.close()


def test_create_invitation_stores_only_token_hash(invitation_db):
    result = create_invitation(
        invitation_db,
        "user-123",
        "Reader@Example.com",
    )

    assert result["token"]
    assert result["token"] != hash_token(result["token"])

    row = invitation_db.execute(
        "SELECT * FROM newsletter_invitations"
    ).fetchone()

    assert row["token_hash"] == hash_token(result["token"])
    assert row["email"] == "reader@example.com"
    assert row["used_at"] is None


def test_valid_invitation_can_only_be_consumed_once(invitation_db):
    result = create_invitation(
        invitation_db,
        "user-123",
        "reader@example.com",
    )

    token = result["token"]

    assert consume_invitation(invitation_db, token) == (
        "reader@example.com"
    )

    assert consume_invitation(invitation_db, token) is None


def test_invalid_invitation_is_rejected(invitation_db):
    assert consume_invitation(
        invitation_db,
        "invalid-token-that-does-not-exist",
    ) is None


def test_new_invitation_invalidates_previous_unused_token(
    invitation_db,
):
    first = create_invitation(
        invitation_db,
        "user-123",
        "reader@example.com",
    )

    second = create_invitation(
        invitation_db,
        "user-123",
        "reader@example.com",
    )

    assert consume_invitation(
        invitation_db,
        first["token"],
    ) is None

    assert consume_invitation(
        invitation_db,
        second["token"],
    ) == "reader@example.com"
