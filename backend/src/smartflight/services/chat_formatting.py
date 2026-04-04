"""Formatting helpers for chat flight responses."""


def _format_datetime(value) -> str:
    if isinstance(value, dict):
        date_value = value.get("date", ())
        time_value = value.get("time", ())
    else:
        date_value = getattr(value, "date", None) or ()
        time_value = getattr(value, "time", None) or ()

    if len(date_value) != 3 or len(time_value) == 0:
        return "Unknown time"

    year, month, day = date_value
    hour = time_value[0]
    minute = time_value[1] if len(time_value) > 1 else 0

    if None in (year, month, day, hour, minute):
        return "Unknown time"

    return f"{int(year):04d}-{int(month):02d}-{int(day):02d} {int(hour):02d}:{int(minute):02d}"


def _format_duration(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _process_flight_segments(segments: list, airlines_list: list, duration: int) -> dict:
    """Process a list of flight segments into a single FlightLeg dictionary."""
    if not segments:
        return None

    first_leg = segments[0]
    last_leg = segments[-1]
    stops_count = max(len(segments) - 1, 0)
    stops = "Direct" if stops_count == 0 else f"{stops_count} stop" + ("s" if stops_count > 1 else "")
    departure_airport = getattr(getattr(first_leg, "from_airport", None), "code", None)
    if not departure_airport and isinstance(first_leg, dict):
        departure_airport = first_leg.get("from_airport", {}).get("code") if isinstance(first_leg.get("from_airport"), dict) else None
    departure_airport = departure_airport or "UNK"

    arrival_airport = getattr(getattr(last_leg, "to_airport", None), "code", None)
    if not arrival_airport and isinstance(last_leg, dict):
        arrival_airport = last_leg.get("to_airport", {}).get("code") if isinstance(last_leg.get("to_airport"), dict) else None
    arrival_airport = arrival_airport or "UNK"

    total_duration = int(duration or 0)
    
    # Extract the true 2-letter airline code from the flight leg
    airline_code = getattr(first_leg, "flight_number_airline_code", None)
    if not airline_code and isinstance(first_leg, dict):
        airline_code = first_leg.get("flight_number_airline_code")
    
    # Fallback to the airlines list if code is missing
    if not airline_code:
        airline_code = (airlines_list or ["NA"])[0]

    return {
        "airlineCode": airline_code,
        "departure": f"{departure_airport} {_format_datetime(first_leg.departure)}",
        "arrival": f"{arrival_airport} {_format_datetime(last_leg.arrival)}",
        "duration": _format_duration(total_duration),
        "duration_minutes": total_duration,
        "stops": stops,
    }


def format_graph_flight(choice: dict, index: int) -> dict:
    """Convert a graph flight choice into the API response shape."""
    legs = []
    
    # Process outbound
    outbound_flights = choice.get("flights") or []
    if not outbound_flights:
        raise ValueError("Flight choice is missing outbound flight segments.")
    outbound_leg = _process_flight_segments(
        outbound_flights, 
        choice.get("airlines"), 
        choice.get("duration")
    )
    if outbound_leg:
        legs.append(outbound_leg)

    # Process inbound (if it's a round trip)
    inbound_flights = choice.get("flights_2") or []
    if inbound_flights:
        inbound_leg = _process_flight_segments(
            inbound_flights, 
            choice.get("airlines_2"), 
            choice.get("duration_2")
        )
        if inbound_leg:
            legs.append(inbound_leg)

    trip_type = choice.get("trip", "one_way")
    if len(legs) == 2 and trip_type == "one_way":
        trip_type = "round_trip"
    elif len(legs) > 2:
        trip_type = "multi_city"

    return {
        "id": f"result-{index}",
        "price": float(choice.get("price") or 0.0),
        "tripType": trip_type,
        "legs": legs,
        "bookingUrl": choice.get("booking_token")  # or bookingUrl depending on what API returns
    }

def format_demo_flight(flight: dict) -> dict:
    """Normalize a demo flight into the API response shape."""
    legs = flight.get("legs", [])
    trip_type = flight.get("tripType")
    if not trip_type:
        trip_type = "round_trip" if len(legs) == 2 else ("multi_city" if len(legs) > 2 else "one_way")
        
    return {
        "id": flight["id"],
        "price": flight["price"],
        "tripType": trip_type,
        "legs": legs,
        "bookingUrl": flight.get("bookingUrl")
    }
