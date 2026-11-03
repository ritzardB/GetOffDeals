
"""Route tests for GetOffDeals Travel Stories."""

from getoffdeals.travel_stories import routes
from pathlib import Path
from tempfile import TemporaryDirectory

USER_ID = "33333333-3333-4333-8333-333333333333"
CSRF_TOKEN = "test-csrf-token-with-sufficient-length-123456"

VALID_STORY = {
    "title": "My Amazing Trip to Tokyo",
    "destination": "Tokyo",
    "country": "Japan",
    "content": (
        "Tokyo was an incredible experience. "
        "The food, culture and people made this trip unforgettable."
    ),
    "csrf_token": CSRF_TOKEN,
}

MOCK_STORY = {
    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "user_id": USER_ID,
    "title": VALID_STORY["title"],
    "slug": "my-amazing-trip-to-tokyo",
    "destination": "Tokyo",
    "country": "Japan",
    "content": VALID_STORY["content"],
    "cover_image_path": None,
    "status": "published",
    "published_at": None,
    "created_at": None,
    "updated_at": None,
}


def authenticate(client, token=CSRF_TOKEN):
    """Set a test user and CSRF token in the Flask session."""
    with client.session_transaction() as session:
        session["user_id"] = USER_ID
        session["travel_stories_csrf_token"] = token


def test_anonymous_user_cannot_publish(client, monkeypatch):
    def should_not_create(*args, **kwargs):
        raise AssertionError("Unauthenticated publishing reached service")

    monkeypatch.setattr(
        routes.service,
        "create_story",
        should_not_create,
    )

    response = client.post(
        "/api/travel-stories",
        json=VALID_STORY,
    )

    assert response.status_code == 401
    assert "sign in" in response.json["error"].lower()


def test_authenticated_user_requires_valid_csrf(client, monkeypatch):
    authenticate(client)

    def should_not_create(*args, **kwargs):
        raise AssertionError("Invalid CSRF reached service")

    monkeypatch.setattr(
        routes.service,
        "create_story",
        should_not_create,
    )

    response = client.post(
        "/api/travel-stories",
        json={**VALID_STORY, "csrf_token": "invalid-token"},
    )

    assert response.status_code == 400


def test_authenticated_user_cannot_publish_invalid_story(
    client,
    monkeypatch,
):
    authenticate(client)

    def should_not_create(*args, **kwargs):
        raise AssertionError("Invalid story reached service")

    monkeypatch.setattr(
        routes.service,
        "create_story",
        should_not_create,
    )

    invalid_story = {
        **VALID_STORY,
        "title": "Bad",
    }

    response = client.post(
        "/api/travel-stories",
        json=invalid_story,
    )

    assert response.status_code == 400
    assert "error" in response.json


def test_authenticated_user_can_publish_story(client, monkeypatch):
    authenticate(client)

    calls = []

    def fake_create_story(user_id, values):
        calls.append((user_id, values))
        return MOCK_STORY

    monkeypatch.setattr(
        routes.service,
        "create_story",
        fake_create_story,
    )

    response = client.post(
        "/api/travel-stories",
        json=VALID_STORY,
    )

    assert response.status_code == 201
    assert response.json["message"]
    assert response.json["story"]["id"] == MOCK_STORY["id"]
    assert response.json["story"]["slug"] == MOCK_STORY["slug"]
    assert response.json["story"]["url"] == (
        "/travel-stories/my-amazing-trip-to-tokyo"
    )

    assert len(calls) == 1
    assert calls[0][0] == USER_ID
    assert calls[0][1]["title"] == VALID_STORY["title"]

def test_daily_story_limit_returns_http_429(client, monkeypatch):
    authenticate(client)

    def reject_story(user_id, values):
        raise routes.service.StoryDailyLimitReached(
            "You have reached the limit of 3 published stories today."
        )

    monkeypatch.setattr(
        routes.service,
        "create_story",
        reject_story,
    )

    response = client.post(
        "/api/travel-stories",
        json=VALID_STORY,
    )

    assert response.status_code == 429
    assert "limit of 3" in response.json["error"]


def test_published_story_image_is_served(client, monkeypatch):
    story_id = MOCK_STORY["id"]
    filename = "cover.jpg"

    with TemporaryDirectory() as temp_dir:
        upload_root = Path(temp_dir)
        story_folder = upload_root / story_id
        story_folder.mkdir()

        image_content = b"test-image-content"
        image_file = story_folder / filename
        image_file.write_bytes(image_content)

        client.application.config[
            "TRAVEL_STORIES_UPLOAD_FOLDER"
        ] = str(upload_root)

        monkeypatch.setattr(
            routes.service,
            "get_published_story_image_path",
            lambda requested_story_id, requested_filename: (
                f"{requested_story_id}/{requested_filename}"
            ),
        )

        response = client.get(
            f"/travel-stories/images/{story_id}/{filename}"
        )

        assert response.status_code == 200
        assert response.data == image_content
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cache-Control"] == "public, max-age=3600"


def test_story_image_rejects_invalid_story_id_and_filename(
    client,
    monkeypatch,
):
    def should_not_lookup(*args, **kwargs):
        raise AssertionError("Invalid image request reached service")

    monkeypatch.setattr(
        routes.service,
        "get_published_story_image_path",
        should_not_lookup,
    )

    invalid_urls = [
        "/travel-stories/images/not-a-uuid/cover.jpg",
        f"/travel-stories/images/{MOCK_STORY['id']}/../secret.jpg",
        f"/travel-stories/images/{MOCK_STORY['id']}/folder/cover.jpg",
    ]

    for url in invalid_urls:
        response = client.get(url)
        assert response.status_code == 404

def test_story_image_returns_404_when_not_registered(
    client,
    monkeypatch,
):
    story_id = MOCK_STORY["id"]
    filename = "private.jpg"

    with TemporaryDirectory() as temp_dir:
        upload_root = Path(temp_dir)
        story_folder = upload_root / story_id
        story_folder.mkdir()

        # The file exists, but the service does not approve it.
        (story_folder / filename).write_bytes(b"private-image")

        client.application.config[
            "TRAVEL_STORIES_UPLOAD_FOLDER"
        ] = str(upload_root)

        monkeypatch.setattr(
            routes.service,
            "get_published_story_image_path",
            lambda requested_story_id, requested_filename: None,
        )

        response = client.get(
            f"/travel-stories/images/{story_id}/{filename}"
        )

        assert response.status_code == 404


def test_story_image_returns_404_when_file_is_missing(
    client,
    monkeypatch,
):
    story_id = MOCK_STORY["id"]
    filename = "missing.jpg"

    with TemporaryDirectory() as temp_dir:
        upload_root = Path(temp_dir)

        client.application.config[
            "TRAVEL_STORIES_UPLOAD_FOLDER"
        ] = str(upload_root)

        monkeypatch.setattr(
            routes.service,
            "get_published_story_image_path",
            lambda requested_story_id, requested_filename: (
                f"{requested_story_id}/{requested_filename}"
            ),
        )

        response = client.get(
            f"/travel-stories/images/{story_id}/{filename}"
        )

        assert response.status_code == 404

def test_story_image_returns_503_when_service_fails(
    client,
    monkeypatch,
):
    def fail_lookup(*args, **kwargs):
        raise RuntimeError("Simulated database failure")

    monkeypatch.setattr(
        routes.service,
        "get_published_story_image_path",
        fail_lookup,
    )

    response = client.get(
        f"/travel-stories/images/{MOCK_STORY['id']}/cover.jpg"
    )

    assert response.status_code == 503
