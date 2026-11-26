
"""PostgreSQL service operations for Travel Stories."""

import logging
from uuid import UUID, uuid4

from getoffdeals.database import get_connection
from getoffdeals.travel_stories import supabase_storage
from getoffdeals.travel_stories.validators import make_slug

logger = logging.getLogger(__name__)

class StoryDailyLimitReached(Exception):
    """Raised when a member exceeds the daily publishing limit."""

class CommentRateLimitReached(Exception):
    """Raised when a member exceeds the hourly comment limit."""

def _canonical_user_id(user_id):
    """Validate and normalize a member UUID."""
    try:
        return str(UUID(str(user_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("A valid member ID is required.") from exc



def _insert_story(cur, user_id, values, slug, cover_image_path=None):
    """Insert a published story and return its database record."""
    cur.execute(
        """
        INSERT INTO public.travel_stories (
            user_id,
            title,
            slug,
            destination,
            country,
            content,
            cover_image_path,
            status,
            published_at
        )
        VALUES (
            %(user_id)s,
            %(title)s,
            %(slug)s,
            %(destination)s,
            %(country)s,
            %(content)s,
            %(cover_image_path)s,
            'published',
            NOW()
        )
        ON CONFLICT (slug) DO NOTHING
        RETURNING
            id, user_id, title, slug, destination, country,
            content, cover_image_path, status, published_at,
            created_at, updated_at
        """,
        {
            "user_id": user_id,
            **values,
            "slug": slug,
            "cover_image_path": cover_image_path,
        },
    )
    return cur.fetchone()



def create_story(
    user_id,
    values,
    cover_image=None,
    gallery_images=None,
):
    """Create a story and save its images to Supabase Storage."""

    user_id = _canonical_user_id(user_id)
    base_slug = make_slug(values["title"])
    gallery_images = gallery_images or []

    if not isinstance(gallery_images, list):
        raise ValueError("Gallery images must be a list.")

    if len(gallery_images) > 10:
        raise ValueError("A maximum of 10 gallery images is allowed.")

    created_paths = []

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT id
                    FROM public.users
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (user_id,),
                )

                if cur.fetchone() is None:
                    raise ValueError("Authenticated member was not found.")

                cur.execute(
                    """
                    WITH dubai_day AS (
                        SELECT
                            (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Dubai')::date
                            AS local_date
                    )
                    SELECT COUNT(*) AS story_count
                    FROM public.travel_stories, dubai_day
                    WHERE user_id = %s
                      AND status = 'published'
                      AND published_at >= (
                          dubai_day.local_date::timestamp
                          AT TIME ZONE 'Asia/Dubai'
                      )
                      AND published_at < (
                          (dubai_day.local_date + 1)::timestamp
                          AT TIME ZONE 'Asia/Dubai'
                      )
                    """,
                    (user_id,),
                )

                result = cur.fetchone()
                daily_count = result["story_count"]

                if daily_count >= 3:
                    raise StoryDailyLimitReached(
                        "You have reached the limit of 3 published stories "
                        "today. Please try again tomorrow."
                    )

                story = _insert_story(
                    cur, user_id, values, base_slug
                )

                if story is None:
                    unique_slug = f"{base_slug}-{uuid4().hex[:8]}"
                    story = _insert_story(
                        cur, user_id, values, unique_slug
                    )

                if story is None:
                    raise RuntimeError("Could not create a unique story URL.")

                story_id = story["id"]

                # Upload cover image to Supabase Storage.
                cover_path = None

                if cover_image is not None:
                    cover_bytes, cover_format = cover_image

                    cover_path = supabase_storage.upload_processed_image(
                        cover_bytes,
                        cover_format,
                        story_id,
                    )

                    created_paths.append(cover_path)

                    cur.execute(
                        """
                        UPDATE public.travel_stories
                        SET cover_image_path = %s
                        WHERE id = %s
                        """,
                        (cover_path, story_id),
                    )

                # Upload gallery images to Supabase Storage.
                gallery_paths = []

                for image_bytes, image_format in gallery_images:
                    image_path = supabase_storage.upload_processed_image(
                        image_bytes,
                        image_format,
                        story_id,
                    )

                    created_paths.append(image_path)
                    gallery_paths.append(image_path)

                # Save gallery image references in PostgreSQL.
                for position, image_path in enumerate(gallery_paths):
                    cur.execute(
                        """
                        INSERT INTO public.story_images (
                            story_id,
                            storage_path,
                            position
                        )
                        VALUES (%s, %s, %s)
                        """,
                        (story_id, image_path, position),
                    )

                story["cover_image_path"] = cover_path

                return dict(story)

    except Exception:
        # Remove uploaded Supabase objects if story creation fails.
        for image_path in reversed(created_paths):
            try:
                supabase_storage.delete_story_image(image_path)
            except Exception:
                logger.exception(
                    "Could not clean up uploaded image after story creation "
                    "failed: %s",
                    image_path,
                )

        raise

def list_published_stories(limit=20, offset=0):
    """Return published stories, newest first."""
    limit = max(1, min(int(limit), 50))
    offset = max(0, int(offset))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, user_id, title, slug, destination, country,
                    content, cover_image_path, status, published_at,
                    created_at, updated_at
                FROM public.travel_stories
                WHERE status = 'published'
                ORDER BY published_at DESC, created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return [dict(row) for row in cur.fetchall()]


def get_published_story(slug):
    """Find one publicly visible story by slug."""
    if not isinstance(slug, str) or not slug.strip():
        return None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, user_id, title, slug, destination, country,
                    content, cover_image_path, status, published_at,
                    created_at, updated_at
                FROM public.travel_stories
                WHERE slug = %s
                  AND status = 'published'
                """,
                (slug.strip(),),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_published_story_by_id(story_id):
    """Find a publicly visible story by UUID."""
    try:
        story_id = str(UUID(str(story_id)))
    except (ValueError, TypeError, AttributeError):
        return None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, user_id, title, slug, destination, country,
                    content, cover_image_path, status, published_at,
                    created_at, updated_at
                FROM public.travel_stories
                WHERE id = %s
                  AND status = 'published'
                """,
                (story_id,),
            )

            row = cur.fetchone()
            return dict(row) if row else None


def get_published_story_image_path(story_id, filename):
    """Return an image path only if it belongs to a published story."""
    try:
        story_id = str(UUID(str(story_id)))
    except (ValueError, TypeError, AttributeError):
        return None

    if not isinstance(filename, str) or not filename:
        return None

    if filename != filename.strip() or "/" in filename or "\\" in filename:
        return None

    expected_path = f"{story_id}/{filename}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cover_image_path AS storage_path
                FROM public.travel_stories
                WHERE id = %s
                  AND status = 'published'
                  AND cover_image_path = %s

                UNION ALL

                SELECT images.storage_path
                FROM public.story_images AS images
                INNER JOIN public.travel_stories AS stories
                    ON stories.id = images.story_id
                WHERE stories.id = %s
                  AND stories.status = 'published'
                  AND images.storage_path = %s

                LIMIT 1
                """,
                (
                    story_id,
                    expected_path,
                    story_id,
                    expected_path,
                ),
            )

            row = cur.fetchone()
            return row["storage_path"] if row else None


def list_published_story_images(story_id):
    """Return gallery images belonging to a published story."""
    try:
        story_id = str(UUID(str(story_id)))
    except (ValueError, TypeError, AttributeError):
        return []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT images.storage_path, images.position
                FROM public.story_images AS images
                INNER JOIN public.travel_stories AS stories
                    ON stories.id = images.story_id
                WHERE stories.id = %s
                  AND stories.status = 'published'
                ORDER BY images.position ASC, images.created_at ASC
                """,
                (story_id,),
            )

            return [dict(row) for row in cur.fetchall()]


