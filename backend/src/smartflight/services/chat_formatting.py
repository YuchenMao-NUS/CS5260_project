"""Formatting helpers for chat flight responses."""


def _format_datetime(value) -> str:
    date_value = getattr(value, "date", None) or ()
    time_value = getattr(value, "time", None) or ()

    if len(date_value) != 3 or len(time_value) != 2:
        return "Unknown time"

    year, month, day = date_value
    hour, minute = time_value

    if None in (year, month, day, hour, minute):
        return "Unknown time"

    return f"{int(year):04d}-{int(month):02d}-{int(day):02d} {int(hour):02d}:{int(minute):02d}"


def _format_duration(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes:02d}m"


def format_graph_flight(choice: dict, index: int) -> dict:
    """Convert a graph flight choice into the API response shape."""
    outbound_flights = choice.get("flights") or []
    if not outbound_flights:
        raise ValueError("Flight choice is missing outbound flight segments.")

    first_leg = outbound_flights[0]
    last_leg = outbound_flights[-1]
    stops_count = max(len(outbound_flights) - 1, 0)
    stops = "Direct" if stops_count == 0 else f"{stops_count} stop" + ("s" if stops_count > 1 else "")
    departure_airport = getattr(getattr(first_leg, "from_airport", None), "code", None) or "UNK"
    arrival_airport = getattr(getattr(last_leg, "to_airport", None), "code", None) or "UNK"
    total_duration = int(choice.get("duration") or 0)

    return {
        "id": f"result-{index}",
        "airlineCode": (choice.get("airlines") or ["NA"])[0],
        "departure": f"{departure_airport} {_format_datetime(first_leg.departure)}",
        "arrival": f"{arrival_airport} {_format_datetime(last_leg.arrival)}",
        "duration": _format_duration(total_duration),
        "duration_minutes": total_duration,
        "price": float(choice.get("price") or 0.0),
        "stops": stops,
    }


def format_demo_flight(flight: dict) -> dict:
    """Normalize a demo flight into the API response shape."""
    return {
        "id": flight["id"],
        "airlineCode": flight["airlineCode"],
        "departure": flight["departure"],
        "arrival": flight["arrival"],
        "duration": flight["duration"],
        "duration_minutes": flight["duration_minutes"],
        "price": flight["price"],
        "stops": flight["stops"],
    }
