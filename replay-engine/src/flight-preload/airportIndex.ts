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

export function findAirportContextByIata(iataCode: string): AirportContextRecord | undefined {
  return contextsByIata.get(normalizeIata(iataCode));
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
