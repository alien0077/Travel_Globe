import { buildPreloadedFlightJourney, type PreloadFlightRequest, type PreloadFlightResult } from './buildPreloadedFlightJourney';
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
  async preloadFlight(request: PreloadFlightRequest): Promise<PreloadFlightResult> {
    const flightNumber = normalizeFlightNumber(request.flightNumber);
    const apiKey = readAviationstackApiKey();
    if (!flightNumber || !apiKey) {
      return buildFromCachedOrOffline(request, flightNumber);
    }

    try {
      const record = await fetchAviationstackFlight(apiKey, flightNumber);
      if (record) {
        writeCachedFlight(record);
        return buildPreloadedFlightJourney({
          ...request,
          ...record,
          source: 'aviationstack'
        });
      }
    } catch {
      // Network, quota, CORS, or provider errors all use the same local fallback path.
    }

    return buildFromCachedOrOffline(request, flightNumber);
  }

  getCachedFlight(flightNumber: string): CachedFlightRecord | undefined {
    return readCachedFlight(normalizeFlightNumber(flightNumber));
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
  const cache = readFlightCache();
  return cache[normalizeFlightNumber(flightNumber)];
}

function buildFromCachedOrOffline(request: PreloadFlightRequest, flightNumber: string): PreloadFlightResult {
  const cached = readCachedFlight(flightNumber);
  const manualOrigin = normalizeOptionalIata(request.originIata);
  const manualDestination = normalizeOptionalIata(request.destinationIata);
  if (cached && (!manualOrigin || !manualDestination)) {
    return buildPreloadedFlightJourney({
      ...request,
      ...cached,
      source: 'aviationstack-cache'
    });
  }
  return buildPreloadedFlightJourney(request);
}

async function fetchAviationstackFlight(apiKey: string, flightNumber: string): Promise<CachedFlightRecord | undefined> {
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
  const flight = payload.data?.find((candidate) => normalizeFlightNumber(candidate.flight?.iata ?? '') === flightNumber)
    ?? payload.data?.[0];
  return flight ? toCachedFlightRecord(flightNumber, flight) : undefined;
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
    lastSeenFlightDate: flight.flight_date
  };
}

function readFlightCache(): Record<string, CachedFlightRecord> {
  const raw = localStorage.getItem(CACHE_STORAGE_KEY);
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(raw) as Record<string, CachedFlightRecord>;
  } catch {
    return {};
  }
}

function writeCachedFlight(record: CachedFlightRecord): void {
  const cache = readFlightCache();
  cache[record.flightNumber] = record;
  localStorage.setItem(CACHE_STORAGE_KEY, JSON.stringify(cache));
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
