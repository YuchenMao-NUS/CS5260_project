export interface FlightLeg {
  airlineCode: string
  departure: string
  arrival: string
  duration: string
  duration_minutes: number
  stops: string
}

export interface FlightOption {
  id: string
  price: number
  tripType: string
  legs: FlightLeg[]
  bookingUrl?: string
}

export interface ChatRequest {
  message: string
  context?: {
    timeZone?: string
    location?: string
  }
}

export interface FilterTag {
  id: string
  label: string
}

export interface ChatResponse {
  reply: string
  flights: FlightOption[] | null
  description_of_recommendation?: string | null
  intent?: Record<string, unknown>
}
