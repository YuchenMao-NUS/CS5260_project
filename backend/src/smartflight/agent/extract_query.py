from datetime import datetime
import logging
import re
from typing import Any, List, Literal, Optional

from openai import OpenAI
from pydantic import BaseModel

from smartflight.agent.state import AgentState
from smartflight.config import settings
from smartflight.services.progress import emit_progress, raise_if_progress_cancelled

logger = logging.getLogger(__name__)

IATA_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")
DESTINATION_SUGGESTION_HINTS = (
    "suggest",
    "recommend",
    "recommendation",
    "any city",
    "anywhere",
    "surprise me",
)
BROAD_DESTINATION_RECOMMENDATIONS = {
    "europe": ["LON", "PAR", "ROM", "AMS", "BCN"],
}


class FlightQueryExtraction(BaseModel):
    trip: Optional[Literal["one_way", "round_trip"]]
    from_airport: Optional[str]
    from_airport_source: Optional[Literal["explicit", "previous", "context", "missing"]]
    to_airports: Optional[List[str]]
    destination_scope: Optional[str]
    destination_source: Optional[Literal["explicit", "previous", "broad", "missing"]]
    departure_date: Optional[str]
    departure_date_source: Optional[Literal["explicit", "previous", "missing"]]
    return_date: Optional[str]
    return_date_source: Optional[Literal["explicit", "previous", "missing", "not_applicable"]]
    seat_classes: Optional[Literal["business", "economy", "first", "premium-economy"]]
    passengers: Optional[int]
    is_multi_destination: Optional[bool]
    holiday_duration_intent: Optional[bool]
    description_of_recommendation: Optional[str]


