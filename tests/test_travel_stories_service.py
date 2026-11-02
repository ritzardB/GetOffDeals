
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from getoffdeals.travel_stories import service


USER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_USER_ID = "44444444-4444-4444-8444-444444444444"
STORY_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.fixture
def fake_database(monkeypatch):
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def fake_connection():
        yield connection

    monkeypatch.setattr(service, "get_connection", fake_connection)

    return cursor, connection


def valid_values():
    return {
        "title": "My Amazing Trip to Tokyo",
        "destination": "Tokyo",
        "country": "Japan",
        "content": (
            "Tokyo was an incredible experience. "
            "The food, culture and people made this trip unforgettable."
        ),
    }


def story_row():
    return {
        "id": STORY_ID,
        "user_id": USER_ID,
        "title": "My Amazing Trip to Tokyo",
        "slug": "my-amazing-trip-to-tokyo",
        "destination": "Tokyo",
        "country": "Japan",
        "content": valid_values()["content"],
        "cover_image_path": None,
        "status": "published",
        "published_at": None,
        "created_at": None,
        "updated_at": None,
    }


def test_create_story_inserts_published_story(fake_database):
    cursor, _ = fake_database

    cursor.fetchone.side_effect = [
        {"id": USER_ID},          # Member exists and is locked
        {"story_count": 0},       # No stories published today
        story_row(),              # Inserted story
    ]

    result = service.create_story(USER_ID, valid_values())

    assert result["id"] == STORY_ID
    assert result["status"] == "published"
    assert cursor.execute.call_count == 3

    lock_sql = cursor.execute.call_args_list[0].args[0]
    count_sql = cursor.execute.call_args_list[1].args[0]
    insert_sql = cursor.execute.call_args_list[2].args[0]

    assert "FOR UPDATE" in lock_sql
    assert "COUNT(*)" in count_sql
    assert "Asia/Dubai" in count_sql
    assert "INSERT INTO public.travel_stories" in insert_sql
    assert "'published'" in insert_sql
    assert "NOW()" in insert_sql


def test_create_story_retries_duplicate_slug(fake_database):
    cursor, _ = fake_database

    cursor.fetchone.side_effect = [
        {"id": USER_ID},          # Member exists and is locked
        {"story_count": 0},       # No stories published today
        None,                     # First slug already exists
        story_row(),              # Retry succeeds
    ]

    result = service.create_story(USER_ID, valid_values())

    assert result["id"] == STORY_ID
    assert cursor.execute.call_count == 4

    first_params = cursor.execute.call_args_list[2].args[1]
    second_params = cursor.execute.call_args_list[3].args[1]

    assert first_params["slug"] == "my-amazing-trip-to-tokyo"
    assert second_params["slug"].startswith(
        "my-amazing-trip-to-tokyo-"
    )


def test_create_story_rejects_invalid_user_id(fake_database):
    with pytest.raises(ValueError):
        service.create_story("not-a-uuid", valid_values())


def test_list_published_stories_uses_pagination(fake_database):
    cursor, _ = fake_database
    cursor.fetchall.return_value = [story_row()]

    result = service.list_published_stories(limit=10, offset=5)

    assert len(result) == 1

    params = cursor.execute.call_args.args[1]
    assert params == (10, 5)

    sql = cursor.execute.call_args.args[0]
    assert "status = 'published'" in sql
    assert "LIMIT %s OFFSET %s" in sql


def test_list_published_stories_clamps_limit(fake_database):
    cursor, _ = fake_database
    cursor.fetchall.return_value = []

    service.list_published_stories(limit=1000, offset=-10)

    params = cursor.execute.call_args.args[1]
    assert params == (50, 0)


def test_get_published_story_returns_story(fake_database):
    cursor, _ = fake_database
    cursor.fetchone.return_value = story_row()

    result = service.get_published_story("my-amazing-trip-to-tokyo")

    assert result["id"] == STORY_ID

    sql = cursor.execute.call_args.args[0]
    assert "WHERE slug = %s" in sql
    assert "status = 'published'" in sql


def test_get_published_story_rejects_empty_slug(fake_database):
    cursor, _ = fake_database

    result = service.get_published_story(" ")

    assert result is None
    cursor.execute.assert_not_called()


def test_list_member_stories_filters_by_owner(fake_database):
    cursor, _ = fake_database
    cursor.fetchall.return_value = [story_row()]

    result = service.list_member_stories(USER_ID)

    assert len(result) == 1

    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]

    assert "WHERE user_id = %s" in sql
    assert params == (USER_ID,)


def test_update_story_restricts_to_owner(fake_database):
    cursor, _ = fake_database
    cursor.fetchone.return_value = story_row()

    result = service.update_story(USER_ID, STORY_ID, valid_values())

    assert result["id"] == STORY_ID

    sql = cursor.execute.call_args.args[0]

    assert "WHERE id = %(story_id)s" in sql
    assert "AND user_id = %(user_id)s" in sql


