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
MAX_DESTINATION_AIRPORTS = 5


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


def _build_active_state_context(state: AgentState) -> str:
    context_parts: List[str] = []

    clarification = state.get("clarification") or {}
    if clarification and not clarification.get("can_search", True):
        context_parts.append(
            "Current pending clarification:\n"
            f"needed_fields={clarification.get('needed_fields')}\n"
            f"question={clarification.get('question')}\n"
            f"partial_flight_query={clarification.get('partial_flight_query')}"
        )

    flight_query = state.get("flight_query")
    if flight_query:
        context_parts.append(f"Current saved flight query: {flight_query}")

    if not context_parts:
        return "No active pending clarification or saved query."

    return "\n\n".join(context_parts)


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
        "extracting_query",
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
    active_state_context = _build_active_state_context(state)

    logger.debug("=== previous_context (query) ===")
    for line in previous_context.split("\n"):
        logger.debug("  %s", line)

    system_prompt = f"""
You are a flight search assistant. Extract structured flight search parameters from the user's natural language input.
Today's date is {today}, {weekday}.
The user's current known location context is: {user_loc_str}.

{previous_context}

{active_state_context}

CRITICAL INSTRUCTION:
The previous context and active state above are the conversation memory.
The user may be refining an earlier request, answering a follow-up question, or providing missing information.
You must use the previous context to infer the final merged query state.
Do not discard previous constraints unless the user explicitly changes them or clearly implies a change.
If there is a current pending clarification, merge the user's answer into its partial_flight_query.
Preserve any fields from partial_flight_query that the user did not change.

Extraction rules:
1. from_airport: MUST use 3-letter IATA codes. Use explicit user input, previous context, or reliable location context. If unknown, leave null and set from_airport_source="missing". Never default to SIN without reliable context.
2. Destination handling:
    - Users usually name cities, countries, regions, or trip themes; they usually do not know airport codes. Convert specific city or airport names into suitable 3-letter IATA AIRPORT codes in to_airports.
    - Do NOT output metropolitan/city umbrella codes (for example: NYC, LON, PAR, TYO). Those are not airport codes and can break downstream follow-up search.
    - For city requests, choose one or more concrete airport codes. Example: New York should map to JFK/EWR/LGA (not NYC). Do not ask for specific airports just because a city has multiple airports.
   - Treat a destination as specific when the user names a city, metro area, airport, or a small explicit list of cities/airports. Put those resolved codes in to_airports and leave destination_scope null unless a broader scope is also useful context.
   - Treat a destination as broad when the user names a country, region, continent, or open-ended category that could reasonably map to more than 5 airport codes, such as Japan, France, Europe, Southeast Asia, beach destinations, or anywhere cheap. In that case set destination_scope, set destination_source="broad", and leave to_airports null so the assistant can ask whether the user has specific cities/airports or wants suggestions.
    - If there is a pending destination_choice clarification and the user asks you to suggest/recommend/choose destinations, choose 3-5 suitable concrete destination airport codes yourself and put them in to_airports.
   - Never return more than 5 destination codes.
3. trip: Infer from context. Keywords like "round trip", "return", or "come back" mean round_trip. Phrases that mean staying or traveling for a few days imply round-trip/holiday duration intent and should set holiday_duration_intent=true.
4. departure_date: If not mentioned, leave null and set departure_date_source="missing". Format: YYYY-MM-DD. Coarse dates are acceptable because the assistant asks "roughly when": "next month" means the first day of next month, "in June" means June 1 of the current year, and "next Friday" means the next calendar Friday after today.
5. return_date: Set this when the user gives either an explicit return date or a stay duration such as "stay for 7 days" / "for 1 week". If a stay duration is provided, compute return_date from the merged departure_date. Do not ask for duration again after it was provided.
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

    parsed = response.choices[0].message.parsed
    if parsed is None:
        logger.error("[extract_query] llm_parse_empty_result")
        raise ValueError("LLM returned empty parsed result")

    extraction: FlightQueryExtraction = parsed

    logger.debug("[extract_query] llm_parsed=%s", extraction.model_dump_json(exclude_none=False))

    logger.info(
        "Query extraction parsed",
        extra={
            "trip": extraction.trip,
            "from_airport": extraction.from_airport,
            "from_airport_source": extraction.from_airport_source,
            "to_airports": ",".join(extraction.to_airports or []),
            "destination_scope": extraction.destination_scope,
            "destination_source": extraction.destination_source,
            "departure_date": extraction.departure_date,
            "departure_date_source": extraction.departure_date_source,
            "return_date": extraction.return_date,
            "return_date_source": extraction.return_date_source,
            "holiday_duration_intent": extraction.holiday_duration_intent,
        },
    )

    from_airport = _normalize_iata_code(extraction.from_airport)
    to_airports = _normalize_iata_codes(extraction.to_airports or [])
    destination_scope = _normalize_destination_scope(extraction.destination_scope)
    departure_date = extraction.departure_date
    return_date = extraction.return_date

    logger.debug(
        "[extract_query] normalized_result trip=%s from=%s to=%s scope=%s dep=%s ret=%s class=%s passengers=%s multi=%s",
        extraction.trip,
        from_airport,
        ",".join(to_airports),
        destination_scope,
        departure_date,
        return_date,
        extraction.seat_classes,
        extraction.passengers,
        extraction.is_multi_destination,
    )

    if len(to_airports) > MAX_DESTINATION_AIRPORTS:
        logger.debug(
            "[extract_query] destination_count_exceeded count=%s max=%s; convert to scope clarification",
            len(to_airports),
            MAX_DESTINATION_AIRPORTS,
        )
        destination_scope = destination_scope or "the requested destination area"
        to_airports = []

    if from_airport and from_airport in to_airports:
        logger.debug("[extract_query] invalid_same_origin_destination code=%s", from_airport)
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
        logger.debug(
            "[extract_query] clarification_required needed_fields=%s partial_query=%s",
            ",".join(clarification.get("needed_fields", [])),
            clarification.get("partial_flight_query"),
        )
        return {
            "flight_query": None,
            "clarification": clarification,
            "error_message": None,
        }

    if not to_airports:
        logger.debug("[extract_query] destination_unresolved_after_normalization")
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
