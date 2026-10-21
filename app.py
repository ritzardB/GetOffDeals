
"""GetOffDeals: Filipino-focused flight deals MVP.

Demo fares are inspiration only. Live flight search requires Amadeus credentials.
Affiliate redirects use a configured partner URL template or the approved
Aviasales tracking link configured in the environment.
"""

import os
import re
import sqlite3
import time
from datetime import date
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, session

from getoffdeals.postgres_sessions import (
    PostgresSessionInterface,
    regenerate_session_id,
)

load_dotenv()

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# Secure server-side authentication session configuration.
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("COOKIE_SECURE", "").lower() == "true"
)

# Store session contents in PostgreSQL; the browser cookie holds only a random ID.
app.session_interface = PostgresSessionInterface()

DB_PATH = os.getenv(
    "TAKEOFF_DB_PATH",
    os.path.join(os.path.dirname(__file__), "takeoff.sqlite3"),
)

# Illustrative inspiration prices only; never present these as live promotions.
DEMO_DEALS = [
    {
        "destination": "Manila, Philippines",
        "code": "MNL",
        "price": 1299,
        "currency": "AED",
        "tag": "Homecoming",
        "emoji": "🇵🇭",
        "days": "Flexible stays",
        "note": "Reconnect with family, food and the places that feel like home.",
        "category": "homecoming",
        "origin": "AUH",
    },
    {
        "destination": "Cebu, Philippines",
        "code": "CEB",
        "price": 1499,
        "currency": "AED",
        "tag": "Island time",
        "emoji": "🌴",
        "days": "5–8 nights",
        "note": "Island hopping, clear water and a slower pace in the Visayas.",
        "category": "nature",
        "origin": "AUH",
    },
    {
        "destination": "Clark, Philippines",
        "code": "CRK",
        "price": 1399,
        "currency": "AED",
        "tag": "Northern Luzon",
        "emoji": "⛰️",
        "days": "Flexible stays",
        "note": "A useful gateway for Central Luzon and trips beyond the capital.",
        "category": "homecoming",
        "origin": "DXB",
    },
    {
        "destination": "Kalibo, Philippines",
        "code": "KLO",
        "price": 1599,
        "currency": "AED",
        "tag": "Beach escape",
        "emoji": "🏝️",
        "days": "4–7 nights",
        "note": "A gateway for exploring Aklan and nearby island destinations.",
        "category": "nature",
        "origin": "AUH",
    },
    {
        "destination": "Istanbul, Türkiye",
        "code": "IST",
        "price": 1099,
        "currency": "AED",
        "tag": "City break",
        "emoji": "🕌",
        "days": "4–6 nights",
        "note": "Historic streets, waterfront views and lively markets.",
        "category": "city",
        "origin": "AUH",
    },
    {
        "destination": "Tbilisi, Georgia",
        "code": "TBS",
        "price": 699,
        "currency": "AED",
        "tag": "Mountain air",
        "emoji": "🏔️",
        "days": "4–6 nights",
        "note": "Old-town cafés, mountain views and a change of scenery.",
        "category": "nature",
        "origin": "AUH",
    },
]

TRAVELPAYOUTS_CACHE_SECONDS = 30 * 60

_travelpayouts_cache = {
    "expires": 0,
    "deals": None,
}

