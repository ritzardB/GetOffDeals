
import os

import psycopg
import pytest
from dotenv import load_dotenv
from psycopg.rows import dict_row


load_dotenv()

EXPECTED_DATABASE = "getoffdeals_travel_stories_test"


@pytest.fixture
def postgres_test_db():
    """Provide an isolated local PostgreSQL test connection."""

    database_url = os.getenv("TEST_DATABASE_URL")

    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    def connect():
        return psycopg.connect(
            database_url,
            connect_timeout=5,
            row_factory=dict_row,
        )

    # Verify the database identity before allowing tests to run.
    with connect() as conn:
        identity = conn.execute(
            """
            SELECT current_database() AS database_name,
                   inet_server_addr() AS server_address
            """
        ).fetchone()

        if identity["database_name"] != EXPECTED_DATABASE:
            raise RuntimeError(
                "Refusing to run integration tests against an unexpected database"
            )

        if identity["server_address"] is not None:
            raise RuntimeError(
                "Refusing to run integration tests against a remote database"
            )

        # Verify required tables exist.
        tables = conn.execute(
            """
            SELECT
                to_regclass('public.subscribers') AS subscribers,
                to_regclass('public.resend_sync_outbox') AS outbox
            """
        ).fetchone()

        if tables["subscribers"] is None:
            raise RuntimeError("Missing public.subscribers table")

        if tables["outbox"] is None:
            raise RuntimeError("Missing public.resend_sync_outbox table")

    tracked_emails = set()

    def track_email(email):
        tracked_emails.add(email)

    yield {
        "connect": connect,
        "track_email": track_email,
    }

    # Remove only records created for this test.
    if tracked_emails:
        with connect() as conn:
            for email in tracked_emails:
                conn.execute(
                    """
                    DELETE FROM public.resend_sync_outbox
                    WHERE LOWER(email) = LOWER(%s)
                    """,
                    (email,),
                )

                conn.execute(
                    """
                    DELETE FROM public.subscribers
                    WHERE LOWER(email) = LOWER(%s)
                    """,
                    (email,),
                )
