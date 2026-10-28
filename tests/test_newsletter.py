
import sqlite3

import app as app_module
import getoffdeals.newsletter_service as newsletter_service


def setup_newsletter_db(monkeypatch, tmp_path):
    db_path = tmp_path / "newsletter-test.sqlite3"
    monkeypatch.setattr(app_module, "DB_PATH", str(db_path))

    # Keep newsletter route tests isolated from live Supabase.
    monkeypatch.setattr(
        app_module,
        "newsletter_db_connect",
        app_module.db_connect,
    )

    app_module.init_db()
    return db_path


def test_newsletter_migration_adds_expected_columns(monkeypatch, tmp_path):
    setup_newsletter_db(monkeypatch, tmp_path)

    with app_module.db_connect() as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(subscribers)")
        }

    assert {
        "status",
        "consent_at",
        "confirmed_at",
        "confirmation_token_hash",
        "confirmation_expires_at",
        "unsubscribe_token_hash",
        "unsubscribed_at",
    }.issubset(columns)


def test_confirmation_token_hash_is_not_plaintext():
    token, token_hash = newsletter_service.generate_token()

    assert token
    assert token_hash != token
    assert newsletter_service.hash_token(token) == token_hash


def test_invalid_and_expired_tokens_are_rejected():
    assert newsletter_service.token_is_expired("not-a-date") is True


def test_signup_saves_pending_subscription_and_sends_one_mock_email(
    client, monkeypatch, tmp_path
):
    setup_newsletter_db(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "PUBLIC_BASE_URL",
        "https://getoffdeals.example",
    )

    sent = []

    def fake_send(to_email, confirmation_url, unsubscribe_url):
        sent.append((to_email, confirmation_url, unsubscribe_url))
        return {"id": "mock-email-id"}

    monkeypatch.setattr(
        app_module,
        "send_newsletter_confirmation",
        fake_send,
    )

    response = client.post(
        "/api/newsletter",
        json={
            "email": "reader@example.com",
            "consent": True,
        },
    )

    assert response.status_code == 202
    assert len(sent) == 1
    assert sent[0][0] == "reader@example.com"
    assert sent[0][1].startswith(
        "https://getoffdeals.example/newsletter/confirm/"
    )
    assert sent[0][2].startswith(
        "https://getoffdeals.example/newsletter/unsubscribe/"
    )

    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM subscribers WHERE email = ?",
            ("reader@example.com",),
        ).fetchone()

    assert row["status"] == "pending"
    assert row["consent"] == 1
    assert row["confirmation_token_hash"]
    assert row["unsubscribe_token_hash"]


def test_signup_rejects_missing_consent(client):
    response = client.post(
        "/api/newsletter",
        json={
            "email": "reader@example.com",
            "consent": False,
        },
    )

    assert response.status_code == 400


def test_confirmation_get_does_not_confirm_subscription(
    client, monkeypatch, tmp_path
):
    setup_newsletter_db(monkeypatch, tmp_path)

    with app_module.db_connect() as conn:
        subscription = newsletter_service.prepare_subscription(
            conn,
            "reader@example.com",
        )

    token = subscription["confirmation_token"]
    response = client.get(f"/newsletter/confirm/{token}")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"

    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT status FROM subscribers WHERE email = ?",
            ("reader@example.com",),
        ).fetchone()

    assert row["status"] == "pending"


def test_confirmation_post_requires_csrf_token(
    client, monkeypatch, tmp_path
):
    setup_newsletter_db(monkeypatch, tmp_path)

    with app_module.db_connect() as conn:
        subscription = newsletter_service.prepare_subscription(
            conn,
            "reader@example.com",
        )

    response = client.post(
        f"/newsletter/confirm/{subscription['confirmation_token']}",
        data={},
    )

    assert response.status_code == 400

    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT status FROM subscribers WHERE email = ?",
            ("reader@example.com",),
        ).fetchone()

    assert row["status"] == "pending"


def test_valid_confirmation_changes_status_to_confirmed(
    client, monkeypatch, tmp_path
):
    setup_newsletter_db(monkeypatch, tmp_path)

    with app_module.db_connect() as conn:
        subscription = newsletter_service.prepare_subscription(
            conn, "reader@example.com"
        )

    token = subscription["confirmation_token"]
    page = client.get(f"/newsletter/confirm/{token}")
    assert page.status_code == 200

    with client.session_transaction() as sess:
        csrf_token = sess["newsletter_confirm_csrf_token"]

    response = client.post(
        f"/newsletter/confirm/{token}",
        data={"csrf_token": csrf_token},
    )
    assert response.status_code == 200
    assert b"confirmed" in response.data.lower()

    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT status, confirmation_token_hash FROM subscribers "
            "WHERE email = ?",
            ("reader@example.com",),
        ).fetchone()

    assert row["status"] == "confirmed"
    assert row["confirmation_token_hash"] is None


def test_expired_confirmation_token_is_rejected(
    client, monkeypatch, tmp_path
):
    setup_newsletter_db(monkeypatch, tmp_path)

    with app_module.db_connect() as conn:
        subscription = newsletter_service.prepare_subscription(
            conn, "reader@example.com"
        )
        conn.execute(
            "UPDATE subscribers SET confirmation_expires_at = ? "
            "WHERE email = ?",
            ("2000-01-01T00:00:00+00:00", "reader@example.com"),
        )

    token = subscription["confirmation_token"]
    client.get(f"/newsletter/confirm/{token}")

    with client.session_transaction() as sess:
        csrf_token = sess["newsletter_confirm_csrf_token"]

    response = client.post(
        f"/newsletter/confirm/{token}",
        data={"csrf_token": csrf_token},
    )
    assert response.status_code == 200
    assert b"Link unavailable" in response.data

    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT status FROM subscribers WHERE email = ?",
            ("reader@example.com",),
        ).fetchone()

    assert row["status"] == "pending"



