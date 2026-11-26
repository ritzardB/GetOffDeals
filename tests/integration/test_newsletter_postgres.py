
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import getoffdeals.resend_sync_worker as worker

from getoffdeals.newsletter_service import (
    prepare_subscription,
    confirm_subscription,
    unsubscribe_subscription,
)


def test_postgres_newsletter_tables_are_available(postgres_test_db):
    with postgres_test_db["connect"]() as conn:
        result = conn.execute(
            """
            SELECT
                to_regclass('public.subscribers') AS subscribers,
                to_regclass('public.resend_sync_outbox') AS outbox
            """
        ).fetchone()

    assert result["subscribers"] == "subscribers"
    assert result["outbox"] == "resend_sync_outbox"


def test_concurrent_unsubscribe_only_creates_one_job(postgres_test_db):
    email = f"concurrent-{uuid.uuid4().hex}@example.com"
    postgres_test_db["track_email"](email)

    # Prepare and confirm the subscriber.
    with postgres_test_db["connect"]() as conn:
        subscription = prepare_subscription(conn, email)
        assert confirm_subscription(
            conn, subscription["confirmation_token"]
        )

    token = subscription["unsubscribe_token"]
    barrier = threading.Barrier(2)

    def attempt_unsubscribe():
        with postgres_test_db["connect"]() as conn:
            barrier.wait(timeout=10)
            return unsubscribe_subscription(conn, token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(attempt_unsubscribe)
            for _ in range(2)
        ]
        results = [future.result(timeout=20) for future in futures]

    assert sorted(results) == [False, True]

    with postgres_test_db["connect"]() as conn:
        subscriber = conn.execute(
            """
            SELECT status, consent
            FROM public.subscribers
            WHERE LOWER(email) = LOWER(%s)
            """,
            (email,),
        ).fetchone()

        job_count = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM public.resend_sync_outbox
            WHERE LOWER(email) = LOWER(%s)
              AND action = 'unsubscribe'
            """,
            (email,),
        ).fetchone()["total"]

    assert subscriber["status"] == "unsubscribed"
    assert subscriber["consent"] is False
    assert job_count == 1


def test_add_operation_and_unsubscribe_are_serialized(
    postgres_test_db, monkeypatch
):
    email = f"race-{uuid.uuid4().hex}@example.com"
    postgres_test_db["track_email"](email)

    # Create and confirm the subscriber.
    with postgres_test_db["connect"]() as conn:
        subscription = prepare_subscription(conn, email)
        assert confirm_subscription(
            conn, subscription["confirmation_token"]
        )

    # Ensure this test claims only its own job.
    def claim_test_job(conn):
        row = conn.execute(
            """
            SELECT id, email, action, attempts
            FROM public.resend_sync_outbox
            WHERE LOWER(email) = LOWER(%s)
              AND action = 'add'
              AND status = 'pending'
            ORDER BY created_at
            LIMIT 1
            """,
            (email,),
        ).fetchone()

        if not row:
            conn.commit()
            return None

        lease_token = str(uuid.uuid4())

        cursor = conn.execute(
            """
            UPDATE public.resend_sync_outbox
            SET status = 'processing',
                lease_token = %s,
                updated_at = %s
            WHERE id = %s
              AND status = 'pending'
            """,
            (
                lease_token,
                worker._timestamp(worker._now()),
                row["id"],
            ),
        )

        if cursor.rowcount != 1:
            conn.commit()
            return None

        conn.commit()

        claimed_job = dict(row)
        claimed_job["lease_token"] = lease_token

        return claimed_job

    monkeypatch.setattr(worker, "_claim_job", claim_test_job)

    add_started = threading.Event()
    release_add = threading.Event()
    add_calls = []

    def fake_add(contact_email):
        add_calls.append(contact_email)
        add_started.set()

        if not release_add.wait(timeout=10):
            raise TimeoutError(
                "Test timed out waiting to release Resend add"
            )

        return "added"

    monkeypatch.setattr(
        worker,
        "add_confirmed_contact",
        fake_add,
    )

    def perform_unsubscribe():
        with postgres_test_db["connect"]() as conn:
            return unsubscribe_subscription(
                conn,
                subscription["unsubscribe_token"],
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        worker_future = executor.submit(
            worker.process_one,
            postgres_test_db["connect"],
        )

        # The worker has checked consent and is holding the subscriber lock.
        assert add_started.wait(timeout=10)

        unsubscribe_future = executor.submit(perform_unsubscribe)

        # Allow the worker's Resend operation to finish.
        release_add.set()

        assert worker_future.result(timeout=20) is True
        assert unsubscribe_future.result(timeout=20) is True

    with postgres_test_db["connect"]() as conn:
        subscriber = conn.execute(
            """
            SELECT status, consent
            FROM public.subscribers
            WHERE LOWER(email) = LOWER(%s)
            """,
            (email,),
        ).fetchone()

        jobs = conn.execute(
            """
            SELECT action, status
            FROM public.resend_sync_outbox
            WHERE LOWER(email) = LOWER(%s)
            ORDER BY action
            """,
            (email,),
        ).fetchall()

    assert add_calls == [email]
    assert subscriber["status"] == "unsubscribed"
    assert subscriber["consent"] is False

    job_statuses = {
        job["action"]: job["status"]
        for job in jobs
    }

    assert job_statuses == {
        "add": "done",
        "unsubscribe": "pending",
    }


def test_stale_unsubscribe_does_not_suppress_reconfirmed_subscriber(
    postgres_test_db, monkeypatch
):
    email = f"reconfirmed-{uuid.uuid4().hex}@example.com"
    postgres_test_db["track_email"](email)

    # First consent and confirmation.
    with postgres_test_db["connect"]() as conn:
        first = prepare_subscription(conn, email)
        assert confirm_subscription(conn, first["confirmation_token"])

        assert unsubscribe_subscription(
            conn, first["unsubscribe_token"]
        )

    # Simulate the subscriber's current state after a separate,
    # legitimate re-consent process.
    #
    # This tests the worker's stale-job safeguard only.
    # It does not test the application's re-subscription workflow.
    with postgres_test_db["connect"]() as conn:
        conn.execute(
            """
            UPDATE public.subscribers
            SET status = 'confirmed',
                consent = TRUE,
                confirmed_at = NOW()
            WHERE LOWER(email) = LOWER(%s)
            """,
            (email,),
        )

    # Claim only this subscriber's old unsubscribe job.
    def claim_test_job(conn):
        row = conn.execute(
            """
            SELECT id, email, action, attempts
            FROM public.resend_sync_outbox
            WHERE LOWER(email) = LOWER(%s)
              AND action = 'unsubscribe'
              AND status = 'pending'
            ORDER BY created_at
            LIMIT 1
            """,
            (email,),
        ).fetchone()

        if not row:
            conn.commit()
            return None

        lease_token = str(uuid.uuid4())

        cursor = conn.execute(
            """
            UPDATE public.resend_sync_outbox
            SET status = 'processing',
                lease_token = %s,
                updated_at = %s
            WHERE id = %s
              AND status = 'pending'
            """,
            (
                lease_token,
                worker._timestamp(worker._now()),
                row["id"],
            ),
        )

        if cursor.rowcount != 1:
            conn.commit()
            return None

        conn.commit()

        claimed_job = dict(row)
        claimed_job["lease_token"] = lease_token

        return claimed_job

    monkeypatch.setattr(worker, "_claim_job", claim_test_job)

    unsubscribe_calls = []

    monkeypatch.setattr(
        worker,
        "unsubscribe_contact",
        lambda contact_email: unsubscribe_calls.append(contact_email),
    )

    assert worker.process_one(postgres_test_db["connect"]) is True
    assert unsubscribe_calls == []

    with postgres_test_db["connect"]() as conn:
        subscriber = conn.execute(
            """
            SELECT status, consent
            FROM public.subscribers
            WHERE LOWER(email) = LOWER(%s)
            """,
            (email,),
        ).fetchone()

        job = conn.execute(
            """
            SELECT status
            FROM public.resend_sync_outbox
            WHERE LOWER(email) = LOWER(%s)
              AND action = 'unsubscribe'
            """,
            (email,),
        ).fetchone()

    assert subscriber["status"] == "confirmed"
    assert subscriber["consent"] is True
    assert job["status"] == "done"
