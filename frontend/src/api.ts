import type { ChatProgressEvent, ChatRequest, ChatResponse } from './types'

const API_BASE = import.meta.env.VITE_API_URL || ''

interface ApiErrorPayload {
  detail?: string
}

export async function sendChatMessage(payload: ChatRequest): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const errorMessage = await getErrorMessage(response)
    throw new Error(errorMessage)
  }

  return response.json() as Promise<ChatResponse>
}

interface ChatStreamHandlers {
  onProgress?: (event: ChatProgressEvent) => void
}

interface StreamEnvelope {
  type?: 'progress' | 'completed' | 'error'
  stage?: ChatProgressEvent['stage']
  message?: string
  data?: ChatResponse
}

export async function sendChatMessageStream(
  payload: ChatRequest,
  handlers: ChatStreamHandlers = {},
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const errorMessage = await getErrorMessage(response)
    throw new Error(errorMessage)
  }

  if (!response.body) {
    throw new Error('Streaming is not supported by this browser.')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completedResponse: ChatResponse | null = null

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })

    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''

    for (const chunk of chunks) {
      const event = parseStreamEvent(chunk)
      if (!event) continue

      if (event.type === 'progress' && event.stage && event.message) {
        handlers.onProgress?.({
          type: 'progress',
          stage: event.stage,
          message: event.message,
        })
      } else if (event.type === 'completed' && event.data) {
        completedResponse = event.data
      } else if (event.type === 'error') {
        throw new Error(event.message || 'Streaming request failed')
      }
    }

    if (done) {
      break
    }
  }

  if (completedResponse) {
    return completedResponse
  }

  throw new Error('Stream ended before a final response was received.')
}

function parseStreamEvent(chunk: string): StreamEnvelope | null {
  const dataLines = chunk
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())

  if (dataLines.length === 0) {
    return null
  }

  const payload = dataLines.join('\n')
  try {
    return JSON.parse(payload) as StreamEnvelope
  } catch {
    return null
  }
}

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const error = (await response.json()) as ApiErrorPayload
    if (typeof error.detail === 'string' && error.detail.trim()) {
      return error.detail
    }
  } catch {
    // Fall back to a status-based message when the response is not JSON.
  }

  return `${response.status} ${response.statusText}`.trim()
}
