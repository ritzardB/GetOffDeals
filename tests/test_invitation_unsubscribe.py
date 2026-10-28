
from unittest.mock import MagicMock

import getoffdeals.invitation_service as service


def test_unsubscribe_rejects_empty_token(monkeypatch):
    def unexpected_connection():
        raise AssertionError("Database must not be accessed")

    monkeypatch.setattr(service, "get_connection", unexpected_connection)

    assert service.unsubscribe_contact("") is False


def test_unsubscribe_rejects_oversized_token(monkeypatch):
    def unexpected_connection():
        raise AssertionError("Database must not be accessed")

    monkeypatch.setattr(service, "get_connection", unexpected_connection)

    assert service.unsubscribe_contact("x" * 201) is False


def test_unsubscribe_returns_false_for_invalid_token(monkeypatch):
    conn = MagicMock()
    cursor = MagicMock()

    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    cursor.fetchone.return_value = None

    monkeypatch.setattr(service, "get_connection", lambda: conn)

    assert service.unsubscribe_contact("invalid-token") is False
    assert cursor.execute.call_count == 1

    query, params = cursor.execute.call_args.args
    assert "token_hash = %s" in query
    assert params[0] != "invalid-token"
