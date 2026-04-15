import { getFlightRouteLabel } from '../utils/flightRoute'
import { useEffect, useState } from 'react'
import type { FlightOption, FlightLeg } from '../types'
import { getAirlineInfo } from '../utils/airlines'

interface FlightCardProps {
  flight: FlightOption
  isBooking?: boolean
  onBook?: (flight: FlightOption) => void
}

function getBookingHost(url?: string) {
  if (!url) return null

  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return null
  }
}

function getStopDetails(leg: FlightLeg) {
  if (leg.stopCount === 0) {
    return null
  }

  if (leg.stopAirports.length > 0) {
    return `Via ${leg.stopAirports.join(', ')}`
  }

  return 'Connection details unavailable'
}

function splitAirportAndTime(value: string) {
  const [airport = 'UNK', ...rest] = value.trim().split(/\s+/)
  return {
    airport,
    time: rest.join(' ') || '--:--',
  }
}

function FlightLegView({ leg, label }: { leg: FlightLeg, label?: string }) {
  const airlineMeta = getAirlineInfo(leg.airlineCode)
  const slug = airlineMeta?.slug
  const airlineName = airlineMeta?.name || leg.airlineCode
  const stopDetails = getStopDetails(leg)
  const departureInfo = splitAirportAndTime(leg.departure)
  const arrivalInfo = splitAirportAndTime(leg.arrival)

  const iconUrl = slug ? `/airlines/${slug}/icon.svg` : null
  const logoUrl = slug ? `/airlines/${slug}/logo.svg` : null

  const [imgState, setImgState] = useState<'icon' | 'logo' | 'error'>(
    iconUrl ? 'icon' : logoUrl ? 'logo' : 'error',
  )

  useEffect(() => {
    setImgState(iconUrl ? 'icon' : logoUrl ? 'logo' : 'error')
  }, [iconUrl, logoUrl])

  const currentSrc = imgState === 'icon' ? iconUrl : imgState === 'logo' ? logoUrl : null

  const handleError = () => {
    if (imgState === 'icon' && logoUrl) {
      setImgState('logo')
    } else {
      setImgState('error')
    }
  }

  return (
    <div className="flight-leg">
      {label && <div className="leg-direction-label">{label}</div>}
      <div className="flight-leg-row">
        <div className="flight-header">
          <div className="airline-info">
            <div className="airline-logo-container">
              {currentSrc && imgState !== 'error' ? (
                <img
                  src={currentSrc}
                  alt={`${airlineName} logo`}
                  className="airline-logo"
                  onError={handleError}
                />
              ) : null}
              <div
                className="airline-logo-placeholder"
                style={{ display: imgState === 'error' ? 'flex' : 'none' }}
              >
                {airlineName.charAt(0).toUpperCase()}
              </div>
            </div>
            <div className="airline-copy">
              <span className="airline">{airlineName}</span>
              <span className={`flight-stops flight-stops-inline ${leg.stopCount === 0 ? 'direct' : ''}`}>
                {leg.stops}
              </span>
            </div>
          </div>
        </div>
        <div className="flight-details">
          <div className="flight-endpoint flight-endpoint-departure">
            <span className="flight-airport-code">{departureInfo.airport}</span>
            <span className="flight-time">{departureInfo.time}</span>
          </div>
          <div className="duration-container">
            <span className="duration">{leg.duration}</span>
            <span className="duration-line" aria-hidden="true"></span>
            {stopDetails ? <span className="flight-stop-airports">{stopDetails}</span> : null}
          </div>
          <div className="flight-endpoint flight-endpoint-arrival">
            <span className="flight-airport-code">{arrivalInfo.airport}</span>
            <span className="flight-time">{arrivalInfo.time}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

export function FlightCard({ flight, isBooking = false, onBook }: FlightCardProps) {
  const bookingHost = getBookingHost(flight.bookingUrl)

  return (
    <div className="flight-card">
      <div className="flight-card-body">
        <div className="flight-legs">
          {flight.legs.map((leg, index) => {
            let label = undefined
            if (flight.tripType === 'round_trip' && flight.legs.length === 2) {
              label = index === 0 ? 'Outbound' : 'Return'
            } else if (flight.tripType === 'multi_city' || flight.legs.length > 1) {
              label = `Leg ${index + 1}`
            }
            return (
              <div key={index} className="flight-leg-container">
                {index > 0 && <div className="leg-divider"></div>}
                <FlightLegView leg={leg} label={label} />
              </div>
            )
          })}
        </div>
        <div className="flight-price-action">
          <span className="price">SGD {flight.price}</span>
          {flight.bookingUrl ? (
            <button
              className="book-btn"
              type="button"
              onClick={() => onBook?.(flight)}
              title={bookingHost ? `Book on ${bookingHost}` : 'Book on external website'}
            >
              <span>{isBooking ? 'Fetching...' : 'Book Now'}</span>
            </button>
          ) : (
            <button
              className="book-btn"
              type="button"
              onClick={() => onBook?.(flight)}
              disabled={isBooking}
              title={isBooking ? `Fetching booking link for ${getFlightRouteLabel(flight)}` : 'Fetch booking link'}
            >
              <span>{isBooking ? 'Fetching...' : 'Book Now'}</span>
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
