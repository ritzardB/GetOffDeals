
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from getoffdeals import welcome_email_worker as worker
from getoffdeals.newsletter_invitation_service import hash_token


@pytest.fixture
def worker_db(tmp_path):
    path = tmp_path / "welcome-worker-test.sqlite3"

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE welcome_email_outbox (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                first_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                resend_message_id TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sent_at TEXT
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


def queue_job(connect, job_id="job-1"):
    now = datetime.now(timezone.utc).isoformat()

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO welcome_email_outbox (
                id, user_id, email, first_name,
                status, attempts, next_attempt_at,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (
                job_id,
                "user-123",
                "reader@example.com",
                "Alex",
                now,
                now,
                now,
            ),
        )


def read_job(connect, job_id="job-1"):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM welcome_email_outbox WHERE id = ?",
            (job_id,),
        ).fetchone()


def read_invitations(connect):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM newsletter_invitations"
        ).fetchall()


def test_successful_delivery_creates_invitation_and_marks_sent(
    worker_db, monkeypatch
):
    queue_job(worker_db)

    monkeypatch.setenv(
        "PUBLIC_BASE_URL",
        "https://getoffdeals.example",
    )

    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": "resend-message-123"}

    monkeypatch.setattr(
        worker,
        "send_welcome_email",
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
    assert invitations[0]["token_hash"]

    assert sent[0]["to_email"] == "reader@example.com"
    assert sent[0]["first_name"] == "Alex"

    subscribe_url = sent[0]["subscribe_url"]

    assert subscribe_url.startswith(
        "https://getoffdeals.example/newsletter/join/"
    )

    token = subscribe_url.rsplit("/", 1)[-1]

    assert invitations[0]["token_hash"] == hash_token(token)
    assert token != invitations[0]["token_hash"]


def test_failed_delivery_is_scheduled_for_retry(
    worker_db, monkeypatch
):
    queue_job(worker_db)

    monkeypatch.setenv(
        "PUBLIC_BASE_URL",
        "https://getoffdeals.example",
    )

    def fake_send(**kwargs):
        raise RuntimeError("Simulated Resend failure")

    monkeypatch.setattr(
        worker,
        "send_welcome_email",
        fake_send,
    )

    assert worker.process_one(worker_db) is True

    job = read_job(worker_db)

    assert job["status"] == "pending"
    assert job["attempts"] == 1
    assert job["last_error"] == "RuntimeError"
    assert job["resend_message_id"] is None

    # A fresh invitation was created for this delivery attempt.
    assert len(read_invitations(worker_db)) == 1


def test_retry_exhaustion_marks_job_failed(
    worker_db,
):
    queue_job(worker_db)

    job = read_job(worker_db)

    for attempt in range(worker.MAX_ATTEMPTS):
        job = dict(job)
        job["attempts"] = attempt

        with worker_db() as conn:
            worker._retry_job(
                conn,
                job,
                RuntimeError("Simulated failure"),
            )

    assert read_job(worker_db)["status"] == "failed"
    assert read_job(worker_db)["attempts"] == worker.MAX_ATTEMPTS


def test_empty_queue_returns_false(worker_db):
    assert worker.process_one(worker_db) is False


def test_invitation_failure_does_not_send_email(
    worker_db, monkeypatch
):
    queue_job(worker_db)

    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

    sent = []

    monkeypatch.setattr(
        worker,
        "send_welcome_email",
        lambda **kwargs: sent.append(kwargs),
    )

    assert worker.process_one(worker_db) is True

    assert sent == []

    job = read_job(worker_db)

    assert job["status"] == "pending"
    assert job["attempts"] == 1
    assert job["last_error"] == "RuntimeError"
    assert read_invitations(worker_db) == []


def test_invitation_token_remains_stable_across_retries(
    worker_db, monkeypatch
):
    queue_job(worker_db)

    monkeypatch.setenv(
        "PUBLIC_BASE_URL",
        "https://getoffdeals.example",
    )
    monkeypatch.setenv(
        "FLASK_SECRET_KEY",
        "test-only-secret",
    )

    sent_urls = []

    monkeypatch.setattr(
        worker,
        "send_welcome_email",
        lambda **kwargs: sent_urls.append(
            kwargs["subscribe_url"]
        ) or {"id": "mock-message"},
    )

    with worker_db() as conn:
        job = dict(conn.execute(
            "SELECT * FROM welcome_email_outbox WHERE id = ?",
            ("job-1",),
        ).fetchone())

    first_url = worker._create_subscription_invitation(
        worker_db,
        job,
    )
    second_url = worker._create_subscription_invitation(
        worker_db,
        job,
    )

    assert first_url == second_url

    token = first_url.rsplit("/", 1)[-1]

    invitations = read_invitations(worker_db)

    assert len(invitations) == 1
    assert invitations[0]["token_hash"] == hash_token(token)


def test_consumed_invitation_cannot_be_recreated(
    worker_db, monkeypatch
):
    from getoffdeals.newsletter_invitation_service import (
        consume_invitation,
    )

    queue_job(worker_db)

    monkeypatch.setenv(
        "PUBLIC_BASE_URL",
        "https://getoffdeals.example",
    )
    monkeypatch.setenv(
        "FLASK_SECRET_KEY",
        "test-only-secret",
    )

    with worker_db() as conn:
        job = dict(conn.execute(
            "SELECT * FROM welcome_email_outbox WHERE id = ?",
            ("job-1",),
        ).fetchone())

    first_url = worker._create_subscription_invitation(
        worker_db,
        job,
    )
    token = first_url.rsplit("/", 1)[-1]

    with worker_db() as conn:
        email = consume_invitation(conn, token)

    assert email == "reader@example.com"

    with pytest.raises(ValueError, match="already been consumed"):
        worker._create_subscription_invitation(
            worker_db,
            job,
        )
