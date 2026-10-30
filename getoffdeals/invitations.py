
"""Core validation and security helpers for GetOffDeals invitations."""

import csv
import hashlib
import io
import re
import secrets
from datetime import datetime, timezone


EMAIL_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)

MAX_CSV_BYTES = 1_000_000
MAX_CSV_RECIPIENTS = 500


def normalize_email(value):
    """Return a normalized email address, or an empty string."""
    if not isinstance(value, str):
        return ""
    return value.strip().casefold()


def validate_email(value):
    """Validate a normalized email address."""
    email = normalize_email(value)

    if not email or len(email) > 254:
        return False

    if any(ord(char) < 33 or ord(char) > 126 for char in email):
        return False

    return bool(EMAIL_RE.fullmatch(email))


def generate_unsubscribe_token():
    """Generate a cryptographically secure unsubscribe token."""
    return secrets.token_urlsafe(32)


def hash_unsubscribe_token(token):
    """Return the SHA-256 hash of an unsubscribe token."""
    if not isinstance(token, str) or not token:
        raise ValueError("A valid unsubscribe token is required.")

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_invitation_csv(csv_text):
    """Validate CSV data; this function does not grant consent."""
    if not isinstance(csv_text, str):
        raise ValueError("CSV content must be text.")

    if len(csv_text.encode("utf-8")) > MAX_CSV_BYTES:
        raise ValueError("CSV file exceeds the 1 MB limit.")

    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))

    if not reader.fieldnames:
        raise ValueError("CSV must include a header row.")

    header_map = {
        header.strip().casefold(): header
        for header in reader.fieldnames
        if header and header.strip()
    }

    required = {"email", "consent_source", "consent_evidence"}
    if not required.issubset(header_map):
        raise ValueError(
            "CSV must include email, consent_source, and consent_evidence columns."
        )

    contacts = []
    seen_emails = set()
    invalid_rows = []
    duplicate_rows = []

    for row_number, row in enumerate(reader, start=2):
        email = normalize_email(row.get(header_map["email"], ""))
        source = (row.get(header_map["consent_source"], "") or "").strip()
        evidence = (row.get(header_map["consent_evidence"], "") or "").strip()

        if not email and not source and not evidence:
            continue

        if not validate_email(email) or not source or not evidence:
            invalid_rows.append(row_number)
            continue

        if email in seen_emails:
            duplicate_rows.append(row_number)
            continue

        seen_emails.add(email)
        contacts.append({
            "email": email,
            "consent_source": source,
            "consent_evidence": evidence,
            "consented_at": datetime.now(timezone.utc),
        })

        if len(contacts) > MAX_CSV_RECIPIENTS:
            raise ValueError(
                f"CSV exceeds the {MAX_CSV_RECIPIENTS}-recipient limit."
            )

    return {
        "contacts": contacts,
        "invalid_rows": invalid_rows,
        "duplicate_rows": duplicate_rows,
    }
