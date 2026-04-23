# smartflight/agent/guardrail.py
from pydantic import BaseModel
from openai import OpenAI
from smartflight.agent.state import AgentState
from smartflight.config import settings
from smartflight.services.progress import emit_progress, raise_if_progress_cancelled
import logging

logger = logging.getLogger(__name__)



# Define a minimal output schema to ensure fast model response
class IntentClassification(BaseModel):
    is_flight_related: bool


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

    system_prompt = """
You are an intent classification router for a flight booking system.
Determine if the user's input is related to searching, booking, inquiring about, or modifying flight tickets.
- Return true for: "Book a flight to Tokyo", "明天去北京", "Are there any cheap tickets?", "I want to go to London".
- Return false for general chit-chat, coding questions, math problems, hotel bookings, or unrelated topics (e.g., "Tell me a joke", "写一段Python代码", "你好").
""".strip()

    response = client.beta.chat.completions.parse(
        model="gpt-5-nano", 
        messages=[
            {"role": "system", "content": system_prompt},
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
