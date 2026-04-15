import { getFlightRouteLabel } from '../utils/flightRoute'
import { useEffect, useState } from 'react'
import type { FlightOption, FlightLeg } from '../types'
import { getAirlineInfo } from '../utils/airlines'
import { ExternalLinkIcon } from './Icons'

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

function FlightLegView({ leg, label }: { leg: FlightLeg, label?: string }) {
  const airlineMeta = getAirlineInfo(leg.airlineCode)
  const slug = airlineMeta?.slug
  const airlineName = airlineMeta?.name || leg.airlineCode
  const stopDetails = getStopDetails(leg)

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
          <span className="airline">{airlineName}</span>
        </div>
      </div>
      <div className="flight-details">
        <span>{leg.departure}</span>
        <div className="duration-container">
          <span className="duration">{leg.duration}</span>
          <span className={`flight-stops ${leg.stopCount === 0 ? 'direct' : ''}`}>{leg.stops}</span>
          {stopDetails ? <span className="flight-stop-airports">{stopDetails}</span> : null}
        </div>
        <span>{leg.arrival}</span>
      </div>
    </div>
  )
}

export function FlightCard({ flight, isBooking = false, onBook }: FlightCardProps) {
  const bookingHost = getBookingHost(flight.bookingUrl)

  const getTripTypeLabel = (type: string) => {
    if (type === 'round_trip') return 'Round Trip'
    if (type === 'multi_city') return 'Multi-City'
    return 'One Way'
  }

  return (
    <div className="flight-card">
      <div className="flight-card-header">
        <span className="trip-type-badge">{getTripTypeLabel(flight.tripType)}</span>
        <div className="flight-price-action">
          <span className="price">SGD {flight.price}</span>
          {flight.bookingUrl ? (
            <button
              className="book-btn"
              type="button"
              onClick={() => onBook?.(flight)}
              title={bookingHost ? `Book on ${bookingHost}` : 'Book on external website'}
            >
              <span>{isBooking ? 'Booking...' : 'Book'}</span>
              <ExternalLinkIcon className="external-icon" />
            </button>
          ) : (
            <button
              className="book-btn"
              type="button"
              onClick={() => onBook?.(flight)}
              disabled={isBooking}
              title={isBooking ? `Fetching booking link for ${getFlightRouteLabel(flight)}` : 'Fetch booking link'}
            >
              <span>{isBooking ? 'Booking...' : 'Book'}</span>
              <ExternalLinkIcon className="external-icon" />
            </button>
          )}
        </div>
      </div>
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
    </div>
  )
}
