export interface FlightLeg {
  airlineCode: string
  departure: string
  arrival: string
  duration: string
  duration_minutes: number
  stops: string
  stopCount: number
  stopAirports: string[]
}

export interface FlightOption {
  id: string
  price: number
  tripType: string
  legs: FlightLeg[]
  bookingUrl?: string
}

export interface BookingUrlRequest {
  session_id: string
  result_set_id: string
  flight_id: string
}

export interface BookingUrlResponse {
  bookingUrl: string
}

export interface ChatRequest {
  message: string
  session_id?: string
  context?: {
    timeZone?: string
    location?: string
    filters?: FilterTag[]
  }
}

export interface FilterTag {
  id: string
  label: string
}

export interface ChatResponse {
  reply: string
  flights: FlightOption[] | null
  resultSetId?: string | null
  description_of_recommendation?: string | null
  intent?: Record<string, unknown>
}

export type ChatProgressStage =
  | 'analyzing_request'
  | 'searching_flights'
  | 'formatting_results'
  | 'generating_summary'

export interface ChatProgressEvent {
  type: 'progress'
  stage: ChatProgressStage
  message: string
}
