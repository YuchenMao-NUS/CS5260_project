from typing import List, Optional
from openai import OpenAI
from pydantic import BaseModel
from smartflight.agent.state import AgentState
from smartflight.config import settings
import logging

logger = logging.getLogger(__name__)



# Structured LLM output schema
class FlightPreferenceExtraction(BaseModel):
    direct_only: Optional[bool]              # Whether direct flights are explicitly requested
    preferred_airlines: Optional[List[str]]  # List of 2-letter airline codes
    max_price: Optional[float]               # Max price SGD
    min_price: Optional[float]               # Min price SGD
    max_duration: Optional[int]              # Max duration (minutes)
    min_duration: Optional[int]              # Min duration (minutes)
    


def extract_preference_node(state: AgentState) -> AgentState:
    api_key = settings.openai_api_key
    client = OpenAI(api_key=api_key) if api_key else None
    if not client:
        raise ValueError("OPENAI_API_KEY not set")
        
    user_input = state["user_input"]

    # Retrieve historical preferences from the current state; if no such preferences exist, initialize them to an empty dictionary
    existing_preference = state.get("flight_preference") or {}

    system_prompt = """
You are a flight preference extraction assistant. Extract the user's soft preferences from their natural language input.
All fields are optional — only populate a field if the user explicitly or implicitly expresses that preference.

Extraction rules:
1. direct_only:
   - true if the user wants non-stop/direct flights only (e.g. "direct", "non-stop", "不转机", "直飞")
   - false if the user explicitly says they don't mind connecting flights
   - null if not mentioned at all

2. preferred_airlines:
   - Extract as a list of IATA 2-letter airline codes (e.g. "CA" for Air China, "MU" for China Eastern, "SQ" for Singapore Airlines)
   - null if no airline preference is mentioned

3. max_price / min_price:
   - Extract price constraints in SGD
   - If user says "under $500", set max_price=500.0, min_price=null
   - If user says "around $300", set min_price=270.0, max_price=330.0 (±10%)
   - null if not mentioned

4. max_duration / min_duration:
   - Extract flight duration constraints in MINUTES
   - If user says "less than 3 hours", set max_duration=180, min_duration=null
   - null if not mentioned
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

    # Merging old and new preferences
    # If the field extracted this time is not None, then overwrite.
    # Otherwise, revert to using the value stored in existing_preference.
    merged_preference = {
        "direct_only": extraction.direct_only if extraction.direct_only is not None else existing_preference.get("direct_only"),
        "preferred_airlines": extraction.preferred_airlines if extraction.preferred_airlines is not None else existing_preference.get("preferred_airlines"),
        "max_price": extraction.max_price if extraction.max_price is not None else existing_preference.get("max_price"),
        "min_price": extraction.min_price if extraction.min_price is not None else existing_preference.get("min_price"),
        "max_duration": extraction.max_duration if extraction.max_duration is not None else existing_preference.get("max_duration"),
        "min_duration": extraction.min_duration if extraction.min_duration is not None else existing_preference.get("min_duration"),
    }

    logger.info(f"[extract_preference] Updated Preferences: {merged_preference}")

    flight_preference = {
        "direct_only": extraction.direct_only,
        "preferred_airlines": extraction.preferred_airlines,
        "max_price": extraction.max_price,
        "min_price": extraction.min_price,
        "max_duration": extraction.max_duration,
        "min_duration": extraction.min_duration,
    }

    return {
        # **state,
        "flight_preference": flight_preference,
    }