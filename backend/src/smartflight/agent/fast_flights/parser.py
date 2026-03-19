import json

from selectolax.lexbor import LexborHTMLParser

from .model import (
    Airline,
    Airport,
    Alliance,
    CarbonEmission,
    Flights,
    JsMetadata,
    SimpleDatetime,
    SingleFlight,
)

import logging
logger = logging.getLogger(__name__)

class MetaList(list[Flights]):
    """Searched flights list, with metadata attached."""

    metadata: JsMetadata


def _safe_get(obj, *idxs, default=None):
    """
    Safely traverse nested list/dict structures.
    Returns default if any step fails.
    """
    cur = obj
    for idx in idxs:
        try:
            cur = cur[idx]
        except (IndexError, KeyError, TypeError):
            return default
    return cur


def _as_list(x):
    return x if isinstance(x, list) else []


def _get_rows(payload: list, *, use_payload3: bool) -> list:
    if use_payload3:
        rows = _safe_get(payload, 3, 0, default=[])
        return rows if isinstance(rows, list) else []

    rows = _safe_get(payload, 2, 0, default=[])
    return rows if isinstance(rows, list) else []


def parse(html: str, *, use_payload3: bool = False) -> MetaList:
    parser = LexborHTMLParser(html)

    script = parser.css_first(r"script.ds\:1")
    if script is None:
        flights = MetaList()
        flights.metadata = JsMetadata(alliances=[], airlines=[])
        return flights

    text = script.text()
    if not text:
        flights = MetaList()
        flights.metadata = JsMetadata(alliances=[], airlines=[])
        return flights

    return parse_js(text, use_payload3=use_payload3)


# Data discovery by @kftang, huge shout out!
def parse_js(js: str, *, use_payload3: bool = False):
    flights = MetaList()
    flights.metadata = JsMetadata(alliances=[], airlines=[])

    if "data:" not in js:
        return flights

    try:
        data = js.split("data:", 1)[1].rsplit(",", 1)[0]
        payload = json.loads(data)
    except Exception:
        return flights

    alliances = []
    airlines = []

    alliances_data = _safe_get(payload, 7, 1, 0, default=[])
    airlines_data = _safe_get(payload, 7, 1, 1, default=[])

    for item in _as_list(alliances_data):
        if not isinstance(item, list) or len(item) < 2:
            continue
        code, name = item[0], item[1]
        if code and name:
            alliances.append(Alliance(code=code, name=name))

    for item in _as_list(airlines_data):
        if not isinstance(item, list) or len(item) < 2:
            continue
        code, name = item[0], item[1]
        if code and name:
            airlines.append(Airline(code=code, name=name))

    meta = JsMetadata(alliances=alliances, airlines=airlines)
    flights.metadata = meta

    rows = _get_rows(payload, use_payload3=use_payload3)
    if not rows:
        return flights

    for idx, k in enumerate(rows, start=1):
        try:
            flight = _safe_get(k, 0)
            if not isinstance(flight, list):
                continue

            # safer price extraction
            price = _safe_get(k, 1, 0, 1)
            if price is None:
                # Without price, skip this result
                continue

            tfu_token = _safe_get(k, 1, 1)

            typ = _safe_get(flight, 0)
            airlines = _safe_get(flight, 1, default=[])
            airlines = airlines if isinstance(airlines, list) else []

            raw_single_flights = _safe_get(flight, 2, default=[])
            if not isinstance(raw_single_flights, list) or not raw_single_flights:
                continue

            sg_flights = []

            for single_flight in raw_single_flights:
                try:
                    if not isinstance(single_flight, list):
                        continue

                    from_code = _safe_get(single_flight, 3)
                    from_name = _safe_get(single_flight, 4)
                    to_name = _safe_get(single_flight, 5)
                    to_code = _safe_get(single_flight, 6)

                    departure_time = _safe_get(single_flight, 8)
                    departure_date = _safe_get(single_flight, 20)
                    arrival_time = _safe_get(single_flight, 10)
                    arrival_date = _safe_get(single_flight, 21)

                    duration = _safe_get(single_flight, 11)
                    plane_type = _safe_get(single_flight, 17, default="")

                    # Key fields missing -> skip this leg
                    if not (from_code and from_name and to_code and to_name):
                        continue
                    if departure_date is None or departure_time is None:
                        continue
                    if arrival_date is None or arrival_time is None:
                        continue
                    if duration is None:
                        continue

                    from_airport = Airport(code=from_code, name=from_name)
                    to_airport = Airport(code=to_code, name=to_name)
                    departure = SimpleDatetime(date=departure_date, time=departure_time)
                    arrival = SimpleDatetime(date=arrival_date, time=arrival_time)

                    raw_flight_number = _safe_get(single_flight, 22)
                    flight_number = None
                    flight_number_airline_code = None
                    flight_number_numeric = None
                    flight_number_airline_name = None

                    if (
                        isinstance(raw_flight_number, list)
                        and len(raw_flight_number) >= 2
                        and raw_flight_number[0]
                        and raw_flight_number[1]
                    ):
                        flight_number_airline_code = raw_flight_number[0]
                        flight_number_numeric = raw_flight_number[1]
                        flight_number = f"{flight_number_airline_code}{flight_number_numeric}"

                        if len(raw_flight_number) >= 4 and raw_flight_number[3]:
                            flight_number_airline_name = raw_flight_number[3]

                    sg_flights.append(
                        SingleFlight(
                            from_airport=from_airport,
                            to_airport=to_airport,
                            departure=departure,
                            arrival=arrival,
                            duration=duration,
                            plane_type=plane_type,
                            flight_number=flight_number,
                            flight_number_airline_code=flight_number_airline_code,
                            flight_number_numeric=flight_number_numeric,
                            flight_number_airline_name=flight_number_airline_name,
                        )
                    )

                except Exception:
                    # bad leg should not kill the whole result
                    continue

            # if no valid legs left, skip this result
            if not sg_flights:
                continue
            
            extras = _safe_get(flight, 22, default=[])
            carbon_emission = _safe_get(extras, 7, default=0)
            typical_carbon_emission = _safe_get(extras, 8, default=0)

            flights.append(
                Flights(
                    type=typ,
                    price=price,
                    airlines=airlines,
                    flights=sg_flights,
                    carbon=CarbonEmission(
                        typical_on_route=typical_carbon_emission,
                        emission=carbon_emission,
                    ),
                    tfu_token=tfu_token,
                )
            )

        except Exception:
            # bad row should not kill the whole page
            continue

    return flights