"""NLU: Parse user intent from natural language using LangGraph agent."""

from datetime import datetime, timedelta
import re
from uuid import uuid4

from smartflight.agent.agent import graph
from smartflight.config import settings
from smartflight.services.progress import ProgressCancelledError

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

DIRECT_TRUE_HINTS = ("direct", "non-stop", "nonstop", "no layover", "直飞", "不转机")
DIRECT_FALSE_HINTS = ("don't mind stops", "dont mind stops", "with stops is fine", "layover is fine")

PRICE_MAX_PATTERN = re.compile(r"(?:under|below|less than|max(?:imum)?(?: price)?)[^\d]*(\d+(?:\.\d+)?)", re.I)
PRICE_MIN_PATTERN = re.compile(r"(?:over|above|min(?:imum)?(?: price)?)[^\d]*(\d+(?:\.\d+)?)", re.I)
PRICE_AROUND_PATTERN = re.compile(r"(?:around|about)[^\d]*(\d+(?:\.\d+)?)", re.I)
ORIGIN_FROM_PATTERN = re.compile(r"\bfrom\s+([a-zA-Z\s]+?)(?:\s+\bto\b|$)", re.I)
DESTINATION_TO_PATTERN = re.compile(
    r"\bto\s+([a-zA-Z\s]+?)(?:$|\s+(?:next|this|tomorrow|today|on|under|below|less|more|above|around|about|with|for|return|round)\b)",
    re.I,
)


def _resolve_session_id(session_id: str | None) -> str:
    return session_id or f"chat-{uuid4()}"


def _build_input_state(
    message: str,
    user_context: dict | None,
    session_id: str,
    progress_id: str | None,
) -> dict:
    return {
        "session_id": session_id,
        "progress_id": progress_id,
        "user_input": message,
        "user_context": user_context or {},
        "flight_query": None,
        "flight_preference": None,
        "error_message": None,
        "flight_choices": None,
    }


def _get_previous_state(session_id: str) -> dict:
    snapshot = graph.get_state({"configurable": {"thread_id": session_id}})
    values = getattr(snapshot, "values", None)
    return values if isinstance(values, dict) else {}


def _safe_get_previous_state(session_id: str) -> dict:
    try:
        return _get_previous_state(session_id)
    except Exception:
        return {}


def _match_airport_hint(text: str) -> str | None:
    normalized = text.lower()
    for airport_code, hints in AIRPORT_HINTS.items():
        if any(hint in normalized for hint in hints):
            return airport_code
    return None


def _infer_origin(message: str, user_context: dict | None, previous_query: dict) -> str:
    explicit_origin = None
    if origin_match := ORIGIN_FROM_PATTERN.search(message):
        explicit_origin = _match_airport_hint(origin_match.group(1))
    if explicit_origin:
        return explicit_origin

    previous_origin = previous_query.get("from_airport")
    if previous_origin:
        return previous_origin

    location = (user_context or {}).get("location") or ""
    time_zone = (user_context or {}).get("timeZone") or ""
    context_match = _match_airport_hint(f"{location} {time_zone}")
    if context_match:
        return context_match

    return "SIN"


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

    return ["TYO"]


def _infer_trip(message: str, previous_query: dict) -> str:
    normalized = message.lower()
    if any(keyword in normalized for keyword in ("round trip", "round-trip", "return", "来回")):
        return "round_trip"
    return previous_query.get("trip") or "one_way"


def _infer_dates(previous_query: dict, trip: str) -> tuple[str, str | None]:
    today = datetime.now().strftime("%Y-%m-%d")
    departure_date = previous_query.get("departure_date") or today

    if trip == "round_trip":
        return_date = previous_query.get("return_date")
        if not return_date:
            return_date = (
                datetime.strptime(departure_date, "%Y-%m-%d") + timedelta(days=7)
            ).strftime("%Y-%m-%d")
        return departure_date, return_date

    return departure_date, None


def _infer_preference(message: str, previous_preference: dict) -> dict:
    normalized = message.lower()
    preference = dict(previous_preference)

    if any(hint in normalized for hint in DIRECT_TRUE_HINTS):
        preference["direct_only"] = True
    elif any(hint in normalized for hint in DIRECT_FALSE_HINTS):
        preference["direct_only"] = False

    matched_airlines = [
        airline_code
        for airline_code, hints in AIRLINE_HINTS.items()
        if any(hint in normalized for hint in hints)
    ]
    if matched_airlines:
        preference["preferred_airlines"] = matched_airlines

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


def _fallback_result(
    message: str,
    user_context: dict | None,
    previous_state: dict,
    error: Exception | str,
) -> dict:
    previous_query = previous_state.get("flight_query") or {}
    previous_preference = previous_state.get("flight_preference") or {}
    trip = _infer_trip(message, previous_query)
    from_airport = _infer_origin(message, user_context, previous_query)
    to_airports = _infer_destinations(message, previous_query, from_airport)
    departure_date, return_date = _infer_dates(previous_query, trip)

    if not to_airports:
        return {
            "user_input": message,
            "flight_query": None,
            "flight_preference": _infer_preference(message, previous_preference),
            "error_message": (
                "I couldn't resolve the destination into airport codes. "
                "Please specify a city or airport."
            ),
            "flight_choices": None,
        }

    if from_airport in to_airports:
        return {
            "user_input": message,
            "flight_query": None,
            "flight_preference": _infer_preference(message, previous_preference),
            "error_message": (
                f"Your origin and destination both seem to be {from_airport}. "
                "Please specify a different destination."
            ),
            "flight_choices": None,
        }

    return {
        "user_input": message,
        "flight_query": {
            "from_airport": from_airport,
            "to_airports": to_airports,
            "departure_date": departure_date,
            "return_date": return_date,
            "passengers": previous_query.get("passengers") or 1,
            "seat_classes": previous_query.get("seat_classes") or "economy",
            "trip": trip,
            "is_multi_destination": previous_query.get("is_multi_destination", len(to_airports) > 1),
            "description_of_recommendation": previous_query.get("description_of_recommendation"),
        },
        "flight_preference": _infer_preference(message, previous_preference),
        "error_message": None,
        "flight_choices": None,
    }


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
    input_state = _build_input_state(message, user_context, resolved_session_id, progress_id)
    previous_state = _safe_get_previous_state(resolved_session_id)

    try:
        if not settings.openai_enabled:
            raise ValueError("OPENAI_API_KEY not set")

        thread_config = {"configurable": {"thread_id": resolved_session_id}}
        return graph.invoke(input_state, config=thread_config)
    except ProgressCancelledError:
        raise
    except Exception as e:
        return _fallback_result(message, user_context, previous_state, e)


def parse_flight_intent(message: str) -> dict:
    """
    Extract structured flight search parameters from user message using LLM.
    """
    result = run_flight_search(message)
    return {
        "flight_query": result.get("flight_query"),
        "flight_preference": result.get("flight_preference"),
        "error_message": result.get("error_message"),
    }