TRAVELPAYOUTS_ROUTES = [
    {
        "origin": "AUH",
        "code": "MNL",
        "destination": "Manila, Philippines",
        "tag": "Homecoming",
        "emoji": "🇵🇭",
        "category": "homecoming",
        "note": "Reconnect with family, food and the places that feel like home.",
        "image": "/static/images/manila.jpg",
    },
    {
        "origin": "AUH",
        "code": "CEB",
        "destination": "Cebu, Philippines",
        "tag": "Island time",
        "emoji": "🌴",
        "category": "nature",
        "note": "Island hopping, clear water and a slower pace in the Visayas.",
        "image": "/static/images/cebu.jpg",
    },
    {
        "origin": "DXB",
        "code": "CRK",
        "destination": "Clark, Philippines",
        "tag": "Northern Luzon",
        "emoji": "⛰️",
        "category": "homecoming",
        "note": "A useful gateway for Central Luzon and trips beyond the capital.",
        "image": "/static/images/clark.jpg",
    },
    {
        "origin": "AUH",
        "code": "KLO",
        "destination": "Kalibo, Philippines",
        "tag": "Beach escape",
        "emoji": "🏝️",
        "category": "nature",
        "note": "Explore Boracay, Aklan and nearby island destinations.",
        "image": "/static/images/boracay.jpg",
    },
    {
        "origin": "AUH",
        "code": "IST",
        "destination": "Istanbul, Türkiye",
        "tag": "City break",
        "emoji": "🕌",
        "category": "city",
        "note": "Historic streets, waterfront views and lively markets.",
        "image": "/static/images/turkeyi.jpg",
    },
    {
        "origin": "AUH",
        "code": "TBS",
        "destination": "Tbilisi, Georgia",
        "tag": "Mountain air",
        "emoji": "🏔️",
        "category": "nature",
        "note": "Old-town cafés, mountain views and a change of scenery.",
        "image": "/static/images/tbilisi.jpg",
    },
]


def affiliate_is_configured():
    """Return whether an affiliate URL template or approved tracking URL exists."""
    template = os.getenv("AFFILIATE_SEARCH_URL_TEMPLATE", "").strip()
    affiliate_url = os.getenv("AVIASALES_AFFILIATE_URL", "").strip()

    return bool(
        template
        or affiliate_url.startswith("https://aviasales.tpm.li/")
    )


def fetch_travelpayouts_deals():
    """Return the cheapest cached fare found for each configured route."""
    token = os.getenv("TRAVELPAYOUTS_API_TOKEN")

    if not token:
        raise RuntimeError("Travelpayouts API token is not configured")

    deals = []
    partner_configured = affiliate_is_configured()

    for route in TRAVELPAYOUTS_ROUTES:
        response = requests.get(
            "https://api.travelpayouts.com/v2/prices/latest",
            headers={"X-Access-Token": token},
            params={
                "currency": "usd",
                "period_type": "year",
                "page": 1,
                "limit": 30,
                "show_to_affiliates": "true",
                "sorting": "price",
                "trip_class": 0,
                "origin": route["origin"],
                "destination": route["code"],
            },
            timeout=15,
        )

        response.raise_for_status()
        payload = response.json()

        if not payload.get("success"):
            app.logger.warning(
                "Travelpayouts returned no success for %s-%s",
                route["origin"],
                route["code"],
            )
            continue

        fares = payload.get("data", [])

        if not isinstance(fares, list) or not fares:
            continue

        valid_fares = [
            fare
            for fare in fares
            if isinstance(fare, dict)
            and isinstance(fare.get("value"), (int, float))
            and fare["value"] > 0
        ]

        if not valid_fares:
            continue

        fare = min(valid_fares, key=lambda item: item["value"])

        departure = fare.get("depart_date", "")
        return_date = fare.get("return_date", "")
        found_at = fare.get("found_at", "")

        deals.append(
            {
                **route,
                "price": fare["value"],
                "currency": "USD",
                "days": (
                    f"{departure} – {return_date}"
                    if departure and return_date
                    else departure or "Dates vary"
                ),
                "priceLabel": "cached fare",
                "source": "travelpayouts",
                "foundAt": found_at,
                "gate": fare.get("gate", ""),
                "partnerConfigured": partner_configured,
            }
        )

    return deals



def supabase_auth_config():
    """Return validated Supabase Auth configuration and request headers."""
    from urllib.parse import urlparse

    base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()

    parsed_url = urlparse(base_url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or not parsed_url.hostname.endswith(".supabase.co")
        or parsed_url.path
        or parsed_url.query
        or parsed_url.fragment
        or not publishable_key.startswith("sb_publishable_")
    ):
        raise RuntimeError("Supabase Auth configuration is invalid")

    return base_url, {
        "apikey": publishable_key,
        "Content-Type": "application/json",
    }


