import { FlightFilters } from './FlightFilters'
import type { FlightOption } from '../types'

interface ChatMessageProps {
  role: 'user' | 'assistant'
  content: string
  flights?: FlightOption[]
  filtersRef?: React.Ref<HTMLDivElement>
}

export function ChatMessage({ role, content, flights, filtersRef }: ChatMessageProps) {
  return (
    <div className={`message ${role}`}>
      {flights && flights.length > 0 ? (
        <div className="message-flights-block" ref={filtersRef}>
          <FlightFilters flights={flights} content={content} />
        </div>
      ) : (
        <div className="bubble">
          <p>{content}</p>
        </div>
      )}
    </div>
  )
}
