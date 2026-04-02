import { useEffect, useMemo, useState } from 'react'
import { FlightCard } from './FlightCard'
import type { FlightOption } from '../types'
import { getAirlineInfo } from '../utils/airlines'

export type StopsFilter = 'all' | 'direct' | '1' | '2+'
export type SortOption = 'price-low' | 'price-high' | 'duration'

interface FlightFiltersProps {
  flights: FlightOption[]
  content?: string
}

function getStopsCount(stops: string): number {
  if (/direct/i.test(stops)) return 0
  const m = stops.match(/^(\d+)\s*stop/)
  return m ? parseInt(m[1], 10) : 1
}

export function FlightFilters({ flights, content }: FlightFiltersProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [stopsFilter, setStopsFilter] = useState<StopsFilter>('all')
  const [airlinesFilter, setAirlinesFilter] = useState<Set<string>>(new Set())
  const [sortBy, setSortBy] = useState<SortOption>('price-low')

  const [currentPage, setCurrentPage] = useState(1)
  const itemsPerPage = 10

  const airlines = useMemo(() => {
    const set = new Set(flights.flatMap((f) => f.legs.map((l) => l.airlineCode)))
    return Array.from(set).sort((a, b) => {
      const nameA = getAirlineInfo(a).name
      const nameB = getAirlineInfo(b).name
      return nameA.localeCompare(nameB)
    })
  }, [flights])

  const filteredAndSorted = useMemo(() => {
    let result = flights.filter((f) => {
      // If any leg doesn't meet the stop criteria, filter out the flight
      const maxStops = Math.max(...f.legs.map(l => getStopsCount(l.stops)))
      if (stopsFilter === 'direct' && maxStops !== 0) return false
      if (stopsFilter === '1' && maxStops !== 1) return false
      if (stopsFilter === '2+' && maxStops < 2) return false

      if (airlinesFilter.size > 0) {
        // Must contain at least one of the selected airlines
        const flightAirlines = new Set(f.legs.map(l => l.airlineCode))
        const hasMatchingAirline = Array.from(flightAirlines).some(code => airlinesFilter.has(code))
        if (!hasMatchingAirline) return false
      }
      
      return true
    })

    result = [...result].sort((a, b) => {
      if (sortBy === 'price-low') return a.price - b.price
      if (sortBy === 'price-high') return b.price - a.price
      const durationA = a.legs.reduce((acc, leg) => acc + leg.duration_minutes, 0)
      const durationB = b.legs.reduce((acc, leg) => acc + leg.duration_minutes, 0)
      return durationA - durationB
    })

    return result
  }, [flights, stopsFilter, airlinesFilter, sortBy])

  useEffect(() => {
    setCurrentPage(1)
  }, [stopsFilter, airlinesFilter, sortBy])

  const totalPages = Math.ceil(filteredAndSorted.length / itemsPerPage)
  const paginatedFlights = filteredAndSorted.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  )

  const toggleAirline = (airline: string) => {
    setAirlinesFilter((prev) => {
      const next = new Set(prev)
      if (next.has(airline)) next.delete(airline)
      else next.add(airline)
      return next
    })
  }

  return (
    <div className="flight-filters-wrapper">
      {content && <p className="flight-results-intro">{content}</p>}
      <div className="flight-filters flight-filters-sticky">
        <div 
          className="filter-header"
          onClick={() => setIsExpanded(!isExpanded)}
          role="button"
          tabIndex={0}
        >
          <h3 className="filter-title">Filter &amp; Sort</h3>
          <span className={`filter-toggle-icon ${isExpanded ? 'expanded' : ''}`}>▼</span>
        </div>
        
        {isExpanded && (
          <div className="filter-content">
            <div className="filter-row">
              <div className="filter-group">
                <span className="filter-label">Stops</span>
                <div className="filter-chips">
                  {(['all', 'direct', '1', '2+'] as const).map((v) => (
                    <button
                      key={v}
                      type="button"
                      className={`filter-chip ${stopsFilter === v ? 'active' : ''}`}
                      onClick={() => setStopsFilter(v)}
                    >
                      {v === 'all' ? 'All' : v === 'direct' ? 'Direct' : v === '1' ? '1 stop' : '2+ stops'}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="filter-row">
              <div className="filter-group">
                <span className="filter-label">Airlines</span>
                <div className="filter-chips filter-chips-wrap">
                  <button
                    type="button"
                    className={`filter-chip ${airlinesFilter.size === 0 ? 'active' : ''}`}
                    onClick={() => setAirlinesFilter(new Set())}
                  >
                    All
                  </button>
            {airlines.map((code) => {
              const name = getAirlineInfo(code).name
              return (
                <label key={code} className="filter-chip filter-chip-check">
                  <input
                    type="checkbox"
                    checked={airlinesFilter.has(code)}
                    onChange={() => toggleAirline(code)}
                  />
                  <span>{name}</span>
                </label>
              )
            })}
                </div>
              </div>
            </div>
            <div className="filter-row">
              <div className="filter-group">
                <span className="filter-label">Sort by</span>
                <select
                  className="filter-select"
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as SortOption)}
                >
                  <option value="price-low">Price: Low to High</option>
                  <option value="price-high">Price: High to Low</option>
                  <option value="duration">Duration</option>
                </select>
              </div>
            </div>
          </div>
        )}
        <div className="filter-result-count">
          {filteredAndSorted.length} flight{filteredAndSorted.length !== 1 ? 's' : ''}
        </div>
      </div>
      <div className="flights">
        {paginatedFlights.map((f) => (
          <FlightCard key={f.id} flight={f} />
        ))}
      </div>
      
      {totalPages > 1 && (
        <div className="pagination">
          <button 
            className="page-btn" 
            disabled={currentPage === 1}
            onClick={() => setCurrentPage(p => p - 1)}
          >
            Previous
          </button>
          <span className="page-info">
            Page {currentPage} of {totalPages}
          </span>
          <button 
            className="page-btn" 
            disabled={currentPage === totalPages}
            onClick={() => setCurrentPage(p => p + 1)}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}

