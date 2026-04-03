"""Flight search - placeholder for later phase."""

# Phrases that trigger demo mode (returns mock flights before real API integration)
DEMO_TRIGGERS = frozenset({"demo", "show demo", "test flights", "show sample", "sample flights"})


def _mock_flights(intent: dict) -> list[dict]:
    """Return mock flight data for demo/testing before API integration."""
    flight_query = intent.get("flight_query") or {}
    origin = flight_query.get("from_airport", "SIN")
    
    to_airports = flight_query.get("to_airports", [])
    destination = to_airports[0] if to_airports else "TYO"
    
    return [
        {
            "id": "demo-1",
            "price": 420.0,
            "bookingUrl": "https://www.singaporeair.com",
            "legs": [{
                "airlineCode": "SQ",
                "departure": f"{origin} 08:00",
                "arrival": f"{destination} 16:30",
                "duration": "7h 30m",
                "duration_minutes": 450,
                "stops": "Direct",
            }]
        },
        {
            "id": "demo-2",
            "price": 385.0,
            "legs": [{
                "airlineCode": "CX",
                "departure": f"{origin} 14:20",
                "arrival": f"{destination} 21:45",
                "duration": "6h 25m",
                "duration_minutes": 385,
                "stops": "1 stop (HKG)",
            }]
        },
        {
            "id": "demo-3",
            "price": 198.0,
            "legs": [{
                "airlineCode": "TR",
                "departure": f"{origin} 23:55",
                "arrival": f"{destination} 07:10+1",
                "duration": "6h 15m",
                "duration_minutes": 375,
                "stops": "Direct",
            }]
        },
        {
            "id": "demo-4",
            "price": 310.0,
            "legs": [{
                "airlineCode": "JL",
                "departure": f"{origin} 06:30",
                "arrival": f"{destination} 18:20",
                "duration": "9h 50m",
                "duration_minutes": 590,
                "stops": "1 stop (NRT)",
            }]
        },
        {
            "id": "demo-5",
            "price": 165.0,
            "legs": [{
                "airlineCode": "AK",
                "departure": f"{origin} 12:00",
                "arrival": f"{destination} 22:30",
                "duration": "11h 30m",
                "duration_minutes": 690,
                "stops": "2 stops (KUL, BKK)",
            }]
        },
        {
            "id": "demo-6",
            "price": 455.0,
            "legs": [{
                "airlineCode": "EK",
                "departure": f"{origin} 09:15",
                "arrival": f"{destination} 23:45",
                "duration": "14h 30m",
                "duration_minutes": 870,
                "stops": "1 stop (DXB)",
            }]
        },
        {
            "id": "demo-7",
            "price": 480.0,
            "legs": [{
                "airlineCode": "NH",
                "departure": f"{origin} 06:15",
                "arrival": f"{destination} 14:05",
                "duration": "6h 50m",
                "duration_minutes": 410,
                "stops": "Direct",
            }]
        },
        {
            "id": "demo-8",
            "price": 340.0,
            "legs": [{
                "airlineCode": "BR",
                "departure": f"{origin} 13:10",
                "arrival": f"{destination} 22:45",
                "duration": "8h 35m",
                "duration_minutes": 515,
                "stops": "1 stop (TPE)",
            }]
        },
        {
            "id": "demo-9",
            "price": 290.0,
            "legs": [{
                "airlineCode": "TG",
                "departure": f"{origin} 12:25",
                "arrival": f"{destination} 23:15",
                "duration": "9h 50m",
                "duration_minutes": 590,
                "stops": "1 stop (BKK)",
            }]
        },
        {
            "id": "demo-10",
            "price": 250.0,
            "legs": [{
                "airlineCode": "VN",
                "departure": f"{origin} 14:30",
                "arrival": f"{destination} 06:40+1",
                "duration": "15h 10m",
                "duration_minutes": 910,
                "stops": "1 stop (SGN)",
            }]
        },
        {
            "id": "demo-11",
            "price": 450.0,
            "legs": [{
                "airlineCode": "SQ",
                "departure": f"{origin} 23:55",
                "arrival": f"{destination} 08:00+1",
                "duration": "7h 05m",
                "duration_minutes": 425,
                "stops": "Direct",
            }]
        },
        {
            "id": "demo-12",
            "price": 210.0,
            "legs": [{
                "airlineCode": "MH",
                "departure": f"{origin} 09:00",
                "arrival": f"{destination} 20:30",
                "duration": "10h 30m",
                "duration_minutes": 630,
                "stops": "1 stop (KUL)",
            }]
        },
        {
            "id": "demo-13",
            "price": 650.0,
            "legs": [{
                "airlineCode": "QR",
                "departure": f"{origin} 02:30",
                "arrival": f"{destination} 22:30",
                "duration": "19h 00m",
                "duration_minutes": 1140,
                "stops": "1 stop (DOH)",
            }]
        },
        {
            "id": "demo-14",
            "price": 180.0,
            "legs": [{
                "airlineCode": "TR",
                "departure": f"{origin} 10:00",
                "arrival": f"{destination} 21:00",
                "duration": "10h 00m",
                "duration_minutes": 600,
                "stops": "1 stop (TPE)",
            }]
        },
        {
            "id": "demo-15",
            "price": 520.0,
            "legs": [{
                "airlineCode": "JL",
                "departure": f"{origin} 02:15",
                "arrival": f"{destination} 09:55",
                "duration": "6h 40m",
                "duration_minutes": 400,
                "stops": "Direct",
            }]
        },
        {
            "id": "demo-16",
            "price": 850.0,
            "bookingUrl": "https://www.singaporeair.com",
            "legs": [
                {
                    "airlineCode": "SQ",
                    "departure": f"{origin} 08:00",
                    "arrival": f"{destination} 16:30",
                    "duration": "7h 30m",
                    "duration_minutes": 450,
                    "stops": "Direct",
                },
                {
                    "airlineCode": "SQ",
                    "departure": f"{destination} 10:00",
                    "arrival": f"{origin} 15:45",
                    "duration": "6h 45m",
                    "duration_minutes": 405,
                    "stops": "Direct",
                }
            ]
        },
        {
            "id": "demo-17",
            "price": 720.0,
            "legs": [
                {
                    "airlineCode": "CX",
                    "departure": f"{origin} 14:20",
                    "arrival": f"{destination} 21:45",
                    "duration": "6h 25m",
                    "duration_minutes": 385,
                    "stops": "1 stop (HKG)",
                },
                {
                    "airlineCode": "CX",
                    "departure": f"{destination} 09:30",
                    "arrival": f"{origin} 18:20",
                    "duration": "9h 50m",
                    "duration_minutes": 590,
                    "stops": "1 stop (HKG)",
                }
            ]
        },
        {
            "id": "demo-18",
            "price": 1150.0,
            "tripType": "multi_city",
            "legs": [
                {
                    "airlineCode": "SQ",
                    "departure": f"{origin} 08:00",
                    "arrival": f"{destination} 16:30",
                    "duration": "7h 30m",
                    "duration_minutes": 450,
                    "stops": "Direct",
                },
                {
                    "airlineCode": "JL",
                    "departure": f"{destination} 10:00",
                    "arrival": "KIX 11:30",
                    "duration": "1h 30m",
                    "duration_minutes": 90,
                    "stops": "Direct",
                },
                {
                    "airlineCode": "SQ",
                    "departure": "KIX 23:25",
                    "arrival": f"{origin} 05:05+1",
                    "duration": "6h 40m",
                    "duration_minutes": 400,
                    "stops": "Direct",
                }
            ]
        }
    ]


def is_demo_trigger(message: str) -> bool:
    """Check if message contains a demo trigger phrase."""
    msg_lower = message.strip().lower()
    return any(trigger in msg_lower for trigger in DEMO_TRIGGERS)


def get_flights(intent: dict, use_demo: bool = False) -> list[dict]:
    """
    Return flight results. Placeholder - real API integration will be added later.
    When use_demo=True, returns mock data for demo/testing.
    """
    if use_demo:
        return _mock_flights(intent)
    return []
