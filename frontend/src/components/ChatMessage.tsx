import { FlightFilters } from './FlightFilters'
import type { FlightOption, FilterTag } from '../types'

interface ChatMessageProps {
  messageId?: string
  role: 'user' | 'assistant'
  content: string
  flights?: FlightOption[]
  resultSetId?: string
  descriptionOfRecommendation?: string
  filtersRef?: React.Ref<HTMLDivElement>
  onToggleTag?: (tag: FilterTag, isActive: boolean) => void
  onBookFlight?: (messageId: string, resultSetId: string | undefined, flight: FlightOption) => void
  bookingState?: Record<string, boolean>
}

export function ChatMessage({
  messageId,
  role,
  content,
  flights,
  resultSetId,
  descriptionOfRecommendation,
  filtersRef,
  onToggleTag,
  onBookFlight,
  bookingState,
}: ChatMessageProps) {
  const hasFlights = Boolean(flights && flights.length > 0)

  return (
    <div className={`message ${role}`}>
      {hasFlights ? (
        <>
          <div className="message-flights-block" ref={filtersRef}>
            <FlightFilters
              flights={flights!}
              content={content}
              onToggleTag={onToggleTag}
              bookingState={bookingState}
              onBookFlight={messageId ? (flight) => onBookFlight?.(messageId, resultSetId, flight) : undefined}
            />
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
