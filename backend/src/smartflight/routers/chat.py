"""Chat / flight search API endpoints."""

from __future__ import annotations

import json
import logging
import re
from asyncio import TimeoutError as AsyncTimeoutError, wait_for
from collections.abc import Iterator
from queue import Empty
from threading import Thread
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from smartflight.services.chat_formatting import format_demo_flight, format_graph_flight
from smartflight.services.booking import (
    get_latest_intent,
    remember_latest_intent,
    resolve_booking_url,
    store_result_set,
)
from smartflight.services.alerts import cancel_active_alerts, create_alert, get_alert, list_alerts
from smartflight.services.emailer import send_test_email
from smartflight.services.nlu import run_flight_search
from smartflight.config import settings
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
from smartflight.logging_config import copy_request_context, get_request_context, set_request_context

router = APIRouter()
logger = logging.getLogger(__name__)
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
ALERT_HINTS = ("notify", "email me", "alert me", "let me know", "send me")
CANCEL_ALERT_HINTS = ("do not notify", "don't notify", "stop notify", "stop notifying", "cancel alert", "stop alert")


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
    alertId: str | None = None
    alertStatus: str | None = None
    description_of_recommendation: str | None = None
    intent: dict | None = None


class BookingUrlRequest(BaseModel):
    session_id: str
    result_set_id: str
    flight_id: str


class BookingUrlResponse(BaseModel):
    bookingUrl: str


class TestEmailRequest(BaseModel):
    to_email: str | None = None


class TestEmailResponse(BaseModel):
    status: str
    recipient: str


class AlertSummary(BaseModel):
    id: str
    session_id: str
    email: str
    status: str
    created_at: str
    expires_at: str
    notified_at: str | None = None
    last_error: str | None = None
    flight_query: dict
    flight_preference: dict
    metadata: dict


def _to_alert_summary(record) -> AlertSummary:
    return AlertSummary(
        id=record.id,
        session_id=record.session_id,
        email=record.email,
        status=record.status,
        created_at=record.created_at.isoformat(),
        expires_at=record.expires_at.isoformat(),
        notified_at=record.notified_at.isoformat() if record.notified_at else None,
        last_error=record.last_error,
        flight_query=dict(record.flight_query or {}),
        flight_preference=dict(record.flight_preference or {}),
        metadata=dict(record.metadata or {}),
    )


