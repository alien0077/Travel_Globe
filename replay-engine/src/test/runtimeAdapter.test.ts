import { beforeEach, describe, expect, it } from 'vitest';
import { BrowserRuntimeAdapter } from '../bridge/RuntimeAdapter';
import { sampleJourney } from '../data/sampleJourney';
import type { Journey } from '../data/types';
import { buildPreloadedFlightJourney } from '../flight-preload/buildPreloadedFlightJourney';
import routeShapeRuntimeRaw from '../../../shared/offline-packs/route-shapes/global.route-shapes.runtime.json?raw';
import { injectRouteShapePackForTest } from '../flight-preload/routeShapeIndex';

const routeShapeRuntime = JSON.parse(routeShapeRuntimeRaw) as unknown;

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
      expect(segment?.derivedReplayRoute.points.map((point) => point.id)).toContain('airgraph-2-parpa');
      expect(segment?.derivedReplayRoute.points.some((point) => point.id.includes('wagon'))).toBe(false);
    } finally {
      injectRouteShapePackForTest(undefined);
    }
  });

  it('refreshes a completed simulated preload but preserves recorded GPS journeys', async () => {
    injectRouteShapePackForTest(routeShapeRuntime as unknown as Parameters<typeof injectRouteShapePackForTest>[0]);
    try {
      const stale = buildPreloadedFlightJourney({
        flightNumber: 'FD234',
        originIata: 'KHH',
        destinationIata: 'NRT',
        departureDate: '2026-07-22',
        departureTime: '07:05'
      }).journey;
      const staleSegment = stale.segments[0];
      if (!staleSegment) throw new Error('expected preload segment');
      const oldRoutePoint = { ...staleSegment.derivedReplayRoute.points[1], longitude: 121.773889, latitude: 23.588056 };
      const completedSimulated: Journey = {
        ...stale,
        status: 'completed',
        segments: [{
          ...staleSegment,
          metadata: { ...staleSegment.metadata, routeMethod: 'great_circle_waypoint_corridor', routeSource: 'legacy-route-pack' },
          rawRoute: { ...staleSegment.rawRoute, points: [staleSegment.rawRoute.points[0], oldRoutePoint, ...staleSegment.rawRoute.points.slice(2)] },
          processedRoute: { ...staleSegment.processedRoute, points: [staleSegment.processedRoute.points[0], oldRoutePoint, ...staleSegment.processedRoute.points.slice(2)] },
          derivedReplayRoute: { ...staleSegment.derivedReplayRoute, points: [staleSegment.derivedReplayRoute.points[0], oldRoutePoint, ...staleSegment.derivedReplayRoute.points.slice(2)] }
        }]
      };
      const adapter = new BrowserRuntimeAdapter(completedSimulated);
      await adapter.saveJourney(completedSimulated);
      const refreshed = await adapter.loadJourney();
      expect(refreshed.segments[0]?.metadata.routeRefresh).toBe('latest-offline-route-shape-pack');
      expect(refreshed.segments[0]?.derivedReplayRoute.points.map((point) => point.id)).toContain('airgraph-2-parpa');

      const recorded = {
        ...completedSimulated,
        metadata: { ...completedSimulated.metadata, recordingStatus: 'completed' },
        segments: [{
          ...completedSimulated.segments[0],
          metadata: { ...completedSimulated.segments[0].metadata, recordingSource: 'ios-core-location' },
          rawRoute: { ...completedSimulated.segments[0].rawRoute, points: completedSimulated.segments[0].rawRoute.points.map((point) => ({ ...point, source: 'gps' as const })) }
        }]
      };
      const recordedAdapter = new BrowserRuntimeAdapter(recorded);
      await recordedAdapter.saveJourney(recorded);
      const preserved = await recordedAdapter.loadJourney();
      expect(preserved.segments[0]?.metadata.routeRefresh).toBeUndefined();
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
