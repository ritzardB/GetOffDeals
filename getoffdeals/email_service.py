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
