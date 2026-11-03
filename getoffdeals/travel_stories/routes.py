
"""Flask routes for the GetOffDeals Travel Stories feature."""

import logging
from pathlib import Path
from uuid import UUID

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from getoffdeals.travel_stories import service, storage
from getoffdeals.travel_stories.validators import (
    current_user_id,
    generate_csrf_token,
    validate_csrf_token,
    validate_story,
)

from getoffdeals.travel_stories.comment_validators import (
    validate_comment,
)

logger = logging.getLogger(__name__)

travel_stories_bp = Blueprint("travel_stories", __name__)


def _require_user_id():
    user_id = current_user_id(session)

    if user_id is None:
        return None

    return user_id


def _request_csrf_token():
    """Read CSRF token from a form or request header."""
    if request.is_json:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            return body.get("csrf_token")

    return request.form.get("csrf_token") or request.headers.get(
        "X-CSRF-Token"
    )


def _validate_request_csrf():
    if not validate_csrf_token(session, _request_csrf_token()):
        abort(400, description="Invalid security token. Refresh and try again.")


@travel_stories_bp.get("/travel-stories")
def story_feed():
    """Display published travel stories."""
    try:
        stories = service.list_published_stories()
    except Exception:
        current_app.logger.exception("Could not load Travel Stories feed.")
        abort(503)

    return render_template(
        "travel_stories/feed.html",
        stories=stories,
    )


@travel_stories_bp.get("/travel-stories/<slug>")
def story_detail(slug):
    """Display one published travel story."""
    story = service.get_published_story(slug)

    if story is None:
        abort(404)

    user_id = _require_user_id()

    gallery_images = service.list_published_story_images(story["id"])

    return render_template(
        "travel_stories/detail.html",
        story=story,
        gallery_images=gallery_images,
        is_authenticated=user_id is not None,
        csrf_token=(
            generate_csrf_token(session)
            if user_id is not None
            else ""
        ),
    )


@travel_stories_bp.get(
    "/travel-stories/images/<story_id>/<filename>"
)
def story_image(story_id, filename):
    """Serve an image only when it belongs to a published story."""
    try:
        normalized_story_id = str(UUID(str(story_id)))
    except (ValueError, TypeError, AttributeError):
        abort(404)

    if (
        not filename
        or filename != filename.strip()
        or "/" in filename
        or "\\" in filename
        or filename in {".", ".."}
    ):
        abort(404)

    try:
        storage_path = service.get_published_story_image_path(
            normalized_story_id,
            filename,
        )
    except Exception:
        current_app.logger.exception(
            "Could not verify travel story image."
        )
        abort(503)

    if storage_path is None:
        abort(404)

    upload_root = Path(
        current_app.config["TRAVEL_STORIES_UPLOAD_FOLDER"]
    ).resolve()

    image_path = (upload_root / storage_path).resolve()

    try:
        image_path.relative_to(upload_root)
    except ValueError:
        abort(404)

    if not image_path.is_file():
        abort(404)

    response = send_file(
        image_path,
        conditional=True,
        etag=True,
        max_age=3600,
    )

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "public, max-age=3600"

    return response


@travel_stories_bp.get("/travel-stories/create")
def story_create_page():
    """Display the story creation form."""
    user_id = _require_user_id()

    if user_id is None:
        return redirect(url_for("login_page"))

    return render_template(
        "travel_stories/create.html",
        csrf_token=generate_csrf_token(session),
        story=None,
        errors=None,
    )


@travel_stories_bp.post("/api/travel-stories")
def story_create():
    """Publish a story with optional cover and gallery images."""
    user_id = _require_user_id()

    if user_id is None:
        return jsonify(error="Please sign in to publish a story."), 401

    _validate_request_csrf()

    try:
        if request.is_json:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify(error="Invalid story data."), 400

            cover_upload = None
            gallery_uploads = []
        else:
            payload = request.form.to_dict()

            cover_upload = request.files.get("cover_image")
            if cover_upload and not cover_upload.filename:
                cover_upload = None

            gallery_uploads = [
                image
                for image in request.files.getlist("gallery_images")
                if image and image.filename
            ]

        values, error = validate_story(payload)

        if error:
            return jsonify(error=error), 400

        max_gallery = current_app.config[
            "TRAVEL_STORIES_MAX_GALLERY_IMAGES"
        ]

        if len(gallery_uploads) > max_gallery:
            return jsonify(
                error=(
                    f"You can upload a maximum of "
                    f"{max_gallery} gallery images."
                )
            ), 400

        # Validate and process all images in memory first.
        # No files are saved until the story has a database UUID.
        processed_cover = (
            storage.process_upload(cover_upload)
            if cover_upload is not None
            else None
        )

        processed_gallery = [
            storage.process_upload(image)
            for image in gallery_uploads
        ]

        upload_root = current_app.config[
            "TRAVEL_STORIES_UPLOAD_FOLDER"
        ]

        if processed_cover is None and not processed_gallery:
            story = service.create_story(user_id, values)
        else:
            story = service.create_story(
                user_id,
                values,
                cover_image=processed_cover,
                gallery_images=processed_gallery,
                upload_root=upload_root,
            )

    except storage.ImageValidationError as exc:
        return jsonify(error=str(exc)), 400

    except service.StoryDailyLimitReached as exc:
        return jsonify(error=str(exc)), 429

    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    except Exception:
        current_app.logger.exception(
            "Could not create travel story."
        )
        return jsonify(
            error="Unable to publish your story right now."
        ), 500

    return jsonify(
        message="Your travel story has been published.",
        story={
            "id": str(story["id"]),
            "title": story["title"],
            "slug": story["slug"],
            "url": url_for(
                "travel_stories.story_detail",
                slug=story["slug"],
                _external=False,
            ),
        },
    ), 201


