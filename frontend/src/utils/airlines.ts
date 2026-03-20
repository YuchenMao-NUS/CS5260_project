import { AIRLINES_BY_CODE, type AirlineInfo } from '../generated/airlines'

export function getAirlineInfo(code: string): AirlineInfo {
  return AIRLINES_BY_CODE[code] ?? { name: code }
}
