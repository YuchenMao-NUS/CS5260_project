import { useState, useRef, useEffect } from 'react'
import { ChatMessage } from './components/ChatMessage'
import './App.css'
import type { ChatProgressStage, FlightOption, FilterTag } from './types'
import { fetchBookingUrl, sendChatMessageStream } from './api'
import { getFlightRouteLabel } from './utils/flightRoute'

function createSessionId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function formatLoadingTitle(message: string | null) {
  const base = (message || 'Searching flights').trim()
  return base.replace(/(\.\.\.|…)+\s*$/, '')
}

const STAGE_SUBTEXT: Record<ChatProgressStage, string> = {
  analyzing_request: 'Understanding your request before we look for flights.',
  searching_flights: 'Checking live route combinations and available options.',
  formatting_results: 'Formatting the results for display.',
  generating_summary: 'Writing a short recommendation based on what was found.',
}

interface MessageRecord {
  id: string
  role: 'user' | 'assistant'
  content: string
  flights?: FlightOption[]
  resultSetId?: string
  descriptionOfRecommendation?: string
}

function createMessageId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function getLoadingSubtext(stage: ChatProgressStage | null, elapsedSeconds: number) {
  if (elapsedSeconds >= 12) {
    return 'Still working. Live flight lookups can take a little longer.'
  }

  if (elapsedSeconds >= 6) {
    return 'Still working. The request is active and more updates should appear soon.'
  }

  if (stage && STAGE_SUBTEXT[stage]) {
    return STAGE_SUBTEXT[stage]
  }

  return 'Preparing your request...'
}

