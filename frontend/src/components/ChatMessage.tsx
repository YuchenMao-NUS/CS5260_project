import { FlightFilters } from './FlightFilters'
import type { FlightOption, FilterTag } from '../types'

interface ChatMessageProps {
  role: 'user' | 'assistant'
  content: string
  flights?: FlightOption[]
  descriptionOfRecommendation?: string
  filtersRef?: React.Ref<HTMLDivElement>
  onToggleTag?: (tag: FilterTag, isActive: boolean) => void
}

export function ChatMessage({ role, content, flights, descriptionOfRecommendation, filtersRef, onToggleTag }: ChatMessageProps) {
  const hasFlights = Boolean(flights && flights.length > 0)

  return (
    <div className={`message ${role}`}>
      {hasFlights ? (
        <>
          <div className="message-flights-block" ref={filtersRef}>
            <FlightFilters flights={flights!} content={content} onToggleTag={onToggleTag} />
          </div>
          {descriptionOfRecommendation ? (
            <div className="bubble">
              <p>{descriptionOfRecommendation}</p>
            </div>
          ) : null}
        </>
      ) : (
        <div className="bubble">
          <p>{content}</p>
        </div>
      )}
    </div>
  )
}