def test_update_story_returns_none_for_invalid_id(fake_database):
    cursor, _ = fake_database

    result = service.update_story(USER_ID, "invalid-id", valid_values())

    assert result is None
    cursor.execute.assert_not_called()


def test_delete_story_restricts_to_owner(fake_database):
    cursor, _ = fake_database
    cursor.fetchone.return_value = {"id": STORY_ID}

    result = service.delete_story(USER_ID, STORY_ID)

    assert result is True

    sql = cursor.execute.call_args.args[0]

    assert "DELETE FROM public.travel_stories" in sql
    assert "WHERE id = %s" in sql
    assert "AND user_id = %s" in sql

    params = cursor.execute.call_args.args[1]
    assert params == (STORY_ID, USER_ID)


def test_delete_story_returns_false_for_invalid_id(fake_database):
    cursor, _ = fake_database

    result = service.delete_story(USER_ID, "invalid-id")

    assert result is False
    cursor.execute.assert_not_called()


def test_delete_story_returns_false_when_not_owned(fake_database):
    cursor, _ = fake_database
    cursor.fetchone.return_value = None

    result = service.delete_story(OTHER_USER_ID, STORY_ID)

    assert result is False


def test_create_story_rejects_fourth_story_today(fake_database):
    cursor, _ = fake_database

    cursor.fetchone.side_effect = [
        {"id": USER_ID},          # Member exists and is locked
        {"story_count": 3},       # Already published three today
    ]

    with pytest.raises(service.StoryDailyLimitReached):
        service.create_story(USER_ID, valid_values())

    # No INSERT should occur.
    assert cursor.execute.call_count == 2

    count_sql = cursor.execute.call_args_list[1].args[0]
    assert "COUNT(*)" in count_sql
    assert "Asia/Dubai" in count_sql


def test_create_story_rejects_missing_member(fake_database):
    cursor, _ = fake_database

    cursor.fetchone.return_value = None

    with pytest.raises(ValueError, match="Authenticated member"):
        service.create_story(USER_ID, valid_values())

    # Stop after checking the member. No count or INSERT.
    assert cursor.execute.call_count == 1

    lock_sql = cursor.execute.call_args.args[0]
    assert "FOR UPDATE" in lock_sql


def test_create_story_saves_cover_and_gallery_images(
    fake_database, monkeypatch, tmp_path
):
    cursor, _ = fake_database

    cursor.fetchone.side_effect = [
        {"id": USER_ID},
        {"story_count": 0},
        story_row(),
    ]

    saved_images = []

    def fake_save(processed, image_format, story_id, upload_root):
        saved_images.append((processed, image_format, str(story_id)))
        return f"{story_id}/{len(saved_images)}.jpg"

    monkeypatch.setattr(
        service.storage,
        "save_processed_image",
        fake_save,
    )

    result = service.create_story(
        USER_ID,
        valid_values(),
        cover_image=(b"cover", "JPEG"),
        gallery_images=[
            (b"gallery-1", "JPEG"),
            (b"gallery-2", "PNG"),
        ],
        upload_root=str(tmp_path),
    )

    assert result["id"] == STORY_ID
    assert result["cover_image_path"] == f"{STORY_ID}/1.jpg"

    assert len(saved_images) == 3
    assert all(item[2] == STORY_ID for item in saved_images)

    gallery_calls = [
        call for call in cursor.execute.call_args_list
        if "INSERT INTO public.story_images" in call.args[0]
    ]

    assert len(gallery_calls) == 2
    assert gallery_calls[0].args[1] == (
        STORY_ID, f"{STORY_ID}/2.jpg", 0
    )
    assert gallery_calls[1].args[1] == (
        STORY_ID, f"{STORY_ID}/3.jpg", 1
    )


def test_create_story_cleans_up_images_when_gallery_save_fails(
    fake_database, monkeypatch, tmp_path
):
    cursor, _ = fake_database

    cursor.fetchone.side_effect = [
        {"id": USER_ID},
        {"story_count": 0},
        story_row(),
    ]

    saved_paths = []
    deleted_paths = []

    def fake_save(processed, image_format, story_id, upload_root):
        if processed == b"gallery":
            raise service.storage.ImageStorageError(
                "Simulated storage failure."
            )

        path = f"{story_id}/cover.jpg"
        saved_paths.append(path)
        return path

    def fake_delete(path, upload_root):
        deleted_paths.append(path)
        return True

    monkeypatch.setattr(
        service.storage,
        "save_processed_image",
        fake_save,
    )
    monkeypatch.setattr(
        service.storage,
        "delete_story_image",
        fake_delete,
    )

    with pytest.raises(
        service.storage.ImageStorageError,
        match="Simulated storage failure",
    ):
        service.create_story(
            USER_ID,
            valid_values(),
            cover_image=(b"cover", "JPEG"),
            gallery_images=[(b"gallery", "JPEG")],
            upload_root=str(tmp_path),
        )

    assert saved_paths == [f"{STORY_ID}/cover.jpg"]
    assert deleted_paths == saved_paths
