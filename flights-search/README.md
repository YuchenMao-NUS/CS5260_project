# flights-search

Typed Python package for two focused Google Flights workflows:

1. search flights from a structured request
2. resolve booking URL candidates for an explicit selected itinerary

The active implementation lives at the repository root. The `legacy/` directory
is reference material only and is not the supported package surface.

## Status

The intended feature surface is implemented for the current project scope.
The repo is now in closeout and maintenance mode:

- the initial search flow is implemented
- the round-trip follow-up flow is implemented
- explicit itinerary booking URL resolution is implemented
- unit coverage is committed for the implemented runtime slices
- representative live validation has been completed

The main remaining work is limited to broader live validation across more route
shapes and deciding whether to commit any sanitized live fixtures for
regression protection.

## Planned Package Shape

```text
src/flights_search/
tests/
pyproject.toml
```

## Development

`pixi` is the intended source of truth for environments and common tasks.

Available tasks:

- `pixi run test`
- `pixi run test-unit`
- `pixi run lint`
- `pixi run typecheck`
- `pixi run format`
- `pixi run docs-check`

The root package now includes the typed model layer, internal request
encoding, the initial and follow-up search runtime paths, and a
Playwright-backed booking-resolution flow for explicit selected itineraries.

For current implementation status and closeout notes, see:

- `.docs/implementation-progress.md`
- `.docs/implementation-plan.md`

Booking resolution needs the Playwright Chromium browser binary in addition to
the Python dependency. After installing dependencies, run
`python -m playwright install chromium` before calling `get_booking_urls(...)`
or `get_booking_url(...)`.

## MCP Server

The repository now includes an MCP server adapter under `src/flights_search_mcp/`.
It is intended to stay thin and delegate business logic to `flights_search`.

Current exposed tools:

- `server_info`
- `search_flights`
- `search_return_flights`
- `resolve_booking_urls`

Canonical local launch commands:

- `python -m flights_search_mcp.server`
- `flights-search-mcp`

Local setup flow:

1. install project dependencies
2. launch the MCP server over `stdio` with one of the commands above
3. install Chromium with `python -m playwright install chromium` only if you
   later need the booking-resolution tool through MCP

Tool-contract notes:

- tool failures use the MCP error path, not a success envelope with `ok: false`
- `search_return_flights` requires the exact opaque
  `outbound_selection_handle` returned by `search_flights`
- selection payload dates are derived from the corresponding request leg date
  in MCP v1
- `resolve_booking_urls` requires an explicit `itinerary` payload whose leg
  count and boundary airports match the original search request

Example `search_flights` request:

```json
{
  "trip_type": "one-way",
  "legs": [
    {
      "date": "2026-05-20",
      "origin_airport": "SFO",
      "destination_airport": "LAX"
    }
  ],
  "passengers": {
    "adults": 1,
    "children": 0,
    "infants_in_seat": 0,
    "infants_on_lap": 0
  },
  "seat": "economy",
  "language": "en-US",
  "currency": "USD"
}
```

Example `search_flights` success payload:

```json
{
  "selection_phase": "initial",
  "options": [
    {
      "kind": "best",
      "price": 120,
      "airlines": ["United"],
      "segment_count": 1,
      "stop_count": 0,
      "segments": [
        {
          "origin_airport": "SFO",
          "origin_airport_name": "San Francisco",
          "destination_airport": "LAX",
          "destination_airport_name": "Los Angeles",
          "date": "2026-05-20",
          "departure_time": "08:00",
          "arrival_time": "09:30",
          "duration_minutes": 90,
          "marketing_airline_code": "UA",
          "flight_number": "100",
          "aircraft_type": "Airbus A320"
        }
      ],
      "selected_leg": {
        "segments": [
          {
            "origin_airport": "SFO",
            "date": "2026-05-20",
            "destination_airport": "LAX",
            "marketing_airline_code": "UA",
            "flight_number": "100"
          }
        ]
      },
      "selected_itinerary": null,
      "outbound_selection_handle": null,
      "selection_unavailable_reason": null
    }
  ]
}
```

Example `search_return_flights` request:

```json
{
  "trip_type": "round-trip",
  "outbound_selection_handle": "<opaque handle returned by search_flights>",
  "legs": [
    {
      "date": "2026-05-20",
      "origin_airport": "SFO",
      "destination_airport": "LAX"
    },
    {
      "date": "2026-05-27",
      "origin_airport": "LAX",
      "destination_airport": "SFO"
    }
  ],
  "seat": "economy",
  "language": "en-US",
  "currency": "USD"
}
```

Example `search_return_flights` success payload:

