from typing import List, Literal, Optional
from openai import OpenAI
from pydantic import BaseModel
from datetime import datetime, timedelta
from smartflight.agent.state import AgentState
from smartflight.config import settings
import logging

logger = logging.getLogger(__name__)



# Structured LLM output schema
class FlightQueryExtraction(BaseModel):
    trip: Optional[Literal["one_way", "round_trip"]]    # One-way / Round-trip
    from_airport: Optional[str]                         # Origin IATA code
    to_airports: Optional[List[str]]                    # List of destination IATA codes
    departure_date: Optional[str]                       # Departure date YYYY-MM-DD
    return_date: Optional[str]                          # Return date YYYY-MM-DD
    seat_classes: Optional[Literal["business", "economy", "first", "premium-economy"]]
    passengers: Optional[int]
    is_multi_destination: Optional[bool]                # Boolean values ​​for LLM output
    description_of_recommendation: Optional[str]



def extract_query_node(state: AgentState) -> AgentState:
    api_key = settings.openai_api_key
    client = OpenAI(api_key=api_key) if api_key else None
    if not client:
        raise ValueError("OPENAI_API_KEY not set")
        
    # Get current time using datetime
    today = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().strftime("%A")
    user_input = state["user_input"]
    
    # Extract user context
    user_context = state.get("user_context", {})
    location = user_context.get("location")
    tz = user_context.get("timeZone", "")
    
    user_loc_str = f"City/Country: {location}" if location else f"Timezone: {tz}"

    # Get incomplete information already extracted in the previous round
    previous_query = state.get("flight_query")
    previous_context = f"Previously extracted parameters: {previous_query}" if previous_query else "No previous parameters. This is a new search."

    system_prompt = f"""
You are a flight search assistant. Extract structured flight search parameters from the user's natural language input.
Today's date is {today}, {weekday}.
The user's current known location context is: {user_loc_str}.

{previous_context}
CRITICAL INSTRUCTION: If there are "Previously extracted parameters", the user is likely answering a follow-up question or providing missing information. You MUST merge the new information from the user's current input with the previously extracted parameters. Do not discard previous constraints unless the user explicitly changes them.

Extraction rules:
1. from_airport: MUST use 3-letter IATA codes. If not explicitly mentioned in the query, deduce the nearest major airport IATA code from their location (e.g. if location is Beijing, use PEK or PKX; if Singapore, use SIN). If location context is completely unhelpful, default to SIN.
2. to_airports: MUST use 3-letter IATA codes (e.g. PEK, SHA, NRT). If no destination is mentioned, recommend 5 suitable destinations based on the origin.
3. trip: Infer from context. Keywords like "round trip", "return", "来回" → round_trip; otherwise → one_way.
4. departure_date: If not mentioned, use today ({today}). Format: YYYY-MM-DD.
5. return_date: Only set for round_trip. If not mentioned, default to departure_date + 7 days.
6. seat_classes: If not specified, return "economy".
7. passengers: If not specified, default to 1.
8. is_multi_destination:
   - Set to `true` when the user has no specific destination.
   - Set to `false` if they only want to visit one destination. (e.g., "I want to go to Tokyo").
9. description_of_recommendation: Give a brief description of your recommendation.
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

    # Fallback missing origin/destination checks
    from_airport = extraction.from_airport
    if not from_airport:
        # If LLM failed to infer it from context, try a generic fallback
        from_airport = "SIN"

    to_airports = extraction.to_airports or []
    if not to_airports:
        # If LLM failed to provide a destination, we can either raise an error or provide generic suggestions
        # Usually we want the user to specify a destination
        return {
            # **state,
            "flight_query": None,
            "error_message": "Where would you like to go? Please provide a destination.",
        }

    # If the user asks for a flight where origin and destination are the same (or LLM confused them)
    if from_airport in to_airports:
        return {
            # **state,
            "flight_query": None,
            "error_message": f"Your origin and destination both seem to be {from_airport}. Please specify a different destination.",
        }

    # Fill in default values
    departure_date = extraction.departure_date or today

    if extraction.trip == "round_trip" and not extraction.return_date:
        return_date = (
            datetime.strptime(departure_date, "%Y-%m-%d") + timedelta(days=7)
        ).strftime("%Y-%m-%d")
    else:
        return_date = extraction.return_date  # None for one_way

    seat_classes = extraction.seat_classes or "economy"

    flight_query = {
        "trip": extraction.trip,
        "from_airport": from_airport,
        "to_airports": to_airports,
        "departure_date": departure_date,
        "return_date": return_date,
        "seat_classes": seat_classes,
        "passengers": extraction.passengers or 1,
        "is_multi_destination": extraction.is_multi_destination,
        "description_of_recommendation": extraction.description_of_recommendation
    }

    return {
        # **state,
        "flight_query": flight_query,
        "error_message": None,
    }
