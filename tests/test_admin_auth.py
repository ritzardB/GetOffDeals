from flask import jsonify

from getoffdeals.admin_auth import admin_required, is_admin_session


def _register_test_route(app):
    endpoint = "test_admin_auth.protected_route"

    if endpoint not in app.view_functions:
        protected_view = admin_required(lambda: jsonify(ok=True))
        app.add_url_rule(
            "/test-admin-access",
            endpoint=endpoint,
            view_func=protected_view,
            methods=["GET"],
        )


def test_anonymous_session_is_not_admin(client, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "getoffdeals@gmail.com")
    _register_test_route(client.application)

    with client.session_transaction() as sess:
        sess.clear()

    with client.application.test_request_context("/"):
        assert is_admin_session() is False

    response = client.get("/test-admin-access")
    assert response.status_code == 401


def test_admin_email_matches_case_insensitively(client, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "getoffdeals@gmail.com")
    _register_test_route(client.application)

    with client.session_transaction() as sess:
        sess["user_id"] = "admin-user"
        sess["email"] = "GetOffDeals@Gmail.com"

    response = client.get("/test-admin-access")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


def test_regular_user_is_forbidden(client, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "getoffdeals@gmail.com")
    _register_test_route(client.application)

    with client.session_transaction() as sess:
        sess["user_id"] = "regular-user"
        sess["email"] = "traveler@example.com"

    response = client.get("/test-admin-access")
    assert response.status_code == 403


def test_missing_admin_configuration_denies_access(client, monkeypatch):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    _register_test_route(client.application)

    with client.session_transaction() as sess:
        sess["user_id"] = "admin-user"
        sess["email"] = "getoffdeals@gmail.com"

    response = client.get("/test-admin-access")
    assert response.status_code == 403