def supabase_auth_request(endpoint, payload=None, method="POST"):
    """Call Supabase Auth without exposing credentials or response secrets."""
    base_url, headers = supabase_auth_config()
    url = f"{base_url}/auth/v1/{endpoint.lstrip('/')}"

    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            json=payload,
            timeout=(5, 15),
            allow_redirects=False,
        )
    except requests.RequestException:
        app.logger.warning("Supabase Auth request failed to connect")
        return None, "Supabase Auth is temporarily unavailable."

    if 300 <= response.status_code < 400:
        app.logger.warning("Supabase Auth returned an unexpected redirect")
        return None, "Supabase Auth returned an unexpected response."

    try:
        data = response.json()
    except ValueError:
        data = {}

    if not response.ok:
        if response.status_code in (400, 401, 422):
            return None, "Unable to authenticate. Check your details or verify your email."
        return None, "Supabase Auth could not complete the request."

    if not isinstance(data, dict):
        return None, "Supabase Auth returned an unexpected response."

    return data, None

@app.post("/auth/register")
def auth_register():
    """Register an account through Supabase; require email verification."""
    if not request.is_json:
        return jsonify(error="Send a JSON request."), 400

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Invalid request body."), 400


    email = body.get("email")
    password = body.get("password")
    first_name = body.get("first_name")
    last_name = body.get("last_name", "")

    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify(error="Email and password are required."), 400

    if not isinstance(first_name, str) or not isinstance(last_name, str):
        return jsonify(error="Enter a valid name."), 400

    email = email.strip().lower()
    first_name = first_name.strip()
    last_name = last_name.strip()

    if not first_name or len(first_name) > 80 or len(last_name) > 80:
        return jsonify(error="Enter a valid first and last name."), 400

    if (
        len(email) > 254
        or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
    ):
        return jsonify(error="Enter a valid email address."), 400

    if len(password) < 8 or len(password) > 128:
        return jsonify(error="Password must be between 8 and 128 characters."), 400

    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify(error="Email and password are required."), 400

    email = email.strip().lower()
    if (
        len(email) > 254
        or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
    ):
        return jsonify(error="Enter a valid email address."), 400

    if len(password) < 8 or len(password) > 128:
        return jsonify(error="Password must be between 8 and 128 characters."), 400

    try:
        data, error = supabase_auth_request(
            "signup",
            payload={
                "email": email,
                "password": password,
                "data": {
                    "first_name": first_name,
                    "last_name": last_name,
                },
            }
        )
    except RuntimeError:
        app.logger.error("Supabase Auth configuration is invalid")
        return jsonify(error="Registration is temporarily unavailable."), 503

    if error:
        return jsonify(error=error), 400

    # Never establish a logged-in session during registration.
    # Supabase email confirmation must happen first.
    return jsonify(
        message=(
            "If registration was accepted, check your email for a "
            "verification link before signing in."
        )
    ), 202

@app.post("/auth/login")
def auth_login():
    """Authenticate through Supabase and establish a server-side session."""

    if not request.is_json:
        return jsonify(error="Send a JSON request."), 400

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Invalid request body."), 400

    email = body.get("email")
    password = body.get("password")

    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify(error="Email and password are required."), 400

    email = email.strip().lower()
    if (
        len(email) > 254
        or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
        or not password
        or len(password) > 128
    ):
        return jsonify(error="Invalid email or password."), 400

    try:
        data, error = supabase_auth_request(
            "token?grant_type=password",
            payload={"email": email, "password": password},
        )
    except RuntimeError:
        app.logger.error("Supabase Auth configuration is invalid")
        return jsonify(error="Login is temporarily unavailable."), 503

    if error or not isinstance(data, dict):
        return jsonify(error="Invalid credentials or unverified email."), 401

    user = data.get("user")
    if not isinstance(user, dict) or not user.get("id"):
        return jsonify(error="Unable to authenticate this account."), 401

    if not (user.get("email_confirmed_at") or user.get("confirmed_at")):
        return jsonify(error="Please verify your email before signing in."), 403

    # Rotate the session ID to prevent session fixation.
    try:
        regenerate_session_id(session)
    except Exception:
        app.logger.exception("Could not rotate the login session")
        return jsonify(error="Login is temporarily unavailable."), 503

    session.clear()

    session["user_id"] = user["id"]
    session["email"] = user.get("email", email)

    user_metadata = user.get("user_metadata")
    if not isinstance(user_metadata, dict):
        user_metadata = {}

    session["first_name"] = (
        user_metadata.get("first_name", "").strip()
        if isinstance(user_metadata.get("first_name"), str)
        else ""
    )
    session["last_name"] = (
        user_metadata.get("last_name", "").strip()
        if isinstance(user_metadata.get("last_name"), str)
        else ""
    )


    return jsonify(
        message="Login successful.",
        user={
            "id": session["user_id"],
            "email": session["email"],
        }
    ), 200


