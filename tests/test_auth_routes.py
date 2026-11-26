
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module


def test_register_rejects_non_json(client):
    response = client.post("/auth/register", data="not json")
    assert response.status_code == 400


def test_register_rejects_invalid_email(client):
    response = client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "StrongPass123!"},
    )
    assert response.status_code == 400


def test_register_rejects_short_password(client):
    response = client.post(
        "/auth/register",
        json={"email": "traveler@example.com", "password": "short"},
    )
    assert response.status_code == 400


def test_register_calls_supabase_and_does_not_log_in(client, monkeypatch):
    def fake_supabase_request(endpoint, payload=None, method="POST"):
        assert endpoint == "signup"
        assert payload == {
            "email": "traveler@example.com",
            "password": "StrongPass123!",
            "data": {
                "first_name": "Alex",
                "last_name": "Traveler",
            },
        }
        return {"user": {"id": "test-user"}}, None

    monkeypatch.setattr(
        app_module, "supabase_auth_request", fake_supabase_request
    )

    response = client.post(
        "/auth/register",
        json={
            "first_name": "Alex",
            "last_name": "Traveler",
            "email": " Traveler@Example.com ",
            "password": "StrongPass123!",
        },
    )

    assert response.status_code == 202
    assert "verification link" in response.get_json()["message"]
    assert "Set-Cookie" not in response.headers


def test_login_rejects_non_json(client):
    response = client.post("/auth/login", data="not json")
    assert response.status_code == 400


def test_login_rejects_unverified_email(client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "supabase_auth_request",
        lambda *args, **kwargs: (
            {
                "user": {
                    "id": "test-user",
                    "email": "traveler@example.com",
                }
            },
            None,
        ),
    )

    response = client.post(
        "/auth/login",
        json={
            "email": "traveler@example.com",
            "password": "StrongPass123!",
        },
    )

    assert response.status_code == 403


def test_login_success_rotates_session_and_returns_user(
    client, monkeypatch
):
    def fake_supabase_request(endpoint, payload=None, method="POST"):
        assert endpoint == "token?grant_type=password"
        assert payload == {
            "email": "traveler@example.com",
            "password": "StrongPass123!",
        }
        return {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "user": {
                "id": "test-user",
                "email": "traveler@example.com",
                "email_confirmed_at": "2026-10-01T10:00:00Z",
            },
        }, None

    def fake_sync_authenticated_user(
        user_id, email, first_name="", last_name=""
    ):
        return user_id

    def fake_regenerate_session_id(session):
        session.sid = "rotated-test-session-id"
        session.modified = True

    monkeypatch.setattr(
        app_module, "supabase_auth_request",
        fake_supabase_request
    )

    monkeypatch.setattr(
        app_module, "sync_authenticated_user",
        fake_sync_authenticated_user,
    )

    monkeypatch.setattr(
        app_module, "regenerate_session_id",
        fake_regenerate_session_id
    )

    response = client.post(
        "/auth/login",
        json={
            "email": " Traveler@Example.com ",
            "password": "StrongPass123!",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["user"] == {
        "id": "test-user",
        "email": "traveler@example.com",
    }
    assert "test-access-token" not in response.get_data(as_text=True)
    assert "test-refresh-token" not in response.get_data(as_text=True)

    with client.session_transaction() as flask_session:
        assert flask_session["user_id"] == "test-user"
        assert flask_session["email"] == "traveler@example.com"

def test_logout_clears_authenticated_session(client):
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = "test-user"
        flask_session["email"] = "traveler@example.com"

    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert response.get_json()["message"] == "Logged out successfully."
    assert "session=" in response.headers.get("Set-Cookie", "")
    assert "Max-Age=0" in response.headers.get("Set-Cookie", "")

    with client.session_transaction() as flask_session:
        assert "user_id" not in flask_session
        assert "email" not in flask_session


from unittest.mock import MagicMock


def test_sync_authenticated_user_updates_user_and_queues_welcome_email(
    monkeypatch,
):
    connection = MagicMock()
    cursor = MagicMock()

    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor

    monkeypatch.setattr(
        app_module,
        "get_connection",
        lambda: connection,
    )

    user_id = "12345678-1234-5678-1234-567812345678"

    result = app_module.sync_authenticated_user(
        user_id,
        " Traveler@Example.com ",
        " Alex ",
        " Traveler ",
    )

    assert result == user_id
    connection.cursor.assert_called_once()

    assert cursor.execute.call_count == 2

    user_query, user_params = cursor.execute.call_args_list[0].args
    welcome_query, welcome_params = cursor.execute.call_args_list[1].args

    assert "INSERT INTO public.users" in user_query
    assert "ON CONFLICT (id) DO UPDATE" in user_query

    assert user_params == (
        user_id,
        "traveler@example.com",
        "Alex",
        "Traveler",
    )

    assert "INSERT INTO public.welcome_email_outbox" in welcome_query
    assert "ON CONFLICT (user_id) DO NOTHING" in welcome_query

    assert welcome_params == (
        user_id,
        "traveler@example.com",
        "Alex",
    )


def test_sync_authenticated_user_rejects_invalid_uuid(monkeypatch):
    connection_called = False

    def fake_get_connection():
        nonlocal connection_called
        connection_called = True
        raise AssertionError("Database should not be accessed.")

    monkeypatch.setattr(
        app_module,
        "get_connection",
        fake_get_connection,
    )

    try:
        app_module.sync_authenticated_user(
            "invalid-user-id",
            "traveler@example.com",
        )
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "valid UUID" in str(exc)

    assert connection_called is False


def test_sync_authenticated_user_rejects_missing_email(monkeypatch):
    connection_called = False

    def fake_get_connection():
        nonlocal connection_called
        connection_called = True
        raise AssertionError("Database should not be accessed.")

    monkeypatch.setattr(
        app_module,
        "get_connection",
        fake_get_connection,
    )

    try:
        app_module.sync_authenticated_user(
            "12345678-1234-5678-1234-567812345678",
            "   ",
        )
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "email is required" in str(exc)

    assert connection_called is False
