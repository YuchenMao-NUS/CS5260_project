"""NLU: Parse user intent from natural language using LangGraph agent."""

from smartflight.agent.agent import graph
from smartflight.config import settings


def run_flight_search(message: str, user_context: dict = None, session_id: str = "default_session") -> dict:
    """
    Run the full flight agent pipeline and return the graph state.
    """
    input_state = {
        "user_input": message,
        "user_context": user_context or {},
        "flight_query": None,
        "flight_preference": None,
        "error_message": None,
        "flight_choices": None,
    }

    try:
        if not settings.openai_enabled:
            raise ValueError("OPENAI_API_KEY not set")

        thread_config = {"configurable": {"thread_id": session_id}}

        return graph.invoke(input_state, config=thread_config)
    except Exception as e:
        # Fallback to rule-based placeholder if LLM fails or no API key
        msg_lower = message.lower()
        origins = {"singapore": "SIN", "sin": "SIN", "sg": "SIN"}
        dests = {"tokyo": "TYO", "tyo": "TYO", "japan": "TYO", "osaka": "KIX"}
        origin = "SIN"
        destination = "TYO"
        for key, value in origins.items():
            if key in msg_lower:
                origin = value
                break
        for key, value in dests.items():
            if key in msg_lower:
                destination = value
                break

        return {
            "user_input": message,
            "flight_query": {
                "from_airport": origin,
                "to_airports": [destination],
                "departure_date": "2026-04-15",
                "return_date": None,
                "passengers": 1,
                "seat_classes": "economy",
                "trip": "one_way",
            },
            "flight_preference": {},
            "error_message": f"LLM parsing failed or disabled: {str(e)}",
            "flight_choices": None,
        }


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
