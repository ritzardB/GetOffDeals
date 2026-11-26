
from getoffdeals.travel_stories.validators import (
    current_user_id,
    generate_csrf_token,
    make_slug,
    validate_csrf_token,
    validate_story,
)


def valid_story():
    return {
        "title": "My Amazing Trip to Tokyo",
        "destination": "Tokyo",
        "country": "Japan",
        "content": (
            "Tokyo was an incredible experience. "
            "The food, culture and people made this trip unforgettable."
        ),
    }


def test_current_user_id_accepts_valid_uuid():
    session = {"user_id": "33333333-3333-4333-8333-333333333333"}

    assert current_user_id(session) == session["user_id"]


def test_current_user_id_rejects_invalid_uuid():
    assert current_user_id({"user_id": "not-a-uuid"}) is None


def test_generate_csrf_token_creates_session_token():
    session = {}

    token = generate_csrf_token(session)

    assert isinstance(token, str)
    assert len(token) >= 32
    assert session["travel_stories_csrf_token"] == token


def test_generate_csrf_token_reuses_existing_token():
    session = {"travel_stories_csrf_token": "existing-token-" + "x" * 32}

    token = generate_csrf_token(session)

    assert token == session["travel_stories_csrf_token"]


def test_validate_csrf_token_accepts_matching_token():
    token = "test-token-" + "x" * 32
    session = {"travel_stories_csrf_token": token}

    assert validate_csrf_token(session, token) is True


def test_validate_csrf_token_rejects_wrong_token():
    session = {"travel_stories_csrf_token": "correct-token-" + "x" * 32}

    assert validate_csrf_token(session, "wrong-token") is False


def test_validate_story_accepts_valid_input():
    values, error = validate_story(valid_story())

    assert error is None
    assert values["destination"] == "Tokyo"


def test_validate_story_rejects_short_title():
    story = valid_story()
    story["title"] = "Hi"

    values, error = validate_story(story)

    assert values is None
    assert "title" in error.lower()


def test_validate_story_rejects_short_content():
    story = valid_story()
    story["content"] = "Too short"

    values, error = validate_story(story)

    assert values is None
    assert "content" in error.lower()


def test_validate_story_rejects_non_object():
    values, error = validate_story("invalid")

    assert values is None
    assert error is not None


def test_make_slug_creates_clean_slug():
    assert make_slug("My Amazing Trip to Tokyo!") == "my-amazing-trip-to-tokyo"
