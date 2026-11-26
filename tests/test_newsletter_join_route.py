from contextlib import nullcontext

import app as app_module
from getoffdeals import newsletter_invitation_service as invitation_service


INVITATION_TOKEN = "test-invitation-token-123456789"
TEST_EMAIL = "traveller@example.com"
CSRF_TOKEN = "test-newsletter-join-csrf-token"


def mock_newsletter_connection(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "newsletter_db_connect",
        lambda: nullcontext(object()),
    )


def set_join_csrf(client):
    with client.session_transaction() as session:
        session["newsletter_join_csrf_token"] = CSRF_TOKEN


def test_valid_invitation_displays_explicit_opt_in(client, monkeypatch):
    mock_newsletter_connection(monkeypatch)

    monkeypatch.setattr(
        invitation_service,
        "get_invitation_email",
        lambda conn, token: TEST_EMAIL,
    )

    response = client.get(
        f"/newsletter/join/{INVITATION_TOKEN}"
    )

    assert response.status_code == 200
    assert TEST_EMAIL.encode() in response.data
    assert b"Yes, subscribe me" in response.data
    assert b"confirmation email" in response.data.lower()

    with client.session_transaction() as session:
        assert session.get("newsletter_join_csrf_token")


def test_invalid_invitation_displays_unavailable_page(
    client,
    monkeypatch,
):
    mock_newsletter_connection(monkeypatch)

    monkeypatch.setattr(
        invitation_service,
        "get_invitation_email",
        lambda conn, token: None,
    )

    response = client.get(
        f"/newsletter/join/{INVITATION_TOKEN}"
    )

    assert response.status_code == 200
    assert b"Invitation unavailable" in response.data


def test_missing_or_invalid_csrf_token_is_rejected(
    client,
    monkeypatch,
):
    mock_newsletter_connection(monkeypatch)

    monkeypatch.setattr(
        invitation_service,
        "consume_invitation",
        lambda conn, token: pytest.fail(
            "Invitation must not be consumed without valid CSRF"
        ),
    )

    response = client.post(
        f"/newsletter/join/{INVITATION_TOKEN}",
        data={"csrf_token": "invalid-token"},
    )

    assert response.status_code == 400


def test_explicit_opt_in_creates_pending_subscription_and_sends_confirmation(
    client,
    monkeypatch,
):
    mock_newsletter_connection(monkeypatch)
    set_join_csrf(client)

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://getoffdeals.com")

    consumed = []
    sent_emails = []

    monkeypatch.setattr(
        invitation_service,
        "consume_invitation",
        lambda conn, token: consumed.append(token) or TEST_EMAIL,
    )

    monkeypatch.setattr(
        app_module,
        "prepare_subscription",
        lambda conn, email: {
            "status": "pending",
            "confirmation_token": "confirmation-token-123456789",
            "unsubscribe_token": "unsubscribe-token-123456789",
        },
    )

    monkeypatch.setattr(
        app_module,
        "send_newsletter_confirmation",
        lambda *args: sent_emails.append(args),
    )

    response = client.post(
        f"/newsletter/join/{INVITATION_TOKEN}",
        data={"csrf_token": CSRF_TOKEN},
    )

    assert response.status_code == 200
    assert b"One more step" in response.data
    assert consumed == [INVITATION_TOKEN]
    assert len(sent_emails) == 1

    email, confirmation_url, unsubscribe_url = sent_emails[0]

    assert email == TEST_EMAIL
    assert confirmation_url.endswith(
        "/newsletter/confirm/confirmation-token-123456789"
    )
    assert unsubscribe_url.endswith(
        "/newsletter/unsubscribe/unsubscribe-token-123456789"
    )


def test_confirmation_email_failure_restores_invitation_for_retry(
    client,
    monkeypatch,
):
    mock_newsletter_connection(monkeypatch)
    set_join_csrf(client)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://getoffdeals.com")

    restored = []

    monkeypatch.setattr(
        invitation_service,
        "consume_invitation",
        lambda conn, token: TEST_EMAIL,
    )

    monkeypatch.setattr(
        app_module,
        "prepare_subscription",
        lambda conn, email: {
            "status": "pending",
            "confirmation_token": "confirmation-token-123456789",
            "unsubscribe_token": "unsubscribe-token-123456789",
        },
    )

    def fail_confirmation_email(*args):
        raise RuntimeError("Simulated email delivery failure")

    monkeypatch.setattr(
        app_module,
        "send_newsletter_confirmation",
        fail_confirmation_email,
    )

    monkeypatch.setattr(
        invitation_service,
        "restore_invitation",
        lambda conn, token: restored.append(token) or True,
    )

    response = client.post(
        f"/newsletter/join/{INVITATION_TOKEN}",
        data={"csrf_token": CSRF_TOKEN},
    )

    assert response.status_code == 503
    assert b"Confirmation email not sent" in response.data
    assert b"Retry sending confirmation email" in response.data
    assert restored == [INVITATION_TOKEN]

    with client.session_transaction() as session:
        assert session.get("newsletter_join_csrf_token")


import pytest

def test_invalid_public_base_url_restores_invitation(
    client,
    monkeypatch,
):
    mock_newsletter_connection(monkeypatch)
    set_join_csrf(client)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://getoffdeals.com")

    restored = []

    monkeypatch.setattr(
        invitation_service,
        "consume_invitation",
        lambda conn, token: TEST_EMAIL,
    )

    monkeypatch.setattr(
        app_module,
        "prepare_subscription",
        lambda conn, email: {
            "status": "pending",
            "confirmation_token": "confirmation-token-123456789",
            "unsubscribe_token": "unsubscribe-token-123456789",
        },
    )

    monkeypatch.setattr(
        invitation_service,
        "restore_invitation",
        lambda conn, token: restored.append(token) or True,
    )

    monkeypatch.setattr(
        app_module,
        "send_newsletter_confirmation",
        lambda *args: pytest.fail(
            "Confirmation email must not be sent with an invalid URL"
        ),
    )

    response = client.post(
        f"/newsletter/join/{INVITATION_TOKEN}",
        data={"csrf_token": CSRF_TOKEN},
    )

    assert response.status_code == 503
    assert restored == [INVITATION_TOKEN]