@app.post("/auth/logout")
def auth_logout():
    """Clear the session and redirect browser users home."""
    session.clear()

    # Regular browser form submissions should return to the homepage.
    if "text/html" in request.headers.get("Accept", ""):
        return redirect("/", code=303)

    # Preserve the JSON response for API clients.
    return jsonify(message="Logged out successfully."), 200


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                consent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS affiliate_clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                departure TEXT,
                return_date TEXT,
                adults INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


init_db()


def amadeus_token():
    """Request an Amadeus access token."""
    key = os.getenv("AMA_API_KEY")
    secret = os.getenv("AMA_API_SECRET")

    if not key or not secret:
        return None

    base = os.getenv(
        "AMADEUS_BASE_URL",
        "https://test.api.amadeus.com",
    ).rstrip("/")

    response = requests.post(
        f"{base}/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": key,
            "client_secret": secret,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=15,
    )

    response.raise_for_status()
    return response.json()["access_token"]


def partner_search_url(
    origin,
    destination,
    departure="",
    return_date="",
    adults=1,
):
    """Use a configured partner template or the approved Aviasales tracking link."""
    template = os.getenv("AFFILIATE_SEARCH_URL_TEMPLATE", "").strip()

    # Use a documented deep-link template if one is configured.
    if template:
        values = {
            "origin": quote(origin),
            "destination": quote(destination),
            "departure": quote(departure),
            "return_date": quote(return_date),
            "adults": str(adults),
        }

        try:
            url = template.format(**values)
        except (KeyError, ValueError):
            app.logger.error(
                "Affiliate URL template has invalid placeholders"
            )
            return None

        if not url.startswith("https://"):
            app.logger.error(
                "Affiliate URL template must produce an HTTPS URL"
            )
            return None

        return url

    # Otherwise, use the exact Aviasales tracking link.
    affiliate_url = os.getenv("AVIASALES_AFFILIATE_URL", "").strip()

    if affiliate_url.startswith("https://aviasales.tpm.li/"):
        return affiliate_url

    return None


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault(
        "Referrer-Policy",
        "strict-origin-when-cross-origin",
    )
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


@app.get("/")
def home():
    return render_template(
        "index.html",
        origin=os.getenv("DEFAULT_ORIGIN", "AUH"),
    )

@app.get("/flights")
def flights():
    return render_template("flights.html")


@app.get("/login")
def login_page():
    if session.get("user_id"):
        return redirect("/")
    return render_template("login.html")


@app.get("/register")
def register_page():
    if session.get("user_id"):
        return redirect("/")
    return render_template("register.html")


# Trust and transparency pages
@app.get("/about")
def about():
    return render_template(
        "info_page.html",
        title="About GetOffDeals",
        page_heading="About GetOffDeals",
        updated="October 15, 2026",
        content=[
            (
                "Our mission",
                "GetOffDeals helps Filipino travellers in the UAE and the "
                "Philippines discover flight deals and travel inspiration "
                "in one convenient place.",
            ),
            (
                "How we work",
                "We aim to make researching travel options easier. Prices "
                "and examples displayed on the site may be illustrative "
                "and are not guaranteed live fares or available offers. "
                "Always confirm the final price, baggage rules, schedule, "
                "and booking conditions with the airline or booking provider.",
            ),
            (
                "How we may earn",
                "Some links may be affiliate links. If you book through a "
                "qualifying link, we may earn a commission at no additional "
                "cost to you. Affiliate relationships do not guarantee that "
                "an offer is the cheapest available.",
            ),
            (
                "Contact",
                "Questions or feedback? Email inforichapps@gmail.com.",
            ),
        ],
    )


