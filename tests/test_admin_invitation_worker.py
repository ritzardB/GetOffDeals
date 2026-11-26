
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from getoffdeals import admin_invitation_worker as worker
from getoffdeals.newsletter_invitation_service import (
    create_invitation,
    hash_token,
)


@pytest.fixture
def worker_db(tmp_path):
    path = tmp_path / "admin-invitation-worker.sqlite3"

    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL
            );

            CREATE TABLE subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                status TEXT NOT NULL
            );

            CREATE TABLE newsletter_invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                email TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE admin_newsletter_invitation_outbox (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                email TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                resend_message_id TEXT,
                last_error TEXT,
                first_attempt_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sent_at TEXT
            );
        """)

    @contextmanager
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    return connect


def add_user(connect, user_id="user-123", email="reader@example.com"):
    with connect() as conn:
        conn.execute(
            "INSERT INTO users (id, email) VALUES (?, ?)",
            (user_id, email),
        )


def queue_job(connect, job_id="job-123", user_id="user-123"):
    now = datetime.now(timezone.utc).isoformat()

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO admin_newsletter_invitation_outbox (
                id, user_id, email, status, attempts,
                next_attempt_at, created_at, updated_at
            )
            VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (
                job_id,
                user_id,
                "reader@example.com",
                now,
                now,
                now,
            ),
        )


def read_job(connect, job_id="job-123"):
    with connect() as conn:
        return conn.execute(
            """
            SELECT *
            FROM admin_newsletter_invitation_outbox
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()


def read_invitations(connect):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM newsletter_invitations"
        ).fetchall()


def set_old_first_attempt(connect, hours=24):
    old = (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).isoformat()

    with connect() as conn:
        conn.execute(
            """
            UPDATE admin_newsletter_invitation_outbox
            SET first_attempt_at = ?
            WHERE id = 'job-123'
            """,
            (old,),
        )


def configure_worker(monkeypatch):
    monkeypatch.setenv(
        "PUBLIC_BASE_URL",
        "https://getoffdeals.example",
    )
    monkeypatch.setenv(
        "FLASK_SECRET_KEY",
        "test-only-secret",
    )


def test_successful_delivery_creates_invitation_and_marks_sent(
    worker_db, monkeypatch
):
    add_user(worker_db)
    queue_job(worker_db)
    configure_worker(monkeypatch)

    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": "resend-message-123"}

    monkeypatch.setattr(
        worker,
        "send_newsletter_invitation",
        fake_send,
    )

    assert worker.process_one(worker_db) is True

    job = read_job(worker_db)
    invitations = read_invitations(worker_db)

    assert job["status"] == "sent"
    assert job["resend_message_id"] == "resend-message-123"
    assert job["sent_at"] is not None
    assert job["attempts"] == 0

    assert len(invitations) == 1
    assert invitations[0]["user_id"] == "user-123"
    assert invitations[0]["email"] == "reader@example.com"

    token = sent[0]["invitation_url"].rsplit("/", 1)[-1]

    assert invitations[0]["token_hash"] == hash_token(token)
    assert token != invitations[0]["token_hash"]

    assert sent[0]["to_email"] == "reader@example.com"
    assert sent[0]["idempotency_key"] == (
        "getoffdeals-admin-newsletter-invitation-job-123"
    )


def test_missing_resend_message_id_retries_instead_of_marking_sent(
    worker_db, monkeypatch
):
    add_user(worker_db)
    queue_job(worker_db)
    configure_worker(monkeypatch)

    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs)
        return {}

    monkeypatch.setattr(
        worker,
        "send_newsletter_invitation",
        fake_send,
    )

    assert worker.process_one(worker_db) is True

    job = read_job(worker_db)

    assert job["status"] == "pending"
    assert job["attempts"] == 1
    assert job["resend_message_id"] is None
    assert job["sent_at"] is None
    assert job["last_error"] == "RuntimeError"
    assert len(sent) == 1


def test_already_subscribed_user_is_skipped(
    worker_db, monkeypatch
):
    add_user(worker_db)

    with worker_db() as conn:
        conn.execute(
            "INSERT INTO subscribers (email, status) VALUES (?, ?)",
            ("reader@example.com", "confirmed"),
        )

    queue_job(worker_db)
    configure_worker(monkeypatch)

    sent = []

    monkeypatch.setattr(
        worker,
        "send_newsletter_invitation",
        lambda **kwargs: sent.append(kwargs),
    )

    assert worker.process_one(worker_db) is True

    assert sent == []
    assert read_job(worker_db)["status"] == "skipped"
    assert read_invitations(worker_db) == []