```json
{
  "selection_phase": "follow-up",
  "options": [
    {
      "kind": "best",
      "price": 140,
      "airlines": ["United"],
      "segment_count": 1,
      "stop_count": 0,
      "segments": [
        {
          "origin_airport": "LAX",
          "origin_airport_name": "Los Angeles",
          "destination_airport": "SFO",
          "destination_airport_name": "San Francisco",
          "date": "2026-05-27",
          "departure_time": "16:00",
          "arrival_time": "17:30",
          "duration_minutes": 90,
          "marketing_airline_code": "UA",
          "flight_number": "200",
          "aircraft_type": "Airbus A320"
        }
      ],
      "selected_leg": {
        "segments": [
          {
            "origin_airport": "LAX",
            "date": "2026-05-27",
            "destination_airport": "SFO",
            "marketing_airline_code": "UA",
            "flight_number": "200"
          }
        ]
      },
      "selected_itinerary": {
        "legs": [
          {
            "segments": [
              {
                "origin_airport": "SFO",
                "date": "2026-05-20",
                "destination_airport": "LAX",
                "marketing_airline_code": "UA",
                "flight_number": "100"
              }
            ]
          },
          {
            "segments": [
              {
                "origin_airport": "LAX",
                "date": "2026-05-27",
                "destination_airport": "SFO",
                "marketing_airline_code": "UA",
                "flight_number": "200"
              }
            ]
          }
        ]
      },
      "outbound_selection_handle": null,
      "selection_unavailable_reason": null
    }
  ]
}
```

Example `resolve_booking_urls` request:

```json
{
  "trip_type": "one-way",
  "legs": [
    {
      "date": "2026-05-20",
      "origin_airport": "SFO",
      "destination_airport": "LAX"
    }
  ],
  "itinerary": {
    "legs": [
      {
        "segments": [
          {
            "origin_airport": "SFO",
            "date": "2026-05-20",
            "destination_airport": "LAX",
            "marketing_airline_code": "UA",
            "flight_number": "100"
          }
        ]
      }
    ]
  },
  "seat": "economy",
  "language": "en-US",
  "currency": "USD"
}
```

Example `resolve_booking_urls` success payload:

```json
{
  "booking_urls": [
    "https://www.google.com/travel/clk/f?u=TOKEN-1",
    "https://www.google.com/travel/clk/f?u=TOKEN-2"
  ]
}
```

Example tool-failure payload shape:

```json
{
  "code": "validation_error",
  "message": "Selected itinerary destination must match the original search leg.",
  "retryable": false,
  "details": {},
  "remediation": "Fix the request payload and retry."
}
```

Example booking-runtime failure payload:

```json
{
  "code": "browser_runtime_missing",
  "message": "Booking resolution requires the Playwright Chromium browser binary. Run `python -m playwright install chromium` and retry. Original error: ...",
  "retryable": false,
  "details": {
    "exception_type": "RuntimeError"
  },
  "remediation": "Run `python -m playwright install chromium` and retry."
}
```

Phase 2 closeout validation:

- `python ..\scripts\live_test.py mcp-phase2-closeout --outbound-date 2026-05-20 --return-date 2026-05-27 --origin SFO --destination LAX`

Phase 3 closeout validation:

- `python ..\scripts\live_test.py mcp-phase3-closeout --outbound-date 2026-05-20 --return-date 2026-05-27 --origin SFO --destination LAX`

Phase 4 closeout validation:

- `python ..\scripts\live_test.py mcp-phase4-closeout --date 2026-05-20 --origin SFO --destination LAX`

Recorded sample on 2026-04-22:

- live one-way derivation probe returned 4 options, all 4 selectable, with no
  `selection_unavailable_reason`
- live round-trip initial probe returned 3 options, all 3 selectable, and all 3
  emitted `outbound_selection_handle`
- real `stdio` MCP client validation listed `server_info` and `search_flights`,
  then executed `search_flights` successfully with `selection_phase="initial"`
  and 4 returned options
- real `stdio` MCP client follow-up validation listed `server_info`,
  `search_flights`, and `search_return_flights`, then executed a round-trip
  initial-plus-follow-up flow successfully with 3 initial options, a returned
  `outbound_selection_handle`, `selection_phase="follow-up"`, 3 follow-up
  options, return segment date `2026-05-27`, and a populated
  `selected_itinerary`
- real `stdio` MCP client booking validation listed `server_info`,
  `search_flights`, `search_return_flights`, and `resolve_booking_urls`, then
  executed a one-way initial search plus booking-resolution flow successfully
  for `SFO -> LAX` on `2026-05-20` with 4 initial options, a populated
  `selected_leg`, and 2 returned booking URLs