def list_member_stories(user_id):
    """Return stories belonging to the authenticated member."""
    user_id = _canonical_user_id(user_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, user_id, title, slug, destination, country,
                    content, cover_image_path, status, published_at,
                    created_at, updated_at
                FROM public.travel_stories
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            return [dict(row) for row in cur.fetchall()]


def update_story(user_id, story_id, values):
    """Update a story only when it belongs to the authenticated member."""
    user_id = _canonical_user_id(user_id)

    try:
        story_id = str(UUID(str(story_id)))
    except (ValueError, TypeError, AttributeError):
        return None

    base_slug = make_slug(values["title"])
    unique_slug = f"{base_slug}-{uuid4().hex[:8]}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.travel_stories
                SET
                    title = %(title)s,
                    slug = %(slug)s,
                    destination = %(destination)s,
                    country = %(country)s,
                    content = %(content)s,
                    updated_at = NOW()
                WHERE id = %(story_id)s
                  AND user_id = %(user_id)s
                  AND status = 'published'
                RETURNING
                    id, user_id, title, slug, destination, country,
                    content, cover_image_path, status, published_at,
                    created_at, updated_at
                """,
                {
                    "story_id": story_id,
                    "user_id": user_id,
                    "slug": unique_slug,
                    **values,
                },
            )
            row = cur.fetchone()

            return dict(row) if row else None


def delete_story(user_id, story_id):
    """
    Delete a member-owned story and clean up its Supabase images.

    Database deletion is committed before Supabase image cleanup.
    """
    user_id = _canonical_user_id(user_id)

    try:
        story_id = str(UUID(str(story_id)))
    except (ValueError, TypeError, AttributeError):
        return False

    image_paths = []

    # Collect image paths and delete the story in one transaction.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, cover_image_path
                FROM public.travel_stories
                WHERE id = %s
                  AND user_id = %s
                FOR UPDATE
                """,
                (story_id, user_id),
            )

            story = cur.fetchone()

            if not story:
                return False

            if story.get("cover_image_path"):
                image_paths.append(story["cover_image_path"])

            cur.execute(
                """
                SELECT storage_path
                FROM public.story_images
                WHERE story_id = %s
                ORDER BY position ASC, created_at ASC
                """,
                (story_id,),
            )

            gallery_images = cur.fetchall()

            image_paths.extend(
                image["storage_path"]
                for image in gallery_images
                if image.get("storage_path")
            )

            cur.execute(
                """
                DELETE FROM public.travel_stories
                WHERE id = %s
                  AND user_id = %s
                RETURNING id
                """,
                (story_id, user_id),
            )

            deleted = cur.fetchone()

            if not deleted:
                return False

    # Database transaction has committed.
    # Remove the associated objects from Supabase Storage.
    for image_path in dict.fromkeys(image_paths):
        try:
            removed = supabase_storage.delete_story_image(image_path)

            if not removed:
                logger.warning(
                    "Could not remove Supabase image %s "
                    "for deleted story %s.",
                    image_path,
                    story_id,
                )

        except Exception:
            logger.exception(
                "Supabase image cleanup failed for deleted story %s: %s",
                story_id,
                image_path,
            )

    return True


