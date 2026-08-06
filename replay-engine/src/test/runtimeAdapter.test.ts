import { beforeEach, describe, expect, it } from 'vitest';
import { BrowserRuntimeAdapter } from '../bridge/RuntimeAdapter';
import { sampleJourney } from '../data/sampleJourney';
import type { Journey } from '../data/types';
import { buildPreloadedFlightJourney } from '../flight-preload/buildPreloadedFlightJourney';
import routeShapeRuntime from '../../../shared/offline-packs/route-shapes/global.route-shapes.runtime.json';
import { injectRouteShapePackForTest } from '../flight-preload/routeShapeIndex';

describe('browser runtime adapter journey history', () => {
  beforeEach(() => {
    installMemoryLocalStorage();
  });

  it('lists, loads, and deletes locally saved journeys', async () => {
    const adapter = new BrowserRuntimeAdapter(sampleJourney);
    const olderJourney: Journey = {
      ...sampleJourney,
      id: 'older-journey',
      title: 'Older Journey',
      startTime: '2025-01-01T00:00:00Z'
    };

    await adapter.saveJourney(olderJourney);
    await adapter.saveJourney(sampleJourney);

    const saved = await adapter.listSavedJourneys();
    expect(saved.map((summary) => summary.id)).toEqual([sampleJourney.id, olderJourney.id]);

    const loaded = await adapter.loadJourneyById(olderJourney.id);
    expect(loaded?.title).toBe('Older Journey');

    await adapter.deleteJourney(olderJourney.id);
    expect((await adapter.listSavedJourneys()).map((summary) => summary.id)).toEqual([sampleJourney.id]);
  });

  it('refreshes a stale planned route from the latest offline route-shape pack', async () => {
    injectRouteShapePackForTest(routeShapeRuntime as unknown as Parameters<typeof injectRouteShapePackForTest>[0]);
    try {
      const stale = buildPreloadedFlightJourney({
        flightNumber: 'FD234',
        originIata: 'KHH',
        destinationIata: 'NRT',
        departureDate: '2026-07-22',
        departureTime: '07:05'
      }).journey;
      const adapter = new BrowserRuntimeAdapter(stale);

      await adapter.saveJourney(stale);
      const refreshed = await adapter.loadJourney();
      const segment = refreshed.segments[0];

      expect(segment?.metadata.routeMethod).toBe('directed_airway_graph');
      expect(segment?.metadata.routeSource).toBe('aviationdb-route-shapes');
      expect(segment?.derivedReplayRoute.points.map((point) => point.id)).toContain('airgraph-2-hcn');
      expect(segment?.derivedReplayRoute.points.some((point) => point.id.includes('wagon'))).toBe(false);
    } finally {
      injectRouteShapePackForTest(undefined);
    }
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
