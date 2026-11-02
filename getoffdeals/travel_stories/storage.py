
"""Secure local image storage for GetOffDeals Travel Stories."""

import io
import os
import uuid
import warnings
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageOps, UnidentifiedImageError


ALLOWED_FORMATS = {
    "JPEG": ("JPEG", ".jpg"),
    "PNG": ("PNG", ".png"),
    "WEBP": ("WEBP", ".webp"),
}

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_DIMENSION = 8000


class ImageValidationError(ValueError):
    """Raised when an uploaded image is invalid or unsupported."""

class ImageStorageError(RuntimeError):
    """Raised when an image cannot be saved or deleted."""


def _validate_story_id(story_id):
    """Validate and normalize the story UUID."""
    try:
        return str(UUID(str(story_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ImageValidationError("Invalid story identifier.") from exc


def _read_upload(upload):
    """Read an uploaded file while enforcing the byte limit."""
    if upload is None or not hasattr(upload, "stream"):
        raise ImageValidationError("No image was provided.")

    try:
        upload.stream.seek(0)
        data = upload.stream.read(MAX_IMAGE_BYTES + 1)
        upload.stream.seek(0)
    except (OSError, AttributeError) as exc:
        raise ImageValidationError("Unable to read the uploaded image.") from exc

    if not data:
        raise ImageValidationError("The uploaded image is empty.")

    if len(data) > MAX_IMAGE_BYTES:
        raise ImageValidationError("Each image must be 5 MB or smaller.")

    return data


def _process_image(data):
    """
    Verify and re-encode an image.

    Only JPEG, PNG and WebP are accepted.
    Re-encoding removes embedded metadata such as EXIF.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)

            # First pass: verify the actual image file.
            with Image.open(io.BytesIO(data)) as source:
                image_format = source.format

                if image_format not in ALLOWED_FORMATS:
                    raise ImageValidationError(
                        "Only JPEG, PNG and WebP images are allowed."
                    )

                if getattr(source, "n_frames", 1) != 1:
                    raise ImageValidationError(
                        "Animated images are not supported."
                    )

                width, height = source.size

                if width <= 0 or height <= 0:
                    raise ImageValidationError("Invalid image dimensions.")

                if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                    raise ImageValidationError(
                        "Image dimensions must not exceed 8,000 pixels."
                    )

                if width * height > MAX_IMAGE_PIXELS:
                    raise ImageValidationError(
                        "Image resolution is too large."
                    )

                source.verify()

            # Second pass: fully decode, normalize orientation and re-encode.
            with Image.open(io.BytesIO(data)) as source:
                if source.format != image_format:
                    raise ImageValidationError("Invalid image format.")

                source.load()
                image = ImageOps.exif_transpose(source)

                if image_format == "JPEG":
                    if image.mode not in ("RGB", "L"):
                        background = Image.new("RGB", image.size, "white")

                        if "A" in image.getbands():
                            background.paste(
                                image,
                                mask=image.getchannel("A"),
                            )
                        else:
                            background.paste(image.convert("RGB"))

                        image = background
                    else:
                        image = image.convert("RGB")

                elif image_format == "PNG":
                    if image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                        image = image.convert("RGBA")

                elif image_format == "WEBP":
                    if image.mode not in ("RGB", "RGBA"):
                        image = image.convert("RGBA")

                output = io.BytesIO()

                save_options = {}

                if image_format == "JPEG":
                    save_options = {
                        "quality": 88,
                        "optimize": True,
                    }
                elif image_format == "PNG":
                    save_options = {
                        "optimize": True,
                    }
                elif image_format == "WEBP":
                    save_options = {
                        "quality": 88,
                        "method": 4,
                    }

                image.save(
                    output,
                    format=image_format,
                    **save_options,
                )

                processed = output.getvalue()

                if not processed:
                    raise ImageValidationError(
                        "Unable to process the uploaded image."
                    )

                return processed, image_format

    except ImageValidationError:
        raise

    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise ImageValidationError(
            "The uploaded file is not a valid supported image."
        ) from exc



def process_upload(upload):
    """
    Validate and re-encode an uploaded image in memory.

    Returns:
        (processed_bytes, image_format)
    """
    data = _read_upload(upload)
    return _process_image(data)


def save_processed_image(processed, image_format, story_id, upload_root):
    """
    Save an already-validated image under its actual story UUID.

    Returns a relative path:
        <story-uuid>/<random-uuid>.jpg
    """
    normalized_story_id = _validate_story_id(story_id)

    if image_format not in ALLOWED_FORMATS:
        raise ImageValidationError("Unsupported image format.")

    if not isinstance(processed, bytes) or not processed:
        raise ImageValidationError("Invalid processed image data.")

    _, extension = ALLOWED_FORMATS[image_format]

    filename = f"{uuid.uuid4().hex}{extension}"
    relative_path = Path(normalized_story_id) / filename

    root = Path(upload_root).resolve()
    story_directory = (root / normalized_story_id).resolve()

    if story_directory.parent != root:
        raise ImageValidationError("Invalid image storage location.")

    story_directory.mkdir(parents=True, exist_ok=True)

    destination = (story_directory / filename).resolve()

    if destination.parent != story_directory:
        raise ImageValidationError("Invalid image destination.")

    try:
        with destination.open("xb") as image_file:
            image_file.write(processed)

    except OSError as exc:
        raise ImageStorageError(
            "Unable to save the uploaded image."
        ) from exc

    return relative_path.as_posix()


def save_story_image(upload, story_id, upload_root):
    """Validate and save an uploaded image under its story UUID."""
    processed, image_format = process_upload(upload)

    return save_processed_image(
        processed,
        image_format,
        story_id,
        upload_root,
    )


def delete_story_image(storage_path, upload_root):
    """
    Delete an image using its database storage path.

    Paths are restricted to a story UUID directory and one filename.
    """
    if not isinstance(storage_path, str) or not storage_path:
        return False

    relative_path = Path(storage_path)

    if relative_path.is_absolute() or len(relative_path.parts) != 2:
        return False

    if ".." in relative_path.parts:
        return False

    try:
        story_id = str(UUID(relative_path.parts[0]))
    except ValueError:
        return False

    filename = relative_path.parts[1]

    if not filename or Path(filename).name != filename:
        return False

    root = Path(upload_root).resolve()
    story_directory = (root / story_id).resolve()
    destination = (story_directory / filename).resolve()

    if story_directory.parent != root:
        return False

    if destination.parent != story_directory:
        return False

    if not destination.is_file():
        return False

    try:
        destination.unlink()

        # Remove the story directory if it is empty.
        try:
            story_directory.rmdir()
        except OSError:
            pass

        return True

    except OSError:
        return False