@app.get("/contact")
def contact():
    return render_template(
        "info_page.html",
        title="Contact GetOffDeals",
        page_heading="Contact Us",
        updated="October 15, 2026",
        content=[
            (
                "Get in touch",
                "For questions, feedback, corrections, or business inquiries, "
                "email us at inforichapps@gmail.com.",
            ),
            (
                "Before booking",
                "GetOffDeals does not issue airline tickets unless explicitly "
                "stated. Your booking, payment, cancellation, and refund "
                "arrangements are handled by the airline or booking provider "
                "you choose.",
            ),
        ],
    )

@app.get("/privacy")
def privacy():
    return render_template(
        "info_page.html",
        title="Privacy Policy",
        page_heading="Privacy Policy",
        updated="October 15, 2026",
        content=[
            (
                "Information we may collect",
                "Depending on the features you use, we may receive information "
                "you submit directly, such as an email address entered into "
                "a contact or subscription form, along with basic technical "
                "information generated when you visit the site.",
            ),
            (
                "How information may be used",
                "Information may be used to respond to inquiries, operate "
                "and improve the website, prevent abuse, and provide features "
                "you request.",
            ),
            (
                "Cookies and analytics",
                "The website or its service providers may use cookies or "
                "similar technologies for site functionality, traffic "
                "measurement, or affiliate attribution if those services "
                "are enabled. The exact technologies depend on the services "
                "configured on the live site.",
            ),
            (
                "Affiliate links and third parties",
                "When you follow a link to an airline, travel agency, or "
                "affiliate partner, that provider's website and privacy "
                "policy apply. We do not control third-party websites or "
                "their data practices.",
            ),
            (
                "Data retention and your choices",
                "We should retain personal information only as needed for "
                "the purpose for which it was collected and applicable "
                "obligations. To ask about information you submitted to us, "
                "email inforichapps@gmail.com.",
            ),
            (
                "Contact",
                "For privacy questions, contact inforichapps@gmail.com.",
            ),
        ],
    )

@app.get("/terms")
def terms():
    return render_template(
        "info_page.html",
        title="Terms of Use",
        page_heading="Terms of Use",
        updated="October 15, 2026",
        content=[
            (
                "Use of this website",
                "You may use GetOffDeals for lawful personal travel research. "
                "Do not misuse the website, attempt unauthorized access, or "
                "interfere with its operation.",
            ),
            (
                "Prices and availability",
                "Flight prices, promotions, schedules, and availability can "
                "change without notice. Any sample or illustrative price is "
                "not a live quote or guarantee. Verify all details with the "
                "airline or booking provider before paying.",
            ),
            (
                "Third-party bookings",
                "Bookings made through external providers are subject to "
                "their terms, fees, policies, and conditions. The provider "
                "is responsible for its booking service, ticket issuance, "
                "and applicable changes, cancellations, and refunds.",
            ),
            (
                "No guarantee",
                "We make reasonable efforts to keep website information "
                "useful, but we do not guarantee that every listing is "
                "complete, current, accurate, or available.",
            ),
            (
                "Changes",
                "We may update these terms as the website develops. "
                "Continued use after changes are published means you "
                "should review the updated terms.",
            ),
            (
                "Contact",
                "Questions about these terms can be sent to "
                "inforichapps@gmail.com.",
            ),
        ],
    )


@app.get("/affiliate-disclosure")
def affiliate_disclosure():
    return render_template(
        "info_page.html",
        title="Affiliate Disclosure",
        page_heading="Affiliate Disclosure",
        updated="October 15, 2026",
        content=[
            (
                "How affiliate links work",
                "Some links on GetOffDeals may be affiliate links. If you "
                "click a link and complete a qualifying booking or purchase, "
                "we may receive a commission from the partner.",
            ),
            (
                "Your price",
                "An affiliate commission generally does not add a separate "
                "charge to your booking, although the price and conditions "
                "are set by the provider.",
            ),
            (
                "Editorial independence",
                "Affiliate participation does not guarantee that a provider "
                "or offer is the best choice for every traveller. Compare "
                "the total price, baggage allowance, payment fees, "
                "cancellation rules, and other conditions before booking.",
            ),
            (
                "Price transparency",
                "Prices used in demonstrations or sample deal cards may be "
                "illustrative rather than live offers. Always check the "
                "current fare on the provider's website.",
            ),
            (
                "Contact",
                "For questions about this disclosure, email "
                "inforichapps@gmail.com.",
            ),
        ],
    )


