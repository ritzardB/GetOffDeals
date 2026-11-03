
-- GetOffDeals Travel Stories V2
-- Migration: 20261030_travel_stories.sql
--
-- Purpose:
--   Create the database foundation for community travel stories.
--
-- Account deletion policy:
--   Published stories and comments are retained.
--   Author references become NULL when a member is deleted.
--   Likes are removed with the member account.
--   Reports are retained but reporter identity is detached.
--
-- IMPORTANT:
--   Review before applying to Supabase.
--   This migration has NOT been applied.
--
-- Existing dependencies:
--   public.users(id UUID PRIMARY KEY)
--
-- Application:
--   Flask + psycopg using getoffdeals.database.get_connection()
--
-- Security:
--   RLS is enabled on all five tables.
--   No permissive policies are created here.
--   Flask must enforce authorization because the current
--   application database connection uses the postgres role.

BEGIN;

-- =========================================================
-- 1. TRAVEL STORIES
-- =========================================================

CREATE TABLE IF NOT EXISTS public.travel_stories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- SET NULL preserves stories when an account is deleted.
    user_id UUID
        REFERENCES public.users(id)
        ON DELETE SET NULL,

    title TEXT NOT NULL
        CHECK (char_length(trim(title)) BETWEEN 5 AND 180),

    slug TEXT NOT NULL UNIQUE
        CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),

    destination TEXT NOT NULL
        CHECK (char_length(trim(destination)) BETWEEN 2 AND 150),

    country TEXT NOT NULL
        CHECK (char_length(trim(country)) BETWEEN 2 AND 100),

    content TEXT NOT NULL
        CHECK (char_length(trim(content)) BETWEEN 50 AND 50000),

    cover_image_path TEXT,

    status TEXT NOT NULL DEFAULT 'published'
        CHECK (status IN ('draft', 'published', 'hidden')),

    published_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT travel_stories_published_at_check
        CHECK (
            status <> 'published'
            OR published_at IS NOT NULL
        )
);

CREATE INDEX IF NOT EXISTS idx_travel_stories_user_id
    ON public.travel_stories(user_id);

