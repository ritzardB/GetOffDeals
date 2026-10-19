
import pytest

import app as app_module


@pytest.fixture()
def client():
    app_module.app.config.update(
        TESTING=True,
        SECRET_KEY="test-only-secret",
    )

    with app_module.app.test_client() as client:
        yield client


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/flights",
        "/about",
        "/contact",
        "/privacy",
        "/terms",
        "/affiliate-disclosure",
    ],
)
def test_existing_pages_load(client, path):
    response = client.get(path)
    assert response.status_code == 200


def test_home_has_security_headers(client):
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert (
        response.headers["Referrer-Policy"]
        == "strict-origin-when-cross-origin"
    )


def test_search_without_amadeus_credentials(client, monkeypatch):
    monkeypatch.delenv("AMA_API_KEY", raising=False)
    monkeypatch.delenv("AMA_API_SECRET", raising=False)

    response = client.get("/api/search")
    assert response.status_code in (400, 422, 503)



def test_database_connection_returns_database_name():
    from getoffdeals.database import check_connection

    assert check_connection() == "postgres"


def test_database_connection_has_expected_tables():
    from getoffdeals.database import get_connection

    expected = {
        "users",
        "flight_alerts",
        "price_checks",
        "alert_notifications",
    }

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
            actual = {row["table_name"] for row in cursor.fetchall()}

    assert expected.issubset(actual)


def test_session_cookie_security_settings(client):
    assert app_module.app.config["SECRET_KEY"]
    assert app_module.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app_module.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
