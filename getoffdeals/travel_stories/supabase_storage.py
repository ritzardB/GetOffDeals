"""Supabase Storage integration for GetOffDeals Travel Stories."""

import os
import uuid
from urllib.parse import quote, urlparse
from uuid import UUID

import requests


DEFAULT_TIMEOUT = 20

CONTENT_TYPES = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


class SupabaseStorageError(RuntimeError):
    """Raised when a Supabase Storage operation fails."""


def _configuration():
    """Load and validate Supabase Storage configuration."""
    base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    bucket = os.getenv(
        "SUPABASE_TRAVEL_STORIES_BUCKET", ""
    ).strip()

    # Support either the newer secret key or legacy service-role key.
    secret_key = (
        os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )

    parsed = urlparse(base_url)

    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".supabase.co")
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise SupabaseStorageError(
            "Supabase URL configuration is invalid."
        )

    if not bucket or "/" in bucket or "\\" in bucket:
        raise SupabaseStorageError(
            "Travel Stories storage bucket is not configured."
        )

    if not secret_key:
        raise SupabaseStorageError(
            "Supabase server-side storage key is not configured."
        )

    return base_url, bucket, {
        "apikey": secret_key,
        "Authorization": f"Bearer {secret_key}",
    }


def _validate_storage_path(storage_path):
    """Validate a story UUID and a single image filename."""
    if not isinstance(storage_path, str) or not storage_path:
        raise SupabaseStorageError("Invalid image storage path.")

    parts = storage_path.split("/")

    if len(parts) != 2:
        raise SupabaseStorageError("Invalid image storage path.")

    try:
        story_id = str(UUID(parts[0]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SupabaseStorageError(
            "Invalid image storage path."
        ) from exc

    filename = parts[1]

    if (
        not filename
        or filename in {".", ".."}
        or filename != filename.strip()
        or "\\" in filename
        or "/" in filename
        or not any(
            filename.lower().endswith(extension)
            for _, extension in CONTENT_TYPES.values()
        )
    ):
        raise SupabaseStorageError("Invalid image filename.")

    return f"{story_id}/{filename}"


def _object_url(base_url, bucket, storage_path):
    """Build a safely encoded Supabase object endpoint."""
    encoded_bucket = quote(bucket, safe="")
    encoded_path = "/".join(
        quote(part, safe="")
        for part in storage_path.split("/")
    )

    return (
        f"{base_url}/storage/v1/object/"
        f"{encoded_bucket}/{encoded_path}"
    )


def upload_processed_image(processed, image_format, story_id):
    """
    Upload an already validated image.

    Returns the relative storage path:
        <story-uuid>/<random-uuid>.jpg
    """
    try:
        normalized_story_id = str(UUID(str(story_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SupabaseStorageError(
            "Invalid story identifier."
        ) from exc

    if image_format not in CONTENT_TYPES:
        raise SupabaseStorageError("Unsupported image format.")

    if not isinstance(processed, bytes) or not processed:
        raise SupabaseStorageError("Invalid image data.")

    content_type, extension = CONTENT_TYPES[image_format]

    filename = f"{uuid.uuid4().hex}{extension}"
    storage_path = f"{normalized_story_id}/{filename}"

    base_url, bucket, headers = _configuration()

    request_headers = {
        **headers,
        "Content-Type": content_type,
        "x-upsert": "false",
    }

    url = _object_url(base_url, bucket, storage_path)

    try:
        response = requests.post(
            url,
            headers=request_headers,
            data=processed,
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()

    except requests.RequestException as exc:
        status = getattr(
            getattr(exc, "response", None),
            "status_code",
            None,
        )

        raise SupabaseStorageError(
            "Supabase image upload failed"
            + (f" (HTTP {status})." if status else ".")
        ) from exc

    return storage_path


def get_public_image_url(storage_path):
    """Return a public URL for a validated image path."""
    normalized_path = _validate_storage_path(storage_path)
    base_url, bucket, _ = _configuration()

    encoded_bucket = quote(bucket, safe="")
    encoded_path = "/".join(
        quote(part, safe="")
        for part in normalized_path.split("/")
    )

    return (
        f"{base_url}/storage/v1/object/public/"
        f"{encoded_bucket}/{encoded_path}"
    )


def delete_story_image(storage_path):
    """Delete an image from Supabase Storage."""
    normalized_path = _validate_storage_path(storage_path)

    base_url, bucket, headers = _configuration()

    encoded_bucket = quote(bucket, safe="")
    url = f"{base_url}/storage/v1/object/{encoded_bucket}"

    try:
        response = requests.delete(
            url,
            headers={
                **headers,
                "Content-Type": "application/json",
            },
            json={"prefixes": [normalized_path]},
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()

        return True

    except requests.RequestException as exc:
        status = getattr(
            getattr(exc, "response", None),
            "status_code",
            None,
        )

        raise SupabaseStorageError(
            "Supabase image deletion failed"
            + (f" (HTTP {status})." if status else ".")
        ) from exc
