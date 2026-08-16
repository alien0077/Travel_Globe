import {
  buildPreloadedFlightJourneyWithRouteShapes,
  type PreloadFlightRequest,
  type PreloadFlightResult
} from './buildPreloadedFlightJourney';
import { normalizeFlightNumber, normalizeOptionalIata } from './flightScheduleIndex';

const API_KEY_STORAGE_KEY = 'travelglobe.aviationstack.apiKey';
const CACHE_STORAGE_KEY = 'travelglobe.aviationstack.flightCache.v1';
const ENDPOINT = 'https://api.aviationstack.com/v1/flights';

export interface CachedFlightRecord {
  flightNumber: string;
  originIata: string;
  destinationIata: string;
  airlineName?: string;
  aircraftType?: string;
  departureTime?: string;
  durationMinutes?: number;
  source: 'aviationstack';
  cachedAt: string;
  flightDate?: string;
  departureScheduled?: string;
  arrivalScheduled?: string;
  lastSeenFlightDate?: string;
}

interface AviationstackResponse {
  data?: AviationstackFlight[];
  error?: {
    code?: string;
    message?: string;
  };
}

interface AviationstackFlight {
  flight_date?: string;
  airline?: {
    name?: string;
  };
  flight?: {
    iata?: string;
    icao?: string;
    number?: string;
  };
  departure?: {
    iata?: string;
    scheduled?: string;
  };
  arrival?: {
    iata?: string;
    scheduled?: string;
  };
  aircraft?: {
    iata?: string;
    icao?: string;
    registration?: string;
  };
}

export class AviationstackFlightPreloadProvider {
  async lookupFlightCandidates(request: PreloadFlightRequest): Promise<CachedFlightRecord[]> {
    const flightNumber = normalizeFlightNumber(request.flightNumber);
    const apiKey = readAviationstackApiKey();
    if (!flightNumber) {
      return [];
    }

    if (apiKey) {
      try {
        const records = await fetchAviationstackFlights(apiKey, flightNumber);
        if (records.length > 0) {
          records.forEach(writeCachedFlight);
          const matchingRecords = records.filter((record) => matchesFlightDate(record, request.departureDate));
          return deduplicateFlightRecords(matchingRecords.length > 0 ? matchingRecords : records);
        }
      } catch {
        // Network, quota, CORS, or provider errors all use the local cache path.
      }
    }

    const cachedRecords = readCachedFlights(flightNumber);
    const matchingCachedRecords = cachedRecords.filter((record) => matchesFlightDate(record, request.departureDate));
    return matchingCachedRecords.length > 0 ? matchingCachedRecords : cachedRecords;
  }

  async preloadFlight(request: PreloadFlightRequest, selectedRecord?: CachedFlightRecord): Promise<PreloadFlightResult> {
    const flightNumber = normalizeFlightNumber(request.flightNumber);
    const record = selectedRecord ?? (await this.lookupFlightCandidates(request))[0];
    if (record) {
      writeCachedFlight(record);
      return await buildPreloadedFlightJourneyWithRouteShapes({
        ...request,
        ...record,
        source: selectedRecord ? 'aviationstack' : 'aviationstack-cache'
      });
    }

    return buildFromCachedOrOffline(request, flightNumber);
  }

  getCachedFlight(flightNumber: string): CachedFlightRecord | undefined {
    return this.getCachedFlights(flightNumber)[0];
  }

  getCachedFlights(flightNumber: string): CachedFlightRecord[] {
    return readCachedFlights(normalizeFlightNumber(flightNumber));
  }
}

export function readAviationstackApiKey(): string {
  return localStorage.getItem(API_KEY_STORAGE_KEY)?.trim() ?? '';
}

export function writeAviationstackApiKey(value: string): void {
  const normalized = value.trim();
  if (normalized) {
    localStorage.setItem(API_KEY_STORAGE_KEY, normalized);
  } else {
    localStorage.removeItem(API_KEY_STORAGE_KEY);
  }
}

export function readCachedFlight(flightNumber: string): CachedFlightRecord | undefined {
  return readCachedFlights(flightNumber)[0];
}

async function buildFromCachedOrOffline(request: PreloadFlightRequest, flightNumber: string): Promise<PreloadFlightResult> {
  const cached = readCachedFlights(flightNumber).find((record) => matchesFlightDate(record, request.departureDate));
  const manualOrigin = normalizeOptionalIata(request.originIata);
  const manualDestination = normalizeOptionalIata(request.destinationIata);
  if (cached && (!manualOrigin || !manualDestination)) {
    return await buildPreloadedFlightJourneyWithRouteShapes({
      ...request,
      ...cached,
      source: 'aviationstack-cache'
    });
  }
  return await buildPreloadedFlightJourneyWithRouteShapes(request);
}

