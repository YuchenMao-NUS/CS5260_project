"""Chat / flight search API endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from smartflight.services.nlu import parse_flight_intent
from smartflight.services.flight_search import get_flights, is_demo_trigger

router = APIRouter()


class ChatRequest(BaseModel):
    """Chat request body."""

    message: str


class FlightOption(BaseModel):
    """Flight option for response."""

    id: str
    airlineCode: str
    departure: str
    arrival: str
    duration: str
    duration_minutes: int
    price: float
    stops: str


class ChatResponse(BaseModel):
    """Chat response body."""

    reply: str
    flights: list[FlightOption] | None = None
    intent: dict | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process user message: parse intent, return response.
    Flight search and API integration will be added in a later phase.
    """
    try:
        intent = parse_flight_intent(request.message)
        use_demo = is_demo_trigger(request.message)
        flights = get_flights(intent, use_demo=use_demo)

        if flights:
            reply = f"Found {len(flights)} flight option(s). See details below."
            flight_options = [
                FlightOption(
                    id=f["id"],
                    airlineCode=f["airlineCode"],
                    departure=f["departure"],
                    arrival=f["arrival"],
                    duration=f["duration"],
                    duration_minutes=f["duration_minutes"],
                    price=f["price"],
                    stops=f["stops"],
                )
                for f in flights
            ]
        else:
            reply = "Intent parsed. Flight search and API integration will be added in a later phase."
            flight_options = None

        return ChatResponse(
            reply=reply,
            flights=flight_options,
            intent=intent,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
