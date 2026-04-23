from __future__ import annotations

import smtplib
from email.message import EmailMessage

from smartflight.config import settings


def build_flight_alert_body(matches: list[dict], context: dict) -> str:
    route = context.get("route") or "your route"
    lines = [
        f"Good news! We found matching flights for {route}.",
        "",
        "Matched options:",
    ]

    for idx, match in enumerate(matches, start=1):
        lines.extend(
            [
                f"{idx}. {match.get('airline', 'Unknown airline')} | {match.get('price', 'N/A')} SGD",
                f"   Stops: {match.get('stops', 'N/A')}",
                f"   Duration: {match.get('duration', 'N/A')}",
                f"   Departure: {match.get('departure', 'N/A')}",
                f"   Arrival: {match.get('arrival', 'N/A')}",
                f"   Booking URL: {match.get('booking_url', 'Unavailable')}",
            ]
        )
    lines.extend(["", "This alert has now been completed."])
    return "\n".join(lines)


def send_flight_alert_email(to_email: str, matches: list[dict], context: dict) -> None:
    if not settings.smtp_enabled:
        raise RuntimeError("SMTP is not configured. Set SMTP_* env vars.")

    msg = EmailMessage()
    msg["Subject"] = "SmartFlight alert: matching flights found"
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg.set_content(build_flight_alert_body(matches, context))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(msg)



def send_test_email(to_email: str) -> None:
    """Send a lightweight SMTP test email to verify configuration."""
    if not settings.smtp_enabled:
        raise RuntimeError("SMTP is not configured. Set SMTP_* env vars.")

    msg = EmailMessage()
    msg["Subject"] = "SmartFlight SMTP test"
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg.set_content(
        "This is a SmartFlight SMTP test email.\n"
        "If you received this message, SMTP settings are working."
    )

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(msg)
