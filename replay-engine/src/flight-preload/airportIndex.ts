import airportsIndex from '../../../shared/offline-packs/core-global/airports-index.json';
import type { PlaceReference } from '../data/types';

export interface AirportRecord extends PlaceReference {
  municipality: string;
  icaoCode?: string;
  type: string;
  scheduledService: boolean;
  runwayCount: number;
  longestRunwayFeet?: number;
}

interface AirportIndexRecord {
  id: string;
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
const airportsByIata = new Map(airports.map((airport) => [airport.iataCode, airport]));

export function findAirportByIata(iataCode: string): AirportRecord | undefined {
  return airportsByIata.get(normalizeIata(iataCode));
}

export function listAirportSuggestions(): AirportRecord[] {
  return airports.filter((airport) => airport.scheduledService);
}

export function normalizeIata(value: string): string {
  return value.trim().toUpperCase();
}

function toAirportRecord(airport: AirportIndexRecord): AirportRecord {
  return {
    id: airport.id,
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