@app.get("/api/deals")
def deals():
    now = time.monotonic()
    partner_configured = affiliate_is_configured()

    # Return cached fares with the current affiliate configuration.
    if (
        _travelpayouts_cache["deals"] is not None
        and now < _travelpayouts_cache["expires"]
    ):
        cached_deals = []

        for deal in _travelpayouts_cache["deals"]:
            item = dict(deal)
            item["partnerConfigured"] = partner_configured
            cached_deals.append(item)

        return jsonify(
            {
                "source": "travelpayouts_cached",
                "notice": (
                    "Cached fares only. Prices and availability may change."
                ),
                "deals": cached_deals,
            }
        )

    try:
        result = fetch_travelpayouts_deals()

        if result:
            _travelpayouts_cache["deals"] = result
            _travelpayouts_cache["expires"] = (
                now + TRAVELPAYOUTS_CACHE_SECONDS
            )

            return jsonify(
                {
                    "source": "travelpayouts_cached",
                    "notice": (
                        "Cached fares only. Prices and availability may change."
                    ),
                    "deals": result,
                }
            )

        app.logger.warning(
            "Travelpayouts returned no usable fares"
        )

    except (
        requests.RequestException,
        RuntimeError,
        ValueError,
    ) as exc:
        app.logger.warning(
            "Travelpayouts deals unavailable: %s",
            type(exc).__name__,
        )

    # Keep the homepage usable without presenting sample prices as live fares.
    fallback = []

    for deal in DEMO_DEALS:
        item = dict(deal)
        item["priceLabel"] = "sample"
        item["source"] = "demo"
        item["partnerConfigured"] = partner_configured
        fallback.append(item)

    return jsonify(
        {
            "source": "demo_fallback",
            "notice": (
                "Provider fares are unavailable. These are illustrative "
                "sample prices, not live offers."
            ),
            "deals": fallback,
        }
    )


@app.get("/api/search")
def search_flights():
    origin = request.args.get(
        "origin",
        os.getenv("DEFAULT_ORIGIN", "AUH"),
    ).strip().upper()

    destination = request.args.get(
        "destination",
        "",
    ).strip().upper()

    departure = request.args.get("departure", "").strip()
    return_date = request.args.get("return", "").strip()

    try:
        if (
            not re.fullmatch(r"[A-Z]{3}", origin)
            or not re.fullmatch(r"[A-Z]{3}", destination)
        ):
            raise ValueError

        dep = date.fromisoformat(departure)

        if dep < date.today():
            return jsonify(
                {"error": "Departure date must be today or later."}
            ), 400

        if return_date:
            ret = date.fromisoformat(return_date)

            if ret <= dep:
                return jsonify(
                    {"error": "Return date must be after departure."}
                ), 400

        adults = int(request.args.get("adults", "1"))

        if not 1 <= adults <= 9:
            raise ValueError

    except (ValueError, TypeError):
        return jsonify(
            {
                "error": (
                    "Check the three-letter airport codes, dates "
                    "and passenger count."
                )
            }
        ), 400

    if (
        not os.getenv("AMA_API_KEY")
        or not os.getenv("AMA_API_SECRET")
    ):
        return jsonify(
            {
                "error": (
                    "Live search is not configured. Add Amadeus API "
                    "credentials to .env. You can still browse destination "
                    "inspiration below."
                )
            }
        ), 503

    try:
        token = amadeus_token()

        if not token:
            return jsonify(
                {"error": "Amadeus authentication is not configured."}
            ), 503

        base = os.getenv(
            "AMADEUS_BASE_URL",
            "https://test.api.amadeus.com",
        ).rstrip("/")

        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure,
            "adults": adults,
            "currencyCode": "AED",
            "max": 10,
        }

        if return_date:
            params["returnDate"] = return_date

        response = requests.get(
            f"{base}/v2/shopping/flight-offers",
            headers={
                "Authorization": f"Bearer {token}",
            },
            params=params,
            timeout=25,
        )

        if response.status_code >= 400:
            app.logger.warning(
                "Amadeus search returned HTTP %s",
                response.status_code,
            )

        response.raise_for_status()
        payload = response.json()
        results = []

        for offer in payload.get("data", []):
            itineraries = offer.get("itineraries", [])
            itinerary = itineraries[0] if itineraries else {}
            segments = itinerary.get("segments", [])

            if not segments:
                continue

            price = float(
                offer.get("price", {}).get("grandTotal", 0)
            )

            if price <= 0:
                continue

            results.append(
                {
                    "price": price,
                    "currency": offer.get(
                        "price", {}
                    ).get("currency", "AED"),
                    "origin": segments[0].get(
                        "departure", {}
                    ).get("iataCode", origin),
                    "destination": segments[-1].get(
                        "arrival", {}
                    ).get("iataCode", destination),
                    "departure": segments[0].get(
                        "departure", {}
                    ).get("at", ""),
                    "arrival": segments[-1].get(
                        "arrival", {}
                    ).get("at", ""),
                    "stops": max(0, len(segments) - 1),
                    "duration": itinerary.get("duration", ""),
                    "bookingUrl": partner_search_url(
                        origin,
                        destination,
                        departure,
                        return_date,
                        adults,
                    ),
                }
            )

        results.sort(key=lambda item: item["price"])

        return jsonify(
            {
                "source": "Amadeus",
                "results": results,
                "notice": (
                    "Provider prices can change. Confirm baggage, fees, "
                    "availability and final price before booking."
                ),
            }
        )

    except requests.RequestException:
        app.logger.exception("Flight provider request failed")

        return jsonify(
            {
                "error": (
                    "Flight provider request failed. "
                    "Check API access and try again."
                )
            }
        ), 502

    except (KeyError, ValueError, TypeError):
        app.logger.exception(
            "Could not parse flight provider response"
        )

        return jsonify(
            {
                "error": (
                    "The flight provider returned an unexpected response."
                )
            }
        ), 502


