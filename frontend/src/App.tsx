import { useState, useRef, useEffect } from 'react'
import { ChatMessage } from './components/ChatMessage'
import './App.css'
import type { ChatProgressStage, FlightOption, FilterTag } from './types'
import { sendChatMessageStream } from './api'

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
  formatting_results: 'Attaching booking links and preparing the results.',
  generating_summary: 'Writing a short recommendation based on what was found.',
}

function getLoadingSubtext(stage: ChatProgressStage | null, elapsedSeconds: number) {
  if (elapsedSeconds >= 12) {
    return 'Still working. Live flight lookups and booking links can take a little longer.'
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
  const [messages, setMessages] = useState<Array<{
    role: 'user' | 'assistant'
    content: string
    flights?: FlightOption[]
    descriptionOfRecommendation?: string
  }>>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingMessage, setLoadingMessage] = useState<string | null>(null)
  const [loadingStage, setLoadingStage] = useState<ChatProgressStage | null>(null)
  const [loadingElapsedSeconds, setLoadingElapsedSeconds] = useState(0)
  const [activeTags, setActiveTags] = useState<FilterTag[]>([])
  const [userLocation, setUserLocation] = useState<string | undefined>(undefined)
  
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const sessionIdRef = useRef(createSessionId())

  const filtersRef = useRef<HTMLDivElement>(null)
  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  const scrollToFilters = () => filtersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  
  useEffect(() => {
    // Attempt to silently get rough location (City, Country) from IP for better default origin matching
    fetch('https://get.geojs.io/v1/ip/geo.json')
      .then(res => res.json())
      .then(data => {
        if (data.city && data.country) {
          setUserLocation(`${data.city}, ${data.country}`)
        }
      })
      .catch(() => {
        // Fail silently; we still have timezone as a fallback
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
    // Only fire at the two subtext threshold boundaries to avoid unnecessary re-renders
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

  const handleRemoveTag = (id: string) => {
    setActiveTags(prev => prev.filter(t => t.id !== id))
  }

  const handleClearTags = () => {
    setActiveTags([])
  }

  const sendMessage = async () => {
    const text = input.trim()
    if (!text && activeTags.length === 0 || loading) return

    let finalMessageText = text
    if (activeTags.length > 0) {
      const tagStrings = activeTags.map(t => `[${t.label}]`).join(' ')
      finalMessageText = text ? `${text} ${tagStrings}` : tagStrings
    }

    setInput('')
    // Clear tags after sending so they don't persist to the NEXT query
    setActiveTags([])
    
    setMessages((prev) => [...prev, { role: 'user', content: finalMessageText }])
    setLoading(true)
    setLoadingMessage('AI is analyzing your request...')

    try {
      const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
      const data = await sendChatMessageStream({
        message: finalMessageText,
        session_id: sessionIdRef.current,
        context: { 
          timeZone,
          location: userLocation
        }
      }, {
        onProgress: (event) => {
          setLoadingMessage(event.message)
          setLoadingStage(event.stage)
        },
      })
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.reply,
          flights: data.flights ?? undefined,
          descriptionOfRecommendation: data.description_of_recommendation ?? undefined,
        },
      ])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
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
              <p className="hint">e.g. &quot;Singapore to Malaysia next month, budget 500 SGD&quot; — or type &quot;demo&quot; for sample flights with filters.</p>
            </div>
          )}
          {messages.map((m, i) => (
            <ChatMessage
              key={i}
              role={m.role}
              content={m.content}
              flights={m.flights}
              descriptionOfRecommendation={m.descriptionOfRecommendation}
              filtersRef={i === messages.length - 1 ? filtersRef : undefined}
              onToggleTag={handleToggleTag}
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
          {activeTags.length > 0 && (
            <div className="input-tags">
              {activeTags.map(tag => (
                <span key={tag.id} className="input-tag">
                  {tag.label}
                  <button onClick={() => handleRemoveTag(tag.id)} title="Remove tag">✕</button>
                </span>
              ))}
              <button className="clear-tags" onClick={handleClearTags}>Clear all</button>
            </div>
          )}
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
