
"""Public unsubscribe confirmation and processing routes."""

import hmac
import secrets

from flask import (
    Blueprint,
    abort,
    current_app,
    render_template,
    request,
    session,
)

from getoffdeals.invitation_service import unsubscribe_contact

unsubscribe_bp = Blueprint("unsubscribe", __name__)


def _valid_token_format(token):
    return isinstance(token, str) and 20 <= len(token) <= 200


@unsubscribe_bp.get("/unsubscribe/<token>")
def unsubscribe_confirmation(token):
    """Show the form without changing the contact's subscription."""
    if not _valid_token_format(token):
        abort(404)

    if not current_app.secret_key:
        current_app.logger.error("Flask secret key is not configured.")
        abort(500)

    csrf_token = secrets.token_urlsafe(32)
    session["unsubscribe_csrf_token"] = csrf_token

    response = current_app.make_response(
        render_template(
            "unsubscribe.html",
            token=token,
            csrf_token=csrf_token,
            result=None,
        )
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@unsubscribe_bp.post("/unsubscribe/<token>")
def unsubscribe_submit(token):
    """Record an unsubscribe only after validating the form token."""
    if not _valid_token_format(token):
        abort(404)

    expected = session.get("unsubscribe_csrf_token")
    submitted = request.form.get("csrf_token", "")

    if (
        not isinstance(expected, str)
        or not isinstance(submitted, str)
        or not hmac.compare_digest(expected, submitted)
    ):
        abort(400, description="Invalid form token. Please reopen the link.")

    # Make the form token single-use for this session.
    session.pop("unsubscribe_csrf_token", None)

    result = unsubscribe_contact(token)

    response = current_app.make_response(
        render_template(
            "unsubscribe.html",
            token=None,
            csrf_token=None,
            result=result,
        )
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
