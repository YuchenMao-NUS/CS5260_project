import type { FlightOption } from '../types'

function airportCodeFromTimestamp(value: string) {
  const [airportCode] = value.split(' ')
  return airportCode || 'Unknown'
}

export function getFlightRouteLabel(flight: FlightOption) {
  const firstLeg = flight.legs[0]
  const lastLeg = flight.legs[flight.legs.length - 1]

  if (!firstLeg || !lastLeg) {
    return flight.id
  }

  return `${airportCodeFromTimestamp(firstLeg.departure)} -> ${airportCodeFromTimestamp(lastLeg.arrival)}`
}
