from math import inf
from smartflight.agent.state import *

def _get_total_price(choice: FlightInformation) -> float:
    if choice["trip"] == "one_way":
        return float(choice["price"])
    return float(choice["price"]) + float(choice["price_2"] or 0.0)


def _get_total_duration(choice: FlightInformation) -> int:
    if choice["trip"] == "one_way":
        return int(choice["duration"])
    return int(choice["duration"]) + int(choice["duration_2"] or 0)


def _is_direct_effective(choice: FlightInformation) -> bool:
    """
    For one-way: direct means outbound is direct.
    For round-trip: direct means both outbound and inbound are direct.
    """
    if choice["trip"] == "one_way":
        return bool(choice["is_direct"])
    return bool(choice["is_direct"]) and bool(choice["is_direct_2"])


def _all_airlines(choice: FlightInformation) -> list[str]:
    airlines = list(choice.get("airlines") or [])
    airlines_2 = list(choice.get("airlines_2") or [])
    return airlines + airlines_2


def _matches_preferences(
    choice: FlightInformation,
    pref: FlightPreference,
) -> bool:
    """
    Hard filtering only.
    """
    total_price = _get_total_price(choice)
    total_duration = _get_total_duration(choice)

    direct_only = pref.get("direct_only")
    max_price = pref.get("max_price")
    min_price = pref.get("min_price")
    max_duration = pref.get("max_duration")
    min_duration = pref.get("min_duration")
    preferred_airlines = pref.get("preferred_airlines")

    # 1) direct_only is a hard constraint only when True
    if direct_only is True and not _is_direct_effective(choice):
        return False

    # 2) price hard constraints
    if max_price is not None and total_price > max_price:
        return False
    if min_price is not None and total_price < min_price:
        return False

    # 3) duration hard constraints
    if max_duration is not None and total_duration > max_duration:
        return False
    if min_duration is not None and total_duration < min_duration:
        return False

    # 4) preferred_airlines:
    # treat as a soft preference, not a hard constraint
    # so do NOT filter here

    return True


def _compute_rank_score(
    choice: FlightInformation,
    pref: FlightPreference,
    price_min: float,
    price_max: float,
    duration_min: int,
    duration_max: int,
) -> float:
    """
    Lower score = better.

    Ranking strategy:
    - cheaper is better
    - shorter is better
    - direct is better
    - airline preference match is better

    Normalization:
    - price_norm in [0,1]
    - duration_norm in [0,1]
    """

    total_price = _get_total_price(choice)
    total_duration = _get_total_duration(choice)
    is_direct = _is_direct_effective(choice)

    preferred_airlines = pref.get("preferred_airlines") or []
    airline_match = 0
    if preferred_airlines:
        choice_airlines = set(_all_airlines(choice))
        if any(a in choice_airlines for a in preferred_airlines):
            airline_match = 1

    # normalize price
    if price_max == price_min:
        price_norm = 0.0
    else:
        price_norm = (total_price - price_min) / (price_max - price_min)

    # normalize duration
    if duration_max == duration_min:
        duration_norm = 0.0
    else:
        duration_norm = (total_duration - duration_min) / (duration_max - duration_min)

    # penalties / bonuses
    direct_penalty = 0.0 if is_direct else 0.15
    airline_penalty = 0.0 if airline_match else (0.08 if preferred_airlines else 0.0)

    # weighted score
    # price is slightly more important than duration
    score = (
        0.55 * price_norm
        + 0.30 * duration_norm
        + direct_penalty
        + airline_penalty
    )

    return score


def filter_flights_node(state: AgentState) -> AgentState:
    """
    Filter and sort flight_choices using flight_preference.

    Behavior:
    - If no flight_choices, return as-is
    - If no flight_preference, still sort by a default ranking:
        cheaper first, then shorter, then direct
    - Hard constraints:
        direct_only=True, price range, duration range
    - Soft preferences:
        preferred_airlines
    """
    flight_choices = state.get("flight_choices")
    flight_preference = state.get("flight_preference") or {}

    if not flight_choices:
        return {
            **state,
            "error_message": None,
        }

    try:
        # Step 1: hard filtering
        filtered_choices = [
            choice
            for choice in flight_choices
            if _matches_preferences(choice, flight_preference)
        ]

        # If everything got filtered out, return empty list instead of failing
        if not filtered_choices:
            return {
                **state,
                "flight_choices": [],
                "error_message": None,
            }

        # Step 2: compute normalization range from filtered results
        prices = [_get_total_price(c) for c in filtered_choices]
        durations = [_get_total_duration(c) for c in filtered_choices]

        price_min = min(prices) if prices else 0.0
        price_max = max(prices) if prices else 0.0
        duration_min = min(durations) if durations else 0
        duration_max = max(durations) if durations else 0

        # Step 3: sort by score, then stable tie-breakers
        def sort_key(choice: FlightInformation):
            score = _compute_rank_score(
                choice=choice,
                pref=flight_preference,
                price_min=price_min,
                price_max=price_max,
                duration_min=duration_min,
                duration_max=duration_max,
            )

            total_price = _get_total_price(choice)
            total_duration = _get_total_duration(choice)
            is_direct = _is_direct_effective(choice)

            # lower is better for all tuple items
            return (
                score,
                total_price,
                total_duration,
                0 if is_direct else 1,
            )

        sorted_choices = sorted(filtered_choices, key=sort_key)

        return {
            **state,
            "flight_choices": sorted_choices,
            "error_message": None,
        }

    except Exception as e:
        return {
            **state,
            "error_message": f"Flight filtering failed: {e}",
        }