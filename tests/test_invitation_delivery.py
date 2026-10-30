
from unittest.mock import MagicMock

import pytest

import getoffdeals.invitation_service as service


def test_start_campaign_rejects_invalid_id():
    with pytest.raises(ValueError, match="Invalid campaign ID"):
        service.start_campaign("invalid")


def test_claim_next_message_rejects_invalid_id():
    with pytest.raises(ValueError, match="Invalid campaign ID"):
        service.claim_next_campaign_message("invalid")


def test_mark_message_suppressed_rejects_invalid_id():
    with pytest.raises(ValueError, match="Invalid message ID"):
        service.mark_message_suppressed("invalid")


def test_finish_campaign_rejects_invalid_id():
    with pytest.raises(ValueError, match="Invalid campaign ID"):
        service.finish_campaign_if_complete("invalid")


def test_claim_next_message_returns_none_when_no_pending_messages(
    monkeypatch,
):
    conn = MagicMock()
    cursor = MagicMock()

    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    cursor.fetchone.return_value = None

    monkeypatch.setattr(service, "get_connection", lambda: conn)

    result = service.claim_next_campaign_message(
        "123e4567-e89b-12d3-a456-426614174000"
    )

    assert result is None
    assert cursor.execute.call_count == 1
