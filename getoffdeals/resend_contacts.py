
"""Resend contact management for the GetOffDeals newsletter."""

import logging
import os

import requests

logger = logging.getLogger(__name__)

RESEND_API_BASE = "https://api.resend.com"


class ResendContactsError(RuntimeError):
    """Raised when Resend contact management fails."""


def _config():
    api_key = os.getenv("RESEND_API_KEY")
    segment_id = os.getenv("RESEND_NEWSLETTER_SEGMENT_ID")

    if not api_key or not segment_id:
        raise ResendContactsError(
            "Resend contact configuration is missing."
        )

    return api_key, segment_id


def _request(method, path, *, payload=None):
    api_key, _ = _config()

    try:
        response = requests.request(
            method,
            f"{RESEND_API_BASE}{path}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
    except requests.RequestException as exc:
        raise ResendContactsError(
            "Could not connect to Resend."
        ) from exc

    if response.status_code >= 400:
        # Do not log API keys, email addresses, or response bodies.
        logger.error(
            "Resend contact API failed: method=%s path=%s status=%s",
            method,
            path,
            response.status_code,
        )
        raise ResendContactsError(
            f"Resend contact API returned HTTP {response.status_code}."
        )

    if response.status_code == 204 or not response.content:
        return {}

    try:
        return response.json()
    except ValueError as exc:
        raise ResendContactsError(
            "Resend returned an invalid response."
        ) from exc


def get_contact(email):
    """Return a Resend contact, or None if it does not exist."""
    from urllib.parse import quote

    try:
        result = _request(
            "GET",
            f"/contacts/{quote(email, safe='')}",
        )
    except ResendContactsError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise

    return result


def add_confirmed_contact(email):
    """Add an opted-in contact without overriding an existing opt-out.

    Returns one of: added, already_present, suppressed.
    """
    _, segment_id = _config()
    contact = get_contact(email)

    if contact:
        # Never silently reactivate a Resend-side unsubscribe.
        if contact.get("unsubscribed") is True:
            return "suppressed"

        contact_id = contact.get("id")
        if not contact_id:
            raise ResendContactsError(
                "Resend contact response is missing its ID."
            )

        # Adding to a segment does not send a campaign.
        from urllib.parse import quote

        _request(
            "POST",
            f"/contacts/{quote(contact_id, safe='')}"
            f"/segments/{quote(segment_id, safe='')}",
        )
        return "already_present"

    # The contact is created only after the application has confirmed
    # the user's double opt-in. No email or campaign is sent here.
    _request(
        "POST",
        "/contacts",
        payload={
            "email": email,
            "unsubscribed": False,
            "segments": [{"id": segment_id}],
        },
    )
    return "added"


def unsubscribe_contact(email):
    """Suppress a contact in Resend without sending any email."""
    contact = get_contact(email)

    if not contact:
        return "not_found"

    if contact.get("unsubscribed") is True:
        return "already_unsubscribed"

    contact_id = contact.get("id")
    if not contact_id:
        raise ResendContactsError(
            "Resend contact response is missing its ID."
        )

    from urllib.parse import quote

    _request(
        "PATCH",
        f"/contacts/{quote(contact_id, safe='')}",
        payload={"unsubscribed": True},
    )
    return "unsubscribed"
