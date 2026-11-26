
from uuid import UUID

import pytest

import getoffdeals.admin_contacts as admin_contacts


TEST_USER_ID = "11111111-1111-4111-8111-111111111111"
TEST_ADMIN_EMAIL = "getoffdeals@gmail.com"
TEST_USER_EMAIL = "traveler@example.com"
TEST_CSRF_TOKEN = "test-csrf-token-that-is-long-enough-123456"


class FakeCursor:
    """Minimal PostgreSQL cursor mock for admin invitation route tests."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.result = None
        self.executed = []
        self.insert_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=None):
        normalized = " ".join(query.split()).lower()
        self.executed.append((normalized, params))

        if "select id, email from public.users" in normalized:
            self.result = {
                "id": UUID(TEST_USER_ID),
                "email": TEST_USER_EMAIL,
            }

        elif "select status from public.subscribers" in normalized:
            self.result = (
                {"status": self.scenario["subscriber_status"]}
                if self.scenario.get("subscriber_status")
                else None
            )

        elif "select 1 from public.newsletter_invitations" in normalized:
            self.result = (
                {"?column?": 1}
                if self.scenario.get("active_invitation")
                else None
            )

        elif (
            "select id from public.admin_newsletter_invitation_outbox"
            in normalized
        ):
            self.result = (
                {"id": "existing-job-id"}
                if self.scenario.get("existing_job")
                else None
            )

        elif (
            "insert into public.admin_newsletter_invitation_outbox"
            in normalized
        ):
            self.insert_count += 1
            self.result = {"id": "new-test-job-id"}

        else:
            raise AssertionError(f"Unexpected SQL query: {normalized}")

    def fetchone(self):
        return self.result


class FakeConnection:
    """Context-manager-compatible database connection mock."""

    def __init__(self, scenario):
        self.cursor_instance = FakeCursor(scenario)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self):
        return self.cursor_instance


@pytest.fixture
def admin_setup(client, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", TEST_ADMIN_EMAIL)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://getoffdeals.com")

    scenario = {}
    fake_connection = FakeConnection(scenario)

    monkeypatch.setattr(
        admin_contacts,
        "get_connection",
        lambda: fake_connection,
    )

    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = "test-admin-user"
        sess["email"] = TEST_ADMIN_EMAIL
        sess["admin_contacts_csrf_token"] = TEST_CSRF_TOKEN

    return fake_connection, scenario


def post_invitation(client, csrf_token=TEST_CSRF_TOKEN):
    return client.post(
        f"/admin/contacts/{TEST_USER_ID}/invite",
        data={"csrf_token": csrf_token},
    )


def test_admin_can_queue_newsletter_invitation(client, admin_setup):
    fake_connection, scenario = admin_setup

    response = post_invitation(client)

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/admin/contacts")

    assert fake_connection.cursor_instance.insert_count == 1

    insert_queries = [
        query
        for query, _ in fake_connection.cursor_instance.executed
        if "insert into public.admin_newsletter_invitation_outbox" in query
    ]
    assert len(insert_queries) == 1


def test_invitation_is_not_queued_for_existing_subscriber(
    client, admin_setup
):
    fake_connection, scenario = admin_setup
    scenario["subscriber_status"] = "unsubscribed"

    response = post_invitation(client)

    assert response.status_code == 302
    assert fake_connection.cursor_instance.insert_count == 0


def test_invitation_is_not_queued_when_active_invitation_exists(
    client, admin_setup
):
    fake_connection, scenario = admin_setup
    scenario["active_invitation"] = True

    response = post_invitation(client)

    assert response.status_code == 302
    assert fake_connection.cursor_instance.insert_count == 0


def test_duplicate_active_admin_job_is_not_queued(
    client, admin_setup
):
    fake_connection, scenario = admin_setup
    scenario["existing_job"] = True

    response = post_invitation(client)

    assert response.status_code == 302
    assert fake_connection.cursor_instance.insert_count == 0


def test_invitation_rejects_invalid_csrf_token(client, admin_setup):
    fake_connection, _ = admin_setup

    response = post_invitation(client, csrf_token="invalid-token")

    assert response.status_code == 400
    assert fake_connection.cursor_instance.executed == []


def test_invitation_rejects_missing_csrf_token(client, admin_setup):
    fake_connection, _ = admin_setup

    response = client.post(
        f"/admin/contacts/{TEST_USER_ID}/invite",
        data={},
    )

    assert response.status_code == 400
    assert fake_connection.cursor_instance.executed == []


def test_regular_user_cannot_queue_invitation(
    client, admin_setup, monkeypatch
):
    fake_connection, _ = admin_setup

    with client.session_transaction() as sess:
        sess["user_id"] = "regular-user"
        sess["email"] = "traveler@example.com"

    response = post_invitation(client)

    assert response.status_code == 403
    assert fake_connection.cursor_instance.executed == []


def test_anonymous_user_cannot_queue_invitation(
    client, admin_setup
):
    fake_connection, _ = admin_setup

    with client.session_transaction() as sess:
        sess.clear()

    response = post_invitation(client)

    assert response.status_code == 401
    assert fake_connection.cursor_instance.executed == []


def test_invalid_user_id_is_rejected(client, admin_setup):
    fake_connection, _ = admin_setup

    response = client.post(
        "/admin/contacts/not-a-uuid/invite",
        data={"csrf_token": TEST_CSRF_TOKEN},
    )

    assert response.status_code == 404
    assert fake_connection.cursor_instance.executed == []


def test_non_https_public_url_prevents_queueing(
    client, admin_setup, monkeypatch
):
    fake_connection, _ = admin_setup
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://getoffdeals.com")

    response = post_invitation(client)

    assert response.status_code == 302
    assert fake_connection.cursor_instance.executed == []


@pytest.mark.parametrize(
    "value",
    [
        "=SUM(A1:A2)",
        "+123",
        "-123",
        "@SUM(A1:A2)",
        "   =SUM(A1:A2)",
        "\t=SUM(A1:A2)",
    ],
)
def test_csv_safe_prevents_spreadsheet_formula_injection(value):
    assert admin_contacts._csv_safe(value).startswith("'")


def test_csv_safe_preserves_normal_values():
    assert admin_contacts._csv_safe("traveler@example.com") == (
        "traveler@example.com"
    )


def test_regular_user_cannot_access_contacts_dashboard(
    client, admin_setup
):
    with client.session_transaction() as sess:
        sess["user_id"] = "regular-user"
        sess["email"] = TEST_USER_EMAIL

    response = client.get("/admin/contacts")

    assert response.status_code == 403


def test_regular_user_cannot_export_contacts(
    client, admin_setup
):
    with client.session_transaction() as sess:
        sess["user_id"] = "regular-user"
        sess["email"] = TEST_USER_EMAIL

    response = client.get("/admin/contacts.csv")

    assert response.status_code == 403


def test_anonymous_user_cannot_export_contacts(
    client, admin_setup
):
    with client.session_transaction() as sess:
        sess.clear()

    response = client.get("/admin/contacts.csv")

    assert response.status_code == 401