def _build_intent(result: dict) -> dict:
    return {
        "flight_query": result.get("flight_query"),
        "clarification": result.get("clarification"),
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


def _fallback_alert_request_from_message(message: str) -> dict:
    normalized = (message or "").lower()
    email_match = EMAIL_PATTERN.search(message or "")
    email = email_match.group(0).strip() if email_match else ""
    if any(hint in normalized for hint in CANCEL_ALERT_HINTS):
        return {"intent": "cancel", "enabled": False, "email": email}
    enabled = bool(email) and any(hint in normalized for hint in ALERT_HINTS)
    return {"intent": "create" if enabled else "none", "enabled": enabled, "email": email}


def _iter_response_events(
    result: dict,
    message: str,
    session_id: str,
    progress_id: str | None = None,
) -> Iterator[dict]:
    intent = _build_intent(result)
    alert_request = result.get("alert_request") or {}
    alert_source = "llm" if alert_request else "regex_fallback"
    if not alert_request:
        alert_request = _fallback_alert_request_from_message(message)

    intent["alert_detection"] = {
        "source": alert_source,
        "intent": alert_request.get("intent"),
        "enabled": bool(alert_request.get("enabled")),
        "email": (alert_request.get("email") or "").strip() or None,
    }

    logger.info(
        "alert_detection source=%s intent=%s enabled=%s email_present=%s",
        alert_source,
        alert_request.get("intent"),
        bool(alert_request.get("enabled")),
        bool((alert_request.get("email") or "").strip()),
    )

    alert_email = (alert_request.get("email") or "").strip()
    alert_enabled = bool(alert_request.get("enabled"))
    alert_intent = str(alert_request.get("intent") or "").strip().lower()
    query_from_result = intent.get("flight_query") or {}
    clarification = intent.get("clarification") or {}

    def _create_alert_from_available_query() -> tuple[str | None, str | None]:
        if not alert_enabled or not alert_email:
            return None, None

        alert_query = query_from_result
        alert_preference = intent.get("flight_preference") or {}
        if not alert_query:
            latest_intent = get_latest_intent(session_id) or {}
            alert_query = latest_intent.get("flight_query") or {}
            alert_preference = latest_intent.get("flight_preference") or alert_preference

        if not alert_query:
            return None, None

        alert_record = create_alert(
            session_id=session_id,
            email=alert_email,
            flight_query=alert_query,
            flight_preference=alert_preference,
            metadata={"source": "chat"},
        )
        return alert_record.id, alert_record.status

    def _cancel_alerts_if_requested() -> tuple[str | None, str | None]:
        if alert_intent != "cancel":
            return None, None
        cancelled = cancel_active_alerts(session_id=session_id, email=alert_email or None)
        if cancelled:
            return f"Okay, I cancelled {cancelled} active alert(s).", "cancelled"
        return "There were no active alerts to cancel.", "cancelled"

    cancel_reply, cancel_status = _cancel_alerts_if_requested()
    if cancel_reply:
        yield {
            "type": "completed",
            "data": ChatResponse(
                reply=cancel_reply,
                flights=None,
                resultSetId=None,
                alertId=None,
                alertStatus=cancel_status,
                description_of_recommendation=None,
                intent=intent,
            ),
        }
        return

    if intent.get("error_message"):
        alert_id, alert_status = _create_alert_from_available_query()
        reply = intent["error_message"]
        if alert_id:
            reply = (
                "No matching flights right now. "
                f"I will notify {alert_email} when any matching flight appears."
            )
        yield {
            "type": "completed",
            "data": ChatResponse(
                reply=reply,
                flights=None,
                resultSetId=None,
                alertId=alert_id,
                alertStatus=alert_status,
                description_of_recommendation=None,
                intent=intent,
            ),
        }
        return

    if clarification and not clarification.get("can_search", True):
        yield {
            "type": "completed",
            "data": ChatResponse(
                reply=clarification.get("question") or "Could you share a bit more detail about the trip?",
                flights=None,
                resultSetId=None,
                alertId=None,
                alertStatus=None,
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

    query = query_from_result
    preference = intent.get("flight_preference") or {}
    if query:
        remember_latest_intent(session_id, query, preference)
    route_info = _build_route_info(query)
    use_demo = is_demo_trigger(message)
    graph_flights = result.get("flight_choices") or []
    result_set_id = str(uuid4())
    alert_id: str | None = None
    alert_status: str | None = None

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

            alert_id, alert_status = _create_alert_from_available_query()
            if alert_id:
                reply = (
                    "No matching flights right now. "
                    f"I will notify {alert_email} when any matching flight appears."
                )

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
            alertId=alert_id,
            alertStatus=alert_status,
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
    start = perf_counter()
    logger.info(
        "Chat pipeline started",
        extra={
            "session_id": session_id,
            "progress_id": progress_id,
            "message_length": len(message),
        },
    )
    result = run_flight_search(message, user_context, session_id, progress_id=progress_id)
    response: ChatResponse | None = None
    for event in _iter_response_events(result, message, session_id, progress_id):
        if on_event is not None:
            on_event(event)
        if event["type"] == "completed":
            response = event["data"]

    if response is None:
        raise RuntimeError("Chat pipeline completed without a response.")

    elapsed_ms = (perf_counter() - start) * 1000
    logger.info(
        "Chat pipeline completed",
        extra={
            "session_id": session_id,
            "progress_id": progress_id,
            "flights_count": len(response.flights or []),
            "result_set_id": response.resultSetId,
            "elapsed_ms": round(elapsed_ms, 1),
        },
    )
    return response


def _serialize_stream_event(event: dict) -> str:
    payload = dict(event)
    if payload.get("type") == "completed" and hasattr(payload.get("data"), "model_dump"):
        payload["data"] = payload["data"].model_dump()
    return f"data: {json.dumps(payload)}\n\n"


async def _stream_chat_request(
    http_request: Request,
    chat_request: ChatRequest,
    request_context: dict[str, str],
):
    user_context = chat_request.context.model_dump() if chat_request.context else {}
    progress_id = _new_progress_id(chat_request.session_id)
    set_request_context(
        request_id=request_context.get("request_id"),
        session_id=chat_request.session_id,
        progress_id=progress_id,
    )
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
                logger.info(
                    "Streaming chat request received",
                    extra={
                        "session_id": chat_request.session_id,
                        "progress_id": progress_id,
                        "message_length": len(chat_request.message),
                    },
                )
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
                logger.info(
                    "Streaming chat request cancelled",
                    extra={
                        "session_id": chat_request.session_id,
                        "progress_id": progress_id,
                    },
                )
                return
            except Exception as exc:
                logger.exception(
                    "Streaming chat request failed",
                    extra={
                        "session_id": chat_request.session_id,
                        "progress_id": progress_id,
                    },
                )
                emit_error(progress_id, str(exc))

        worker_context = copy_request_context()
        worker = Thread(target=lambda: worker_context.run(run_worker), daemon=True)
        worker.start()

        while worker.is_alive() or not progress_queue.empty():
            if await http_request.is_disconnected():
                logger.info(
                    "Streaming client disconnected",
                    extra={
                        "session_id": chat_request.session_id,
                        "progress_id": progress_id,
                    },
                )
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
        set_request_context(session_id=request.session_id)
        logger.info(
            "Chat request received",
            extra={
                "session_id": request.session_id,
                "message_length": len(request.message),
            },
        )
        return await run_in_threadpool(
            _run_chat_request_sync,
            request.message,
            user_context,
            request.session_id,
            None,
        )
    except Exception as e:
        logger.exception(
            "Chat request failed",
            extra={"session_id": request.session_id},
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/booking-url", response_model=BookingUrlResponse)
async def booking_url(request: BookingUrlRequest):
    set_request_context(session_id=request.session_id)
    start = perf_counter()
    logger.info(
        "Booking URL request received",
        extra={
            "session_id": request.session_id,
            "result_set_id": request.result_set_id,
            "flight_id": request.flight_id,
        },
    )
    try:
        booking_url_value = await run_in_threadpool(
            resolve_booking_url,
            request.session_id,
            request.result_set_id,
            request.flight_id,
        )
    except HTTPException as exc:
        logger.warning(
            "Booking URL request failed",
            extra={
                "session_id": request.session_id,
                "result_set_id": request.result_set_id,
                "flight_id": request.flight_id,
                "status_code": exc.status_code,
                "elapsed_ms": round((perf_counter() - start) * 1000, 1),
            },
        )
        raise

    logger.info(
        "Booking URL request completed",
        extra={
            "session_id": request.session_id,
            "result_set_id": request.result_set_id,
            "flight_id": request.flight_id,
            "elapsed_ms": round((perf_counter() - start) * 1000, 1),
        },
    )
    return BookingUrlResponse(bookingUrl=booking_url_value)


@router.post("/email/test", response_model=TestEmailResponse)
async def test_email(
    request: TestEmailRequest,
    to_email: str | None = Query(default=None),
):
    if not settings.ENABLE_EMAIL_TEST_ENDPOINT:
        raise HTTPException(status_code=404, detail="Email test endpoint is disabled.")

    recipient = (to_email or request.to_email or settings.SMTP_FROM_EMAIL or "").strip()
    if not recipient:
        raise HTTPException(status_code=400, detail="No recipient provided. Set query to_email, body to_email, or SMTP_FROM_EMAIL.")

    try:
        await run_in_threadpool(send_test_email, recipient)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to send test email: {exc}")

    return TestEmailResponse(status="sent", recipient=recipient)


@router.get("/alerts", response_model=list[AlertSummary])
async def alerts(session_id: str = Query(..., min_length=1)):
    records = await run_in_threadpool(list_alerts, session_id)
    return [_to_alert_summary(record) for record in records]


@router.get("/alerts/{alert_id}", response_model=AlertSummary)
async def alert_detail(alert_id: str):
    record = await run_in_threadpool(get_alert, alert_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    return _to_alert_summary(record)


@router.post("/chat/stream")
async def chat_stream(request: Request, payload: ChatRequest):
    """
    Stream real backend progress updates and the final chat response.
    """
    return StreamingResponse(
        _stream_chat_request(request, payload, get_request_context()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
