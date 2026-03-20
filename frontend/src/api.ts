import type { ChatRequest, ChatResponse } from './types'

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