def _normalize_iata_code(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    code = value.strip().upper()
    if IATA_CODE_PATTERN.fullmatch(code):
        return code
    return None


def _normalize_iata_codes(values: Optional[List[str]]) -> List[str]:
    normalized: List[str] = []
    seen: set[str] = set()
    for value in values or []:
        code = _normalize_iata_code(value)
        if code and code not in seen:
            seen.add(code)
            normalized.append(code)
    return normalized


def _normalize_destination_scope(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    scope = value.strip()
    return scope or None


def _wants_destination_suggestions(user_input: str) -> bool:
    normalized = user_input.lower()
    return any(hint in normalized for hint in DESTINATION_SUGGESTION_HINTS)


def _recommended_destinations_for_scope(destination_scope: Optional[str]) -> List[str]:
    if not destination_scope:
        return []
    return BROAD_DESTINATION_RECOMMENDATIONS.get(destination_scope.strip().lower(), [])


def _build_previous_context(history: Optional[List[dict]], max_turns: int = 5) -> str:
    if not history:
        return "No previous context. This is a new search."

    recent = history[-max_turns:]
    lines: List[str] = []

    for i, turn in enumerate(recent, 1):
        lines.append(f"[Turn {i}]")
        lines.append(f"User: {turn.get('user_input')}")

        fq = turn.get("flight_query")
        if fq:
            lines.append(
                "Query: "
                f"trip={fq.get('trip')}, "
                f"from={fq.get('from_airport')}, "
                f"to={fq.get('to_airports')}, "
                f"scope={fq.get('destination_scope')}, "
                f"departure={fq.get('departure_date')}, "
                f"return={fq.get('return_date')}, "
                f"class={fq.get('seat_classes')}, "
                f"passengers={fq.get('passengers')}"
            )
        else:
            lines.append("Query: None")

        clarification = turn.get("clarification")
        if clarification:
            lines.append(
                "Clarification: "
                f"needed={clarification.get('needed_fields')}, "
                f"partial={clarification.get('partial_flight_query')}"
            )

        pref = turn.get("flight_preference")
        if pref:
            lines.append("Preference: " + ", ".join(f"{k}={v}" for k, v in pref.items()))
        else:
            lines.append("Preference: None")

        lines.append("")

    return "\n".join(lines)


def _build_partial_query(
    *,
    extraction: FlightQueryExtraction,
    from_airport: Optional[str],
    to_airports: List[str],
    destination_scope: Optional[str],
    departure_date: Optional[str],
    return_date: Optional[str],
) -> dict[str, Any]:
    partial = {
        "trip": extraction.trip,
        "from_airport": from_airport,
        "to_airports": to_airports,
        "destination_scope": destination_scope,
        "departure_date": departure_date,
        "return_date": return_date,
        "seat_classes": extraction.seat_classes or "economy",
        "passengers": extraction.passengers or 1,
        "is_multi_destination": bool(extraction.is_multi_destination) or len(to_airports) > 1,
        "description_of_recommendation": extraction.description_of_recommendation,
    }
    return {key: value for key, value in partial.items() if value not in (None, [], "")}


def _is_reliable_origin(extraction: FlightQueryExtraction, from_airport: Optional[str]) -> bool:
    return bool(from_airport and extraction.from_airport_source in {"explicit", "previous", "context"})


def _has_round_trip_intent(extraction: FlightQueryExtraction) -> bool:
    return extraction.trip == "round_trip" or bool(extraction.holiday_duration_intent)


def _build_clarification(
    *,
    extraction: FlightQueryExtraction,
    from_airport: Optional[str],
    to_airports: List[str],
    destination_scope: Optional[str],
    departure_date: Optional[str],
    return_date: Optional[str],
) -> Optional[dict[str, Any]]:
    needed_fields: List[str] = []

    if not _is_reliable_origin(extraction, from_airport):
        needed_fields.append("origin")

    if not to_airports and not destination_scope:
        needed_fields.append("destination")
    elif destination_scope and not to_airports:
        needed_fields.append("destination_choice")

    if not departure_date or extraction.departure_date_source == "missing":
        needed_fields.append("departure_date")

    if _has_round_trip_intent(extraction) and (
        not return_date or extraction.return_date_source == "missing"
    ):
        needed_fields.append("return_date_or_duration")

    if not needed_fields:
        return None

    partial_query = _build_partial_query(
        extraction=extraction,
        from_airport=from_airport,
        to_airports=to_airports,
        destination_scope=destination_scope,
        departure_date=departure_date,
        return_date=return_date,
    )

    question_parts: List[str] = []
    if "origin" in needed_fields:
        question_parts.append("where you will depart from")
    if "destination" in needed_fields:
        question_parts.append("which city or region you want to visit")
    if "departure_date" in needed_fields:
        question_parts.append("roughly when you want to depart")
    if "return_date_or_duration" in needed_fields:
        question_parts.append("how many days you will stay or when you will return")

    if question_parts:
        question = "Sure, I need to confirm " + ", ".join(question_parts) + "."
    else:
        label = destination_scope or "that region"
        question = (
            f"For {label}, would you like to choose specific cities, "
            "or should I suggest 3-5 popular or lower-price cities?"
        )

    if destination_scope and "destination_choice" in needed_fields and question_parts:
        question += f" For {destination_scope}, I can later suggest popular or lower-price cities."

    return {
        "needed_fields": needed_fields,
        "question": question,
        "partial_flight_query": partial_query,
        "can_search": False,
    }


def extract_query_node(state: AgentState) -> AgentState:
    raise_if_progress_cancelled(state.get("progress_id"))

    api_key = settings.openai_api_key
    client = OpenAI(api_key=api_key) if api_key else None
    if not client:
        raise ValueError("OPENAI_API_KEY not set")

    emit_progress(
        state.get("progress_id"),
        "analyzing_request",
        "Extracting route, dates, passengers, and destination details...",
    )
    raise_if_progress_cancelled(state.get("progress_id"))

    today = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().strftime("%A")
    user_input = state["user_input"]

    user_context = state.get("user_context", {})
    location = user_context.get("location")
    tz = user_context.get("timeZone", "")
    user_loc_str = f"City/Country: {location}" if location else f"Timezone: {tz}"

    history = state.get("history")
    previous_context = _build_previous_context(history)

    logger.debug("=== previous_context (query) ===")
    for line in previous_context.split("\n"):
        logger.debug("  %s", line)

    system_prompt = f"""
You are a flight search assistant. Extract structured flight search parameters from the user's natural language input.
Today's date is {today}, {weekday}.
The user's current known location context is: {user_loc_str}.

{previous_context}

CRITICAL INSTRUCTION:
The previous context above is the conversation memory.
The user may be refining an earlier request, answering a follow-up question, or providing missing information.
You must use the previous context to infer the final merged query state.
Do not discard previous constraints unless the user explicitly changes them or clearly implies a change.

Extraction rules:
1. from_airport: MUST use 3-letter IATA codes. Use explicit user input, previous context, or reliable location context. If unknown, leave null and set from_airport_source="missing". Never default to SIN without reliable context.
2. to_airports: MUST use only 3-letter IATA codes for specific destinations. If the user gives a broad region like Europe, store it in destination_scope and leave to_airports null unless they already chose specific cities. Do not recommend default airports when the user has not chosen them.
3. trip: Infer from context. Keywords like "round trip", "return", or "come back" mean round_trip. Phrases that mean staying or traveling for a few days imply round-trip/holiday duration intent and should set holiday_duration_intent=true.
4. departure_date: If not mentioned, leave null and set departure_date_source="missing". Format: YYYY-MM-DD.
5. return_date: Only set when explicitly mentioned or present in previous context. Do not default to departure_date + 7 days.
6. seat_classes: If not specified, return "economy".
7. passengers: If not specified, default to 1.
8. is_multi_destination: Set true for broad destination scopes or multiple destinations; false for one specific destination.
9. description_of_recommendation: Give a brief description of your recommendation.
10. Source fields: set each *_source field to explicit, previous, context, broad, missing, or not_applicable as appropriate.

Return the fully merged final query state.
""".strip()

    logger.debug("[extract_query] system_prompt:\n%s", system_prompt)
    logger.debug("[extract_query] user_input: %s", user_input)

    response = client.beta.chat.completions.parse(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        response_format=FlightQueryExtraction,
    )

    extraction: FlightQueryExtraction = response.choices[0].message.parsed

    from_airport = _normalize_iata_code(extraction.from_airport)
    to_airports = _normalize_iata_codes(extraction.to_airports or [])
    destination_scope = _normalize_destination_scope(extraction.destination_scope)
    departure_date = extraction.departure_date
    return_date = extraction.return_date

    if destination_scope and not to_airports and _wants_destination_suggestions(user_input):
        to_airports = _recommended_destinations_for_scope(destination_scope)

    if from_airport and from_airport in to_airports:
        return {
            "flight_query": None,
            "clarification": None,
            "error_message": (
                f"Your origin and destination both seem to be {from_airport}. "
                "Please specify a different destination."
            ),
        }

    clarification = _build_clarification(
        extraction=extraction,
        from_airport=from_airport,
        to_airports=to_airports,
        destination_scope=destination_scope,
        departure_date=departure_date,
        return_date=return_date,
    )
    if clarification:
        return {
            "flight_query": None,
            "clarification": clarification,
            "error_message": None,
        }

    if not to_airports:
        return {
            "flight_query": None,
            "clarification": None,
            "error_message": (
                "I couldn't resolve the destination into airport codes. "
                "Please specify a city or airport."
            ),
        }

    flight_query = {
        "trip": extraction.trip or "one_way",
        "from_airport": from_airport,
        "to_airports": to_airports,
        "departure_date": departure_date,
        "return_date": return_date,
        "seat_classes": extraction.seat_classes or "economy",
        "passengers": extraction.passengers or 1,
        "is_multi_destination": bool(extraction.is_multi_destination) or len(to_airports) > 1,
        "description_of_recommendation": extraction.description_of_recommendation,
    }
    if destination_scope:
        flight_query["destination_scope"] = destination_scope

    logger.info(
        "Query extraction completed",
        extra={
            "from_airport": flight_query["from_airport"],
            "to_airport": ",".join(flight_query["to_airports"]),
            "departure_date": flight_query["departure_date"],
            "return_date": flight_query["return_date"],
            "trip": flight_query["trip"],
        },
    )

    return {
        "flight_query": flight_query,
        "clarification": None,
        "error_message": None,
    }
