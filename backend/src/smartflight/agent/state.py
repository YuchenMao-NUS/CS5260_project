from typing import Any, TypedDict, Optional, List, Literal

class FlightQuery(TypedDict):
    trip: Literal["one_way", "round_trip"]
    from_airport: str                    # IATA 3-letter code
    to_airports: List[str]               # List of IATA codes (could be 5 recommended)
    departure_date: str                  # YYYY-MM-DD
    return_date: Optional[str]           # YYYY-MM-DD, only valid for round_trip
    seat_classes: Literal["business", "economy", "first", "premium-economy"]
    passengers: int
    is_multi_destination: bool           # Determine whether it is a single destination or multiple destinations.
    description_of_recommendation: Optional[str]


class FlightPreference(TypedDict):
    direct_only: Optional[bool]               # True=direct only, False=doesn't matter, None=not mentioned
    max_stops: Optional[int]                  # Maximum allowed stops across a leg
    min_stops: Optional[int]                  # Minimum required stops across a leg
    preferred_airlines: Optional[List[str]]   # List of IATA airline codes, e.g. ["CA", "MU"]
    max_price: Optional[float]                # Max price (SGD)
    min_price: Optional[float]                # Min price (SDG)
    max_duration: Optional[int]               # Max flight duration (minutes)
    min_duration: Optional[int]               # Min flight duration (minutes)


class FlightInformation(TypedDict):
    trip: Literal["one_way", "round_trip"]
    from_airport: str
    to_airport: str
    departure_date: str
    return_date: Optional[str]
    booking_url: Optional[str]
    outbound_selection_handle: Optional[str]
    selected_leg: Optional[dict[str, Any]]
    selected_itinerary: Optional[dict[str, Any]]
    # outbound ticket
    is_direct: bool
    airlines: List[str]
    price: float
    duration: int
    flights: list[dict[str, Any]]
    # inbound ticket
    is_direct_2: Optional[bool]
    airlines_2: Optional[List[str]]
    price_2: Optional[float]
    duration_2: Optional[int]
    flights_2: Optional[list[dict[str, Any]]]
    
    
class AgentState(TypedDict):
    session_id: str                                # Session identifier for conversation memory
    progress_id: Optional[str]                     # Request-scoped progress channel identifier
    user_input: str                                # Original user input
    user_context: dict                             # Context passed from frontend (e.g. timezone, location)
    flight_query: Optional[FlightQuery]            # Extracted search parameters
    flight_preference: Optional[FlightPreference]  # Extracted user preferences
    alert_request: Optional[dict]                  # Email alert request metadata from conversation
    flight_choices: Optional[List[FlightInformation]]
    error_message: Optional[str]                   # Node error message (e.g. missing origin)
    history: Optional[List[dict]]                  # history of turns
