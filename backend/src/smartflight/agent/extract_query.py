from smartflight.agent.state import AgentState
from typing import List, Literal, Optional
from openai import OpenAI
from pydantic import BaseModel
from datetime import datetime, timedelta

import logging
from smartflight.config import settings
logger = logging.getLogger(__name__)

# Structured model for LLM extraction results
class FlightQueryExtraction(BaseModel):
    """Structured model for LLM extraction results."""
    has_origin: bool                                    # Whether the user provided an origin
    trip: Optional[Literal["one_way", "round_trip"]]    # One-way / Round-trip
    from_airport: Optional[str]                         # Origin IATA code
    to_airports: Optional[List[str]]                    # List of destination IATA codes
    departure_date: Optional[str]                       # Departure date YYYY-MM-DD
    return_date: Optional[str]                          # Return date YYYY-MM-DD
    seat_classes: Optional[Literal["business", "economy", "first", "premium-economy"]]
    passengers: Optional[int]



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

    system_prompt = f"""
You are a flight search assistant. Extract structured flight search parameters from the user's natural language input.
Today's date is {today}, {weekday}.
The user's current known location context is: {user_loc_str}.

Extraction rules:
1. has_origin: Set to true. If no departure city/airport is explicitly mentioned, implicitly infer the origin airport based on the user's location context.
2. from_airport: MUST use 3-letter IATA codes. If not explicitly mentioned in the query, deduce the nearest major airport IATA code from their location (e.g. if location is Beijing, use PEK or PKX; if Singapore, use SIN). If location context is completely unhelpful, default to SIN.
3. to_airports: MUST use 3-letter IATA codes (e.g. PEK, SHA, NRT). If no destination is mentioned, recommend 5 suitable destinations based on the origin.
4. trip: Infer from context. Keywords like "round trip", "return", "来回" → round_trip; otherwise → one_way.
5. departure_date: If not mentioned, use today ({today}). Format: YYYY-MM-DD.
6. return_date: Only set for round_trip. If not mentioned, default to departure_date + 7 days.
7. seat_classes: If not specified, return "economy".
8. passengers: If not specified, default to 1.
""".strip()
    
    logger.debug("[LLM] system_prompt:\n%s", system_prompt)
    logger.debug("[LLM] user_input: %s", user_input)

    response = client.beta.chat.completions.parse(
        model="gpt-5-mini", # gpt-4o-mini is too dumb
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
            **state,
            "flight_query": None,
            "error_message": "Where would you like to go? Please provide a destination.",
        }

    # If the user asks for a flight where origin and destination are the same (or LLM confused them)
    if from_airport in to_airports:
        return {
            **state,
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
    }

    return {
        **state,
        "flight_query": flight_query,
        "error_message": None,
    }
