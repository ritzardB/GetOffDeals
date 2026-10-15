
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()
APP = ROOT / "app.py"
INDEX = ROOT / "templates" / "index.html"
CSS = ROOT / "static" / "style.css"
INFO_TEMPLATE = ROOT / "templates" / "info_page.html"

required = [APP, INDEX, CSS]

for path in required:
    if not path.exists():
        sys.exit(f"ERROR: Required file not found: {path}")

app_text = APP.read_text()
index_text = INDEX.read_text()
css_text = CSS.read_text()

# Check the existing app before making changes.
route_marker = '@app.get("/api/deals")'
footer_start = '<footer class="footer"><div class="container footer-inner">'
footer_end = '</footer>\n<script src="{{ url_for(\'static\', filename=\'app.js\') }}"></script>'

if route_marker not in app_text:
    sys.exit(
        'STOP: Could not find @app.get("/api/deals") in app.py. '
        "No files were changed."
    )

if footer_start not in index_text or footer_end not in index_text:
    sys.exit(
        "STOP: Could not identify the expected footer in templates/index.html. "
        "No files were changed."
    )

if INFO_TEMPLATE.exists():
    sys.exit(
        "STOP: templates/info_page.html already exists. "
        "Review your existing work before running this installer."
    )

# Create backups before changing anything.
for path in required:
    backup = path.with_name(path.name + ".trust-pages.bak")
    shutil.copy2(path, backup)
    print(f"Backup created: {backup}")

routes = '''

# Trust and transparency pages
@app.get("/about")
def about():
    return render_template(
        "info_page.html",
        title="About GetOffDeals",
        page_heading="About GetOffDeals",
        updated="October 15, 2026",
        content=[
            ("Our mission", "GetOffDeals helps Filipino travellers in the UAE and the Philippines discover flight deals and travel inspiration in one convenient place."),
            ("How we work", "We aim to make researching travel options easier. Prices and examples displayed on the site may be illustrative and are not guaranteed live fares or available offers. Always confirm the final price, baggage rules, schedule, and booking conditions with the airline or booking provider."),
            ("How we may earn", "Some links may be affiliate links. If you book through a qualifying link, we may earn a commission at no additional cost to you. Affiliate relationships do not guarantee that an offer is the cheapest available."),
            ("Contact", "Questions or feedback? Email inforichapps@gmail.com.")
        ]
    )


@app.get("/contact")
def contact():
    return render_template(
        "info_page.html",
        title="Contact GetOffDeals",
        page_heading="Contact Us",
        updated="October 15, 2026",
        content=[
            ("Get in touch", "For questions, feedback, corrections, or business inquiries, email us at inforichapps@gmail.com."),
            ("Before booking", "GetOffDeals does not issue airline tickets unless explicitly stated. Your booking, payment, cancellation, and refund arrangements are handled by the airline or booking provider you choose.")
        ]
    )


@app.get("/privacy")
def privacy():
    return render_template(
        "info_page.html",
        title="Privacy Policy",
        page_heading="Privacy Policy",
        updated="October 15, 2026",
        content=[
            ("Information we may collect", "Depending on the features you use, we may receive information you submit directly, such as an email address entered into a contact or subscription form, along with basic technical information generated when you visit the site."),
            ("How information may be used", "Information may be used to respond to inquiries, operate and improve the website, prevent abuse, and provide features you request."),
            ("Cookies and analytics", "The website or its service providers may use cookies or similar technologies for site functionality, traffic measurement, or affiliate attribution if those services are enabled. The exact technologies depend on the services configured on the live site."),
            ("Affiliate links and third parties", "When you follow a link to an airline, travel agency, or affiliate partner, that provider's website and privacy policy apply. We do not control third-party websites or their data practices."),
            ("Data retention and your choices", "We should retain personal information only as needed for the purpose for which it was collected and applicable obligations. To ask about information you submitted to us, email inforichapps@gmail.com."),
            ("Contact", "For privacy questions, contact inforichapps@gmail.com.")
        ]
    )


@app.get("/terms")
def terms():
    return render_template(
        "info_page.html",
        title="Terms of Use",
        page_heading="Terms of Use",
        updated="October 15, 2026",
        content=[
            ("Use of this website", "You may use GetOffDeals for lawful personal travel research. Do not misuse the website, attempt unauthorized access, or interfere with its operation."),
            ("Prices and availability", "Flight prices, promotions, schedules, and availability can change without notice. Any sample or illustrative price is not a live quote or guarantee. Verify all details with the airline or booking provider before paying."),
            ("Third-party bookings", "Bookings made through external providers are subject to their terms, fees, policies, and conditions. The provider is responsible for its booking service, ticket issuance, and applicable changes, cancellations, and refunds."),
            ("No guarantee", "We make reasonable efforts to keep website information useful, but we do not guarantee that every listing is complete, current, accurate, or available."),
            ("Changes", "We may update these terms as the website develops. Continued use after changes are published means you should review the updated terms."),
            ("Contact", "Questions about these terms can be sent to inforichapps@gmail.com.")
        ]
    )


@app.get("/affiliate-disclosure")
def affiliate_disclosure():
    return render_template(
        "info_page.html",
        title="Affiliate Disclosure",
        page_heading="Affiliate Disclosure",
        updated="October 15, 2026",
        content=[
            ("How affiliate links work", "Some links on GetOffDeals may be affiliate links. If you click a link and complete a qualifying booking or purchase, we may receive a commission from the partner."),
            ("Your price", "An affiliate commission generally does not add a separate charge to your booking, although the price and conditions are set by the provider."),
            ("Editorial independence", "Affiliate participation does not guarantee that a provider or offer is the best choice for every traveller. Compare the total price, baggage allowance, payment fees, cancellation rules, and other conditions before booking."),
            ("Price transparency", "Prices used in demonstrations or sample deal cards may be illustrative rather than live offers. Always check the current fare on the provider's website."),
            ("Contact", "For questions about this disclosure, email inforichapps@gmail.com.")
        ]
    )

'''

