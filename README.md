# Takeoff — Flight Deals MVP

A Flask website prototype aimed at Filipino travellers in the UAE and the Philippines. It combines destination inspiration, optional Amadeus flight search, a locally stored email-signup list, and a configurable affiliate booking hand-off.

## What's working

- Responsive landing page and flight-search form.
- Destination inspiration for Manila, Cebu, Clark, Kalibo, and international destinations.
- Filters for city breaks, nature/coast, and Philippines trips.
- Server-side Amadeus Flight Offers integration (test API by default).
- SQLite storage for newsletter signups and outbound affiliate click events.
- Optional affiliate search redirect, enabled only when `AFFILIATE_SEARCH_URL_TEMPLATE` is configured.
- Basic validation and security response headers; secrets stay server-side.

## Important limitations

- **Destination prices are illustrative sample prices, not live fares or confirmed discounts.** They must not be advertised as live deals.
- Amadeus test API results can be incomplete and do not guarantee bookability.
- Amadeus flight offers do not by themselves guarantee a checkout URL. To earn commissions, first join a suitable affiliate program and configure its documented, approved deep-link format.
- Newsletter addresses are stored in a local SQLite database, but no email is sent yet. Add an email provider, unsubscribe handling, retention policy, and privacy notice before collecting signups publicly.
- The first version does not include accounts, a fare-history engine, automatic deal publishing, a production admin dashboard, or a full booking engine.

## Run locally (macOS/Linux)

Python 3.10+ recommended.

```bash
cd flight-deals-website
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open http://127.0.0.1:5000. The site works without credentials, but live search returns a clear setup message until Amadeus credentials are configured.

### Amadeus setup

Add your API key and secret to `.env`. The app defaults to `https://test.api.amadeus.com`. Keep credentials private and do not commit `.env`. Switch to a production endpoint only after you have approved access and verified your intended commercial use is permitted.

### Affiliate booking setup

1. Apply to an affiliate program that supports flight searches or deep links for your audience and target markets.
2. Review its terms, allowed markets, disclosure rules, and URL template documentation.
3. Put the approved template in `AFFILIATE_SEARCH_URL_TEMPLATE` in `.env`. Supported placeholders are `{origin}`, `{destination}`, `{departure}`, `{return_date}`, and `{adults}`.
4. Test a few routes and confirm the resulting partner URL preserves your tracking ID and correctly carries search criteria.

The website will not invent affiliate links. Until the template is configured, it directs visitors to the search form rather than claiming that booking links are active. The `/go/search` endpoint records outbound clicks in SQLite only when the partner template is enabled.

## Routes

- `GET /` — landing page.
- `GET /api/deals` — illustrative destination inspiration with demo/live disclosures.
- `GET /api/search?origin=AUH&destination=MNL&departure=YYYY-MM-DD&return=YYYY-MM-DD&adults=1` — Amadeus flight-offer search.
- `POST /api/newsletter` — validates consent and stores the email in SQLite; does not send email.
- `GET /go/search?...` — tracked redirect to the configured affiliate URL; returns an explanatory error if no partner is configured.

## Review of the uploaded starter

The original script is useful as a source of the flight-search and alert concept, but it is not a website backend as-is. Issues to fix before reusing its modules:

1. `main.py` calls `check_flights(..., from_time=..., to_time=...)`, while `FlightSearch.check_flights()` accepts `departure_date` and `return_date`.
2. `check_flights()` returns a list, but `find_cheapest_flight()` expects a dictionary containing a `data` key.
3. Amadeus Flight Offers expects a specific departure date (and optional return date), not a six-month date range in a single request.
4. `flight_search.py` prints the bearer token to stdout; credentials/tokens must never be logged.
5. The original search requests USD while notifications format prices using GBP.
6. There is no website, persistent fare history, affiliate deep link, or verified booking hand-off.
7. The uploaded archive contains `.env` and a virtual environment. If any credentials in that archive are active, rotate them and avoid sharing or committing the file.

## Recommended next steps

1. Connect an approved affiliate provider and test deep links with real tracking IDs.
2. Connect a consent-based email service and implement unsubscribe/consent management.
3. Add scheduled fare checks and persistent fare history before calling anything a price drop.
4. Add production deployment configuration, rate limiting, CSRF protections where applicable, database backups, privacy/terms pages, error monitoring, and automated tests.

## Deploy on Render (free MVP)

1. Push this folder to a GitHub repository. Do not commit `.env` or API credentials.
2. In Render, choose **New + → Blueprint** and select the repository containing `render.yaml`, or create a Web Service manually.
3. For manual setup use:
   - Runtime: Python
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
4. Deploy and open the generated `https://<service-name>.onrender.com` URL.

### Important free-hosting limitations

- Render free services can sleep when idle and may have limited availability.
- The app currently stores newsletter signups and click events in SQLite. The local filesystem on a free web service is not durable; records can be lost on redeploy/restart. Do not rely on this deployment for collecting or retaining subscriber data until a persistent database and appropriate privacy/consent workflow are configured.
- Live Amadeus search will not work without valid credentials and account access. Sample destination fares are illustrative only, not verified offers.
- Affiliate redirects remain disabled until an approved partner's documented link template is configured.
