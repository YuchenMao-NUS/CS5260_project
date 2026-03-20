export interface FlightOption {
  id: string
  airlineCode: string
  departure: string
  arrival: string
  duration: string
  duration_minutes: number
  price: number
  stops: string
}

export interface ChatRequest {
  message: string
}

export interface ChatResponse {
  reply: string
  flights: FlightOption[] | null
  intent?: Record<string, unknown>
}
