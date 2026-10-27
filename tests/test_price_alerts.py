from datetime import date
from decimal import Decimal
from uuid import uuid4

import app as app_module
import getoffdeals.price_alerts as alerts_module


def valid_alert_payload():
    return {
        "origin": "AUH",
        "destination": "MNL",
        "departure_date": "2027-06-15",
        "return_date": "2027-06-29",
        "adults": 1,
        "cabin_class": "ECONOMY",
        "target_price": 1800,
        "currency": "AED",
    }


def test_list_price_alerts_requires_login(client):
    response = client.get("/api/price-alerts")

    assert response.status_code == 401


def test_create_price_alert_requires_login(client):
    response = client.post(
        "/api/price-alerts",
        json=valid_alert_payload(),
    )

    assert response.status_code == 401


def test_create_price_alert_rejects_invalid_airport_codes(client):
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = str(uuid4())

    payload = valid_alert_payload()
    payload["origin"] = "AB"

    response = client.post("/api/price-alerts", json=payload)

    assert response.status_code == 400
    assert "airport codes" in response.get_json()["error"].lower()


def test_create_price_alert_rejects_same_origin_and_destination(client):
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = str(uuid4())

    payload = valid_alert_payload()
    payload["destination"] = payload["origin"]

    response = client.post("/api/price-alerts", json=payload)

    assert response.status_code == 400
    assert "different" in response.get_json()["error"].lower()


def test_create_price_alert_rejects_return_date_before_departure(client):
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = str(uuid4())

    payload = valid_alert_payload()
    payload["return_date"] = "2027-06-10"

    response = client.post("/api/price-alerts", json=payload)

    assert response.status_code == 400
    assert "return date" in response.get_json()["error"].lower()


def test_create_price_alert_rejects_non_positive_target_price(client):
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = str(uuid4())

    payload = valid_alert_payload()
    payload["target_price"] = 0

    response = client.post("/api/price-alerts", json=payload)

    assert response.status_code == 400
    assert "target price" in response.get_json()["error"].lower()


def test_update_price_alert_rejects_invalid_alert_id(client):
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = str(uuid4())

    response = client.patch(
        "/api/price-alerts/not-a-uuid",
        json={"is_active": False},
    )

    assert response.status_code == 400


def test_delete_price_alert_rejects_invalid_alert_id(client):
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = str(uuid4())

    response = client.delete("/api/price-alerts/not-a-uuid")

    assert response.status_code == 400


def test_create_price_alert_inserts_for_authenticated_user(
    client, monkeypatch
):
    user_id = str(uuid4())
    alert_id = str(uuid4())
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            captured["query"] = query
            captured["params"] = params

        def fetchone(self):
            params = captured["params"]
            return {
                "id": alert_id,
                "user_id": params["user_id"],
                "origin": params["origin"],
                "destination": params["destination"],
                "departure_date": params["departure_date"],
                "return_date": params["return_date"],
                "adults": params["adults"],
                "cabin_class": params["cabin_class"],
                "target_price": params["target_price"],
                "currency": params["currency"],
                "is_active": True,
                "last_checked_at": None,
                "created_at": None,
                "updated_at": None,
            }

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        alerts_module, "get_connection", lambda: FakeConnection()
    )

    with client.session_transaction() as flask_session:
        flask_session["user_id"] = user_id

    response = client.post(
        "/api/price-alerts",
        json=valid_alert_payload(),
    )

    assert response.status_code == 201
    assert response.get_json()["alert"]["id"] == alert_id
    assert captured["params"]["user_id"] == user_id
    assert captured["params"]["origin"] == "AUH"
    assert captured["params"]["destination"] == "MNL"
    assert Decimal(str(captured["params"]["target_price"])) == Decimal("1800")
    assert "INSERT INTO public.flight_alerts" in captured["query"]


def test_list_price_alerts_scopes_query_to_current_user(
    client, monkeypatch
):
    user_id = str(uuid4())
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            captured["query"] = query
            captured["params"] = params

        def fetchall(self):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        alerts_module, "get_connection", lambda: FakeConnection()
    )

    with client.session_transaction() as flask_session:
        flask_session["user_id"] = user_id

    response = client.get("/api/price-alerts")

    assert response.status_code == 200
    assert response.get_json()["alerts"] == []
    assert captured["params"] == (user_id,)
    assert "WHERE user_id = %s" in captured["query"]



def test_update_price_alert_only_targets_current_users_alert(
    client, monkeypatch
):
    user_id = str(uuid4())
    alert_id = str(uuid4())
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            captured["query"] = query
            captured["params"] = params

        def fetchone(self):
            # Simulate no alert owned by this user with that ID.
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        alerts_module, "get_connection", lambda: FakeConnection()
    )

    with client.session_transaction() as flask_session:
        flask_session["user_id"] = user_id

    response = client.patch(
        f"/api/price-alerts/{alert_id}",
        json={"is_active": False},
    )

    assert response.status_code == 404
    assert captured["params"]["user_id"] == user_id
    assert captured["params"]["alert_id"] == alert_id
    assert "WHERE id = %(alert_id)s AND user_id = %(user_id)s" in captured["query"]


def test_delete_price_alert_only_targets_current_users_alert(
    client, monkeypatch
):
    user_id = str(uuid4())
    alert_id = str(uuid4())
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            captured["query"] = query
            captured["params"] = params

        def fetchone(self):
            # Simulate no alert owned by this user with that ID.
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        alerts_module, "get_connection", lambda: FakeConnection()
    )

    with client.session_transaction() as flask_session:
        flask_session["user_id"] = user_id

    response = client.delete(f"/api/price-alerts/{alert_id}")

    assert response.status_code == 404
    assert captured["params"] == (alert_id, user_id)
    assert "WHERE id = %s AND user_id = %s" in captured["query"]
