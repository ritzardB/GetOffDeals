
import os

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()


def get_connection():
    """Open a PostgreSQL connection using DATABASE_URL."""
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    return psycopg.connect(
        database_url,
        connect_timeout=10,
        row_factory=dict_row,
    )


def check_connection():
    """Verify PostgreSQL connectivity without modifying data."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database() AS database_name")
            result = cursor.fetchone()

    return result["database_name"]

