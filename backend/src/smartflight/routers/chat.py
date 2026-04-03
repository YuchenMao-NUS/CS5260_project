"""Chat / flight search API endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from smartflight.services.chat_formatting import format_demo_flight, format_graph_flight
from smartflight.services.nlu import run_flight_search
from smartflight.services.flight_search import get_flights, is_demo_trigger

router = APIRouter()


class ChatRequest(BaseModel):
    """Chat request body."""

    message: str


class FlightLeg(BaseModel):
    """A single leg of a journey (e.g. Outbound or Inbound)."""
    airlineCode: str
    departure: str
    arrival: str
    duration: str
    duration_minutes: int
    stops: str


class FlightOption(BaseModel):
    """Flight option for response, containing one or more legs."""

    id: str
    price: float
    tripType: str
    legs: list[FlightLeg]
    bookingUrl: str | None = None


class ChatResponse(BaseModel):
    """Chat response body."""

    reply: str
    flights: list[FlightOption] | None = None
    intent: dict | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process user message, run the flight agent pipeline, and return matching flights.
    """
    try:
        result = run_flight_search(request.message)
        intent = {
            "flight_query": result.get("flight_query"),
            "flight_preference": result.get("flight_preference"),
            "error_message": result.get("error_message"),
        }

        use_demo = is_demo_trigger(request.message)
        graph_flights = result.get("flight_choices") or []

        if graph_flights:
            reply = f"Found {len(graph_flights)} flight option(s). See details below."
            flight_options = [
                FlightOption(**format_graph_flight(choice, idx))
                for idx, choice in enumerate(graph_flights, start=1)
            ]
        else:
            demo_flights = get_flights(intent, use_demo=use_demo)
            if demo_flights:
                reply = f"Found {len(demo_flights)} flight option(s). See details below."
                flight_options = [FlightOption(**format_demo_flight(flight)) for flight in demo_flights]
            elif intent["error_message"]:
                reply = intent["error_message"]
                flight_options = None
            else:
                reply = "No matching flights were found for your request."
                flight_options = None

        return ChatResponse(
            reply=reply,
            flights=flight_options,
            intent=intent,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
