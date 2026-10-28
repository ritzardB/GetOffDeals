
import pytest

from getoffdeals import resend_contacts as contacts


def test_add_confirmed_contact_creates_contact_in_segment(
    monkeypatch,
):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_NEWSLETTER_SEGMENT_ID", "segment-123")

    calls = []

    def fake_request(method, path, *, payload=None):
        calls.append((method, path, payload))

        if method == "GET":
            return None

        return {"id": "contact-123"}

    monkeypatch.setattr(contacts, "_request", fake_request)
    monkeypatch.setattr(contacts, "get_contact", lambda email: None)

    result = contacts.add_confirmed_contact("reader@example.com")

    assert result == "added"
    assert calls == [
        (
            "POST",
            "/contacts",
            {
                "email": "reader@example.com",
                "unsubscribed": False,
                "segments": [{"id": "segment-123"}],
            },
        )
    ]


def test_existing_unsubscribed_contact_is_never_reactivated(
    monkeypatch,
):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_NEWSLETTER_SEGMENT_ID", "segment-123")

    monkeypatch.setattr(
        contacts,
        "get_contact",
        lambda email: {
            "id": "contact-123",
            "unsubscribed": True,
        },
    )

    def unexpected_request(*args, **kwargs):
        pytest.fail("An unsubscribed contact must not be modified.")

    monkeypatch.setattr(contacts, "_request", unexpected_request)

    result = contacts.add_confirmed_contact("reader@example.com")

    assert result == "suppressed"


def test_unsubscribe_contact_updates_resend_contact(
    monkeypatch,
):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_NEWSLETTER_SEGMENT_ID", "segment-123")

    calls = []

    monkeypatch.setattr(
        contacts,
        "get_contact",
        lambda email: {
            "id": "contact-123",
            "unsubscribed": False,
        },
    )

    def fake_request(method, path, *, payload=None):
        calls.append((method, path, payload))
        return {}

    monkeypatch.setattr(contacts, "_request", fake_request)

    result = contacts.unsubscribe_contact("reader@example.com")

    assert result == "unsubscribed"
    assert calls == [
        (
            "PATCH",
            "/contacts/contact-123",
            {"unsubscribed": True},
        )
    ]


def test_unsubscribe_unknown_contact_is_safe(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_NEWSLETTER_SEGMENT_ID", "segment-123")

    monkeypatch.setattr(
        contacts,
        "get_contact",
        lambda email: None,
    )

    result = contacts.unsubscribe_contact("reader@example.com")

    assert result == "not_found"
