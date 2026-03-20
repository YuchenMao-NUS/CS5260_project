export interface AirlineInfo {
  name: string
  slug?: string
}

export const AIRLINES_BY_CODE: Record<string, AirlineInfo> = {
  "A3": {
    "name": "Aegean Airlines",
    "slug": "aegean-airlines"
  },
  "EI": {
    "name": "Aer Lingus",
    "slug": "aer-lingus"
  },
  "AR": {
    "name": "Aerolíneas Argentinas",
    "slug": "aerolineas-argentinas"
  },
  "AM": {
    "name": "Aeroméxico",
    "slug": "aeromexico"
  },
  "ZB": {
    "name": "Air Albania",
    "slug": "air-albania"
  },
  "AH": {
    "name": "Air Algérie",
    "slug": "air-algerie"
  },
  "KC": {
    "name": "Air Astana",
    "slug": "air-astana"
  },
  "AC": {
    "name": "Air Canada",
    "slug": "air-canada"
  },
  "EN": {
    "name": "Air Dolomiti",
    "slug": "air-dolomiti"
  },
  "UX": {
    "name": "Air Europa",
    "slug": "air-europa"
  },
  "AF": {
    "name": "Air France",
    "slug": "air-france"
  },
  "AI": {
    "name": "Air India",
    "slug": "air-india"
  },
  "MK": {
    "name": "Air Mauritius",
    "slug": "air-mauritius"
  },
  "NZ": {
    "name": "Air New Zealand",
    "slug": "air-new-zealand"
  },
  "JU": {
    "name": "Air Serbia",
    "slug": "air-serbia"
  },
  "TS": {
    "name": "Air Transat",
    "slug": "air-transat"
  },
  "AK": {
    "name": "AirAsia",
    "slug": "airasia"
  },
  "KT": {
    "name": "AirAsia Cambodia",
    "slug": "airasia"
  },
  "FD": {
    "name": "Thai AirAsia",
    "slug": "airasia"
  },
  "QZ": {
    "name": "Indonesia AirAsia",
    "slug": "airasia"
  },
  "Z2": {
    "name": "Philippines AirAsia",
    "slug": "airasia"
  },
  "BT": {
    "name": "airBaltic",
    "slug": "airbaltic"
  },
  "QP": {
    "name": "Akasa Air",
    "slug": "akasa-air"
  },
  "AS": {
    "name": "Alaska Airlines",
    "slug": "alaska-airlines"
  },
  "OZ": {
    "name": "Asiana Airlines",
    "slug": "asiana-airlines"
  },
  "RC": {
    "name": "Atlantic Airways",
    "slug": "atlantic-airways"
  },
  "AV": {
    "name": "avianca",
    "slug": "avianca"
  },
  "LR": {
    "name": "Avianca Costa Rica",
    "slug": "avianca"
  },
  "2K": {
    "name": "Avianca Ecuador",
    "slug": "avianca"
  },
  "TA": {
    "name": "Avianca El Salvador",
    "slug": "avianca"
  },
  "J2": {
    "name": "Azerbaijan Airlines",
    "slug": "azerbaijan-airlines"
  },
  "QH": {
    "name": "Bamboo Airways",
    "slug": "bamboo-airways"
  },
  "PG": {
    "name": "Bangkok Airways",
    "slug": "bangkok-airways"
  },
  "BA": {
    "name": "British Airways",
    "slug": "british-airways"
  },
  "SN": {
    "name": "Brussels Airlines",
    "slug": "brussels-airlines"
  },
  "CX": {
    "name": "Cathay Pacific",
    "slug": "cathay-pacific"
  },
  "CM": {
    "name": "Copa Airlines",
    "slug": "copa-airlines"
  },
  "EK": {
    "name": "Emirates",
    "slug": "emirates"
  },
  "ET": {
    "name": "Ethiopian Airlines",
    "slug": "ethiopian-airlines"
  },
  "EY": {
    "name": "Etihad Airways",
    "slug": "etihad-airways"
  },
  "EW": {
    "name": "Eurowings",
    "slug": "eurowings"
  },
  "ZD": {
    "name": "Ewa Air",
    "slug": "ewa-air"
  },
  "FJ": {
    "name": "Fiji Airways",
    "slug": "fiji-airways"
  },
  "FY": {
    "name": "Firefly",
    "slug": "firefly"
  },
  "XY": {
    "name": "flynas",
    "slug": "flynas"
  },
  "GA": {
    "name": "Garuda Indonesia",
    "slug": "garuda-indonesia"
  },
  "UO": {
    "name": "HK Express",
    "slug": "hk-express"
  },
  "IB": {
    "name": "Iberia",
    "slug": "iberia"
  },
  "FI": {
    "name": "Icelandair",
    "slug": "icelandair"
  },
  "6E": {
    "name": "IndiGo",
    "slug": "indigo"
  },
  "JL": {
    "name": "Japan Airlines",
    "slug": "japan-airlines"
  },
  "JQ": {
    "name": "Jetstar",
    "slug": "jetstar"
  },
  "GK": {
    "name": "Jetstar Japan",
    "slug": "jetstar"
  },
  "KQ": {
    "name": "Kenya Airways",
    "slug": "kenya-airways"
  },
  "KL": {
    "name": "KLM",
    "slug": "klm"
  },
  "KE": {
    "name": "Korean Air",
    "slug": "korean-air"
  },
  "KU": {
    "name": "Kuwait Airways",
    "slug": "kuwait-airways"
  },
  "LA": {
    "name": "LATAM Airlines",
    "slug": "latam-airlines"
  },
  "JJ": {
    "name": "LATAM Airlines Brasil",
    "slug": "latam-airlines"
  },
  "4C": {
    "name": "LATAM Airlines Colombia",
    "slug": "latam-airlines"
  },
  "XL": {
    "name": "LATAM Airlines Ecuador",
    "slug": "latam-airlines"
  },
  "LP": {
    "name": "LATAM Airlines Perú",
    "slug": "latam-airlines"
  },
  "PZ": {
    "name": "LATAM Airlines Paraguay",
    "slug": "latam-airlines"
  },
  "LO": {
    "name": "LOT Polish Airlines",
    "slug": "lot-polish-airlines"
  },
  "LH": {
    "name": "Lufthansa",
    "slug": "lufthansa"
  },
  "MH": {
    "name": "Malaysia Airlines",
    "slug": "malaysia-airlines"
  },
  "UB": {
    "name": "Myanmar National Airlines",
    "slug": "myanmar-national-airlines"
  },
  "WY": {
    "name": "Oman Air",
    "slug": "oman-air"
  },
  "ZP": {
    "name": "Paranair",
    "slug": "paranair"
  },
  "MM": {
    "name": "Peach Aviation",
    "slug": "peach-aviation"
  },
  "PR": {
    "name": "Philippine Airlines",
    "slug": "philippine-airlines"
  },
  "QF": {
    "name": "Qantas",
    "slug": "qantas"
  },
  "QR": {
    "name": "Qatar Airways",
    "slug": "qatar-airways"
  },
  "RX": {
    "name": "Riyadh Air",
    "slug": "riyadh-air"
  },
  "AT": {
    "name": "Royal Air Maroc",
    "slug": "royal-air-maroc"
  },
  "BI": {
    "name": "Royal Brunei Airlines",
    "slug": "royal-brunei-airlines"
  },
  "FR": {
    "name": "Ryanair",
    "slug": "ryanair"
  },
  "SV": {
    "name": "Saudia",
    "slug": "saudia"
  },
  "SK": {
    "name": "Scandinavian Airlines",
    "slug": "scandinavian-airlines"
  },
  "SL": {
    "name": "SAS Connect",
    "slug": "scandinavian-airlines"
  },
  "TR": {
    "name": "Scoot",
    "slug": "scoot"
  },
  "SQ": {
    "name": "Singapore Airlines",
    "slug": "singapore-airlines"
  },
  "WN": {
    "name": "Southwest Airlines",
    "slug": "southwest-airlines"
  },
  "JX": {
    "name": "Starlux Airlines",
    "slug": "starlux-airlines"
  },
  "9G": {
    "name": "Sun PhuQuoc Airways",
    "slug": "sun-phuquoc-airways"
  },
  "LX": {
    "name": "SWISS",
    "slug": "swiss"
  },
  "TW": {
    "name": "T'way Air",
    "slug": "tway-air"
  },
  "TP": {
    "name": "TAP Air Portugal",
    "slug": "tap-air-portugal"
  },
  "RO": {
    "name": "TAROM",
    "slug": "tarom"
  },
  "TG": {
    "name": "Thai Airways",
    "slug": "thai-airways"
  },
  "HV": {
    "name": "Transavia",
    "slug": "transavia"
  },
  "TK": {
    "name": "Turkish Airlines",
    "slug": "turkish-airlines"
  },
  "UA": {
    "name": "United Airlines",
    "slug": "united-airlines"
  },
  "VJ": {
    "name": "VietJet Air",
    "slug": "vietjet-air"
  },
  "VN": {
    "name": "Vietnam Airlines",
    "slug": "vietnam-airlines"
  },
  "VS": {
    "name": "Virgin Atlantic",
    "slug": "virgin-atlantic"
  },
  "VA": {
    "name": "Virgin Australia",
    "slug": "virgin-australia"
  },
  "WS": {
    "name": "WestJet",
    "slug": "westjet"
  },
  "W6": {
    "name": "Wizz Air",
    "slug": "wizz-air"
  },
  "5W": {
    "name": "Wizz Air Abu Dhabi",
    "slug": "wizz-air"
  },
  "W9": {
    "name": "Wizz Air UK",
    "slug": "wizz-air"
  },
  "MF": {
    "name": "XiamenAir",
    "slug": "xiamenair"
  }
} as const
