"""NLU: Parse user intent from natural language using LangGraph agent."""

from datetime import datetime
import logging
import re
from uuid import uuid4

from smartflight.agent.agent import graph
from smartflight.config import settings
from smartflight.services.progress import ProgressCancelledError

logger = logging.getLogger(__name__)

AIRPORT_HINTS: dict[str, tuple[str, ...]] = {
    "SIN": ("singapore", "asia/singapore", "sg"),
    "TYO": ("tokyo", "japan", "asia/tokyo"),
    "KIX": ("osaka", "kix"),
    "LON": ("london", "europe/london", "uk"),
    "KUL": ("malaysia", "kuala lumpur", "asia/kuala_lumpur"),
}

AIRLINE_HINTS: dict[str, tuple[str, ...]] = {
    "SQ": ("singapore airlines", "singapore airline", "sia", "sq"),
    "TR": ("scoot", "tr"),
    "CX": ("cathay", "cathay pacific", "cx"),
    "JL": ("japan airlines", "jal", "jl"),
    "NH": ("ana", "all nippon", "nh"),
    "AK": ("airasia", "air asia", "ak"),
}

DIRECT_TRUE_HINTS = ("direct", "non-stop", "nonstop", "no layover")
DIRECT_FALSE_HINTS = ("don't mind stops", "dont mind stops", "with stops is fine", "layover is fine")

PRICE_MAX_PATTERN = re.compile(r"(?:under|below|less than|max(?:imum)?(?: price)?)[^\d]*(\d+(?:\.\d+)?)", re.I)
PRICE_MIN_PATTERN = re.compile(r"(?:over|above|min(?:imum)?(?: price)?)[^\d]*(\d+(?:\.\d+)?)", re.I)
PRICE_AROUND_PATTERN = re.compile(r"(?:around|about)[^\d]*(\d+(?:\.\d+)?)", re.I)
ORIGIN_FROM_PATTERN = re.compile(
    r"\bfrom\s+([a-zA-Z\s]+?)(?:\s+\bto\b|,|$|\s+(?:june|jun|next|this|tomorrow|today|on)\b)",
    re.I,
)
DESTINATION_TO_PATTERN = re.compile(
    r"\bto\s+([a-zA-Z\s]+?)(?:$|\s+(?:next|this|tomorrow|today|on|under|below|less|more|above|around|about|with|for|return|round)\b)",
    re.I,
)
DATE_RANGE_PATTERN = re.compile(
    r"(?:june|jun)\s+(\d{1,2})(?:\s*(?:to|-)\s*(\d{1,2}))?",
    re.I,
)
MONTH_ONLY_PATTERN = re.compile(r"\b(?:june|jun)\b", re.I)
BROAD_DESTINATION_HINTS: dict[str, tuple[str, ...]] = {
    "Europe": ("europe",),
}
BROAD_DESTINATION_RECOMMENDATIONS: dict[str, list[str]] = {
    "Europe": ["LON", "PAR", "ROM", "AMS", "BCN"],
}
HOLIDAY_DURATION_HINTS = ("for a few days", "few days")
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
ALERT_HINTS = ("notify", "notify me", "email me", "send me", "alert me", "let me know")
CANCEL_ALERT_HINTS = ("do not notify", "don't notify", "stop notify", "stop notifying", "cancel alert", "stop alert")


def _resolve_session_id(session_id: str | None) -> str:
    return session_id or f"chat-{uuid4()}"


def _build_input_state(
    message: str,
    user_context: dict | None,
    session_id: str,
    progress_id: str | None,
    previous_state: dict | None = None,
) -> dict:
    """
    Build only the fresh per-turn input state.

    Previous graph state will be restored automatically by LangGraph
    via the checkpointer using thread_id.
    """
    previous_state = previous_state or {}
    return {
        "session_id": session_id,
        "progress_id": progress_id,
        "user_input": message,
        "user_context": user_context or {},
        "flight_query": previous_state.get("flight_query"),
        "clarification": previous_state.get("clarification"),
        "flight_preference": previous_state.get("flight_preference"),
        "alert_request": previous_state.get("alert_request"),
        "error_message": None,
        "flight_choices": None,
    }


def _get_previous_state(session_id: str) -> dict:
    snapshot = graph.get_state({"configurable": {"thread_id": session_id}})
    values = getattr(snapshot, "values", None)
    return values if isinstance(values, dict) else {}


def _safe_get_previous_state(session_id: str) -> dict:
    try:
        previous_state = _get_previous_state(session_id)
        logger.info(
            "Previous chat state found" if previous_state else "Previous chat state missing",
            extra={"session_id": session_id},
        )
        return previous_state
    except Exception:
        logger.warning(
            "Previous chat state lookup failed",
            extra={"session_id": session_id},
            exc_info=True,
        )
        return {}


