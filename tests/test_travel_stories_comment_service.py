"""Tests for Travel Stories comment service operations."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from getoffdeals.travel_stories import service


USER_ID = "33333333-3333-4333-8333-333333333333"
STORY_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
COMMENT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PARENT_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

COMMENT_VALUES = {
    "content": "Beautiful destination!",
    "parent_id": None,
}


def mock_connection(monkeypatch, fetchone_values, fetchall_values=None):
    """Provide a mocked PostgreSQL connection and cursor."""
    cursor = MagicMock()
    cursor.fetchone.side_effect = fetchone_values
    cursor.fetchall.return_value = fetchall_values or []

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def fake_connection():
        yield connection

    monkeypatch.setattr(service, "get_connection", fake_connection)

    return cursor


def comment_row():
    return {
        "id": COMMENT_ID,
        "story_id": STORY_ID,
        "user_id": USER_ID,
        "parent_id": None,
        "content": "Beautiful destination!",
        "status": "visible",
    }


def test_create_comment_success(monkeypatch):
    cursor = mock_connection(
        monkeypatch,
        [
            {"id": USER_ID},
            {"comment_count": 2},
            {"id": STORY_ID},
            comment_row(),
        ],
    )

    result = service.create_comment(
        USER_ID,
        STORY_ID,
        COMMENT_VALUES,
    )

    assert result["id"] == COMMENT_ID
    assert result["content"] == "Beautiful destination!"

    assert cursor.execute.call_count == 4

    sql_statements = [
        call.args[0]
        for call in cursor.execute.call_args_list
    ]

    assert "FOR UPDATE" in sql_statements[0]
    assert "INTERVAL '1 hour'" in sql_statements[1]
    assert "FOR SHARE" in sql_statements[2]
    assert "INSERT INTO public.story_comments" in sql_statements[3]


def test_create_reply_success(monkeypatch):
    values = {
        "content": "Thanks for sharing!",
        "parent_id": PARENT_ID,
    }

    reply = {
        **comment_row(),
        "parent_id": PARENT_ID,
        "content": "Thanks for sharing!",
    }

    cursor = mock_connection(
        monkeypatch,
        [
            {"id": USER_ID},
            {"comment_count": 2},
            {"id": STORY_ID},
            {"id": PARENT_ID},
            reply,
        ],
    )

    result = service.create_comment(USER_ID, STORY_ID, values)

    assert result["parent_id"] == PARENT_ID
    assert result["content"] == "Thanks for sharing!"
    assert cursor.execute.call_count == 5

    insert_call = cursor.execute.call_args_list[-1]
    assert insert_call.args[1][2] == PARENT_ID


def test_create_comment_rejects_hourly_limit(monkeypatch):
    cursor = mock_connection(
        monkeypatch,
        [
            {"id": USER_ID},
            {"comment_count": 10},
        ],
    )

    with pytest.raises(service.CommentRateLimitReached):
        service.create_comment(USER_ID, STORY_ID, COMMENT_VALUES)

    assert cursor.execute.call_count == 2


def test_create_comment_rejects_missing_member(monkeypatch):
    cursor = mock_connection(monkeypatch, [None])

    with pytest.raises(ValueError, match="Authenticated member"):
        service.create_comment(USER_ID, STORY_ID, COMMENT_VALUES)

    assert cursor.execute.call_count == 1


def test_create_comment_rejects_unpublished_story(monkeypatch):
    cursor = mock_connection(
        monkeypatch,
        [
            {"id": USER_ID},
            {"comment_count": 0},
            None,
        ],
    )

    with pytest.raises(ValueError, match="Story not found"):
        service.create_comment(USER_ID, STORY_ID, COMMENT_VALUES)

    assert cursor.execute.call_count == 3


def test_create_reply_rejects_invalid_parent(monkeypatch):
    cursor = mock_connection(
        monkeypatch,
        [
            {"id": USER_ID},
            {"comment_count": 0},
            {"id": STORY_ID},
            None,
        ],
    )

    with pytest.raises(ValueError, match="replying to"):
        service.create_comment(
            USER_ID,
            STORY_ID,
            {
                "content": "My reply",
                "parent_id": PARENT_ID,
            },
        )

    assert cursor.execute.call_count == 4


def test_list_story_comments(monkeypatch):
    expected = [
        comment_row(),
    ]

    cursor = mock_connection(
        monkeypatch,
        [],
        fetchall_values=expected,
    )

    result = service.list_story_comments(STORY_ID)

    assert result == expected
    assert cursor.execute.call_count == 1

    sql = cursor.execute.call_args.args[0]
    assert "author_label" in sql
    assert "Former member" in sql
    assert "status = 'visible'" in sql


def test_list_story_comments_rejects_invalid_story_id(monkeypatch):
    def should_not_connect():
        raise AssertionError("Invalid story ID reached database")

    monkeypatch.setattr(service, "get_connection", should_not_connect)

    assert service.list_story_comments("invalid-id") == []


def test_delete_comment_without_replies(monkeypatch):
    cursor = mock_connection(
        monkeypatch,
        [
            {"id": COMMENT_ID},
            {"has_replies": False},
        ],
    )

    result = service.delete_comment(USER_ID, COMMENT_ID)

    assert result is True
    assert cursor.execute.call_count == 3

    final_sql = cursor.execute.call_args_list[-1].args[0]
    assert "DELETE FROM public.story_comments" in final_sql


def test_delete_comment_with_replies_hides_parent(monkeypatch):
    cursor = mock_connection(
        monkeypatch,
        [
            {"id": COMMENT_ID},
            {"has_replies": True},
        ],
    )

    result = service.delete_comment(USER_ID, COMMENT_ID)

    assert result is True
    assert cursor.execute.call_count == 3

    final_sql = cursor.execute.call_args_list[-1].args[0]
    assert "UPDATE public.story_comments" in final_sql
    assert "status = 'hidden'" in final_sql


def test_delete_comment_rejects_non_owner(monkeypatch):
    cursor = mock_connection(monkeypatch, [None])

    result = service.delete_comment(USER_ID, COMMENT_ID)

    assert result is False
    assert cursor.execute.call_count == 1


def test_delete_comment_rejects_invalid_id(monkeypatch):
    def should_not_connect():
        raise AssertionError("Invalid comment ID reached database")

    monkeypatch.setattr(service, "get_connection", should_not_connect)

    assert service.delete_comment(USER_ID, "invalid-id") is False
