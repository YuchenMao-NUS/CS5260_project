"""Helpers for phrasing recommendation text for chat responses."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from smartflight.config import settings


def _fallback_rephrase(raw_text: str) -> str:
    cleaned = " ".join((raw_text or "").strip().split())
    if not cleaned:
        return ""
    if cleaned.endswith((".", "!", "?")):
        return f"I'd recommend these options because {cleaned[0].lower() + cleaned[1:] if len(cleaned) > 1 else cleaned.lower()}"
    return f"I'd recommend these options because {cleaned[0].lower() + cleaned[1:] if len(cleaned) > 1 else cleaned.lower()}."


def _extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                value = item.get("text")
                if isinstance(value, str) and value.strip():
                    text_parts.append(value.strip())
        return " ".join(text_parts).strip()
    return ""


def rephrase_recommendation_as_assistant(
    raw_text: str | None,
    *,
    flight_query: dict | None = None,
    flight_count: int | None = None,
) -> str | None:
    """Rewrite extracted recommendation text into a natural assistant reply."""
    if not raw_text or not raw_text.strip():
        return None

    cleaned_raw_text = " ".join(raw_text.strip().split())
    fallback_text = _fallback_rephrase(cleaned_raw_text)

    if not settings.openai_enabled:
        return fallback_text

    client = OpenAI(api_key=settings.openai_api_key)
    query = flight_query or {}
    origin = query.get("from_airport")
    destinations = query.get("to_airports") or []
    trip = query.get("trip")
    departure_date = query.get("departure_date")
    return_date = query.get("return_date")

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a flight search assistant writing a short result summary for the user. "
                    "Turn internal search notes into a natural, polished assistant reply. "
                    "Write in first person, directly addressing the user. "
                    "The message should briefly explain what I searched for and why these results are being shown. "
                    "Sound warm, concise, and travel-assistant-like, not robotic or operational. "
                    "Do not say 'I’ve prepared'. "
                    "Do not say 'flight option to compare routes and fares'. "
                    "Do not mention internal processing, raw notes, or that you are rewriting. "
                    "Do not use bullet points. "
                    "Keep it to 1-2 sentences."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Search details:\n"
                    f"- Origin: {origin}\n"
                    f"- Destinations: {', '.join(destinations) if destinations else 'unknown'}\n"
                    f"- Trip type: {trip}\n"
                    f"- Departure date: {departure_date}\n"
                    f"- Return date: {return_date}\n"
                    f"- Number of flight options shown: {flight_count}\n"
                    f"- Internal note: {cleaned_raw_text}\n\n"
                    "Write a user-facing summary that sounds like a helpful flight assistant. "
                    "Mention the route scope, travel dates, trip type, and how many results are shown, "
                    "but phrase it naturally."
                ),
            },
        ],
    )
    content = _extract_message_text(response.choices[0].message.content)
    return content or fallback_text
