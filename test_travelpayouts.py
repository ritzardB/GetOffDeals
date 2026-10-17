import os
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("TRAVELPAYOUTS_API_TOKEN")

if not token:
    print("ERROR: TRAVELPAYOUTS_API_TOKEN was not found in .env")
    raise SystemExit(1)

url = "https://api.travelpayouts.com/v2/prices/latest"

params = {
    "currency": "usd",
    "period_type": "year",
    "page": 1,
    "limit": 5,
    "show_to_affiliates": "true",
    "sorting": "price",
    "trip_class": 0,
    "origin": "AUH",
    "destination": "MNL",
}

try:
    response = requests.get(
        url,
        params=params,
        headers={"X-Access-Token": token},
        timeout=20,
    )

    print("HTTP status:", response.status_code)

    try:
        data = response.json()
        print("API success:", data.get("success", "not provided"))
        print("API error:", data.get("error") or "none reported")

        fares = data.get("data", [])
        print("Number of results:", len(fares) if isinstance(fares, list) else "unexpected format")

        if isinstance(fares, list):
            for fare in fares[:5]:
                if isinstance(fare, dict):
                    print({
                        key: fare.get(key)
                        for key in (
                            "origin", "destination", "value",
                            "currency", "depart_date", "return_date",
                            "found_at", "gate"
                        )
                        if key in fare
                    })
        elif not response.ok:
            print("Response preview:", str(data)[:500])

    except ValueError:
        print("Response was not JSON.")
        print("Response preview:", response.text[:300])

except requests.RequestException as exc:
    print("Request failed:", type(exc).__name__, str(exc)[:300])