info_template = '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} | GetOffDeals</title>
  <meta name="description" content="{{ page_heading }} - GetOffDeals travel information.">
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <header class="info-header">
    <div class="container info-header-inner">
      <a class="info-brand" href="/">GetOffDeals</a>
      <a class="info-home" href="/">Back to deals</a>
    </div>
  </header>
  <main class="container info-main">
    <p class="info-eyebrow">GETOFFDEALS · TRAVEL WITH CLARITY</p>
    <h1>{{ page_heading }}</h1>
    <p class="info-updated">Last updated: {{ updated }}</p>
    {% for heading, paragraph in content %}
      <section class="info-section">
        <h2>{{ heading }}</h2>
        <p>{{ paragraph }}</p>
      </section>
    {% endfor %}
    <p class="info-contact">Contact: <a href="mailto:inforichapps@gmail.com">inforichapps@gmail.com</a></p>
  </main>
  <footer class="info-footer">
    <div class="container">
      <a href="/">Home</a>
      <a href="/about">About</a>
      <a href="/contact">Contact</a>
      <a href="/privacy">Privacy Policy</a>
      <a href="/terms">Terms of Use</a>
      <a href="/affiliate-disclosure">Affiliate Disclosure</a>
    </div>
  </footer>
</body>
</html>
'''

footer_links = '''
    <div class="trust-links">
      <a href="/about">About</a>
      <a href="/contact">Contact</a>
      <a href="/privacy">Privacy Policy</a>
      <a href="/terms">Terms of Use</a>
      <a href="/affiliate-disclosure">Affiliate Disclosure</a>
    </div>
'''

css_addition = '''

/* Trust and transparency pages */
.info-header {
  border-bottom: 1px solid #e7eaf0;
  background: #fff;
}
.info-header-inner {
  min-height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.info-brand {
  color: #15233b;
  font-size: 1.25rem;
  font-weight: 800;
  text-decoration: none;
}
.info-home,
.info-footer a {
  color: #3659a8;
  text-decoration: none;
}
.info-main {
  max-width: 850px;
  padding-top: 48px;
  padding-bottom: 64px;
}
.info-eyebrow {
  color: #3659a8;
  font-size: .78rem;
  font-weight: 800;
  letter-spacing: .12em;
}
.info-main h1 {
  margin: 12px 0;
  color: #15233b;
  font-size: clamp(2rem, 5vw, 3.25rem);
  line-height: 1.1;
}
.info-updated {
  color: #687386;
  font-size: .9rem;
  margin-bottom: 36px;
}
.info-section {
  padding: 22px 0;
  border-bottom: 1px solid #e7eaf0;
}
.info-section h2 {
  color: #15233b;
  font-size: 1.2rem;
  margin: 0 0 10px;
}
.info-section p,
.info-contact {
  color: #455168;
  line-height: 1.8;
}
.info-contact a {
  color: #3659a8;
}
.info-footer {
  padding: 24px 0;
  border-top: 1px solid #e7eaf0;
}
.info-footer .container,
.trust-links {
  display: flex;
  flex-wrap: wrap;
  gap: 14px 22px;
}
.trust-links {
  margin-top: 14px;
}
.trust-links a {
  font-size: .88rem;
  color: inherit;
}
@media (max-width: 600px) {
  .info-header-inner {
    min-height: 62px;
  }
  .info-main {
    padding-top: 32px;
    padding-bottom: 44px;
  }
}
'''

# Avoid duplicating routes if a previous partial attempt was made.
if "def affiliate_disclosure():" in app_text:
    sys.exit("STOP: Affiliate disclosure route already exists; inspect app.py first.")

new_index = index_text.replace(
    footer_end,
    footer_links + "\n" + footer_end,
    1
)

# Save all changes only after validation.
try:
    APP.write_text(app_text.replace(route_marker, routes + "\n" + route_marker, 1))
    INFO_TEMPLATE.write_text(info_template)
    INDEX.write_text(new_index)
    CSS.write_text(css_text + css_addition)
except Exception:
    # Restore backed-up files if an error occurs during writing.
    for path in required:
        backup = path.with_name(path.name + ".trust-pages.bak")
        if backup.exists():
            shutil.copy2(backup, path)
    if INFO_TEMPLATE.exists():
        INFO_TEMPLATE.unlink()
    raise

print("\\nTrust pages created successfully.")
print("Next: run `python3 -m py_compile app.py` and then test your site.")