def _append_history(result: dict, previous_history: list[dict], max_turns: int = 5) -> dict:
    history = list(previous_history)
    history.append(
        {
            "user_input": result.get("user_input"),
            "flight_query": result.get("flight_query"),
            "clarification": result.get("clarification"),
            "flight_preference": result.get("flight_preference"),
        }
    )
    result["history"] = history[-max_turns:]
    return result


def _persist_fallback_result(result: dict, session_id: str) -> None:
    try:
        graph.update_state({"configurable": {"thread_id": session_id}}, result)
    except Exception:
        logger.warning(
            "Fallback parser state persistence failed",
            extra={"session_id": session_id},
            exc_info=True,
        )


def _match_airport_hint(text: str) -> str | None:
    normalized = text.lower()
    for airport_code, hints in AIRPORT_HINTS.items():
        if any(hint in normalized for hint in hints):
            return airport_code
    return None


def _infer_origin(message: str, user_context: dict | None, previous_query: dict) -> tuple[str | None, bool]:
    explicit_origin = None
    if origin_match := ORIGIN_FROM_PATTERN.search(message):
        explicit_origin = _match_airport_hint(origin_match.group(1))
    if not explicit_origin and re.search(r"\bto\b", message, re.I):
        explicit_origin = _match_airport_hint(re.split(r"\bto\b", message, flags=re.I)[0])
    if explicit_origin:
        return explicit_origin, True

    previous_origin = previous_query.get("from_airport")
    if previous_origin:
        return previous_origin, True

    location = (user_context or {}).get("location") or ""
    time_zone = (user_context or {}).get("timeZone") or ""
    context_match = _match_airport_hint(f"{location} {time_zone}")
    if context_match:
        return context_match, True

    return None, False


def _infer_destination_scope(message: str, previous_query: dict) -> str | None:
    normalized = message.lower()
    for scope, hints in BROAD_DESTINATION_HINTS.items():
        if any(hint in normalized for hint in hints):
            return scope
    return previous_query.get("destination_scope")


def _infer_destinations(message: str, previous_query: dict, from_airport: str | None) -> list[str]:
    if destination_match := DESTINATION_TO_PATTERN.search(message):
        explicit_destination = _match_airport_hint(destination_match.group(1))
        if explicit_destination:
            return [explicit_destination]

    normalized = message.lower()
    matched_destinations = [
        airport_code
        for airport_code, hints in AIRPORT_HINTS.items()
        if airport_code != from_airport and any(hint in normalized for hint in hints)
    ]
    if matched_destinations:
        return matched_destinations

    previous_destinations = previous_query.get("to_airports")
    if previous_destinations:
        return list(previous_destinations)

    return []


def _recommended_destinations_for_scope(destination_scope: str | None) -> list[str]:
    if not destination_scope:
        return []
    return list(BROAD_DESTINATION_RECOMMENDATIONS.get(destination_scope, []))


def _infer_trip(message: str, previous_query: dict) -> str:
    normalized = message.lower()
    if any(keyword in normalized for keyword in ("round trip", "round-trip", "return")):
        return "round_trip"
    return previous_query.get("trip") or "one_way"


def _has_holiday_duration_intent(message: str) -> bool:
    normalized = message.lower()
    return any(hint in normalized for hint in HOLIDAY_DURATION_HINTS)


def _infer_dates(message: str, previous_query: dict) -> tuple[str | None, str | None]:
    if match := DATE_RANGE_PATTERN.search(message):
        year = datetime.now().year
        month = 6
        start_day = int(match.group(1))
        end_day = int(match.group(2)) if match.group(2) else None

        departure_date = f"{year:04d}-{month:02d}-{start_day:02d}"
        return_date = f"{year:04d}-{month:02d}-{end_day:02d}" if end_day else None
        return departure_date, return_date

    if MONTH_ONLY_PATTERN.search(message):
        return None, None

    return previous_query.get("departure_date"), previous_query.get("return_date")


def _build_clarification(
    *,
    from_airport: str | None,
    origin_reliable: bool,
    to_airports: list[str],
    destination_scope: str | None,
    departure_date: str | None,
    return_date: str | None,
    trip: str,
    holiday_duration_intent: bool,
    partial_query: dict,
) -> dict | None:
    needed_fields: list[str] = []
    if not origin_reliable or not from_airport:
        needed_fields.append("origin")
    if not to_airports and not destination_scope:
        needed_fields.append("destination")
    elif destination_scope and not to_airports:
        needed_fields.append("destination_choice")
    if not departure_date:
        needed_fields.append("departure_date")
    if (trip == "round_trip" or holiday_duration_intent) and not return_date:
        needed_fields.append("return_date_or_duration")

    if not needed_fields:
        return None

    question_parts: list[str] = []
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


