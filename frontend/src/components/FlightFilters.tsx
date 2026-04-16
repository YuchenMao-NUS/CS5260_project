import { useEffect, useMemo, useState } from 'react'
import { FlightCard } from './FlightCard'
import type { FlightOption, FilterTag } from '../types'
import { getAirlineInfo } from '../utils/airlines'

export type StopsFilter = 'all' | 'direct' | '1' | '2+'

interface FlightFiltersProps {
  flights: FlightOption[]
  content?: string
  onToggleTag?: (tag: FilterTag, isActive: boolean) => void
  onBookFlight?: (flight: FlightOption) => void
  bookingState?: Record<string, boolean>
}

function getStopsCount(stopCount: number | undefined, stops: string): number {
  if (typeof stopCount === 'number') return stopCount
  if (/direct/i.test(stops)) return 0
  const m = stops.match(/^(\d+)\s*stop/)
  return m ? parseInt(m[1], 10) : 1
}

export function FlightFilters({ flights, content, onToggleTag, onBookFlight, bookingState }: FlightFiltersProps) {
  const [stopsFilter, setStopsFilter] = useState<StopsFilter>('all')
  const [airlineFilter, setAirlineFilter] = useState<string>('all')
  const [currentPage, setCurrentPage] = useState(1)
  const itemsPerPage = 10

  const airlines = useMemo(() => {
    const set = new Set(flights.flatMap((flight) => flight.legs.map((leg) => leg.airlineCode)))
    return Array.from(set).sort((a, b) => {
      const nameA = getAirlineInfo(a).name
      const nameB = getAirlineInfo(b).name
      return nameA.localeCompare(nameB)
    })
  }, [flights])

  const setStopsFilterWithTag = (value: StopsFilter) => {
    setStopsFilter(value)

    if (value === 'all') {
      onToggleTag?.({ id: 'stops', label: '' }, false)
      return
    }

    const label = value === 'direct' ? 'Direct flights only' : value === '1' ? 'Max 1 stop' : '2+ stops'
    onToggleTag?.({ id: 'stops', label }, true)
  }

  const setAirlineFilterWithTag = (value: string) => {
    if (airlineFilter !== 'all') {
      onToggleTag?.({ id: `airline-${airlineFilter}`, label: getAirlineInfo(airlineFilter).name }, false)
    }

    setAirlineFilter(value)

    if (value === 'all') {
      return
    }

    onToggleTag?.({ id: `airline-${value}`, label: getAirlineInfo(value).name }, true)
  }

  const filteredFlights = useMemo(() => {
    const result = flights.filter((flight) => {
      const maxStops = Math.max(...flight.legs.map((leg) => getStopsCount(leg.stopCount, leg.stops)))
      if (stopsFilter === 'direct' && maxStops !== 0) return false
      if (stopsFilter === '1' && maxStops !== 1) return false
      if (stopsFilter === '2+' && maxStops < 2) return false

      if (airlineFilter !== 'all') {
        const flightAirlines = new Set(flight.legs.map((leg) => leg.airlineCode))
        if (!flightAirlines.has(airlineFilter)) return false
      }

      return true
    })

    return [...result].sort((a, b) => a.price - b.price)
  }, [airlineFilter, flights, stopsFilter])

  useEffect(() => {
    setCurrentPage(1)
  }, [stopsFilter, airlineFilter])

  const totalPages = Math.ceil(filteredFlights.length / itemsPerPage)
  const paginatedFlights = filteredFlights.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)

  return (
    <div className="flight-filters-wrapper">
      {content && <p className="flight-results-intro">{content}</p>}
      <div className="flight-filters flight-filters-sticky">
        <div className="filter-header">
          <h3 className="filter-title">Filter &amp; Sort</h3>
          <div className="filter-controls" aria-label="Flight filters">
            <select
              className="filter-select compact"
              value={stopsFilter}
              onChange={(e) => setStopsFilterWithTag(e.target.value as StopsFilter)}
              aria-label="Stops filter"
            >
              <option value="all">Stops</option>
              <option value="direct">Direct</option>
              <option value="1">1 stop</option>
              <option value="2+">2+ stops</option>
            </select>
            <select
              className="filter-select compact"
              value={airlineFilter}
              onChange={(e) => setAirlineFilterWithTag(e.target.value)}
              aria-label="Airline filter"
            >
              <option value="all">Airlines</option>
              {airlines.map((code) => (
                <option key={code} value={code}>
                  {getAirlineInfo(code).name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
      <div className="flights">
        {paginatedFlights.map((flight) => (
          <FlightCard
            key={flight.id}
            flight={flight}
            isBooking={Boolean(bookingState?.[flight.id])}
            onBook={onBookFlight}
          />
        ))}
      </div>

      {totalPages > 1 && (
        <div className="pagination">
          <button className="page-btn" disabled={currentPage === 1} onClick={() => setCurrentPage((page) => page - 1)}>
            Previous
          </button>
          <span className="page-info">
            Page {currentPage} of {totalPages}
          </span>
          <button className="page-btn" disabled={currentPage === totalPages} onClick={() => setCurrentPage((page) => page + 1)}>
            Next
          </button>
        </div>
      )}
    </div>
  )
}
