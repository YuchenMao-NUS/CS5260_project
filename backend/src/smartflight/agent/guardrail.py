# smartflight/agent/guardrail.py
from pydantic import BaseModel
from openai import OpenAI
from smartflight.agent.state import AgentState
from smartflight.config import settings
import logging

logger = logging.getLogger(__name__)



# Define a minimal output schema to ensure fast model response
class IntentClassification(BaseModel):
    is_flight_related: bool


def intent_guardrail_node(state: AgentState) -> AgentState:
    api_key = settings.openai_api_key
    client = OpenAI(api_key=api_key) if api_key else None
    
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
        response_format=IntentClassification,
        temperature=0.0,
    )

    is_flight_related = response.choices[0].message.parsed.is_flight_related
    logger.debug(f"[Guardrail] Input: {user_input} | Is Flight Related: {is_flight_related}")

    if not is_flight_related:
        return {
            **state,
            "error_message": "I'm your personal flight assistant; currently, I can only help you search for and book flights. Do you have any travel plans?"
        }
    
    return {
        **state,
        "error_message": None
    }