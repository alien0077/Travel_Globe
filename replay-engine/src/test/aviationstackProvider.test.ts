import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  AviationstackFlightPreloadProvider,
  writeAviationstackApiKey
} from '../flight-preload/aviationstackProvider';

describe('aviationstack flight candidates', () => {
  beforeEach(() => {
    installMemoryLocalStorage();
    writeAviationstackApiKey('test-key');
    vi.restoreAllMocks();
  });

  it('keeps both legs when one flight number has multiple records', async () => {
    const requestedURLs: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      requestedURLs.push(String(input));
      return {
        ok: true,
        json: async () => ({
          data: [
            {
              flight_date: '2026-07-22',
              flight: { iata: 'XY987' },
              departure: { iata: 'DMK', scheduled: '2026-07-22T02:35:00+00:00' },
              arrival: { iata: 'KHH', scheduled: '2026-07-22T07:05:00+00:00' }
            },
            {
              flight_date: '2026-07-22',
              flight: { iata: 'XY987' },
              departure: { iata: 'KHH', scheduled: '2026-07-22T08:05:00+00:00' },
              arrival: { iata: 'NRT', scheduled: '2026-07-22T12:55:00+00:00' }
            }
          ]
        })
      } as Response;
    }));

    const provider = new AviationstackFlightPreloadProvider();
    const candidates = await provider.lookupFlightCandidates({
      flightNumber: 'XY987',
      departureDate: '2026-08-20',
      departureTime: ''
    });

    expect(candidates.map((candidate) => `${candidate.originIata}-${candidate.destinationIata}`)).toEqual([
      'DMK-KHH',
      'KHH-NRT'
    ]);
    expect(requestedURLs[0]).toContain('flight_iata=XY987');
    expect(requestedURLs[0]).not.toContain('flight_date=');
    expect(provider.getCachedFlights('XY987')).toHaveLength(2);
  });
});

function installMemoryLocalStorage(): void {
  const storage = new Map<string, string>();
  Object.defineProperty(globalThis, 'localStorage', {
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear()
    },
    configurable: true
  });
}
