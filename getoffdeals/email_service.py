"""Email notifications for GetOffDeals price alerts."""

import logging
import os
from html import escape

import resend

logger = logging.getLogger(__name__)


def send_price_alert_confirmation(to_email, alert):
    """Send a confirmation after a price alert has been saved."""
    api_key = os.getenv("RESEND_API_KEY")
    sender = os.getenv("EMAIL_FROM")

    if not api_key or not sender:
        raise RuntimeError("Resend email configuration is missing.")

    origin = escape(str(alert["origin"]))
    destination = escape(str(alert["destination"]))
    departure = escape(str(alert["departure_date"]))
    return_date = alert.get("return_date")
    target_price = escape(str(alert["target_price"]))
    currency = escape(str(alert["currency"]))

    dates = f"Departure: {departure}"
    if return_date:
        dates += f"<br>Return: {escape(str(return_date))}"

    resend.api_key = api_key

    return resend.Emails.send({
        "from": sender,
        "to": [to_email],
        "subject": f"Your GetOffDeals alert: {origin} → {destination}",
        "html": f"""
        <div style="font-family:Arial,sans-serif;line-height:1.6">
          <h2>Your flight price alert is set up!</h2>
          <p>We'll use these details for your price alert:</p>
          <ul>
            <li><strong>Route:</strong> {origin} → {destination}</li>
            <li>{dates}</li>
            <li><strong>Target price:</strong> {currency} {target_price}</li>
          </ul>
          <p>We'll notify you when a qualifying fare is found by our
          configured price-checking service.</p>
          <p>Thanks for using GetOffDeals!</p>
        </div>
        """,
    })



def send_newsletter_confirmation(
    to_email,
    confirmation_url,
    unsubscribe_url,
):
    """Send a double-opt-in confirmation email for the newsletter."""
    api_key = os.getenv("RESEND_API_KEY")
    sender = os.getenv("EMAIL_FROM")

    if not api_key or not sender:
        raise RuntimeError("Resend email configuration is missing.")

    safe_confirmation_url = escape(confirmation_url, quote=True)
    safe_unsubscribe_url = escape(unsubscribe_url, quote=True)

    resend.api_key = api_key

    return resend.Emails.send({
        "from": sender,
        "to": [to_email],
        "subject": "Confirm your GetOffDeals fare updates",
        "html": f"""
        <div style="font-family:Arial,sans-serif;line-height:1.6;max-width:600px">
          <h2>Confirm your GetOffDeals subscription</h2>
          <p>You requested occasional flight-deal inspiration
          from GetOffDeals.</p>
          <p>Please confirm your email address using the link below:</p>
          <p>
            <a href="{safe_confirmation_url}"
               style="display:inline-block;padding:12px 18px;
                      background:#c8f169;color:#14202b;
                      text-decoration:none;font-weight:bold">
              Confirm my subscription
            </a>
          </p>
          <p>This link expires in 24 hours. If you didn't request these
          emails, you can ignore this message.</p>
          <p>
            To stop receiving GetOffDeals fare updates later,
            <a href="{safe_unsubscribe_url}">unsubscribe here</a>.
          </p>
          <p>GetOffDeals</p>
        </div>
        """,
    })
