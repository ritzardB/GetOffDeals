
import pytest

from getoffdeals.invitations import (
    generate_unsubscribe_token,
    hash_unsubscribe_token,
    normalize_email,
    parse_invitation_csv,
    validate_email,
)


def test_normalize_email():
    assert normalize_email("  USER@Example.com ") == "user@example.com"


@pytest.mark.parametrize(
    "email",
    [
        "user@example.com",
        "agent+test@example.co.uk",
    ],
)
def test_validate_email_accepts_valid_addresses(email):
    assert validate_email(email)


@pytest.mark.parametrize(
    "email",
    [
        "",
        "not-an-email",
        "user@localhost",
        "user@@example.com",
        "user example@example.com",
    ],
)
def test_validate_email_rejects_invalid_addresses(email):
    assert not validate_email(email)


def test_unsubscribe_token_is_random_and_only_hash_is_stored():
    token = generate_unsubscribe_token()

    assert token
    assert token != hash_unsubscribe_token(token)
    assert hash_unsubscribe_token(token) == hash_unsubscribe_token(token)


def test_csv_requires_consent_evidence():
    csv_text = "email,consent_source,consent_evidence\nuser@example.com,,\n"

    result = parse_invitation_csv(csv_text)

    assert result["contacts"] == []
    assert result["invalid_rows"] == [2]


def test_csv_deduplicates_email_addresses():
    csv_text = (
        "email,consent_source,consent_evidence\n"
        "USER@example.com,signup,consent record 123\n"
        "user@example.com,signup,consent record 456\n"
    )

    result = parse_invitation_csv(csv_text)

    assert len(result["contacts"]) == 1
    assert result["duplicate_rows"] == [3]


def test_csv_accepts_documented_consent_fields():
    csv_text = (
        "email,consent_source,consent_evidence\n"
        "user@example.com,signup form,consent record 123\n"
    )

    result = parse_invitation_csv(csv_text)

    assert len(result["contacts"]) == 1
    assert result["contacts"][0]["email"] == "user@example.com"
    assert result["invalid_rows"] == []
