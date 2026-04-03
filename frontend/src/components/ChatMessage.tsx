import { FlightFilters } from './FlightFilters'
import type { FlightOption, FilterTag } from '../types'

interface ChatMessageProps {
  role: 'user' | 'assistant'
  content: string
  flights?: FlightOption[]
  filtersRef?: React.Ref<HTMLDivElement>
  onToggleTag?: (tag: FilterTag, isActive: boolean) => void
}

export function ChatMessage({ role, content, flights, filtersRef, onToggleTag }: ChatMessageProps) {
  return (
    <div className={`message ${role}`}>
      {flights && flights.length > 0 ? (
        <div className="message-flights-block" ref={filtersRef}>
          <FlightFilters flights={flights} content={content} onToggleTag={onToggleTag} />
        </div>
      ) : (
        <div className="bubble">
          <p>{content}</p>
        </div>
      )}
    </div>
  )
}
