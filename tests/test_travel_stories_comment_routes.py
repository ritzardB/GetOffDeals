"""Route tests for Travel Stories comments."""

from datetime import datetime, timezone

from getoffdeals.travel_stories import routes


USER_ID = "33333333-3333-4333-8333-333333333333"
STORY_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
COMMENT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PARENT_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
CSRF_TOKEN = "test-csrf-token-with-sufficient-length-123456"

VALID_COMMENT = {
    "content": "Beautiful destination!",
    "csrf_token": CSRF_TOKEN,
}

MOCK_COMMENT = {
    "id": COMMENT_ID,
    "story_id": STORY_ID,
    "user_id": USER_ID,
    "parent_id": None,
    "content": "Beautiful destination!",
    "status": "visible",
    "author_label": "GetOffDeals member",
    "created_at": datetime(2026, 10, 30, tzinfo=timezone.utc),
    "updated_at": datetime(2026, 10, 30, tzinfo=timezone.utc),
}

MOCK_STORY = {
    "id": STORY_ID,
    "slug": "my-trip",
    "status": "published",
}


def authenticate(client, token=CSRF_TOKEN):
    with client.session_transaction() as session:
        session["user_id"] = USER_ID
        session["travel_stories_csrf_token"] = token


def test_anonymous_user_cannot_comment(client, monkeypatch):
    def should_not_create(*args, **kwargs):
        raise AssertionError("Anonymous request reached service")

    monkeypatch.setattr(routes.service, "create_comment", should_not_create)

    response = client.post(
        f"/api/travel-stories/{STORY_ID}/comments",
        json=VALID_COMMENT,
    )

    assert response.status_code == 401


def test_comment_requires_valid_csrf(client, monkeypatch):
    authenticate(client)

    def should_not_create(*args, **kwargs):
        raise AssertionError("Invalid CSRF reached service")

    monkeypatch.setattr(routes.service, "create_comment", should_not_create)

    response = client.post(
        f"/api/travel-stories/{STORY_ID}/comments",
        json={**VALID_COMMENT, "csrf_token": "invalid"},
    )

    assert response.status_code == 400


def test_authenticated_member_can_comment(client, monkeypatch):
    authenticate(client)
    calls = []

    def fake_create(user_id, story_id, values):
        calls.append((user_id, story_id, values))
        return MOCK_COMMENT

    monkeypatch.setattr(routes.service, "create_comment", fake_create)

    response = client.post(
        f"/api/travel-stories/{STORY_ID}/comments",
        json=VALID_COMMENT,
    )

    assert response.status_code == 201
    assert response.json["comment"]["id"] == COMMENT_ID
    assert response.json["comment"]["content"] == MOCK_COMMENT["content"]
    assert calls[0][0] == USER_ID
    assert calls[0][1] == STORY_ID
    assert calls[0][2]["content"] == MOCK_COMMENT["content"]


def test_browser_cannot_choose_comment_author(client, monkeypatch):
    authenticate(client)
    calls = []

    def fake_create(user_id, story_id, values):
        calls.append(user_id)
        return MOCK_COMMENT

    monkeypatch.setattr(routes.service, "create_comment", fake_create)

    response = client.post(
        f"/api/travel-stories/{STORY_ID}/comments",
        json={
            **VALID_COMMENT,
            "user_id": "99999999-9999-4999-8999-999999999999",
        },
    )

    assert response.status_code == 201
    assert calls == [USER_ID]


def test_invalid_comment_returns_400(client, monkeypatch):
    authenticate(client)

    def should_not_create(*args, **kwargs):
        raise AssertionError("Invalid comment reached service")

    monkeypatch.setattr(routes.service, "create_comment", should_not_create)

    response = client.post(
        f"/api/travel-stories/{STORY_ID}/comments",
        json={
            "content": "   ",
            "csrf_token": CSRF_TOKEN,
        },
    )

    assert response.status_code == 400


def test_comment_rate_limit_returns_429(client, monkeypatch):
    authenticate(client)

    def reject(*args, **kwargs):
        raise routes.service.CommentRateLimitReached("Hourly limit reached.")

    monkeypatch.setattr(routes.service, "create_comment", reject)

    response = client.post(
        f"/api/travel-stories/{STORY_ID}/comments",
        json=VALID_COMMENT,
    )

    assert response.status_code == 429
    assert "Hourly limit" in response.json["error"]


def test_comment_list_returns_visible_comments(client, monkeypatch):
    monkeypatch.setattr(
        routes.service,
        "get_published_story_by_id",
        lambda story_id: MOCK_STORY,
    )
    monkeypatch.setattr(
        routes.service,
        "list_story_comments",
        lambda story_id: [MOCK_COMMENT],
    )

    response = client.get(
        f"/api/travel-stories/{STORY_ID}/comments"
    )

    assert response.status_code == 200
    assert len(response.json["comments"]) == 1
    assert response.json["comments"][0]["author"] == "GetOffDeals member"


def test_comment_list_rejects_unpublished_story(client, monkeypatch):
    monkeypatch.setattr(
        routes.service,
        "get_published_story_by_id",
        lambda story_id: None,
    )

    response = client.get(
        f"/api/travel-stories/{STORY_ID}/comments"
    )

    assert response.status_code == 404


def test_anonymous_user_cannot_delete_comment(client, monkeypatch):
    def should_not_delete(*args, **kwargs):
        raise AssertionError("Anonymous request reached service")

    monkeypatch.setattr(routes.service, "delete_comment", should_not_delete)

    response = client.delete(
        f"/api/story-comments/{COMMENT_ID}",
    )

    assert response.status_code == 401


def test_delete_comment_requires_csrf(client, monkeypatch):
    authenticate(client)

    def should_not_delete(*args, **kwargs):
        raise AssertionError("Invalid CSRF reached service")

    monkeypatch.setattr(routes.service, "delete_comment", should_not_delete)

    response = client.delete(
        f"/api/story-comments/{COMMENT_ID}",
    )

    assert response.status_code == 400


def test_member_can_delete_own_comment(client, monkeypatch):
    authenticate(client)

    calls = []

    def fake_delete(user_id, comment_id):
        calls.append((user_id, comment_id))
        return True

    monkeypatch.setattr(routes.service, "delete_comment", fake_delete)

    response = client.delete(
        f"/api/story-comments/{COMMENT_ID}",
        headers={"X-CSRF-Token": CSRF_TOKEN},
    )

    assert response.status_code == 200
    assert calls == [(USER_ID, COMMENT_ID)]


def test_delete_comment_not_owned_returns_404(client, monkeypatch):
    authenticate(client)

    monkeypatch.setattr(
        routes.service,
        "delete_comment",
        lambda user_id, comment_id: False,
    )

    response = client.delete(
        f"/api/story-comments/{COMMENT_ID}",
        headers={"X-CSRF-Token": CSRF_TOKEN},
    )

    assert response.status_code == 404