def create_comment(user_id, story_id, values):
    """Create a comment or reply with a per-member hourly limit."""
    user_id = _canonical_user_id(user_id)

    try:
        story_id = str(UUID(str(story_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("A valid story ID is required.") from exc

    parent_id = values.get("parent_id")
    content = values["content"]

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Serialize comment requests for this member.
            cur.execute(
                """
                SELECT id
                FROM public.users
                WHERE id = %s
                FOR UPDATE
                """,
                (user_id,),
            )

            if cur.fetchone() is None:
                raise ValueError("Authenticated member was not found.")

            # Enforce a rolling 60-minute limit.
            cur.execute(
                """
                SELECT COUNT(*) AS comment_count
                FROM public.story_comments
                WHERE user_id = %s
                  AND created_at >= statement_timestamp() - INTERVAL '1 hour'
                """,
                (user_id,),
            )

            result = cur.fetchone()

            if result["comment_count"] >= 10:
                raise CommentRateLimitReached(
                    "You have reached the limit of 10 comments per hour. "
                    "Please try again later."
                )

            # Verify that the story is still published.
            cur.execute(
                """
                SELECT id
                FROM public.travel_stories
                WHERE id = %s
                  AND status = 'published'
                FOR SHARE
                """,
                (story_id,),
            )

            if cur.fetchone() is None:
                raise ValueError("Story not found or unavailable.")

            # A reply must target a visible comment in this story.
            if parent_id is not None:
                cur.execute(
                    """
                    SELECT id
                    FROM public.story_comments
                    WHERE id = %s
                      AND story_id = %s
                      AND status = 'visible'
                      AND parent_id IS NULL
                    """,
                    (parent_id, story_id),
                )

                if cur.fetchone() is None:
                    raise ValueError(
                        "The comment you're replying to is unavailable."
                    )

            cur.execute(
                """
                INSERT INTO public.story_comments (
                    story_id,
                    user_id,
                    parent_id,
                    content,
                    status
                )
                VALUES (%s, %s, %s, %s, 'visible')
                RETURNING
                    id, story_id, user_id, parent_id,
                    content, status, created_at, updated_at
                """,
                (story_id, user_id, parent_id, content),
            )

            return dict(cur.fetchone())


def list_story_comments(story_id):
    """Return visible comments and replies for a published story."""
    try:
        story_id = str(UUID(str(story_id)))
    except (ValueError, TypeError, AttributeError):
        return []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.id,
                    c.story_id,
                    c.user_id,
                    c.parent_id,
                    c.content,
                    c.status,
                    c.created_at,
                    c.updated_at,
                    CASE
                        WHEN c.user_id IS NULL THEN 'Former member'
                        ELSE 'GetOffDeals member'
                    END AS author_label
                FROM public.story_comments AS c
                WHERE c.story_id = %s
                  AND c.status = 'visible'
                ORDER BY c.created_at ASC, c.id ASC
                """,
                (story_id,),
            )

            return [dict(row) for row in cur.fetchall()]


def delete_comment(user_id, comment_id):
    """
    Delete a member's comment.

    Comments with replies are hidden rather than deleted so that
    their replies are not removed by the database cascade.
    """
    user_id = _canonical_user_id(user_id)

    try:
        comment_id = str(UUID(str(comment_id)))
    except (ValueError, TypeError, AttributeError):
        return False

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM public.story_comments
                WHERE id = %s
                  AND user_id = %s
                  AND status = 'visible'
                FOR UPDATE
                """,
                (comment_id, user_id),
            )

            if cur.fetchone() is None:
                return False

            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM public.story_comments
                    WHERE parent_id = %s
                ) AS has_replies
                """,
                (comment_id,),
            )

            has_replies = cur.fetchone()["has_replies"]

            if has_replies:
                cur.execute(
                    """
                    UPDATE public.story_comments
                    SET
                        status = 'hidden',
                        content = '[This comment was deleted.]',
                        updated_at = statement_timestamp()
                    WHERE id = %s
                    """,
                    (comment_id,),
                )
            else:
                cur.execute(
                    """
                    DELETE FROM public.story_comments
                    WHERE id = %s
                    """,
                    (comment_id,),
                )

            return True
