
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

    def fake_regenerate_session_id(session):
        session.sid = "rotated-test-session-id"
        session.modified = True

    monkeypatch.setattr(
        app_module, "supabase_auth_request", fake_supabase_request
    )
    monkeypatch.setattr(
        app_module, "regenerate_session_id", fake_regenerate_session_id
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
