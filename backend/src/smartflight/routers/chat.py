"""Chat / flight search API endpoints."""

from __future__ import annotations

import json
from asyncio import TimeoutError as AsyncTimeoutError, wait_for
from collections.abc import Iterator
from queue import Empty
from threading import Thread
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from smartflight.services.chat_formatting import format_demo_flight, format_graph_flight
from smartflight.services.booking import resolve_booking_url, store_result_set
from smartflight.services.nlu import run_flight_search
from smartflight.services.flight_search import get_flights, is_demo_trigger
from smartflight.services.progress import (
    cancel_progress,
    emit_completed,
    emit_error,
    emit_progress,
    is_progress_cancelled,
    ProgressCancelledError,
    register_progress_queue,
    unregister_progress_queue,
)
from smartflight.services.recommendation_text import rephrase_recommendation_as_assistant

router = APIRouter()


class ChatContext(BaseModel):
    timeZone: str | None = None
    location: str | None = None
    filters: list[dict[str, str]] | None = None

class ChatRequest(BaseModel):
    """Chat request body."""

    message: str
    session_id: str = Field(default_factory=lambda: f"chat-{uuid4()}")  # Unique conversation id unless client supplies one
    context: ChatContext | None = None


class FlightLeg(BaseModel):
    """A single leg of a journey (e.g. Outbound or Inbound)."""
    airlineCode: str
    departure: str
    arrival: str
    duration: str
    duration_minutes: int
    stops: str
    stopCount: int
    stopAirports: list[str]


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
    resultSetId: str | None = None
    description_of_recommendation: str | None = None
    intent: dict | None = None


class BookingUrlRequest(BaseModel):
    session_id: str
    result_set_id: str
    flight_id: str


class BookingUrlResponse(BaseModel):
    bookingUrl: str


def _build_intent(result: dict) -> dict:
    return {
        "flight_query": result.get("flight_query"),
        "flight_preference": result.get("flight_preference"),
        "error_message": result.get("error_message"),
    }


def _build_route_info(query: dict) -> str:
    origin_str = query.get("from_airport", "Unknown Origin")
    destinations = query.get("to_airports", [])

    if not destinations:
        destination_str = "anywhere"
    elif len(destinations) > 2:
        destination_str = f"several destinations (including {destinations[0]}, {destinations[1]})"
    else:
        destination_str = " and ".join(destinations)

    departure_date = query.get("departure_date")
    return_date = query.get("return_date")
    trip_type = query.get("trip")

    date_info = f" on {departure_date}" if departure_date else ""
    if trip_type == "round_trip" and return_date:
        date_info += f" (returning {return_date})"

    return f"from {origin_str} to {destination_str}{date_info}"


def _new_progress_id(session_id: str) -> str:
    return f"{session_id}:stream:{uuid4()}"


def _iter_response_events(
    result: dict,
    message: str,
    session_id: str,
    progress_id: str | None = None,
) -> Iterator[dict]:
    intent = _build_intent(result)
    if intent.get("error_message"):
        yield {
            "type": "completed",
            "data": ChatResponse(
                reply=intent["error_message"],
                flights=None,
                resultSetId=None,
                description_of_recommendation=None,
                intent=intent,
            ),
        }
        return

    yield {
        "type": "progress",
        "stage": "formatting_results",
        "message": "Preparing results for display...",
    }

    query = intent.get("flight_query") or {}
    route_info = _build_route_info(query)
    use_demo = is_demo_trigger(message)
    graph_flights = result.get("flight_choices") or []
    result_set_id = str(uuid4())

    if graph_flights:
        store_result_set(
            session_id,
            result_set_id,
            query,
            flight_choices=graph_flights,
        )
        reply = f"Found {len(graph_flights)} flight option(s) {route_info}. See details below."
        flight_options = [
            FlightOption(**format_graph_flight(choice, idx))
            for idx, choice in enumerate(graph_flights, start=1)
        ]
    else:
        demo_flights = get_flights(intent, use_demo=use_demo)
        if demo_flights:
            store_result_set(
                session_id,
                result_set_id,
                query,
                demo_flights=demo_flights,
            )
            reply = f"Found {len(demo_flights)} flight option(s) {route_info}. See details below."
            flight_options = [FlightOption(**format_demo_flight(flight)) for flight in demo_flights]
        else:
            reply = "No matching flights were found for your request."
            flight_options = None
            result_set_id = None

    yield {
        "type": "progress",
        "stage": "generating_summary",
        "message": "Generating recommendation summary...",
    }

    description_of_recommendation = None
    if not is_progress_cancelled(progress_id):
        description_of_recommendation = rephrase_recommendation_as_assistant(
            query.get("description_of_recommendation"),
            flight_query=query,
            flight_count=len(flight_options) if flight_options else 0,
        )

    yield {
        "type": "completed",
        "data": ChatResponse(
            reply=reply,
            flights=flight_options,
            resultSetId=result_set_id,
            description_of_recommendation=description_of_recommendation,
            intent=intent,
        ),
    }


