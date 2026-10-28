from pathlib import Path

import pytest

from flask import Flask

import getoffdeals.unsubscribe_routes as routes


@pytest.fixture
def app(monkeypatch):
    application = Flask(
        __name__,
        template_folder=str(
            Path(__file__).resolve().parents[1] / "templates"
        ),
    )
    application.config.update(
        TESTING=True,
        SECRET_KEY="test-secret-for-csrf",
    )
    application.register_blueprint(routes.unsubscribe_bp)

    monkeypatch.setattr(
        routes,
        "unsubscribe_contact",
        lambda token: True,
    )

    return application


def test_get_displays_confirmation_without_unsubscribing(app, monkeypatch):
    called = []
    monkeypatch.setattr(
        routes,
        "unsubscribe_contact",
        lambda token: called.append(token),
    )

    client = app.test_client()
    response = client.get("/unsubscribe/" + "a" * 32)

    assert response.status_code == 200
    assert b"Unsubscribe me" in response.data
    assert called == []
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_post_without_csrf_token_is_rejected(app):
    response = app.test_client().post(
        "/unsubscribe/" + "a" * 32,
        data={},
    )

    assert response.status_code == 400


def test_post_with_csrf_token_unsubscribes(app):
    client = app.test_client()

    client.get("/unsubscribe/" + "a" * 32)

    with client.session_transaction() as sess:
        csrf_token = sess["unsubscribe_csrf_token"]

    response = client.post(
        "/unsubscribe/" + "a" * 32,
        data={"csrf_token": csrf_token},
    )

    assert response.status_code == 200
    assert b"unsubscribed" in response.data.lower()

    with client.session_transaction() as sess:
        assert "unsubscribe_csrf_token" not in sess


def test_post_with_wrong_csrf_token_is_rejected(app, monkeypatch):
    called = []
    monkeypatch.setattr(
        routes,
        "unsubscribe_contact",
        lambda token: called.append(token),
    )

    client = app.test_client()
    client.get("/unsubscribe/" + "a" * 32)

    response = client.post(
        "/unsubscribe/" + "a" * 32,
        data={"csrf_token": "wrong-token"},
    )

    assert response.status_code == 400
    assert called == []