async function fetchAviationstackFlights(apiKey: string, flightNumber: string): Promise<CachedFlightRecord[]> {
  const url = new URL(ENDPOINT);
  url.searchParams.set('access_key', apiKey);
  url.searchParams.set('flight_iata', flightNumber);
  url.searchParams.set('limit', '10');

  const response = await fetch(url.href);
  if (!response.ok) {
    throw new Error(`aviationstack HTTP ${response.status}`);
  }
  const payload = (await response.json()) as AviationstackResponse;
  if (payload.error) {
    throw new Error(payload.error.message || payload.error.code || 'aviationstack error');
  }
  return (payload.data ?? [])
    .filter((candidate) => normalizeFlightNumber(candidate.flight?.iata ?? '') === flightNumber)
    .map((flight) => toCachedFlightRecord(flightNumber, flight))
    .filter((record): record is CachedFlightRecord => Boolean(record));
}

function toCachedFlightRecord(flightNumber: string, flight: AviationstackFlight): CachedFlightRecord | undefined {
  const originIata = normalizeOptionalIata(flight.departure?.iata);
  const destinationIata = normalizeOptionalIata(flight.arrival?.iata);
  if (!originIata || !destinationIata) {
    return undefined;
  }
  const departureTime = timeFromIso(flight.departure?.scheduled);
  const durationMinutes = durationFromIso(flight.departure?.scheduled, flight.arrival?.scheduled);
  return {
    flightNumber,
    originIata,
    destinationIata,
    airlineName: flight.airline?.name,
    aircraftType: flight.aircraft?.iata || flight.aircraft?.icao,
    departureTime,
    durationMinutes,
    source: 'aviationstack',
    cachedAt: new Date().toISOString(),
    flightDate: flight.flight_date,
    departureScheduled: flight.departure?.scheduled,
    arrivalScheduled: flight.arrival?.scheduled,
    lastSeenFlightDate: flight.flight_date
  };
}

function readFlightCache(): Record<string, CachedFlightRecord> {
  const raw = localStorage.getItem(CACHE_STORAGE_KEY);
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(parsed).flatMap(([key, value]) => {
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
          return [];
        }
        const record = value as Partial<CachedFlightRecord>;
        if (typeof record.flightNumber !== 'string' || typeof record.originIata !== 'string' || typeof record.destinationIata !== 'string') {
          return [];
        }
        return [[key, record as CachedFlightRecord]];
      })
    );
  } catch {
    return {};
  }
}

function readCachedFlights(flightNumber: string): CachedFlightRecord[] {
  const normalized = normalizeFlightNumber(flightNumber);
  if (!normalized) {
    return [];
  }
  return deduplicateFlightRecords(
    Object.values(readFlightCache()).filter((record) => normalizeFlightNumber(record.flightNumber) === normalized)
  );
}

function writeCachedFlight(record: CachedFlightRecord): void {
  const cache = readFlightCache();
  cache[flightCacheKey(record)] = record;
  localStorage.setItem(CACHE_STORAGE_KEY, JSON.stringify(cache));
}

function flightCacheKey(record: CachedFlightRecord): string {
  return [
    normalizeFlightNumber(record.flightNumber),
    record.flightDate ?? record.lastSeenFlightDate ?? '',
    record.originIata,
    record.destinationIata,
    record.departureScheduled ?? record.departureTime ?? ''
  ].join('|');
}

function deduplicateFlightRecords(records: CachedFlightRecord[]): CachedFlightRecord[] {
  const seen = new Set<string>();
  return records.filter((record) => {
    const key = flightCacheKey(record);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function matchesFlightDate(record: CachedFlightRecord, departureDate: string): boolean {
  if (!departureDate || !record.flightDate) {
    return true;
  }
  return record.flightDate === departureDate;
}

function timeFromIso(value?: string): string | undefined {
  if (!value) {
    return undefined;
  }
  const match = value.match(/T(\d{2}:\d{2})/);
  return match?.[1];
}

function durationFromIso(start?: string, end?: string): number | undefined {
  if (!start || !end) {
    return undefined;
  }
  const startMs = Date.parse(start);
  const endMs = Date.parse(end);
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
    return undefined;
  }
  return Math.round((endMs - startMs) / 60000);
}