@travel_stories_bp.get("/api/my-travel-stories")
def my_stories():
    """List stories belonging to the authenticated member."""
    user_id = _require_user_id()

    if user_id is None:
        return jsonify(error="Please sign in again."), 401

    try:
        stories = service.list_member_stories(user_id)
    except Exception:
        current_app.logger.exception("Could not load member stories.")
        return jsonify(error="Unable to load member stories."), 500

    story_items = []

    for story in stories:
        story_id = str(story["id"])
        cover_image_url = None
        cover_image_path = story.get("cover_image_path")

        if cover_image_path:
            image_path = Path(str(cover_image_path))

            if (
                image_path.parent.name == story_id
                and image_path.name not in {"", ".", ".."}
                and "/" not in image_path.name
                and "\\" not in image_path.name
            ):
                cover_image_url = url_for(
                    "travel_stories.story_image",
                    story_id=story_id,
                    filename=image_path.name,
                )

        story_items.append({
            "id": story_id,
            "title": story["title"],
            "slug": story["slug"],
            "destination": story["destination"],
            "country": story["country"],
            "status": story["status"],
            "cover_image_url": cover_image_url,
        })

    return jsonify(stories=story_items), 200


@travel_stories_bp.delete("/api/travel-stories/<story_id>")
def story_delete(story_id):
    """Delete a story owned by the authenticated member."""
    user_id = _require_user_id()

    if user_id is None:
        return jsonify(error="Please sign in again."), 401

    _validate_request_csrf()

    try:
        story_id = str(UUID(str(story_id)))
    except (ValueError, TypeError, AttributeError):
        return jsonify(error="Invalid story ID."), 400

    try:
        deleted = service.delete_story(
            user_id,
            story_id,
            upload_root=current_app.config.get(
                "TRAVEL_STORIES_UPLOAD_FOLDER"
            ),
        )
    except Exception:
        current_app.logger.exception("Could not delete travel story.")
        return jsonify(error="Unable to delete your story."), 500

    if not deleted:
        return jsonify(error="Story not found or access denied."), 404

    return jsonify(message="Story deleted successfully."), 200


@travel_stories_bp.post("/api/travel-stories/<story_id>/comments")
def comment_create(story_id):
    """Create a comment or reply on a published story."""
    user_id = _require_user_id()

    if user_id is None:
        return jsonify(error="Please sign in to comment."), 401

    _validate_request_csrf()

    payload = request.get_json(silent=True)

    values, error = validate_comment(payload)

    if error:
        return jsonify(error=error), 400

    try:
        comment = service.create_comment(
            user_id,
            story_id,
            values,
        )

    except service.CommentRateLimitReached as exc:
        return jsonify(error=str(exc)), 429

    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    except Exception:
        current_app.logger.exception("Could not create story comment.")
        return jsonify(error="Unable to post your comment right now."), 500

    return jsonify(
        message="Your comment has been posted.",
        comment={
            "id": str(comment["id"]),
            "story_id": str(comment["story_id"]),
            "parent_id": (
                str(comment["parent_id"])
                if comment["parent_id"]
                else None
            ),
            "content": comment["content"],
            "status": comment["status"],
        },
    ), 201


@travel_stories_bp.get("/api/travel-stories/<story_id>/comments")
def comment_list(story_id):
    """Return visible comments for a published story."""
    try:
        story = service.get_published_story_by_id(story_id)

        if story is None:
            return jsonify(error="Story not found."), 404

        comments = service.list_story_comments(story_id)

    except Exception:
        current_app.logger.exception("Could not load story comments.")
        return jsonify(error="Unable to load comments."), 500

    return jsonify(
        comments=[
        {
            "id": str(comment["id"]),
            "parent_id": (
                str(comment["parent_id"])
                if comment["parent_id"]
                else None
            ),
            "content": comment["content"],
            "author": comment["author_label"],
            "can_delete": bool(
                _require_user_id()
                and comment["user_id"] == _require_user_id()
            ),
            "created_at": (
                comment["created_at"].isoformat()
                if comment["created_at"]
                else None
            ),
        }
        for comment in comments
    ]
    ), 200


@travel_stories_bp.delete("/api/story-comments/<comment_id>")
def comment_delete(comment_id):
    """Delete a comment belonging to the authenticated member."""
    user_id = _require_user_id()

    if user_id is None:
        return jsonify(error="Please sign in again."), 401

    _validate_request_csrf()

    try:
        deleted = service.delete_comment(user_id, comment_id)

    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    except Exception:
        current_app.logger.exception("Could not delete story comment.")
        return jsonify(error="Unable to delete your comment."), 500

    if not deleted:
        return jsonify(error="Comment not found or access denied."), 404

    return jsonify(message="Comment deleted successfully."), 200
