"""Authenticated PostgreSQL-backed price-alert API."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import Blueprint, jsonify, request, session

from getoffdeals.database import get_connection

price_alerts_bp = Blueprint("price_alerts", __name__)

CABIN_CLASSES = {
    "ECONOMY",
    "PREMIUM_ECONOMY",
    "BUSINESS",
    "FIRST",
}
CURRENCIES = {"AED", "USD", "PHP"}
AIRPORT_CODE = re.compile(r"^[A-Z]{3}$")


def _current_user_id():
    """Return a canonical UUID for the authenticated session, or None."""
    raw_id = session.get("user_id")
    if not raw_id:
        return None
    try:
        return str(UUID(str(raw_id)))
    except (ValueError, TypeError, AttributeError):
        return None


def _alert_dict(row):
    """Convert a database row to a JSON-friendly object."""
    result = dict(row)
    for field in ("id", "user_id"):
        if result.get(field) is not None:
            result[field] = str(result[field])
    for field in ("departure_date", "return_date"):
        if result.get(field) is not None:
            result[field] = result[field].isoformat()
    for field in ("created_at", "updated_at", "last_checked_at"):
        if result.get(field) is not None:
            result[field] = result[field].isoformat()
    if result.get("target_price") is not None:
        result["target_price"] = float(result["target_price"])
    return result


def _validate_create(body):
    """Validate a create request. Return (values, error_message)."""
    if not isinstance(body, dict):
        return None, "Send a JSON object."

    origin = body.get("origin")
    destination = body.get("destination")
    if not isinstance(origin, str) or not isinstance(destination, str):
        return None, "Origin and destination airport codes are required."

    origin = origin.strip().upper()
    destination = destination.strip().upper()
    if not AIRPORT_CODE.fullmatch(origin) or not AIRPORT_CODE.fullmatch(destination):
        return None, "Airport codes must be three letters."
    if origin == destination:
        return None, "Origin and destination must be different."

    try:
        departure = date.fromisoformat(body.get("departure_date", ""))
    except (TypeError, ValueError):
        return None, "Enter a valid departure_date in YYYY-MM-DD format."

    return_raw = body.get("return_date")
    if return_raw in (None, ""):
        return_date = None
    else:
        try:
            return_date = date.fromisoformat(return_raw)
        except (TypeError, ValueError):
            return None, "Enter a valid return_date in YYYY-MM-DD format."
        if return_date <= departure:
            return None, "Return date must be after departure date."

    try:
        adults = int(body.get("adults", 1))
    except (ValueError, TypeError):
        return None, "Adults must be a whole number."
    if not 1 <= adults <= 9:
        return None, "Adults must be between 1 and 9."

    cabin_class = body.get("cabin_class", "ECONOMY")
    if not isinstance(cabin_class, str):
        return None, "Invalid cabin class."
    cabin_class = cabin_class.strip().upper()
    if cabin_class not in CABIN_CLASSES:
        return None, "Unsupported cabin class."

    currency = body.get("currency", "AED")
    if not isinstance(currency, str):
        return None, "Unsupported currency."
    currency = currency.strip().upper()
    if currency not in CURRENCIES:
        return None, "Currency must be AED, USD, or PHP."

    try:
        target_price = Decimal(str(body.get("target_price", "")))
    except (InvalidOperation, ValueError, TypeError):
        return None, "Enter a valid target price."
    if not target_price.is_finite() or target_price <= 0:
        return None, "Target price must be greater than zero."
    if target_price > Decimal("999999999999"):
        return None, "Target price is too large."

    return {
        "origin": origin,
        "destination": destination,
        "departure_date": departure,
        "return_date": return_date,
        "adults": adults,
        "cabin_class": cabin_class,
        "target_price": target_price,
        "currency": currency,
    }, None


@price_alerts_bp.get("/api/price-alerts")
def list_price_alerts():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(error="Please sign in again."), 401

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, origin, destination, departure_date,
                       return_date, adults, cabin_class, target_price,
                       currency, is_active, last_checked_at, created_at,
                       updated_at
                FROM public.flight_alerts
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            alerts = [_alert_dict(row) for row in cur.fetchall()]

    return jsonify(alerts=alerts), 200


@price_alerts_bp.post("/api/price-alerts")
def create_price_alert():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(error="Please sign in again."), 401
    if not request.is_json:
        return jsonify(error="Send a JSON request."), 400

    values, error = _validate_create(request.get_json(silent=True))
    if error:
        return jsonify(error=error), 400

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.flight_alerts (
                    user_id, origin, destination, departure_date,
                    return_date, adults, cabin_class, target_price, currency
                )
                VALUES (
                    %(user_id)s, %(origin)s, %(destination)s,
                    %(departure_date)s, %(return_date)s, %(adults)s,
                    %(cabin_class)s, %(target_price)s, %(currency)s
                )
                RETURNING id, user_id, origin, destination, departure_date,
                          return_date, adults, cabin_class, target_price,
                          currency, is_active, last_checked_at, created_at,
                          updated_at
                """,
                {"user_id": user_id, **values},
            )
            alert = _alert_dict(cur.fetchone())

    return jsonify(alert=alert), 201


@price_alerts_bp.patch("/api/price-alerts/<alert_id>")
def update_price_alert(alert_id):
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(error="Please sign in again."), 401

    try:
        alert_id = str(UUID(alert_id))
    except (ValueError, TypeError, AttributeError):
        return jsonify(error="Invalid alert ID."), 400

    if not request.is_json:
        return jsonify(error="Send a JSON request."), 400
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not body:
        return jsonify(error="Send a non-empty JSON object."), 400

    allowed = {"is_active", "target_price"}
    if set(body) - allowed:
        return jsonify(error="Only is_active and target_price can be updated."), 400

    assignments = []
    params = {"alert_id": alert_id, "user_id": user_id}

    if "is_active" in body:
        if not isinstance(body["is_active"], bool):
            return jsonify(error="is_active must be true or false."), 400
        assignments.append("is_active = %(is_active)s")
        params["is_active"] = body["is_active"]

    if "target_price" in body:
        try:
            price = Decimal(str(body["target_price"]))
        except (InvalidOperation, ValueError, TypeError):
            return jsonify(error="Enter a valid target price."), 400
        if not price.is_finite() or price <= 0 or price > Decimal("999999999999"):
            return jsonify(error="Target price must be greater than zero."), 400
        assignments.append("target_price = %(target_price)s")
        params["target_price"] = price

    assignments.append("updated_at = NOW()")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE public.flight_alerts
                SET {", ".join(assignments)}
                WHERE id = %(alert_id)s AND user_id = %(user_id)s
                RETURNING id, user_id, origin, destination, departure_date,
                          return_date, adults, cabin_class, target_price,
                          currency, is_active, last_checked_at, created_at,
                          updated_at
                """,
                params,
            )
            row = cur.fetchone()

    if row is None:
        return jsonify(error="Price alert not found."), 404
    return jsonify(alert=_alert_dict(row)), 200


@price_alerts_bp.delete("/api/price-alerts/<alert_id>")
def delete_price_alert(alert_id):
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(error="Please sign in again."), 401

    try:
        alert_id = str(UUID(alert_id))
    except (ValueError, TypeError, AttributeError):
        return jsonify(error="Invalid alert ID."), 400

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM public.flight_alerts
                WHERE id = %s AND user_id = %s
                RETURNING id
                """,
                (alert_id, user_id),
            )
            deleted = cur.fetchone()

    if deleted is None:
        return jsonify(error="Price alert not found."), 404
    return jsonify(message="Price alert deleted."), 200