CREATE INDEX IF NOT EXISTS idx_travel_stories_status_published
    ON public.travel_stories(status, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_travel_stories_destination
    ON public.travel_stories(destination);

CREATE INDEX IF NOT EXISTS idx_travel_stories_country
    ON public.travel_stories(country);


-- =========================================================
-- 2. STORY COMMENTS
-- =========================================================

CREATE TABLE IF NOT EXISTS public.story_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    story_id UUID NOT NULL
        REFERENCES public.travel_stories(id)
        ON DELETE CASCADE,

    -- Preserve comments but anonymize the author on deletion.
    user_id UUID
        REFERENCES public.users(id)
        ON DELETE SET NULL,

    -- Optional parent comment for threaded replies.
    parent_id UUID,

    content TEXT NOT NULL
        CHECK (char_length(trim(content)) BETWEEN 1 AND 5000),

    status TEXT NOT NULL DEFAULT 'visible'
        CHECK (status IN ('visible', 'hidden')),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Required for the composite self-reference below.
    CONSTRAINT story_comments_id_story_unique
        UNIQUE (id, story_id),

    -- A reply must belong to the same story as its parent.
    CONSTRAINT story_comments_parent_same_story
        FOREIGN KEY (parent_id, story_id)
        REFERENCES public.story_comments(id, story_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_story_comments_story_id
    ON public.story_comments(story_id, created_at);

CREATE INDEX IF NOT EXISTS idx_story_comments_user_id
    ON public.story_comments(user_id);

CREATE INDEX IF NOT EXISTS idx_story_comments_parent_id
    ON public.story_comments(parent_id);


-- =========================================================
-- 3. STORY LIKES
-- =========================================================

CREATE TABLE IF NOT EXISTS public.story_likes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    story_id UUID NOT NULL
        REFERENCES public.travel_stories(id)
        ON DELETE CASCADE,

    -- Likes are removed when the member account is deleted.
    user_id UUID NOT NULL
        REFERENCES public.users(id)
        ON DELETE CASCADE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One like per member per story.
    CONSTRAINT story_likes_unique_member_story
        UNIQUE (story_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_story_likes_user_id
    ON public.story_likes(user_id);


-- =========================================================
-- 4. STORY IMAGES
-- =========================================================

CREATE TABLE IF NOT EXISTS public.story_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    story_id UUID NOT NULL
        REFERENCES public.travel_stories(id)
        ON DELETE CASCADE,

    -- Path inside the Supabase Storage bucket.
    -- Do not store private storage credentials or tokens here.
    storage_path TEXT NOT NULL UNIQUE,

    position INTEGER NOT NULL DEFAULT 0
        CHECK (position >= 0),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_story_images_story_position
    ON public.story_images(story_id, position);


-- =========================================================
-- 5. STORY REPORTS
-- =========================================================

CREATE TABLE IF NOT EXISTS public.story_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Exactly one report target must be supplied.
    story_id UUID
        REFERENCES public.travel_stories(id)
        ON DELETE CASCADE,

    comment_id UUID
        REFERENCES public.story_comments(id)
        ON DELETE CASCADE,

    -- Preserve reports while anonymizing the reporter.
    reporter_id UUID
        REFERENCES public.users(id)
        ON DELETE SET NULL,

    reason TEXT NOT NULL
        CHECK (
            reason IN (
                'spam',
                'harassment',
                'inappropriate',
                'misinformation',
                'copyright',
                'other'
            )
        ),

    details TEXT
        CHECK (
            details IS NULL
            OR char_length(details) <= 2000
        ),

    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            status IN (
                'pending',
                'reviewed',
                'resolved',
                'dismissed'
            )
        ),

    reviewed_by UUID
        REFERENCES public.users(id)
        ON DELETE SET NULL,

    reviewed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT story_reports_exactly_one_target
        CHECK (
            (story_id IS NOT NULL AND comment_id IS NULL)
            OR
            (story_id IS NULL AND comment_id IS NOT NULL)
        )
);

CREATE INDEX IF NOT EXISTS idx_story_reports_status_created
    ON public.story_reports(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_story_reports_story_id
    ON public.story_reports(story_id)
    WHERE story_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_story_reports_comment_id
    ON public.story_reports(comment_id)
    WHERE comment_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_story_reports_reporter_id
    ON public.story_reports(reporter_id);


-- =========================================================
-- 6. ROW LEVEL SECURITY
-- =========================================================
--
-- RLS is enabled as a secure default for future access models.
-- No client-facing policies are created in this migration.
--
-- The current Flask application uses the PostgreSQL postgres
-- role, which bypasses ordinary RLS enforcement.
-- Therefore, Flask authorization remains mandatory.
--
-- Do not expose direct database credentials to browsers.

ALTER TABLE public.travel_stories
    ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.story_comments
    ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.story_likes
    ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.story_images
    ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.story_reports
    ENABLE ROW LEVEL SECURITY;


-- =========================================================
-- 7. TABLE DOCUMENTATION
-- =========================================================

COMMENT ON TABLE public.travel_stories IS
    'Community travel stories published by GetOffDeals members.';

COMMENT ON COLUMN public.travel_stories.user_id IS
    'Nullable author reference. NULL means the original member account was deleted or anonymized.';

COMMENT ON TABLE public.story_comments IS
    'Comments and threaded replies attached to travel stories.';

COMMENT ON COLUMN public.story_comments.user_id IS
    'Nullable author reference to preserve comments after account deletion.';

COMMENT ON TABLE public.story_likes IS
    'Member likes on travel stories.';

COMMENT ON TABLE public.story_images IS
    'Image storage paths and display order for travel stories.';

COMMENT ON TABLE public.story_reports IS
    'Private moderation reports submitted by community members.';

COMMIT;
