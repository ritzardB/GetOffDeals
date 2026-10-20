
"""PostgreSQL-backed Flask sessions using psycopg."""

import json
import secrets
from datetime import datetime, timedelta, timezone

from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict

from getoffdeals.database import get_connection


class ServerSideSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None, new=False):
        def on_update(session):
            session.modified = True

        super().__init__(initial or {}, on_update)
        self.sid = sid
        self.new = new
        self.modified = False

    def clear(self):
        # Ensure clearing an empty or populated session triggers cleanup.
        super().clear()
        self.modified = True


class PostgresSessionInterface(SessionInterface):
    """Store session contents in PostgreSQL; cookie contains only an ID."""

    session_class = ServerSideSession

    def __init__(self, lifetime=timedelta(hours=12)):
        self.lifetime = lifetime

    def _expiry(self):
        return datetime.now(timezone.utc) + self.lifetime

    def open_session(self, app, request):
        sid = request.cookies.get(self.get_cookie_name(app))

        if not sid or len(sid) > 128:
            return self.session_class(
                sid=secrets.token_urlsafe(32), new=True
            )

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_data
                    FROM public.web_sessions
                    WHERE session_id = %s AND expires_at > NOW()
                    """,
                    (sid,),
                )
                row = cur.fetchone()

        if not row:
            return self.session_class(
                sid=secrets.token_urlsafe(32), new=True
            )

        try:
            data = json.loads(bytes(row["session_data"]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, TypeError):
            data = {}

        if not isinstance(data, dict):
            data = {}

        return self.session_class(data, sid=sid)

    def save_session(self, app, session, response):
        cookie_name = self.get_cookie_name(app)
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)

        if not session:
            if session.modified:
                # Expire the browser cookie before attempting database cleanup.
                response.delete_cookie(
                    cookie_name,
                    domain=domain,
                    path=path,
                    secure=self.get_cookie_secure(app),
                    httponly=self.get_cookie_httponly(app),
                    samesite=self.get_cookie_samesite(app),
                )

                # A database failure still propagates to the caller.
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            DELETE FROM public.web_sessions
                            WHERE session_id = %s
                            """,
                            (session.sid,),
                        )
            return

        # Don't write unchanged sessions back to PostgreSQL.
        if not session.modified:
            return

        serialized = json.dumps(
            dict(session), separators=(",", ":")
        ).encode("utf-8")

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.web_sessions
                        (session_id, session_data, expires_at, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (session_id) DO UPDATE SET
                        session_data = EXCLUDED.session_data,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = NOW()
                    """,
                    (session.sid, serialized, self._expiry()),
                )

        response.set_cookie(
            cookie_name,
            session.sid,
            expires=self.get_expiration_time(app, session),
            httponly=self.get_cookie_httponly(app),
            secure=self.get_cookie_secure(app),
            samesite=self.get_cookie_samesite(app),
            domain=domain,
            path=path,
        )


def regenerate_session_id(session):
    """Rotate the session ID only after deleting the old server-side session."""
    old_sid = session.sid
    new_sid = secrets.token_urlsafe(32)

    if old_sid:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM public.web_sessions WHERE session_id = %s",
                    (old_sid,),
                )

    session.sid = new_sid
    session.new = True
    session.modified = True

