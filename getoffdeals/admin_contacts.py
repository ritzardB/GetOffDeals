

"""Administrator contact management for GetOffDeals."""

import csv
import io
import os

from uuid import UUID

from flask import (
    Blueprint,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
    current_app,
)

from getoffdeals.admin_auth import admin_required
from getoffdeals.database import get_connection

import hmac
import secrets


admin_contacts_bp = Blueprint(
    "admin_contacts",
    __name__,
    url_prefix="/admin",
)

PAGE_SIZE = 25


def generate_csrf_token(session):
    """Create or reuse an independent Admin Contacts CSRF token."""
    token = session.get("admin_contacts_csrf_token")

    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        session["admin_contacts_csrf_token"] = token

    return token


def validate_csrf_token(session, submitted_token):
    """Validate the Admin Contacts CSRF token securely."""
    expected = session.get("admin_contacts_csrf_token")

    return (
        isinstance(expected, str)
        and isinstance(submitted_token, str)
        and bool(submitted_token)
        and hmac.compare_digest(expected, submitted_token)
    )


CONTACTS_CTE = """
    WITH user_contacts AS (
        SELECT
            u.id,
            u.email,
            u.first_name,
            u.last_name,
            u.created_at,
            s.status AS newsletter_status,
            s.consent,
            s.consent_at,
            s.confirmed_at,
            s.unsubscribed_at,
            ai.status AS invitation_delivery_status,
            ai.created_at AS invitation_created_at,
            ai.sent_at AS invitation_sent_at,
            ai.last_error AS invitation_last_error
        FROM public.users AS u
        LEFT JOIN public.subscribers AS s
            ON LOWER(s.email) = LOWER(u.email)
        LEFT JOIN LATERAL (
            SELECT
                status,
                created_at,
                sent_at,
                last_error
            FROM public.admin_newsletter_invitation_outbox
            WHERE user_id = u.id
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) AS ai ON TRUE
    )
"""

def _filters():
    """Build safe, parameterized contact filters."""
    search = request.args.get("q", "").strip()[:200]
    status = request.args.get("status", "all").strip()

    allowed_statuses = {
        "all",
        "confirmed",
        "pending",
        "unsubscribed",
        "not_subscribed",
    }

    if status not in allowed_statuses:
        status = "all"

    conditions = []
    params = []

    if search:
        conditions.append(
            """
            (
                email ILIKE %s
                OR first_name ILIKE %s
                OR last_name ILIKE %s
            )
            """
        )
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])

    if status == "not_subscribed":
        conditions.append("newsletter_status IS NULL")
    elif status != "all":
        conditions.append("newsletter_status = %s")
        params.append(status)

    where = (
        "WHERE " + " AND ".join(conditions)
        if conditions else ""
    )

    return search, status, where, params



def _statistics(conn):
    """Return accurate registered-user and newsletter statistics."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                (
                    SELECT COUNT(*)
                    FROM public.users
                ) AS registered_users,

                (
                    SELECT COUNT(*)
                    FROM public.subscribers
                    WHERE status = 'confirmed'
                ) AS confirmed_subscribers,

                (
                    SELECT COUNT(*)
                    FROM public.users u
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM public.subscribers s
                        WHERE LOWER(s.email) = LOWER(u.email)
                    )
                ) AS registered_not_subscribed,

                (
                    SELECT COUNT(*)
                    FROM public.subscribers
                    WHERE status = 'pending'
                ) AS pending_subscribers,

                (
                    SELECT COUNT(*)
                    FROM public.subscribers
                    WHERE status = 'unsubscribed'
                ) AS unsubscribed_subscribers
        """)

        return cur.fetchone()


def _contact_rows(conn, where, params, limit=None, offset=0):
    """Retrieve registered users with their newsletter status."""
    pagination = ""
    query_params = list(params)

    if limit is not None:
        pagination = "LIMIT %s OFFSET %s"
        query_params.extend([limit, offset])

    with conn.cursor() as cur:
        cur.execute(
            CONTACTS_CTE + f"""
                SELECT *
                FROM user_contacts
                {where}
                ORDER BY created_at DESC, id
                {pagination}
            """,
            query_params,
        )
        return cur.fetchall()


@admin_contacts_bp.get("/contacts")
@admin_required
def contacts():
    """Display the administrator's registered-user directory."""
    search, status, where, params = _filters()

    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        page = 1

    with get_connection() as conn:
        statistics = _statistics(conn)

        with conn.cursor() as cur:
            cur.execute(
                CONTACTS_CTE + f"""
                    SELECT COUNT(*) AS total
                    FROM user_contacts
                    {where}
                """,
                params,
            )
            total = cur.fetchone()["total"]

        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, total_pages)

        rows = _contact_rows(
            conn,
            where,
            params,
            limit=PAGE_SIZE,
            offset=(page - 1) * PAGE_SIZE,
        )

    return render_template(
        "admin/contacts.html",
        statistics=statistics,
        contacts=rows,
        search=search,
        status=status,
        page=page,
        total_pages=total_pages,
        total=total,
        csrf_token=generate_csrf_token(session),
    )


def _csv_safe(value):
    """Prevent spreadsheet formula injection in exported cells."""
    value = "" if value is None else str(value)

    # Check after leading whitespace and control characters.
    probe = value.lstrip()

    if probe.startswith(("=", "+", "-", "@")):
        return "'" + value

    return value

