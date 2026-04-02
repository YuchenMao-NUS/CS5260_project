import type { FlightOption, FlightLeg } from '../types'
import { getAirlineInfo } from '../utils/airlines'

interface FlightCardProps {
  flight: FlightOption
}

function FlightLegView({ leg, label }: { leg: FlightLeg, label?: string }) {
  const airlineMeta = getAirlineInfo(leg.airlineCode)
  const slug = airlineMeta?.slug
  const airlineName = airlineMeta?.name || leg.airlineCode
  
  // Try icon first, fallback to logo if icon doesn't exist
  // We'll let the img onError handler deal with actual 404s
  const iconUrl = slug ? `/airlines/${slug}/icon.svg` : null
  const logoUrl = slug ? `/airlines/${slug}/logo.svg` : null

  return (
    <div className="flight-leg">
      {label && <div className="leg-direction-label">{label}</div>}
      <div className="flight-header">
        <div className="airline-info">
          <div className="airline-logo-container">
            {iconUrl ? (
              <img 
                src={iconUrl} 
                alt={`${airlineName} logo`} 
                className="airline-logo"
                onError={(e) => {
                  const target = e.currentTarget
                  // If icon fails, try logo.svg
                  if (target.src.endsWith('icon.svg') && logoUrl) {
                    target.src = logoUrl
                  } else {
                    // If both fail, hide image and show placeholder
                    target.style.display = 'none'
                    const placeholder = target.parentElement?.querySelector('.airline-logo-placeholder') as HTMLElement
                    if (placeholder) {
                      placeholder.style.display = 'flex'
                    }
                  }
                }}
              />
            ) : null}
            <div 
              className="airline-logo-placeholder" 
              style={{ display: iconUrl ? 'none' : 'flex' }}
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
          <span className={`flight-stops ${leg.stops === 'Direct' ? 'direct' : ''}`}>{leg.stops}</span>
        </div>
        <span>{leg.arrival}</span>
      </div>
    </div>
  )
}

export function FlightCard({ flight }: FlightCardProps) {
  const getTripTypeLabel = (type: string) => {
    if (type === 'round_trip') return 'Round Trip'
    if (type === 'multi_city') return 'Multi-City'
    return 'One Way'
  }

  return (
    <div className="flight-card">
      <div className="flight-card-header">
        <span className="trip-type-badge">{getTripTypeLabel(flight.tripType)}</span>
        <span className="price">SGD {flight.price}</span>
      </div>
      <div className="flight-legs">
        {flight.legs.map((leg, index) => {
          let label = undefined;
          if (flight.tripType === 'round_trip' && flight.legs.length === 2) {
            label = index === 0 ? '🛫 Outbound' : '🛬 Return';
          } else if (flight.tripType === 'multi_city' || flight.legs.length > 1) {
            label = `✈️ Leg ${index + 1}`;
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
