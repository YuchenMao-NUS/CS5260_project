from typing import List, Optional
import logging

from openai import OpenAI
from pydantic import BaseModel

from smartflight.agent.state import AgentState
from smartflight.config import settings
from smartflight.services.progress import emit_progress, raise_if_progress_cancelled

logger = logging.getLogger(__name__)


class FlightPreferenceExtraction(BaseModel):
    direct_only: Optional[bool] = None
    max_stops: Optional[int] = None
    min_stops: Optional[int] = None
    preferred_airlines: Optional[List[str]] = None
    max_price: Optional[float] = None
    min_price: Optional[float] = None
    max_duration: Optional[int] = None
    min_duration: Optional[int] = None


def _preference_from_filters(user_filters: list[dict]) -> dict[str, object]:
    preference: dict[str, object] = {}

    for raw_filter in user_filters:
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

    return preference


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
                f"departure={fq.get('departure_date')}, "
                f"return={fq.get('return_date')}, "
                f"class={fq.get('seat_classes')}, "
                f"passengers={fq.get('passengers')}"
            )
        else:
            lines.append("Query: None")

        pref = turn.get("flight_preference")
        if pref:
            lines.append(
                "Preference: "
                + ", ".join(f"{k}={v}" for k, v in pref.items())
            )
        else:
            lines.append("Preference: None")

        lines.append("")

    return "\n".join(lines)


def extract_preference_node(state: AgentState) -> AgentState:
    raise_if_progress_cancelled(state.get("progress_id"))

    api_key = settings.openai_api_key
    client = OpenAI(api_key=api_key) if api_key else None
    if not client:
        raise ValueError("OPENAI_API_KEY not set")

    emit_progress(
        state.get("progress_id"),
        "analyzing_request",
        "Identifying airline, price, stop, and duration preferences...",
    )
    raise_if_progress_cancelled(state.get("progress_id"))

    user_input = state["user_input"]
    user_filters = state.get("user_context", {}).get("filters") or []
    existing_preference = state.get("flight_preference") or {}
    history = state.get("history")
    previous_context = _build_previous_context(history)

    logger.debug("=== previous_context (preference) ===")
    for line in previous_context.split("\n"):
        logger.debug("  %s", line)

    system_prompt = f"""
You are a flight preference extraction assistant. Extract the user's soft preferences from their natural language input.

The previous context below is the conversation memory:
{previous_context}

CRITICAL INSTRUCTION:
Use the previous context to understand whether the user is adding, refining, or changing a preference.
Do not discard previous preferences unless the user explicitly changes them or clearly implies a change.

All fields are optional and should only be populated if the user expresses that preference.

Extraction rules:
1. direct_only:
   - true if the user wants direct/non-stop flights only
   - false if the user explicitly says stops are acceptable
   - null if not mentioned
2. max_stops / min_stops:
   - Extract stop-count constraints when stated
   - "direct only" implies max_stops=0
   - "max 1 stop" implies max_stops=1
   - "2+ stops" implies min_stops=2
3. preferred_airlines:
   - Return IATA 2-letter airline codes
4. max_price / min_price:
   - Extract price constraints in SGD
   - "around 300" means min_price=270 and max_price=330
5. max_duration / min_duration:
   - Extract duration constraints in minutes
""".strip()

    logger.debug("[extract_preference] system_prompt:\n%s", system_prompt)
    logger.debug("[extract_preference] user_input: %s", user_input)

    response = client.beta.chat.completions.parse(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        response_format=FlightPreferenceExtraction,
    )

    extraction: FlightPreferenceExtraction = response.choices[0].message.parsed

    merged_preference = {
        "direct_only": extraction.direct_only if extraction.direct_only is not None else existing_preference.get("direct_only"),
        "max_stops": extraction.max_stops if extraction.max_stops is not None else existing_preference.get("max_stops"),
        "min_stops": extraction.min_stops if extraction.min_stops is not None else existing_preference.get("min_stops"),
        "preferred_airlines": extraction.preferred_airlines if extraction.preferred_airlines is not None else existing_preference.get("preferred_airlines"),
        "max_price": extraction.max_price if extraction.max_price is not None else existing_preference.get("max_price"),
        "min_price": extraction.min_price if extraction.min_price is not None else existing_preference.get("min_price"),
        "max_duration": extraction.max_duration if extraction.max_duration is not None else existing_preference.get("max_duration"),
        "min_duration": extraction.min_duration if extraction.min_duration is not None else existing_preference.get("min_duration"),
    }

    merged_preference.update(_preference_from_filters(user_filters))

    logger.info(
        "Preference extraction completed",
        extra={"choices_count": len([value for value in merged_preference.values() if value is not None])},
    )

    return {
        "flight_preference": merged_preference,
    }
