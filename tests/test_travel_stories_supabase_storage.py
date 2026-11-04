import requests
import pytest

from getoffdeals.travel_stories import supabase_storage as storage


STORY_ID = "33333333-3333-4333-8333-333333333333"


def configure_storage(monkeypatch):
    monkeypatch.setenv(
        "SUPABASE_URL",
        "https://example.supabase.co",
    )
    monkeypatch.setenv(
        "SUPABASE_SECRET_KEY",
        "sb_secret_test_key",
    )
    monkeypatch.setenv(
        "SUPABASE_TRAVEL_STORIES_BUCKET",
        "travel-stories",
    )


def test_upload_processed_image(monkeypatch):
    configure_storage(monkeypatch)

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(storage.requests, "post", fake_post)

    path = storage.upload_processed_image(
        b"test-image",
        "JPEG",
        STORY_ID,
    )

    assert path.startswith(STORY_ID + "/")
    assert path.endswith(".jpg")
    assert captured["url"].startswith(
        "https://example.supabase.co/storage/v1/object/"
    )
    assert captured["data"] == b"test-image"
    assert captured["headers"]["Content-Type"] == "image/jpeg"


def test_public_image_url(monkeypatch):
    configure_storage(monkeypatch)

    path = f"{STORY_ID}/photo.jpg"

    url = storage.get_public_image_url(path)

    assert url == (
        "https://example.supabase.co/storage/v1/object/public/"
        f"travel-stories/{path}"
    )


def test_delete_story_image(monkeypatch):
    configure_storage(monkeypatch)

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_delete(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(
        storage.requests,
        "delete",
        fake_delete,
    )

    result = storage.delete_story_image(
        f"{STORY_ID}/photo.jpg"
    )

    assert result is True
    assert captured["json"] == {
        "prefixes": [f"{STORY_ID}/photo.jpg"]
    }


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../../outside.jpg",
        "photo.jpg",
        f"{STORY_ID}/../../outside.jpg",
        f"{STORY_ID}/photo.gif",
        "invalid-uuid/photo.jpg",
    ],
)
def test_rejects_invalid_storage_paths(path, monkeypatch):
    configure_storage(monkeypatch)

    with pytest.raises(storage.SupabaseStorageError):
        storage.get_public_image_url(path)


def test_rejects_invalid_story_uuid(monkeypatch):
    configure_storage(monkeypatch)

    with pytest.raises(storage.SupabaseStorageError):
        storage.upload_processed_image(
            b"image",
            "JPEG",
            "invalid-story-id",
        )


def test_rejects_unsupported_image_format(monkeypatch):
    configure_storage(monkeypatch)

    with pytest.raises(storage.SupabaseStorageError):
        storage.upload_processed_image(
            b"image",
            "GIF",
            STORY_ID,
        )


def test_upload_failure_is_handled(monkeypatch):
    configure_storage(monkeypatch)

    def fake_post(*args, **kwargs):
        raise requests.Timeout("Timed out")

    monkeypatch.setattr(storage.requests, "post", fake_post)

    with pytest.raises(storage.SupabaseStorageError):
        storage.upload_processed_image(
            b"image",
            "JPEG",
            STORY_ID,
        )


def test_delete_failure_is_handled(monkeypatch):
    configure_storage(monkeypatch)

    def fake_delete(*args, **kwargs):
        raise requests.ConnectionError("Connection failed")

    monkeypatch.setattr(
        storage.requests,
        "delete",
        fake_delete,
    )

    with pytest.raises(storage.SupabaseStorageError):
        storage.delete_story_image(
            f"{STORY_ID}/photo.jpg"
        )


def test_missing_secret_key_is_rejected(monkeypatch):
    monkeypatch.setenv(
        "SUPABASE_URL",
        "https://example.supabase.co",
    )
    monkeypatch.setenv(
        "SUPABASE_TRAVEL_STORIES_BUCKET",
        "travel-stories",
    )
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv(
        "SUPABASE_SERVICE_ROLE_KEY",
        raising=False,
    )

    with pytest.raises(storage.SupabaseStorageError):
        storage.get_public_image_url(
            f"{STORY_ID}/photo.jpg"
        )

@pytest.mark.parametrize("status_code", [400, 401, 403, 500])
def test_upload_http_error_is_handled(
    monkeypatch,
    status_code,
):
    configure_storage(monkeypatch)

    class FakeResponse:
        def raise_for_status(self):
            response = requests.Response()
            response.status_code = status_code
            raise requests.HTTPError(
                f"HTTP {status_code}",
                response=response,
            )

    monkeypatch.setattr(
        storage.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(
        storage.SupabaseStorageError,
        match=f"HTTP {status_code}",
    ):
        storage.upload_processed_image(
            b"image",
            "JPEG",
            STORY_ID,
        )


@pytest.mark.parametrize("status_code", [401, 403, 404, 500])
def test_delete_http_error_is_handled(
    monkeypatch,
    status_code,
):
    configure_storage(monkeypatch)

    class FakeResponse:
        def raise_for_status(self):
            response = requests.Response()
            response.status_code = status_code
            raise requests.HTTPError(
                f"HTTP {status_code}",
                response=response,
            )

    monkeypatch.setattr(
        storage.requests,
        "delete",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(
        storage.SupabaseStorageError,
        match=f"HTTP {status_code}",
    ):
        storage.delete_story_image(
            f"{STORY_ID}/photo.jpg"
        )