@app.post("/api/newsletter")
def newsletter_signup():
    payload = request.get_json(silent=True) or request.form

    email = str(
        payload.get("email", "")
    ).strip().lower()

    consent = payload.get("consent") in (
        True,
        "true",
        "on",
        "1",
        1,
    )

    if (
        len(email) > 254
        or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
    ):
        return jsonify(
            {"error": "Enter a valid email address."}
        ), 400

    if not consent:
        return jsonify(
            {
                "error": (
                    "Please confirm you agree to receive "
                    "GetOffDeals fare updates."
                )
            }
        ), 400

    try:
        with db_connect() as conn:
            conn.execute(
                """
                INSERT INTO subscribers (email, consent)
                VALUES (?, 1)
                ON CONFLICT(email)
                DO UPDATE SET consent=1
                """,
                (email,),
            )

    except sqlite3.Error:
        app.logger.exception(
            "Could not save newsletter subscription"
        )

        return jsonify(
            {
                "error": (
                    "Signup could not be saved right now. "
                    "Please try again later."
                )
            }
        ), 500

    return jsonify(
        {
            "message": (
                "You're on the list! Email delivery is not connected yet, "
                "but your signup has been saved."
            )
        }
    ), 201


@app.get("/go/search")
def affiliate_search():
    origin = request.args.get(
        "origin",
        os.getenv("DEFAULT_ORIGIN", "AUH"),
    ).strip().upper()

    destination = request.args.get(
        "destination",
        "",
    ).strip().upper()

    departure = request.args.get("departure", "").strip()
    return_date = request.args.get("return", "").strip()

    try:
        adults = int(request.args.get("adults", "1"))
    except ValueError:
        abort(400)

    if (
        not re.fullmatch(r"[A-Z]{3}", origin)
        or not re.fullmatch(r"[A-Z]{3}", destination)
        or not 1 <= adults <= 9
    ):
        abort(400)

    url = partner_search_url(
        origin,
        destination,
        departure,
        return_date,
        adults,
    )

    if not url:
        return jsonify(
            {
                "error": (
                    "Affiliate booking is not configured yet. "
                    "Add an approved Aviasales tracking URL or configure "
                    "an approved partner's documented URL template."
                )
            }
        ), 503

    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO affiliate_clicks (
                origin,
                destination,
                departure,
                return_date,
                adults
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                origin,
                destination,
                departure or None,
                return_date or None,
                adults,
            ),
        )

    return redirect(url, code=302)


if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        port=int(os.getenv("PORT", "5000")),
    )
