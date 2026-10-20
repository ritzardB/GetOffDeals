import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from flask import Flask, session

import getoffdeals.postgres_sessions as postgres_sessions


def make_app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-only-secret",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    app.session_interface = postgres_sessions.PostgresSessionInterface()

    @app.get("/set")
    def set_session():
        session["user_id"] = "test-user-123"
        return "saved"

    @app.get("/read")
    def read_session():
        return session.get("user_id", "missing")

    return app


def test_session_is_saved_server_side(monkeypatch):
    app = make_app()
    conn = MagicMock()
    cursor = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cursor

    monkeypatch.setattr(
        postgres_sessions, "get_connection", lambda: conn
    )

    with app.test_client() as client:
        response = client.get("/set")

    assert response.status_code == 200
    cookie = response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" in cookie
    assert "test-user-123" not in cookie
    cursor.execute.assert_called_once()

    sql, params = cursor.execute.call_args.args
    assert "INSERT INTO public.web_sessions" in sql
    assert len(params[0]) >= 32
    assert json.loads(bytes(params[1]).decode("utf-8")) == {
        "user_id": "test-user-123"
    }
    assert isinstance(params[2], datetime)
    assert params[2] > datetime.now(timezone.utc)




def test_session_is_restored_from_postgres(monkeypatch):
    app = make_app()
    conn = MagicMock()
    cursor = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cursor

    saved_data = json.dumps({"user_id": "test-user-123"}).encode("utf-8")
    cursor.fetchone.return_value = {"session_data": saved_data}

    monkeypatch.setattr(
        postgres_sessions, "get_connection", lambda: conn
    )

    session_id = "a" * 43

    with app.test_client() as client:
        client.set_cookie("session", session_id)
        response = client.get("/read")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "test-user-123"
    assert cursor.execute.call_count == 1

    select_call = cursor.execute.call_args_list[0]
    select_sql, select_params = select_call.args
    assert "SELECT session_data" in select_sql
    assert select_params == (session_id,)

def test_reading_unchanged_session_does_not_write(monkeypatch):
    app = make_app()
    conn = MagicMock()
    cursor = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cursor

    cursor.fetchone.return_value = {
        "session_data": json.dumps({"user_id": "test-user-123"}).encode("utf-8")
    }

    monkeypatch.setattr(
        postgres_sessions, "get_connection", lambda: conn
    )

    with app.test_client() as client:
        client.set_cookie("session", "a" * 43)
        response = client.get("/read")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "test-user-123"

    assert cursor.execute.call_count == 1
    sql, params = cursor.execute.call_args.args
    assert "SELECT session_data" in sql
    assert params == ("a" * 43,)

def test_regenerate_session_id_rotates_and_deletes_old_session(monkeypatch):
    old_session_id = "old-session-id"
    test_session = postgres_sessions.ServerSideSession(
        {"user_id": "test-user-123"},
        sid=old_session_id,
    )

    conn = MagicMock()
    conn.__enter__.return_value = conn
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    monkeypatch.setattr(
        postgres_sessions, "get_connection", lambda: conn
    )

    postgres_sessions.regenerate_session_id(test_session)

    assert test_session.sid != old_session_id
    assert test_session.modified is True

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args.args
    assert "DELETE FROM public.web_sessions" in sql
    assert params == (old_session_id,)


def test_regenerate_session_id_does_not_rotate_if_delete_fails(monkeypatch):
    old_session_id = "old-session-id"
    test_session = postgres_sessions.ServerSideSession(
        {"user_id": "test-user-123"},
        sid=old_session_id,
    )

    def fail_connection():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        postgres_sessions, "get_connection", fail_connection
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        postgres_sessions.regenerate_session_id(test_session)

    assert test_session.sid == old_session_id
    assert test_session.modified is False


def test_logout_clears_server_session_and_cookie(monkeypatch):
    app = make_app()

    conn = MagicMock()
    cursor = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cursor

    monkeypatch.setattr(
        postgres_sessions, "get_connection", lambda: conn
    )

    @app.get("/logout-test")
    def logout_test():
        session.clear()
        return "logged out"

    with app.test_client() as client:
        client.set_cookie("session", "a" * 43)

        # Simulate a session that already exists in PostgreSQL.
        # The mock returns no row, so the test must first create a session.
        with client.session_transaction() as sess:
            sess["user_id"] = "test-user-123"

        response = client.get("/logout-test")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "logged out"
    assert any(
        "DELETE FROM public.web_sessions" in str(call.args[0])
        for call in cursor.execute.call_args_list
    )
    assert "session=" in response.headers.get("Set-Cookie", "")
    assert "Max-Age=0" in response.headers.get("Set-Cookie", "")




def test_open_session_propagates_database_failure(monkeypatch):
    app = make_app()
    session_interface = postgres_sessions.PostgresSessionInterface()

    def fail_connection():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        postgres_sessions, "get_connection", fail_connection
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        with app.test_request_context(
            "/",
            headers={"Cookie": "session=existing-session-id"},
        ):
            pass


def test_save_session_propagates_database_failure(monkeypatch):
    app = make_app()
    session_interface = postgres_sessions.PostgresSessionInterface()
    test_session = postgres_sessions.ServerSideSession(
        {"user_id": "test-user-123"},
        sid="test-session-id",
    )
    test_session.modified = True

    response = app.response_class()

    def fail_connection():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        postgres_sessions, "get_connection", fail_connection
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        session_interface.save_session(app, test_session, response)

def test_logout_expires_cookie_even_if_database_delete_fails(monkeypatch):
    app = make_app()
    session_interface = postgres_sessions.PostgresSessionInterface()

    test_session = postgres_sessions.ServerSideSession(
        {"user_id": "test-user-123"},
        sid="test-session-id",
    )
    test_session.clear()

    response = app.response_class()

    def fail_connection():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        postgres_sessions, "get_connection", fail_connection
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        session_interface.save_session(app, test_session, response)

    cookie = response.headers.get("Set-Cookie", "")
    assert "session=" in cookie
    assert "Max-Age=0" in cookie