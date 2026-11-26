
import io
from uuid import uuid4

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from getoffdeals.travel_stories import storage


STORY_ID = "33333333-3333-4333-8333-333333333333"


def make_image(image_format="JPEG", size=(100, 100), color="blue"):
    """Create an in-memory test image."""
    output = io.BytesIO()

    image = Image.new("RGB", size, color)
    image.save(output, format=image_format)
    output.seek(0)

    return output


def make_upload(image_format="JPEG", size=(100, 100)):
    """Create a Werkzeug upload object."""
    extension = {
        "JPEG": "photo.jpg",
        "PNG": "photo.png",
        "WEBP": "photo.webp",
    }[image_format]

    return FileStorage(
        stream=make_image(image_format, size),
        filename=extension,
        content_type=f"image/{image_format.lower()}",
    )


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_save_story_image_accepts_supported_formats(
    tmp_path, image_format
):
    upload = make_upload(image_format)

    path = storage.save_story_image(
        upload,
        STORY_ID,
        tmp_path,
    )

    saved_file = tmp_path / path

    assert saved_file.exists()
    assert saved_file.is_file()
    assert path.startswith(STORY_ID + "/")

    with Image.open(saved_file) as image:
        assert image.format == image_format


def test_save_story_image_uses_random_filename(tmp_path):
    first = storage.save_story_image(
        make_upload(),
        STORY_ID,
        tmp_path,
    )

    second = storage.save_story_image(
        make_upload(),
        STORY_ID,
        tmp_path,
    )

    assert first != second


def test_save_story_image_does_not_use_original_filename(tmp_path):
    upload = FileStorage(
        stream=make_image(),
        filename="../../private-information.jpg",
        content_type="image/jpeg",
    )

    path = storage.save_story_image(
        upload,
        STORY_ID,
        tmp_path,
    )

    assert ".." not in path
    assert "private-information" not in path


def test_save_story_image_rejects_invalid_file(tmp_path):
    upload = FileStorage(
        stream=io.BytesIO(b"This is not an image"),
        filename="photo.jpg",
        content_type="image/jpeg",
    )

    with pytest.raises(storage.ImageValidationError):
        storage.save_story_image(
            upload,
            STORY_ID,
            tmp_path,
        )


def test_save_story_image_rejects_unsupported_format(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (100, 100)).save(output, format="GIF")
    output.seek(0)

    upload = FileStorage(
        stream=output,
        filename="animation.gif",
        content_type="image/gif",
    )

    with pytest.raises(storage.ImageValidationError):
        storage.save_story_image(
            upload,
            STORY_ID,
            tmp_path,
        )


def test_save_story_image_rejects_oversized_file(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(storage, "MAX_IMAGE_BYTES", 100)

    upload = make_upload("PNG")

    with pytest.raises(storage.ImageValidationError):
        storage.save_story_image(
            upload,
            STORY_ID,
            tmp_path,
        )


def test_save_story_image_rejects_invalid_story_uuid(tmp_path):
    with pytest.raises(storage.ImageValidationError):
        storage.save_story_image(
            make_upload(),
            "invalid-story-id",
            tmp_path,
        )


def test_save_story_image_rejects_excessive_dimensions(tmp_path):
    upload = make_upload("PNG", size=(9000, 100))

    with pytest.raises(storage.ImageValidationError):
        storage.save_story_image(
            upload,
            STORY_ID,
            tmp_path,
        )


def test_delete_story_image_removes_saved_file(tmp_path):
    path = storage.save_story_image(
        make_upload(),
        STORY_ID,
        tmp_path,
    )

    saved_file = tmp_path / path

    assert saved_file.exists()

    result = storage.delete_story_image(
        path,
        tmp_path,
    )

    assert result is True
    assert not saved_file.exists()


def test_delete_story_image_rejects_path_traversal(tmp_path):
    result = storage.delete_story_image(
        "../../outside.jpg",
        tmp_path,
    )

    assert result is False


def test_delete_story_image_rejects_invalid_path(tmp_path):
    assert storage.delete_story_image("", tmp_path) is False
    assert storage.delete_story_image("photo.jpg", tmp_path) is False
