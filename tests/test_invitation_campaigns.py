
from unittest.mock import MagicMock

import pytest

import getoffdeals.invitation_service as service


def test_add_campaign_recipients_rejects_invalid_campaign_id():
    with pytest.raises(ValueError, match="Invalid campaign ID"):
        service.add_campaign_recipients("invalid", [])


def test_get_campaign_summary_rejects_invalid_campaign_id():
    with pytest.raises(ValueError, match="Invalid campaign ID"):
        service.get_campaign_summary("invalid")


def test_get_campaign_summary_returns_none_for_missing_campaign(monkeypatch):
    conn = MagicMock()
    cursor = MagicMock()

    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    cursor.fetchone.return_value = None

    monkeypatch.setattr(service, "get_connection", lambda: conn)

    assert service.get_campaign_summary(
        "123e4567-e89b-12d3-a456-426614174000"
    ) is None

    assert cursor.execute.call_count == 1