def _infer_preference(
    message: str,
    previous_preference: dict,
    context_filters: list[dict] | None = None,
) -> dict:
    normalized = message.lower()
    preference = dict(previous_preference)

    if any(hint in normalized for hint in DIRECT_TRUE_HINTS):
        preference["direct_only"] = True
        preference["max_stops"] = 0
        preference["min_stops"] = None
    elif any(hint in normalized for hint in DIRECT_FALSE_HINTS):
        preference["direct_only"] = False

    if "max 1 stop" in normalized or "up to 1 stop" in normalized:
        preference["direct_only"] = False
        preference["max_stops"] = 1
        preference["min_stops"] = None

    if "2+ stops" in normalized or "at least 2 stops" in normalized:
        preference["direct_only"] = False
        preference["max_stops"] = None
        preference["min_stops"] = 2

    matched_airlines = [
        airline_code
        for airline_code, hints in AIRLINE_HINTS.items()
        if any(hint in normalized for hint in hints)
    ]
    if matched_airlines:
        preference["preferred_airlines"] = matched_airlines

    for raw_filter in (context_filters or []):
        filter_id = str(raw_filter.get("id") or "").strip()
        filter_label = str(raw_filter.get("label") or "").strip()
        if filter_id == "stops":
            if filter_label == "Direct flights only":
                preference["direct_only"] = True
                preference["max_stops"] = 0
                preference["min_stops"] = None
            elif filter_label == "Max 1 stop":
                preference["direct_only"] = False
                preference["max_stops"] = 1
                preference["min_stops"] = None
            elif filter_label == "2+ stops":
                preference["direct_only"] = False
                preference["max_stops"] = None
                preference["min_stops"] = 2
        elif filter_id.startswith("airline-"):
            airline_code = filter_id.removeprefix("airline-").upper()
            if airline_code:
                preference["preferred_airlines"] = [airline_code]

    if around_match := PRICE_AROUND_PATTERN.search(message):
        price = float(around_match.group(1))
        preference["min_price"] = round(price * 0.9, 2)
        preference["max_price"] = round(price * 1.1, 2)
    else:
        if max_match := PRICE_MAX_PATTERN.search(message):
            preference["max_price"] = float(max_match.group(1))
        if min_match := PRICE_MIN_PATTERN.search(message):
            preference["min_price"] = float(min_match.group(1))

    return preference


def _extract_email(text: str) -> str | None:
    match = EMAIL_PATTERN.search(text or "")
    return match.group(0).strip() if match else None


def _infer_alert_request(message: str, previous_alert_request: dict | None) -> dict | None:
    normalized = (message or "").lower()
    email = _extract_email(message)
    previous = dict(previous_alert_request or {})
    enabled = bool(previous.get("enabled", False))
    intent = previous.get("intent")

    if any(hint in normalized for hint in CANCEL_ALERT_HINTS):
        if email:
            previous["email"] = email
        previous["enabled"] = False
        previous["intent"] = "cancel"
        return previous

    if any(hint in normalized for hint in ALERT_HINTS):
        enabled = True
        intent = "create"

    if email:
        previous["email"] = email
        if any(hint in normalized for hint in ALERT_HINTS):
            enabled = True
            intent = "create"

    if not enabled and not previous.get("email"):
        return previous or None

    previous["enabled"] = bool(enabled)
    if intent:
        previous["intent"] = intent
    return previous