export default function App() {
  const [messages, setMessages] = useState<MessageRecord[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingMessage, setLoadingMessage] = useState<string | null>(null)
  const [loadingStage, setLoadingStage] = useState<ChatProgressStage | null>(null)
  const [loadingElapsedSeconds, setLoadingElapsedSeconds] = useState(0)
  const [activeTags, setActiveTags] = useState<FilterTag[]>([])
  const [userLocation, setUserLocation] = useState<string | undefined>(undefined)
  const [bookingFlightIds, setBookingFlightIds] = useState<Record<string, boolean>>({})

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const sessionIdRef = useRef(createSessionId())

  const filtersRef = useRef<HTMLDivElement>(null)
  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  const scrollToFilters = () => filtersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  useEffect(() => {
    fetch('https://get.geojs.io/v1/ip/geo.json')
      .then(res => res.json())
      .then(data => {
        if (data.city && data.country) {
          setUserLocation(`${data.city}, ${data.country}`)
        }
      })
      .catch(() => {
        // Fail silently; we still have timezone as a fallback.
      })
  }, [])

  useEffect(() => {
    const last = messages[messages.length - 1]
    if (last?.role === 'assistant' && last?.flights?.length) {
      scrollToFilters()
    } else {
      scrollToBottom()
    }
  }, [messages])

  useEffect(() => {
    if (!loading) {
      setLoadingElapsedSeconds(0)
      return
    }

    setLoadingElapsedSeconds(0)
    const t1 = window.setTimeout(() => setLoadingElapsedSeconds(6), 6_000)
    const t2 = window.setTimeout(() => setLoadingElapsedSeconds(12), 12_000)

    return () => {
      window.clearTimeout(t1)
      window.clearTimeout(t2)
    }
  }, [loading])

  const handleToggleTag = (tag: FilterTag, isActive: boolean) => {
    setActiveTags(prev => {
      if (!isActive) {
        return prev.filter(t => t.id !== tag.id)
      }

      const idx = prev.findIndex(t => t.id === tag.id)
      if (idx >= 0) {
        const copy = [...prev]
        copy[idx] = tag
        return copy
      }

      return [...prev, tag]
    })
  }

  const appendAssistantMessage = (content: string) => {
    setMessages(prev => [...prev, { id: createMessageId(), role: 'assistant', content }])
  }

  const cacheBookingUrl = (messageId: string, flightId: string, bookingUrl: string) => {
    setMessages(prev =>
      prev.map(message => {
        if (message.id !== messageId || !message.flights) {
          return message
        }

        return {
          ...message,
          flights: message.flights.map(flight =>
            flight.id === flightId ? { ...flight, bookingUrl } : flight,
          ),
        }
      }),
    )
  }

  const handleBookFlight = async (messageId: string, resultSetId: string | undefined, flight: FlightOption) => {
    const bookingKey = `${messageId}:${flight.id}`
    const routeLabel = getFlightRouteLabel(flight)

    if (flight.bookingUrl) {
      window.open(flight.bookingUrl, '_blank', 'noopener,noreferrer')
      return
    }

    if (!resultSetId) {
      appendAssistantMessage(`Error fetching booking URL for flight ${routeLabel}: missing result set reference`)
      return
    }

    appendAssistantMessage(
      `Fetching booking URL for flight ${routeLabel}. You will be automatically redirected to the booking page shortly.`,
    )
    setBookingFlightIds(prev => ({ ...prev, [bookingKey]: true }))

    try {
      const result = await fetchBookingUrl({
        session_id: sessionIdRef.current,
        result_set_id: resultSetId,
        flight_id: flight.id,
      })

      cacheBookingUrl(messageId, flight.id, result.bookingUrl)
      window.open(result.bookingUrl, '_blank', 'noopener,noreferrer')
    } catch (err) {
      appendAssistantMessage(
        `Error fetching booking URL for flight ${routeLabel}: ${err instanceof Error ? err.message : 'Request failed'}`,
      )
    } finally {
      setBookingFlightIds(prev => {
        const next = { ...prev }
        delete next[bookingKey]
        return next
      })
    }
  }

  const sendMessage = async () => {
    const text = input.trim()
    if ((!text && activeTags.length === 0) || loading) return

    let finalMessageText = text
    if (activeTags.length > 0) {
      const tagStrings = activeTags.map(t => `[${t.label}]`).join(' ')
      finalMessageText = text ? `${text} ${tagStrings}` : tagStrings
    }

    setInput('')
    setActiveTags([])

    setMessages(prev => [...prev, { id: createMessageId(), role: 'user', content: finalMessageText }])
    setLoading(true)
    setLoadingMessage('AI is analyzing your request...')

    try {
      const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
      const data = await sendChatMessageStream({
        message: finalMessageText,
        session_id: sessionIdRef.current,
        context: {
          timeZone,
          location: userLocation,
        },
      }, {
        onProgress: (event) => {
          setLoadingMessage(event.message)
          setLoadingStage(event.stage)
        },
      })

      setMessages(prev => [
        ...prev,
        {
          id: createMessageId(),
          role: 'assistant',
          content: data.reply,
          flights: data.flights ?? undefined,
          resultSetId: data.resultSetId ?? undefined,
          descriptionOfRecommendation: data.description_of_recommendation ?? undefined,
        },
      ])
    } catch (err) {
      setMessages(prev => [
        ...prev,
        {
          id: createMessageId(),
          role: 'assistant',
          content: `Error: ${err instanceof Error ? err.message : 'Request failed'}`,
        },
      ])
    } finally {
      setLoading(false)
      setLoadingMessage(null)
      setLoadingStage(null)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>SmartFlight</h1>
        <p className="subtitle">Intelligent Flight-Discovery Agent · NUS CS5260 Project</p>
      </header>

      <main className="chat-container">
        <div className="messages">
          {messages.length === 0 && (
            <div className="welcome">
              <p>Tell me your travel plans in natural language.</p>
              <p className="hint">e.g. &quot;Singapore to Malaysia next month, budget 500 SGD&quot; or type &quot;demo&quot; for sample flights with filters.</p>
            </div>
          )}
          {messages.map((m, i) => (
            <ChatMessage
              key={m.id}
              messageId={m.id}
              role={m.role}
              content={m.content}
              flights={m.flights}
              resultSetId={m.resultSetId}
              descriptionOfRecommendation={m.descriptionOfRecommendation}
              filtersRef={i === messages.length - 1 ? filtersRef : undefined}
              onToggleTag={handleToggleTag}
              onBookFlight={handleBookFlight}
              bookingState={
                Object.fromEntries(
                  Object.entries(bookingFlightIds)
                    .filter(([key]) => key.startsWith(`${m.id}:`))
                    .map(([key, value]) => [key.slice(m.id.length + 1), value]),
                )
              }
            />
          ))}
          {loading && (
            <div className="message assistant">
              <div className="bubble loading-bubble" aria-live="polite">
                <div className="loading-line">
                  <span className="loading-text">{formatLoadingTitle(loadingMessage)}</span>
                  <span className="loading-dots" aria-hidden="true">
                    <span></span>
                    <span></span>
                    <span></span>
                  </span>
                </div>
                <div className="loading-subtext">
                  {getLoadingSubtext(loadingStage, loadingElapsedSeconds)}
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-container">
          <div className="input-area">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
              placeholder="Describe your trip..."
              disabled={loading}
            />
            <button onClick={sendMessage} disabled={loading || (!input.trim() && activeTags.length === 0)}>
              Send
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
