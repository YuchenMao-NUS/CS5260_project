import type { FlightOption } from '../types'
import { getAirline } from 'soaring-symbols'

interface FlightCardProps {
  flight: FlightOption
}

export function FlightCard({ flight }: FlightCardProps) {
  // Find the airline slug from soaring-symbols using the official API
  const airlineMeta = getAirline(flight.airlineCode)
  const slug = airlineMeta?.slug
  const airlineName = airlineMeta?.name || flight.airlineCode
  
  // Try icon first, fallback to logo if icon doesn't exist
  // We'll let the img onError handler deal with actual 404s
  const iconUrl = slug ? `/airlines/${slug}/icon.svg` : null
  const logoUrl = slug ? `/airlines/${slug}/logo.svg` : null

  return (
    <div className="flight-card">
      <div className="flight-header">
        <div className="airline-info">
          <div className="airline-logo-container">
            {iconUrl ? (
              <img 
                src={iconUrl} 
                alt={`${airlineName} logo`} 
                className="airline-logo"
                onError={(e) => {
                  const target = e.currentTarget;
                  // If icon fails, try logo.svg
                  if (target.src.endsWith('icon.svg') && logoUrl) {
                    target.src = logoUrl;
                  } else {
                    // If both fail, hide image and show placeholder
                    target.style.display = 'none';
                    const placeholder = target.parentElement?.querySelector('.airline-logo-placeholder') as HTMLElement;
                    if (placeholder) {
                      placeholder.style.display = 'flex';
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
        <span className="price">SGD {flight.price}</span>
      </div>
      <div className="flight-details">
        <span>{flight.departure}</span>
        <span className="duration">{flight.duration}</span>
        <span>{flight.arrival}</span>
      </div>
      <div className="flight-stops">{flight.stops}</div>
    </div>
  )
}
