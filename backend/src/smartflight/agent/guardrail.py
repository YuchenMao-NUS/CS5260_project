# smartflight/agent/guardrail.py
import logging
import re

from openai import OpenAI
from pydantic import BaseModel

from smartflight.agent.state import AgentState
from smartflight.config import settings
from smartflight.services.progress import emit_progress, raise_if_progress_cancelled

logger = logging.getLogger(__name__)


SHORT_FOLLOWUP_PATTERN = re.compile(
    r"""
    ^\s*
    (?:
        yes|no|ok|okay|sure|
        suggest|recommend|any\s+city|anywhere|surprise\s+me|
        \d{1,3}\s*(?:day|days|night|nights|week|weeks)|
        (?:under|below|less\s+than|around|about)\s+\d+(?:\.\d+)?|
        (?:january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sep|october|oct|november|nov|december|dec)\s+\d{1,2}|
        next\s+\w+|this\s+\w+|tomorrow|today|
        from\s+.+|to\s+.+
    )
    [.!?]?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


# Define a minimal output schema to ensure fast model response
class IntentClassification(BaseModel):
    is_flight_related: bool


def _is_pending_clarification_followup(state: AgentState) -> bool:
    clarification = state.get("clarification") or {}
    if not clarification or clarification.get("can_search", True):
        return False

    user_input = str(state.get("user_input") or "").strip()
    if not user_input:
        return False

    return bool(SHORT_FOLLOWUP_PATTERN.fullmatch(user_input))


def _build_guardrail_context(state: AgentState) -> str:
    context_parts: list[str] = []

    clarification = state.get("clarification") or {}
    if clarification:
        context_parts.append(
            "Pending flight clarification: "
            f"needed_fields={clarification.get('needed_fields')}, "
            f"question={clarification.get('question')}, "
            f"partial_flight_query={clarification.get('partial_flight_query')}"
        )

    flight_query = state.get("flight_query")
    if flight_query:
        context_parts.append(f"Previous flight query: {flight_query}")

    history = state.get("history") or []
    if history:
        recent = history[-3:]
        history_lines = []
        for turn in recent:
            history_lines.append(
                "User: "
                f"{turn.get('user_input')}; "
                f"clarification={turn.get('clarification')}; "
                f"flight_query={turn.get('flight_query')}"
            )
        context_parts.append("Recent turns:\n" + "\n".join(history_lines))

    if not context_parts:
        return "No previous flight context."

    return "\n\n".join(context_parts)


def intent_guardrail_node(state: AgentState) -> AgentState:
    raise_if_progress_cancelled(state.get("progress_id"))

    api_key = settings.openai_api_key
    client = OpenAI(api_key=api_key) if api_key else None
    emit_progress(
        state.get("progress_id"),
        "analyzing_request",
        "Checking whether your request is flight-related...",
    )
    raise_if_progress_cancelled(state.get("progress_id"))

    user_input = state["user_input"]
    guardrail_context = _build_guardrail_context(state)

    if _is_pending_clarification_followup(state):
        logger.info(
            "Intent guardrail accepted pending clarification follow-up",
            extra={"message_length": len(user_input)},
        )
        return {
            **state,
            "error_message": None
        }

    system_prompt = """
You are an intent classification router for a flight booking system.
Determine if the user's input is related to searching, booking, inquiring about, or modifying flight tickets.
- Return true for: "Book a flight to Tokyo", "I need a flight tomorrow", "Are there any cheap tickets?", "I want to go to London".
- Return true when the user gives a short answer to a pending flight clarification, such as "next week", "7 days", "any city", "suggest", "yes", "no", a city name, a date, or a budget.
- Return false for general chit-chat, coding questions, math problems, hotel bookings, or unrelated topics (e.g., "Tell me a joke", "Write a Python script", "Hello").
Use the previous flight context below only to decide whether the current input is a follow-up to an active flight search.
""".strip()

    response = client.beta.chat.completions.parse(
        model="gpt-5-nano", 
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"Previous flight context:\n{guardrail_context}"},
            {"role": "user", "content": user_input},
        ],
        response_format=IntentClassification
    )

    is_flight_related = response.choices[0].message.parsed.is_flight_related
    logger.info(
        "Intent guardrail completed",
        extra={"message_length": len(user_input), "is_flight_related": is_flight_related},
    )

    if not is_flight_related:
        return {
            **state,
            "error_message": "I'm your personal flight assistant; currently, I can only help you search for and book flights. Do you have any travel plans?"
        }
    
    return {
        **state,
        "error_message": None
    }