@admin_contacts_bp.get("/contacts.csv")
@admin_required
def export_contacts():
    """Export matching registered users for authorized administrators."""
    _, _, where, params = _filters()

    with get_connection() as conn:
        rows = _contact_rows(conn, where, params)

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)

    writer.writerow([
        "User ID",
        "Email",
        "First Name",
        "Last Name",
        "Registration Date",
        "Newsletter Status",
        "Consent",
        "Consent Date",
        "Confirmation Date",
        "Unsubscribed Date",
        "Invitation Delivery Status",
        "Invitation Created Date",
        "Invitation Sent Date",
            ])

    for row in rows:
        writer.writerow([
            _csv_safe(row["id"]),
            _csv_safe(row["email"]),
            _csv_safe(row["first_name"]),
            _csv_safe(row["last_name"]),
            _csv_safe(row["created_at"]),
            _csv_safe(row["newsletter_status"] or "not_subscribed"),
            _csv_safe(row["consent"]),
            _csv_safe(row["consent_at"]),
            _csv_safe(row["confirmed_at"]),
            _csv_safe(row["unsubscribed_at"]),
            _csv_safe(row["invitation_delivery_status"] or "no_invitation"),
            _csv_safe(row["invitation_created_at"]),
            _csv_safe(row["invitation_sent_at"]),
        ])

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        'attachment; filename="getoffdeals-registered-users.csv"'
    )
    response.headers["Cache-Control"] = "no-store"

    return response



@admin_contacts_bp.post("/contacts/<user_id>/invite")
@admin_required
def invite_contact(user_id):
    """Queue an optional newsletter invitation for an eligible user."""

    submitted_token = request.form.get("csrf_token", "")

    if not validate_csrf_token(session, submitted_token):
        abort(400, description="Invalid security token. Refresh and try again.")

    try:
        user_id = str(UUID(str(user_id)))
    except (ValueError, TypeError, AttributeError):
        abort(404)

    public_base_url = os.getenv(
        "PUBLIC_BASE_URL", ""
    ).strip().rstrip("/")

    if not public_base_url.startswith("https://"):
        flash(
            "Invitation service requires a valid HTTPS configuration.",
            "error",
        )
        return redirect(url_for("admin_contacts.contacts"))

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Serialize invitation requests for this account.
                cur.execute(
                    """
                    SELECT id, email
                    FROM public.users
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (user_id,),
                )

                user = cur.fetchone()

                if user is None:
                    flash("Registered account not found.", "error")
                    return redirect(url_for("admin_contacts.contacts"))

                # Never invite pending, confirmed, or unsubscribed contacts.
                cur.execute(
                    """
                    SELECT status
                    FROM public.subscribers
                    WHERE LOWER(email) = LOWER(%s)
                    LIMIT 1
                    """,
                    (user["email"],),
                )

                if cur.fetchone() is not None:
                    flash(
                        "This account already has a newsletter subscription "
                        "record. No invitation was queued.",
                        "error",
                    )
                    return redirect(url_for("admin_contacts.contacts"))

                # Preserve any valid invitation from the welcome-email flow.
                cur.execute(
                    """
                    SELECT 1
                    FROM public.newsletter_invitations
                    WHERE user_id = %s
                      AND used_at IS NULL
                      AND expires_at > NOW()
                    LIMIT 1
                    """,
                    (user_id,),
                )

                if cur.fetchone():
                    flash(
                        "An active newsletter invitation already exists "
                        "for this account.",
                        "info",
                    )
                    return redirect(url_for("admin_contacts.contacts"))

                # Prevent multiple active administrator invitation jobs.
                cur.execute(
                    """
                    SELECT id
                    FROM public.admin_newsletter_invitation_outbox
                    WHERE user_id = %s
                      AND status IN ('pending', 'processing')
                    LIMIT 1
                    """,
                    (user_id,),
                )

                existing_job = cur.fetchone()

                if existing_job:
                    flash(
                        "An invitation is already queued or being processed "
                        "for this account.",
                        "info",
                    )
                    return redirect(url_for("admin_contacts.contacts"))

                # Queue only. The background worker handles Resend delivery.
                cur.execute(
                    """
                    INSERT INTO public.admin_newsletter_invitation_outbox (
                        user_id,
                        email
                    )
                    VALUES (%s, %s)
                    RETURNING id
                    """,
                    (user_id, user["email"]),
                )

                queued_job = cur.fetchone()

        flash(
            f"Newsletter invitation queued for {user['email']}. "
            "The background worker will process it.",
            "success",
        )

        current_app.logger.info(
            "Admin newsletter invitation queued: job_id=%s user_id=%s",
            queued_job["id"],
            user_id,
        )

    except Exception:
        current_app.logger.exception(
            "Could not queue admin newsletter invitation for user %s.",
            user_id,
        )
        flash(
            "The invitation could not be queued. Please check the database "
            "and try again.",
            "error",
        )

    return redirect(
        url_for(
            "admin_contacts.contacts",
            q=request.form.get("q", ""),
            status=request.form.get("status", "all"),
            page=request.form.get("page", "1"),
        )
    )
