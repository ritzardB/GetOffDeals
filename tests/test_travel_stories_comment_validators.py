"""Tests for Travel Stories comment validation."""

from getoffdeals.travel_stories.comment_validators import validate_comment


PARENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_valid_comment():
    values, error = validate_comment({
        "content": "  Beautiful destination!  ",
    })

    assert error is None
    assert values == {
        "content": "Beautiful destination!",
        "parent_id": None,
    }


def test_valid_reply():
    values, error = validate_comment({
        "content": "Thanks for sharing!",
        "parent_id": PARENT_ID,
    })

    assert error is None
    assert values["parent_id"] == PARENT_ID


def test_rejects_missing_content():
    values, error = validate_comment({})

    assert values is None
    assert error is not None


def test_rejects_empty_comment():
    values, error = validate_comment({
        "content": "   ",
    })

    assert values is None
    assert error is not None


def test_rejects_comment_over_5000_characters():
    values, error = validate_comment({
        "content": "a" * 5001,
    })

    assert values is None
    assert error is not None


def test_rejects_invalid_parent_id():
    values, error = validate_comment({
        "content": "This is a reply.",
        "parent_id": "not-a-uuid",
    })

    assert values is None
    assert error is not None


def test_rejects_non_object_payload():
    values, error = validate_comment("This is not an object")

    assert values is None
    assert error is not None
