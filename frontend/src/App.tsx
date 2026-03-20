import { useState, useRef, useEffect } from 'react'
import { ChatMessage } from './components/ChatMessage'
import './App.css'
import type { FlightOption } from './types'
import { sendChatMessage } from './api'

export default function App() {
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string; flights?: FlightOption[] }>>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const filtersRef = useRef<HTMLDivElement>(null)
  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  const scrollToFilters = () => filtersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  useEffect(() => {
    const last = messages[messages.length - 1]
    if (last?.role === 'assistant' && last?.flights?.length) {
      scrollToFilters()
    } else {
      scrollToBottom()
    }
  }, [messages])

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || loading) return

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setLoading(true)

    try {
      const data = await sendChatMessage({ message: text })
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.reply,
          flights: data.flights ?? undefined,
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
              <p className="hint">e.g. &quot;Singapore to Tokyo next month, budget 500 SGD&quot; — or type &quot;demo&quot; for sample flights with filters.</p>
            </div>
          )}
          {messages.map((m, i) => (
            <ChatMessage
              key={i}
              role={m.role}
              content={m.content}
              flights={m.flights}
              filtersRef={i === messages.length - 1 ? filtersRef : undefined}
            />
          ))}
          {loading && (
            <div className="message assistant">
              <div className="bubble">Searching flights...</div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-area">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
            placeholder="Describe your trip..."
            disabled={loading}
          />
          <button onClick={sendMessage} disabled={loading || !input.trim()}>
            Send
          </button>
        </div>
      </main>
    </div>
  )
}