def test_existing_welcome_invitation_is_preserved(
    worker_db, monkeypatch
):
    add_user(worker_db)
    queue_job(worker_db)
    configure_worker(monkeypatch)

    with worker_db() as conn:
        existing = create_invitation(
            conn,
            "user-123",
            "reader@example.com",
        )

    sent = []

    monkeypatch.setattr(
        worker,
        "send_newsletter_invitation",
        lambda **kwargs: sent.append(kwargs),
    )

    assert worker.process_one(worker_db) is True

    assert sent == []
    assert read_job(worker_db)["status"] == "skipped"

    invitations = read_invitations(worker_db)

    assert len(invitations) == 1
    assert invitations[0]["token_hash"] == hash_token(
        existing["token"]
    )


def test_failed_delivery_retries_with_same_job_identity(
    worker_db, monkeypatch
):
    add_user(worker_db)
    queue_job(worker_db)
    configure_worker(monkeypatch)

    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs)
        raise RuntimeError("Simulated Resend failure")

    monkeypatch.setattr(
        worker,
        "send_newsletter_invitation",
        fake_send,
    )

    assert worker.process_one(worker_db) is True

    job = read_job(worker_db)

    assert job["status"] == "pending"
    assert job["attempts"] == 1
    assert job["last_error"] == "RuntimeError"
    assert job["first_attempt_at"] is not None

    assert len(sent) == 1

    first_token = sent[0]["invitation_url"].rsplit("/", 1)[-1]
    first_key = sent[0]["idempotency_key"]

    # The invitation is reused on another preparation attempt.
    with worker_db() as conn:
        claimed_job = dict(
            conn.execute(
                """
                SELECT *
                FROM admin_newsletter_invitation_outbox
                WHERE id = ?
                """,
                ("job-123",),
            ).fetchone()
        )

    second_url = worker._prepare_invitation(
        worker_db,
        claimed_job,
    )

    second_token = second_url.rsplit("/", 1)[-1]

    assert first_token == second_token
    assert first_key == worker._idempotency_key(claimed_job)
    assert len(read_invitations(worker_db)) == 1


def test_retry_exhaustion_marks_job_failed(worker_db):
    add_user(worker_db)
    queue_job(worker_db)

    for _ in range(worker.MAX_ATTEMPTS):
        # Simulate the worker claiming the job.
        with worker_db() as conn:
            conn.execute(
                """
                UPDATE admin_newsletter_invitation_outbox
                SET status = 'processing'
                WHERE id = ?
                """,
                ("job-123",),
            )

        job = dict(read_job(worker_db))

        with worker_db() as conn:
            worker._retry_job(
                conn,
                job,
                RuntimeError("Simulated failure"),
            )

    final_job = read_job(worker_db)

    assert final_job["status"] == "failed"
    assert final_job["attempts"] == worker.MAX_ATTEMPTS



def test_expired_idempotency_window_marks_job_failed(
    worker_db,
):
    add_user(worker_db)
    queue_job(worker_db)

    set_old_first_attempt(worker_db, hours=24)

    with worker_db() as conn:
        assert worker._claim_job(conn) is None

    job = read_job(worker_db)

    assert job["status"] == "failed"
    assert "idempotency window expired" in job["last_error"]


def test_stale_processing_job_is_recovered(worker_db):
    add_user(worker_db)
    queue_job(worker_db)

    old = (
        datetime.now(timezone.utc)
        - timedelta(minutes=20)
    ).isoformat()

    with worker_db() as conn:
        conn.execute(
            """
            UPDATE admin_newsletter_invitation_outbox
            SET status = 'processing',
                first_attempt_at = ?,
                updated_at = ?
            WHERE id = 'job-123'
            """,
            (old, old),
        )

    with worker_db() as conn:
        job = worker._claim_job(conn)

    assert job is not None
    assert job["id"] == "job-123"

    stored = read_job(worker_db)

    assert stored["status"] == "processing"
    assert stored["first_attempt_at"] == old


def test_empty_queue_returns_false(worker_db):
    assert worker.process_one(worker_db) is False


def test_invitation_token_is_stable_for_same_job(
    monkeypatch,
):
    configure_worker(monkeypatch)

    job = {
        "id": "job-123",
        "user_id": "user-123",
    }

    first = worker._invitation_token(job)
    second = worker._invitation_token(job)

    assert first == second

    different_job = {
        "id": "job-456",
        "user_id": "user-123",
    }

    assert first != worker._invitation_token(different_job)


def test_changed_account_email_skips_invitation(
    worker_db, monkeypatch
):
    add_user(
        worker_db,
        email="new-address@example.com",
    )
    queue_job(worker_db)
    configure_worker(monkeypatch)

    sent = []

    monkeypatch.setattr(
        worker,
        "send_newsletter_invitation",
        lambda **kwargs: sent.append(kwargs),
    )

    assert worker.process_one(worker_db) is True

    job = read_job(worker_db)

    assert job["status"] == "skipped"
    assert sent == []
    assert read_invitations(worker_db) == []