def _fallback_result(
    message: str,
    user_context: dict | None,
    previous_state: dict,
    session_id: str,
    progress_id: str | None,
    error: Exception | str,
) -> dict:
    logger.info(
        "Fallback parser used",
        extra={"session_id": session_id},
    )
    previous_clarification = previous_state.get("clarification") or {}
    previous_query = previous_state.get("flight_query") or previous_clarification.get("partial_flight_query") or {}
    previous_preference = dict(previous_state.get("flight_preference") or {})
    previous_history = list(previous_state.get("history") or [])
    previous_alert_request = dict(previous_state.get("alert_request") or {})
    context_filters = list((user_context or {}).get("filters") or [])

    trip = _infer_trip(message, previous_query)
    holiday_duration_intent = _has_holiday_duration_intent(message)
    if holiday_duration_intent:
        trip = "round_trip"
    from_airport, origin_reliable = _infer_origin(message, user_context, previous_query)
    destination_scope = _infer_destination_scope(message, previous_query)
    to_airports = _infer_destinations(message, previous_query, from_airport)
    if destination_scope and not to_airports:
        to_airports = _recommended_destinations_for_scope(destination_scope)
    departure_date, return_date = _infer_dates(message, previous_query)
    inferred_preference = _infer_preference(message, previous_preference, context_filters)
    inferred_alert_request = _infer_alert_request(message, previous_alert_request)

    partial_query = {
        "from_airport": from_airport,
        "to_airports": to_airports,
        "destination_scope": destination_scope,
        "departure_date": departure_date,
        "return_date": return_date,
        "passengers": previous_query.get("passengers") or 1,
        "seat_classes": previous_query.get("seat_classes") or "economy",
        "trip": trip,
        "is_multi_destination": previous_query.get(
            "is_multi_destination",
            bool(destination_scope) or len(to_airports) > 1,
        ),
        "description_of_recommendation": previous_query.get("description_of_recommendation"),
    }
    partial_query = {
        key: value for key, value in partial_query.items() if value not in (None, [], "")
    }

    if from_airport in to_airports:
        return _append_history(
            {
                "session_id": session_id,
                "progress_id": progress_id,
                "user_input": message,
                "user_context": user_context or {},
                "flight_query": None,
                "clarification": None,
                "flight_preference": inferred_preference,
                "alert_request": inferred_alert_request,
                "error_message": (
                    f"Your origin and destination both seem to be {from_airport}. "
                    "Please specify a different destination."
                ),
                "flight_choices": None,
            },
            previous_history,
        )

    clarification = _build_clarification(
        from_airport=from_airport,
        origin_reliable=origin_reliable,
        to_airports=to_airports,
        destination_scope=destination_scope,
        departure_date=departure_date,
        return_date=return_date,
        trip=trip,
        holiday_duration_intent=holiday_duration_intent,
        partial_query=partial_query,
    )
    if clarification:
        return _append_history(
            {
                "session_id": session_id,
                "progress_id": progress_id,
                "user_input": message,
                "user_context": user_context or {},
                "flight_query": None,
                "clarification": clarification,
                "flight_preference": inferred_preference,
                "alert_request": inferred_alert_request,
                "error_message": None,
                "flight_choices": None,
            },
            previous_history,
        )

    flight_query = {
        "from_airport": from_airport,
        "to_airports": to_airports,
        "departure_date": departure_date,
        "return_date": return_date,
        "passengers": previous_query.get("passengers") or 1,
        "seat_classes": previous_query.get("seat_classes") or "economy",
        "trip": trip,
        "is_multi_destination": previous_query.get("is_multi_destination", len(to_airports) > 1),
        "description_of_recommendation": previous_query.get("description_of_recommendation"),
    }
    if destination_scope:
        flight_query["destination_scope"] = destination_scope

    return _append_history(
        {
            "session_id": session_id,
            "progress_id": progress_id,
            "user_input": message,
            "user_context": user_context or {},
            "flight_query": flight_query,
            "clarification": None,
            "flight_preference": inferred_preference,
            "alert_request": inferred_alert_request,
            "error_message": None,
            "flight_choices": None,
        },
        previous_history,
    )


def run_flight_search(
    message: str,
    user_context: dict | None = None,
    session_id: str | None = None,
    progress_id: str | None = None,
) -> dict:
    """
    Run the full flight agent pipeline and return the graph state.
    """
    resolved_session_id = _resolve_session_id(session_id)
    previous_state = _safe_get_previous_state(resolved_session_id)
    input_state = _build_input_state(
        message,
        user_context,
        resolved_session_id,
        progress_id,
        previous_state,
    )

    try:
        if not settings.openai_enabled:
            logger.info(
                "OpenAI disabled; using fallback parser",
                extra={"session_id": resolved_session_id},
            )
            raise ValueError("OPENAI_API_KEY not set")

        logger.info("OpenAI extraction started", extra={"session_id": resolved_session_id})
        thread_config = {"configurable": {"thread_id": resolved_session_id}}
        result = graph.invoke(input_state, config=thread_config)
        logger.info(
            "OpenAI extraction completed",
            extra={
                "session_id": resolved_session_id,
                "flights_count": len(result.get("flight_choices") or []),
            },
        )
        return result
    except ProgressCancelledError:
        raise
    except Exception as e:
        result = _fallback_result(
            message,
            user_context,
            previous_state,
            resolved_session_id,
            progress_id,
            e,
        )
        _persist_fallback_result(result, resolved_session_id)
        return result


def parse_flight_intent(message: str) -> dict:
    """
    Extract structured flight search parameters from user message using LLM.
    """
    result = run_flight_search(message)
    return {
        "flight_query": result.get("flight_query"),
        "clarification": result.get("clarification"),
        "flight_preference": result.get("flight_preference"),
        "error_message": result.get("error_message"),
    }
