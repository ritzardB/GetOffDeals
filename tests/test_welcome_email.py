import getoffdeals.email_service as email_service


def test_welcome_email_content_and_resend_payload(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-api-key")
    monkeypatch.setenv("EMAIL_FROM", "GetOffDeals <hello@example.com>")

    captured = {}

    class FakeEmails:
        @staticmethod
        def send(payload):
            captured.update(payload)
            return {"id": "test-message-id"}

    class FakeResend:
        Emails = FakeEmails

        api_key = None

    monkeypatch.setattr(email_service, "resend", FakeResend)

    result = email_service.send_welcome_email(
        "reader@example.com",
        "Alex",
        "https://example.com/newsletter/join/test-token",
    )

    assert result["id"] == "test-message-id"
    assert captured["to"] == ["reader@example.com"]
    assert "Welcome to GetOffDeals" in captured["subject"]
    assert "Subscribe to GetOffDeals Newsletter" in captured["html"]
    assert "Alex" in captured["html"]
    assert "test-token" in captured["html"]
    assert "getoffdeals-welcome-poster.png" in captured["html"]
    assert FakeResend.api_key == "test-api-key"