def _run_chat_request_sync(
    message: str,
    user_context: dict,
    session_id: str,
    progress_id: str | None = None,
    on_event=None,
) -> ChatResponse:
    result = run_flight_search(message, user_context, session_id, progress_id=progress_id)
    response: ChatResponse | None = None
    for event in _iter_response_events(result, message, session_id, progress_id):
        if on_event is not None:
            on_event(event)
        if event["type"] == "completed":
            response = event["data"]

    if response is None:
        raise RuntimeError("Chat pipeline completed without a response.")

    return response


def _serialize_stream_event(event: dict) -> str:
    payload = dict(event)
    if payload.get("type") == "completed" and hasattr(payload.get("data"), "model_dump"):
        payload["data"] = payload["data"].model_dump()
    return f"data: {json.dumps(payload)}\n\n"


async def _stream_chat_request(http_request: Request, chat_request: ChatRequest):
    user_context = chat_request.context.model_dump() if chat_request.context else {}
    progress_id = _new_progress_id(chat_request.session_id)
    progress_queue = register_progress_queue(progress_id)

    try:
        def on_event(event: dict) -> None:
            if event["type"] == "completed":
                emit_completed(progress_id, event["data"].model_dump())
            else:
                emit_progress(
                    progress_id,
                    event["stage"],
                    event["message"],
                )

        def run_worker() -> None:
            try:
                emit_progress(
                    progress_id,
                    "analyzing_request",
                    "AI is analyzing your request...",
                )
                _run_chat_request_sync(
                    chat_request.message,
                    user_context,
                    chat_request.session_id,
                    progress_id,
                    on_event,
                )
            except ProgressCancelledError:
                return
            except Exception as exc:
                emit_error(progress_id, str(exc))

        worker = Thread(target=run_worker, daemon=True)
        worker.start()

        while worker.is_alive() or not progress_queue.empty():
            if await http_request.is_disconnected():
                cancel_progress(progress_id)
                break

            try:
                event = await wait_for(
                    run_in_threadpool(progress_queue.get, True, 0.5),
                    timeout=1.0,
                )
            except (Empty, AsyncTimeoutError):
                continue
            yield _serialize_stream_event(event)
    finally:
        cancel_progress(progress_id)
        unregister_progress_queue(progress_id)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process user message, run the flight agent pipeline, and return matching flights.
    """
    try:
        user_context = request.context.model_dump() if request.context else {}
        return await run_in_threadpool(
            _run_chat_request_sync,
            request.message,
            user_context,
            request.session_id,
            None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/booking-url", response_model=BookingUrlResponse)
async def booking_url(request: BookingUrlRequest):
    booking_url_value = await run_in_threadpool(
        resolve_booking_url,
        request.session_id,
        request.result_set_id,
        request.flight_id,
    )
    return BookingUrlResponse(bookingUrl=booking_url_value)


@router.post("/chat/stream")
async def chat_stream(request: Request, payload: ChatRequest):
    """
    Stream real backend progress updates and the final chat response.
    """
    return StreamingResponse(
        _stream_chat_request(request, payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
