
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from getoffdeals import resend_sync_worker as worker
from getoffdeals.resend_contacts import ResendContactsError


@pytest.fixture
def worker_db(tmp_path):
    path = tmp_path / "worker-test.sqlite3"

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE subscribers (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL
            );

            CREATE TABLE resend_sync_outbox (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                last_error TEXT,
                lease_token TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
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


def queue_job(connect, email, action="add"):
    now = datetime.now(timezone.utc).isoformat()

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO resend_sync_outbox (
                id, email, action, status, attempts,
                next_attempt_at, created_at, updated_at
            )
            VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            ("job-1", email, action, now, now, now),
        )


def read_job(connect):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM resend_sync_outbox WHERE id = ?",
            ("job-1",),
        ).fetchone()


def test_successful_add_marks_job_done(worker_db, monkeypatch):
    with worker_db() as conn:
        conn.execute(
            "INSERT INTO subscribers (email, status) VALUES (?, ?)",
            ("reader@example.com", "confirmed"),
        )

    queue_job(worker_db, "reader@example.com")

    calls = []
    monkeypatch.setattr(
        worker,
        "add_confirmed_contact",
        lambda email: calls.append(email) or "added",
    )

    assert worker.process_one(worker_db) is True
    assert calls == ["reader@example.com"]
    assert read_job(worker_db)["status"] == "done"


def test_stale_add_does_not_reactivate_unsubscribed_user(
    worker_db, monkeypatch
):
    with worker_db() as conn:
        conn.execute(
            "INSERT INTO subscribers (email, status) VALUES (?, ?)",
            ("reader@example.com", "unsubscribed"),
        )

    queue_job(worker_db, "reader@example.com")

    calls = []
    monkeypatch.setattr(
        worker,
        "add_confirmed_contact",
        lambda email: calls.append(email),
    )

    assert worker.process_one(worker_db) is True
    assert calls == []
    assert read_job(worker_db)["status"] == "done"


def test_resend_failure_schedules_retry(worker_db, monkeypatch):
    with worker_db() as conn:
        conn.execute(
            "INSERT INTO subscribers (email, status) VALUES (?, ?)",
            ("reader@example.com", "confirmed"),
        )

    queue_job(worker_db, "reader@example.com")

    def fail_sync(email):
        raise ResendContactsError("Temporary provider failure")

    monkeypatch.setattr(worker, "add_confirmed_contact", fail_sync)

    assert worker.process_one(worker_db) is True

    job = read_job(worker_db)
    assert job["status"] == "pending"
    assert job["attempts"] == 1
    assert job["last_error"] == "ResendContactsError"
    assert job["next_attempt_at"] > datetime.now(
        timezone.utc
    ).isoformat()


def test_successful_unsubscribe_marks_job_done(worker_db, monkeypatch):
    with worker_db() as conn:
        conn.execute(
            "INSERT INTO subscribers (email, status) VALUES (?, ?)",
            ("reader@example.com", "unsubscribed"),
        )

    queue_job(worker_db, "reader@example.com", action="unsubscribe")

    calls = []

    monkeypatch.setattr(
        worker,
        "unsubscribe_contact",
        lambda email: calls.append(email) or "unsubscribed",
    )

    assert worker.process_one(worker_db) is True
    assert calls == ["reader@example.com"]
    assert read_job(worker_db)["status"] == "done"


def test_stale_unsubscribe_does_not_suppress_confirmed_user(
    worker_db, monkeypatch
):
    with worker_db() as conn:
        conn.execute(
            "INSERT INTO subscribers (email, status) VALUES (?, ?)",
            ("reader@example.com", "confirmed"),
        )

    queue_job(worker_db, "reader@example.com", action="unsubscribe")

    calls = []

    monkeypatch.setattr(
        worker,
        "unsubscribe_contact",
        lambda email: calls.append(email),
    )

    assert worker.process_one(worker_db) is True
    assert calls == []
    assert read_job(worker_db)["status"] == "done"


def test_missing_subscriber_does_not_create_resend_contact(
    worker_db, monkeypatch
):
    queue_job(worker_db, "missing@example.com")

    calls = []

    monkeypatch.setattr(
        worker,
        "add_confirmed_contact",
        lambda email: calls.append(email),
    )

    assert worker.process_one(worker_db) is True
    assert calls == []
    assert read_job(worker_db)["status"] == "done"



def test_claim_job_assigns_and_replaces_expired_lease(worker_db):
    from datetime import timedelta

    queue_job(worker_db, "reader@example.com")

    old_token = "old-worker-token"
    expired_at = (
        datetime.now(timezone.utc) - timedelta(minutes=16)
    ).isoformat()

    with worker_db() as conn:
        conn.execute(
            """
            UPDATE resend_sync_outbox
            SET status = 'processing',
                lease_token = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (old_token, expired_at, "job-1"),
        )

    with worker_db() as conn:
        claimed = worker._claim_job(conn)

    assert claimed is not None
    assert claimed["lease_token"]
    assert claimed["lease_token"] != old_token

    job = read_job(worker_db)
    assert job["status"] == "processing"
    assert job["lease_token"] == claimed["lease_token"]


def test_old_worker_cannot_finish_reclaimed_job(worker_db):
    queue_job(worker_db, "reader@example.com")

    with worker_db() as conn:
        old_job = worker._claim_job(conn)

    assert old_job is not None

    new_token = "new-worker-token"

    with worker_db() as conn:
        conn.execute(
            """
            UPDATE resend_sync_outbox
            SET lease_token = ?
            WHERE id = ?
            """,
            (new_token, old_job["id"]),
        )

    with worker_db() as conn:
        completed = worker._finish_job(conn, old_job)

    assert completed is False

    job = read_job(worker_db)
    assert job["status"] == "processing"
    assert job["lease_token"] == new_token


def test_old_worker_cannot_retry_reclaimed_job(worker_db):
    queue_job(worker_db, "reader@example.com")

    with worker_db() as conn:
        old_job = worker._claim_job(conn)

    assert old_job is not None

    new_token = "new-worker-token"

    with worker_db() as conn:
        conn.execute(
            """
            UPDATE resend_sync_outbox
            SET lease_token = ?
            WHERE id = ?
            """,
            (new_token, old_job["id"]),
        )

    with worker_db() as conn:
        retried = worker._retry_job(
            conn,
            old_job,
            ResendContactsError("Temporary failure"),
        )

    assert retried is False

    job = read_job(worker_db)
    assert job["status"] == "processing"
    assert job["attempts"] == 0
    assert job["lease_token"] == new_token


def test_unexpected_error_schedules_retry(worker_db, monkeypatch):
    with worker_db() as conn:
        conn.execute(
            "INSERT INTO subscribers (email, status) VALUES (?, ?)",
            ("reader@example.com", "confirmed"),
        )

    queue_job(worker_db, "reader@example.com")

    def fail_unexpectedly(email):
        raise RuntimeError("Unexpected worker failure")

    monkeypatch.setattr(
        worker,
        "add_confirmed_contact",
        fail_unexpectedly,
    )

    assert worker.process_one(worker_db) is True

    job = read_job(worker_db)

    assert job["status"] == "pending"
    assert job["attempts"] == 1
    assert job["last_error"] == "RuntimeError"
    assert job["lease_token"] is None
