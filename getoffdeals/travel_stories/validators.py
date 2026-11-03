
"""Input validation and CSRF helpers for Travel Stories."""

import hmac
import re
import secrets
from uuid import UUID

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def current_user_id(session):
    """Return a canonical UUID from the authenticated session."""
    raw_id = session.get("user_id")

    if not raw_id:
        return None

    try:
        return str(UUID(str(raw_id)))
    except (ValueError, TypeError, AttributeError):
        return None


def generate_csrf_token(session):
    """Create or reuse a CSRF token for the current session."""
    token = session.get("travel_stories_csrf_token")

    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        session["travel_stories_csrf_token"] = token

    return token


def validate_csrf_token(session, submitted_token):
    """Compare the submitted CSRF token securely."""
    expected = session.get("travel_stories_csrf_token")

    return (
        isinstance(expected, str)
        and isinstance(submitted_token, str)
        and bool(submitted_token)
        and hmac.compare_digest(expected, submitted_token)
    )


def validate_story(payload):
    """
    Validate story fields.

    Return (cleaned_values, error_message).
    """
    if not isinstance(payload, dict):
        return None, "Send a valid story object."

    title = payload.get("title")
    destination = payload.get("destination")
    country = payload.get("country")
    content = payload.get("content")

    fields = {
        "title": (title, 5, 180, "Story title"),
        "destination": (destination, 2, 150, "Destination"),
        "country": (country, 2, 100, "Country"),
        "content": (content, 50, 50000, "Story content"),
    }

    cleaned = {}

    for key, (value, minimum, maximum, label) in fields.items():
        if not isinstance(value, str):
            return None, f"{label} is required."

        value = value.strip()

        if not minimum <= len(value) <= maximum:
            return None, (
                f"{label} must contain between "
                f"{minimum} and {maximum} characters."
            )

        cleaned[key] = value

    return cleaned, None


def make_slug(title):
    """Generate a URL-friendly slug from a title."""
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")

    if not SLUG_PATTERN.fullmatch(slug):
        raise ValueError("Unable to generate a valid story slug.")

    return slug