def test_confirmed_subscriber_can_unsubscribe(
    client, monkeypatch, tmp_path
):
    setup_newsletter_db(monkeypatch, tmp_path)

    with app_module.db_connect() as conn:
        subscription = newsletter_service.prepare_subscription(
            conn, "reader@example.com"
        )
        newsletter_service.confirm_subscription(
            conn, subscription["confirmation_token"]
        )

    token = subscription["unsubscribe_token"]
    page = client.get(f"/newsletter/unsubscribe/{token}")
    assert page.status_code == 200

    with client.session_transaction() as sess:
        csrf_token = sess["newsletter_unsubscribe_csrf_token"]

    response = client.post(
        f"/newsletter/unsubscribe/{token}",
        data={"csrf_token": csrf_token},
    )
    assert response.status_code == 200
    assert b"unsubscribed" in response.data.lower()

    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM subscribers WHERE email = ?",
            ("reader@example.com",),
        ).fetchone()

    assert row["status"] == "unsubscribed"
    assert row["consent"] == 0
    assert row["unsubscribe_token_hash"] is None
    assert row["confirmation_token_hash"] is None


def test_repeat_signup_does_not_demote_confirmed_subscriber(
    monkeypatch, tmp_path
):
    setup_newsletter_db(monkeypatch, tmp_path)

    with app_module.db_connect() as conn:
        subscription = newsletter_service.prepare_subscription(
            conn, "reader@example.com"
        )
        newsletter_service.confirm_subscription(
            conn, subscription["confirmation_token"]
        )

        repeated = newsletter_service.prepare_subscription(
            conn, "reader@example.com"
        )

    assert repeated["status"] == "already_confirmed"

    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT status FROM subscribers WHERE email = ?",
            ("reader@example.com",),
        ).fetchone()

    assert row["status"] == "confirmed"


def test_unsubscribe_rejects_pending_subscriber(
    monkeypatch, tmp_path
):
    setup_newsletter_db(monkeypatch, tmp_path)

    with app_module.db_connect() as conn:
        subscription = newsletter_service.prepare_subscription(
            conn, "reader@example.com"
        )
        result = newsletter_service.unsubscribe_subscription(
            conn, subscription["unsubscribe_token"]
        )

    assert result is False

    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT status FROM subscribers WHERE email = ?",
            ("reader@example.com",),
        ).fetchone()

    assert row["status"] == "pending"



def test_signup_can_retry_after_confirmation_email_failure(
    client, monkeypatch, tmp_path
):
    setup_newsletter_db(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "PUBLIC_BASE_URL",
        "https://getoffdeals.example",
    )

    attempts = []

    def fake_send(to_email, confirmation_url, unsubscribe_url):
        attempts.append(
            (to_email, confirmation_url, unsubscribe_url)
        )
        if len(attempts) == 1:
            raise RuntimeError("Simulated email provider failure")
        return {"id": "mock-retry-email"}

    monkeypatch.setattr(
        app_module,
        "send_newsletter_confirmation",
        fake_send,
    )

    payload = {
        "email": "retry-reader@example.com",
        "consent": True,
    }

    # First attempt: email delivery fails.
    first_response = client.post(
        "/api/newsletter",
        json=payload,
    )
    assert first_response.status_code == 503
    assert len(attempts) == 1

    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM subscribers WHERE email = ?",
            ("retry-reader@example.com",),
        ).fetchone()

    assert row["status"] == "pending"
    assert row["confirmation_token_hash"] is not None

    first_confirmation_url = attempts[0][1]
    first_unsubscribe_url = attempts[0][2]

    # Second attempt: a new confirmation email succeeds.
    second_response = client.post(
        "/api/newsletter",
        json=payload,
    )
    assert second_response.status_code == 202
    assert len(attempts) == 2

    second_confirmation_url = attempts[1][1]
    second_unsubscribe_url = attempts[1][2]

    # Retrying must issue fresh links.
    assert second_confirmation_url != first_confirmation_url
    assert second_unsubscribe_url != first_unsubscribe_url

    # The database must store hashes for the newest tokens.
    from getoffdeals.newsletter_service import hash_token

    second_confirmation_token = second_confirmation_url.rsplit("/", 1)[-1]
    second_unsubscribe_token = second_unsubscribe_url.rsplit("/", 1)[-1]

    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM subscribers WHERE email = ?",
            ("retry-reader@example.com",),
        ).fetchone()

    assert row["status"] == "pending"
    assert row["confirmation_token_hash"] == hash_token(
        second_confirmation_token
    )
    assert row["unsubscribe_token_hash"] == hash_token(
        second_unsubscribe_token
    )


def test_repeat_signup_does_not_reactivate_unsubscribed_contact(
    monkeypatch, tmp_path
):
    setup_newsletter_db(monkeypatch, tmp_path)

    with app_module.db_connect() as conn:
        subscription = newsletter_service.prepare_subscription(
            conn, "reader@example.com"
        )

        newsletter_service.confirm_subscription(
            conn, subscription["confirmation_token"]
        )

        newsletter_service.unsubscribe_subscription(
            conn, subscription["unsubscribe_token"]
        )

        repeated = newsletter_service.prepare_subscription(
            conn, "reader@example.com"
        )

    assert repeated["status"] == "already_unsubscribed"

    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT status, consent FROM subscribers "
            "WHERE email = ?",
            ("reader@example.com",),
        ).fetchone()

    assert row["status"] == "unsubscribed"
    assert row["consent"] == 0
