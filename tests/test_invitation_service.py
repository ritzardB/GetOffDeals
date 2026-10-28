
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

import getoffdeals.invitation_service as service


@pytest.fixture
def mock_db(monkeypatch):
    conn = MagicMock()
    cursor = MagicMock()

    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False

    monkeypatch.setattr(service, "get_connection", lambda: conn)

    return conn, cursor


def test_record_consented_contact_requires_valid_email():
    with pytest.raises(ValueError, match="valid email"):
        service.record_consented_contact(
            "not-an-email",
            "signup form",
            "consent record 123",
            datetime.now(timezone.utc),
        )


def test_record_consented_contact_requires_evidence():
    with pytest.raises(ValueError, match="Consent evidence"):
        service.record_consented_contact(
            "user@example.com",
            "signup form",
            " ",
            datetime.now(timezone.utc),
        )


def test_record_consented_contact_uses_parameterized_upsert(mock_db):
    _, cursor = mock_db
    cursor.fetchone.return_value = {
        "id": "contact-id",
        "email_normalized": "user@example.com",
        "consent_status": "consented",
    }

    result = service.record_consented_contact(
        "User@example.com",
        "signup form",
        "consent record 123",
        datetime.now(timezone.utc),
    )

    assert result["consent_status"] == "consented"
    query, params = cursor.execute.call_args.args

    assert "ON CONFLICT (email_normalized)" in query
    assert "consent_status <> 'revoked'" in query
    assert "user@example.com" in params


def test_create_campaign_rejects_invalid_user_id():
    with pytest.raises(ValueError, match="administrator user ID"):
        service.create_campaign("Test campaign", "not-a-uuid")


def test_create_campaign_rejects_empty_name():
    with pytest.raises(ValueError, match="Campaign name"):
        service.create_campaign(" ", "123e4567-e89b-12d3-a456-426614174000")


def test_list_eligible_contacts_returns_empty_for_invalid_ids(mock_db):
    _, cursor = mock_db

    result = service.list_eligible_contacts(["not-a-uuid"])

    assert result == []
    cursor.execute.assert_not_called()


def test_list_eligible_contacts_excludes_unsubscribed(mock_db):
    _, cursor = mock_db
    cursor.fetchall.return_value = []

    result = service.list_eligible_contacts()

    assert result == []
    query = cursor.execute.call_args.args[0]

    assert "consent_status = 'consented'" in query
    assert "NOT EXISTS" in query
    assert "invitation_unsubscribes" in query


def test_create_unsubscribe_token_rejects_invalid_contact_id():
    with pytest.raises(ValueError, match="Invalid contact ID"):
        service.create_unsubscribe_token("invalid-id", "a" * 64)


def test_create_unsubscribe_token_requires_sha256_length():
    with pytest.raises(ValueError, match="token hash"):
        service.create_unsubscribe_token(
            "123e4567-e89b-12d3-a456-426614174000",
            "too-short",
        )
