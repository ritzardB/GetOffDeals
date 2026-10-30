"""Admin authorization helpers for GetOffDeals."""

import os
from functools import wraps

from flask import jsonify, session


def is_admin_session():
    """Return True when the authenticated session email is allowlisted."""
    user_id = session.get("user_id")
    email = session.get("email")

    if not isinstance(user_id, str) or not user_id.strip():
        return False

    if not isinstance(email, str) or not email.strip():
        return False

    configured = os.getenv("ADMIN_EMAILS", "")
    admin_emails = {
        item.strip().casefold()
        for item in configured.split(",")
        if item.strip()
    }

    return email.strip().casefold() in admin_emails


def admin_required(view):
    """Require an authenticated, allowlisted administrator."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify(error="Authentication required."), 401

        if not is_admin_session():
            return jsonify(error="Administrator access required."), 403

        return view(*args, **kwargs)

    return wrapped
