import airportsIndex from '../../../shared/offline-packs/core-global/airports-index.json';
import aviationContextIndex from '../../../shared/offline-packs/core-global/aviation-context-index.json';
import type { PlaceReference } from '../data/types';

export interface AirportRecord extends PlaceReference {
  ident?: string;
  municipality: string;
  icaoCode?: string;
  type: string;
  scheduledService: boolean;
  runwayCount: number;
  longestRunwayFeet?: number;
}

export interface AirportFrequencyRecord {
  type: string;
  description?: string;
  frequencyMhz?: number;
}

export interface NavaidRecord {
  id: string;
  ident: string;
  name: string;
  type: string;
  countryCode: string;
  associatedAirportIata?: string;
  latitude: number;
  longitude: number;
  frequencyKhz?: number;
  usageType?: string;
  power?: string;
}

export interface AirportContextRecord {
  iataCode: string;
  frequencies: AirportFrequencyRecord[];
  navaids: NavaidRecord[];
  routeGraph?: AirportRouteGraphRecord;
}

export interface AirportRouteGraphRecord {
  source: string;
  outgoingRoutes: number;
  incomingRoutes: number;
  destinations?: Array<{ code: string; count: number; aircraftTypes?: string[] }>;
  topDestinations: Array<{ code: string; count: number }>;
  airlines: string[];
  aircraftTypes: string[];
}

interface AirportIndexRecord {
  id: string;
  ident?: string;
  type: string;
  name: string;
  iataCode: string;
  icaoCode?: string;
  countryCode: string;
  municipality: string;
  latitude: number;
  longitude: number;
  scheduledService: boolean;
  runwayCount: number;
  longestRunwayFeet?: number;
}

const airports = (airportsIndex.airports as AirportIndexRecord[]).map(toAirportRecord);
const airportsByCode = new Map<string, AirportRecord>();
for (const airport of airports) {
  for (const code of [airport.iataCode, airport.icaoCode, airport.ident]) {
    if (code) {
      airportsByCode.set(normalizeIata(code), airport);
    }
  }
}
const contexts = aviationContextIndex.contexts as AirportContextRecord[];
const contextsByIata = new Map(contexts.map((context) => [context.iataCode, context]));

export function findAirportByIata(iataCode: string): AirportRecord | undefined {
  return airportsByCode.get(normalizeIata(iataCode));
}

export function listAirportSuggestions(): AirportRecord[] {
  return airports.filter((airport) => airport.scheduledService);
}

export function searchAirports(
  query: string,
  options: { limit?: number; scheduledOnly?: boolean } = {}
): AirportRecord[] {
  const normalizedQuery = query.trim().toUpperCase();
  const pool = options.scheduledOnly === false ? airports : listAirportSuggestions();
  const limit = options.limit ?? 40;
  return pool
    .map((airport) => ({
      airport,
      rank: airportSearchRank(airport, normalizedQuery)
    }))
    .filter((match) => match.rank >= 0)
    .sort((left, right) =>
      left.rank - right.rank ||
      airportSearchSortKey(left.airport).localeCompare(airportSearchSortKey(right.airport))
    )
    .slice(0, limit)
    .map((match) => match.airport);
}

export function findAirportContextByIata(iataCode: string): AirportContextRecord | undefined {
  return contextsByIata.get(normalizeIata(iataCode));
}

export function findOpenFlightsRoute(
  originIata: string,
  destinationIata: string
): { count: number; source: string; aircraftTypes: string[] } | undefined {
  const originContext = findAirportContextByIata(originIata);
  const routeGraph = originContext?.routeGraph;
  if (!routeGraph) {
    return undefined;
  }
  const destinationCode = normalizeIata(destinationIata);
  const match = (routeGraph.destinations ?? routeGraph.topDestinations).find((route) => route.code === destinationCode);
  if (!match) {
    return undefined;
  }
  const aircraftTypes = (match as { aircraftTypes?: unknown }).aircraftTypes;
  return {
    count: match.count,
    source: routeGraph.source,
    aircraftTypes: Array.isArray(aircraftTypes) ? aircraftTypes.filter((value): value is string => typeof value === 'string') : []
  };
}

export function getAirportIndexSummary(): { airports: number; airportContexts: number; navaids: number } {
  return {
    airports: airports.length,
    airportContexts: contexts.length,
    navaids: aviationContextIndex.contents.navaids
  };
}

export function normalizeIata(value: string): string {
  return value.trim().toUpperCase();
}

function airportSearchRank(airport: AirportRecord, query: string): number {
  const iata = airport.iataCode?.toUpperCase() ?? '';
  const icao = airport.icaoCode?.toUpperCase() ?? '';
  const ident = airport.ident?.toUpperCase() ?? '';
  const name = airport.name.toUpperCase();
  const municipality = airport.municipality.toUpperCase();
  const country = airport.countryCode?.toUpperCase() ?? '';

  if (query.length === 0) {
    if (airport.scheduledService && airport.type === 'large_airport') {
      return 50;
    }
    if (airport.scheduledService && airport.type === 'medium_airport') {
      return 70;
    }
    return 90;
  }
  if (iata === query) {
    return 0;
  }
  if (icao === query || ident === query) {
    return 2;
  }
  if (iata.startsWith(query) || icao.startsWith(query) || ident.startsWith(query)) {
    return 10;
  }
  if (name.startsWith(query) || municipality.startsWith(query)) {
    return 20;
  }
  if (name.includes(query) || municipality.includes(query) || country.includes(query)) {
    return 40;
  }
  return -1;
}

function airportSearchSortKey(airport: AirportRecord): string {
  const scheduledRank = airport.scheduledService ? '0' : '1';
  const typeRank = airport.type === 'large_airport' ? '0' : airport.type === 'medium_airport' ? '1' : '2';
  return `${scheduledRank}-${typeRank}-${airport.iataCode ?? airport.icaoCode ?? airport.ident ?? ''}-${airport.name}`;
}

function toAirportRecord(airport: AirportIndexRecord): AirportRecord {
  return {
    id: airport.id,
    ident: airport.ident,
    name: airport.name,
    iataCode: airport.iataCode,
    icaoCode: airport.icaoCode,
    countryCode: airport.countryCode,
    latitude: airport.latitude,
    longitude: airport.longitude,
    municipality: airport.municipality,
    type: airport.type,
    scheduledService: airport.scheduledService,
    runwayCount: airport.runwayCount,
    longestRunwayFeet: airport.longestRunwayFeet
  };
}
