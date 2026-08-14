import { describe, expect, it } from 'vitest';
import { getPrimaryFlightSegment } from '../data/types';
import { assertJourney } from '../data/validateJourney';
import routeShapeRuntimeRaw from '../../../shared/offline-packs/route-shapes/global.route-shapes.runtime.json?raw';
import {
  buildPreloadedFlightJourney,
  buildPreloadedFlightJourneyWithRouteShapes
} from '../flight-preload/buildPreloadedFlightJourney';
import { findAirportContextByIata, getAirportIndexSummary } from '../flight-preload/airportIndex';
import { injectRouteShapePackForTest } from '../flight-preload/routeShapeIndex';
import { getRouteTimeBounds, sampleReplayAt } from '../replay/buildReplayFrames';

const routeShapeRuntime = JSON.parse(routeShapeRuntimeRaw) as unknown;

describe('flight preload', () => {
  it('resolves a known flight number through the offline schedule index', () => {
    const result = buildPreloadedFlightJourney({
      flightNumber: 'CI100',
      departureDate: '2026-07-11',
      departureTime: '09:30'
    });

    assertJourney(result.journey);
    const segment = getPrimaryFlightSegment(result.journey);

    expect(result.source).toBe('offline-schedule-index');
    expect(result.journey.title).toBe('CI100 TPE to NRT');
    expect(segment.origin.iataCode).toBe('TPE');
    expect(segment.destination.iataCode).toBe('NRT');
    expect(segment.statistics?.durationSeconds).toBe(185 * 60);
    expect(segment.metadata.aircraftType).toBe('744');
    expect(segment.metadata.aircraftTypeSource).toBe('openflights-route-graph');
    expect(segment.metadata.routeMethod).toBe('great_circle_fallback');
    expect(segment.metadata.routeSource).toBe('great-circle');
    expect(segment.metadata.airgraphWaypoints).toBeUndefined();
    expect(result.warnings[0]).toContain('CI100 已由離線班表解析為 TPE -> NRT');
  });

  it('uses known schedule defaults when the form only has a flight number and date', () => {
    const result = buildPreloadedFlightJourney({
      flightNumber: 'BR190',
      departureDate: '2026-07-11',
      departureTime: ''
    });
    const segment = getPrimaryFlightSegment(result.journey);

    expect(segment.origin.iataCode).toBe('TPE');
    expect(segment.destination.iataCode).toBe('HND');
    expect(segment.startTime).toBe(new Date('2026-07-11T09:30').toISOString());
    expect(segment.statistics?.durationSeconds).toBe(190 * 60);
    expect(segment.metadata.aircraftType).toBe('333');
    expect(segment.metadata.aircraftTypeSource).toBe('openflights-route-graph');
  });

  it('resolves FD235 without replacing the selected departure time', () => {
    const result = buildPreloadedFlightJourney({
      flightNumber: 'FD235',
      departureDate: '2026-07-11',
      departureTime: '10:15'
    });
    const segment = getPrimaryFlightSegment(result.journey);

    expect(result.source).toBe('offline-schedule-index');
    expect(segment.origin.iataCode).toBe('NRT');
    expect(segment.destination.iataCode).toBe('KHH');
    expect(segment.startTime).toBe(new Date('2026-07-11T10:15').toISOString());
    expect(segment.statistics?.durationSeconds).toBe(235 * 60);
    expect(segment.metadata.aircraftType).toBe('321');
    expect(segment.metadata.aircraftTypeSource).toBe('openflights-route-graph');
  });

  it('uses the route-shapes pack before airgraph fallback for KHH to NRT', async () => {
    injectRouteShapePackForTest(routeShapeRuntime as unknown as Parameters<typeof injectRouteShapePackForTest>[0]);
    const result = await buildPreloadedFlightJourneyWithRouteShapes({
      flightNumber: 'FD234',
      originIata: 'KHH',
      destinationIata: 'NRT',
      departureDate: '2026-07-22',
      departureTime: '07:05'
    });
    const segment = getPrimaryFlightSegment(result.journey);

    expect(segment.metadata.routeMethod).toBe('directed_airway_graph');
    expect(segment.metadata.routeSource).toBe('aviationdb-route-shapes');
    expect(segment.metadata.airgraphWaypoints).toEqual([
      'PARPA',
      'HCN',
      'BONEY',
      'MEVIN',
      'ELMAS',
      'BISIG',
      'SAKON',
      'TIC',
      'TAMAK',
      'SHIBK',
      'NIKAI',
      'JERID',
      'MISAK',
      'MJE',
      'BAFFY',
      'ORGAN',
      'PANDA'
    ]);
    expect(segment.derivedReplayRoute.points.map((point) => point.id)).toContain('airgraph-2-parpa');
    expect(result.warnings[0]).toContain('AviationDB route-shapes');
    injectRouteShapePackForTest(undefined);
  });

  it('replays an observed ADS-B route shape instead of falling back to great circle', async () => {
    injectRouteShapePackForTest({
      routes: {
        'TPE-NRT': {
          m: 'observed_adsb_mapped',
          d: 2_100_000,
          p: [
            ['TPE', 25.0777, 121.2328, 'AIRPORT'],
            ['OBS001', 25.8, 123.0, 'OBSERVED_ADSB'],
            ['OBS002', 30.0, 132.0, 'OBSERVED_ADSB'],
            ['NRT', 35.7686, 140.3887, 'AIRPORT']
          ],
          w: ['Observed ADS-B route']
        }
      }
    });
    try {
      const result = await buildPreloadedFlightJourneyWithRouteShapes({
        flightNumber: 'OBS1',
        originIata: 'TPE',
        destinationIata: 'NRT',
        departureDate: '2026-07-22',
        departureTime: '07:05'
      });
      const segment = getPrimaryFlightSegment(result.journey);

      expect(segment.metadata.routeMethod).toBe('observed_adsb_mapped');
      expect(segment.derivedReplayRoute.points.map((point) => point.id)).toContain('airgraph-2-obs001');
      expect(segment.derivedReplayRoute.points.some((point) => point.longitude > 130)).toBe(true);
      expect(result.warnings[0]).toContain('ADS-B 觀測航跡');
    } finally {
      injectRouteShapePackForTest(undefined);
    }
  });

  it('uses a directed route-shapes pack for TPE to HKG instead of runtime airgraph guessing', async () => {
    injectRouteShapePackForTest(routeShapeRuntime as unknown as Parameters<typeof injectRouteShapePackForTest>[0]);
    const result = await buildPreloadedFlightJourneyWithRouteShapes({
      flightNumber: 'CX451',
      originIata: 'TPE',
      destinationIata: 'HKG',
      departureDate: '2026-07-28',
      departureTime: '20:00'
    });
    const segment = getPrimaryFlightSegment(result.journey);

    expect(segment.metadata.routeMethod).toBe('directed_airway_graph');
    expect(segment.metadata.routeSource).toBe('aviationdb-route-shapes');
    expect(segment.metadata.airgraphWaypoints).toEqual([
      'HLG',
      'SWORD',
      'MKG',
      'KADLO',
      'ELATO',
      'MAGOG',
      'CH',
      'TAMOT',
      'NLG'
    ]);
    expect(segment.derivedReplayRoute.points.every((point) => point.longitude < 121.5)).toBe(true);
    injectRouteShapePackForTest(undefined);
  });

  it('uses the validated PARPA arrival connector for NRT to KHH', async () => {
    injectRouteShapePackForTest(routeShapeRuntime as unknown as Parameters<typeof injectRouteShapePackForTest>[0]);
    try {
      const result = await buildPreloadedFlightJourneyWithRouteShapes({
        flightNumber: 'FD235',
        originIata: 'NRT',
        destinationIata: 'KHH',
        departureDate: '2026-07-22',
        departureTime: '07:05'
      });
      const segment = getPrimaryFlightSegment(result.journey);
      const waypoints = segment.metadata.airgraphWaypoints as string[] | undefined;

      expect(segment.metadata.routeMethod).toBe('directed_airway_graph');
      expect(waypoints?.[0]).toBe('PANDA');
      expect(waypoints?.at(-1)).toBe('PARPA');
      expect(segment.derivedReplayRoute.points.at(-2)?.id).toBe('airgraph-18-parpa');
    } finally {
      injectRouteShapePackForTest(undefined);
    }
  });

  it('annotates a reverse geometry fallback when directed validation is unavailable', async () => {
    injectRouteShapePackForTest(routeShapeRuntime as unknown as Parameters<typeof injectRouteShapePackForTest>[0]);
    try {
      const result = await buildPreloadedFlightJourneyWithRouteShapes({
        flightNumber: 'FD234',
        originIata: 'BGW',
        destinationIata: 'AUH',
        departureDate: '2026-07-22',
        departureTime: '07:05'
      });
      const segment = getPrimaryFlightSegment(result.journey);

      expect(segment.metadata.routeMethod).toBe('reverse_route_fallback');
      expect(segment.derivedReplayRoute.points).toHaveLength(27);
      expect(segment.derivedReplayRoute.points.map((point) => point.id)).toContain('airgraph-2-pusto');
      expect(result.warnings[0]).toContain('反向 airway 未驗證');
      expect(result.warnings[0]).toContain('Not IFR-validated');
    } finally {
      injectRouteShapePackForTest(undefined);
    }
  });

  it('builds a valid planned journey from flight form input', () => {
    const result = buildPreloadedFlightJourney({
      flightNumber: 'XX901',
      originIata: 'TPE',
      destinationIata: 'HND',
      departureDate: '2026-07-11',
      departureTime: '09:30',
      durationMinutes: 190
    });

    assertJourney(result.journey);
    const segment = getPrimaryFlightSegment(result.journey);
    const bounds = getRouteTimeBounds(segment);
    const end = sampleReplayAt(segment, bounds.durationSeconds);

    expect(result.source).toBe('offline-airport-index');
    expect(result.journey.title).toBe('XX901 TPE to HND');
    expect(segment.origin.iataCode).toBe('TPE');
    expect(segment.destination.iataCode).toBe('HND');
    expect(segment.derivedReplayRoute.points).toHaveLength(7);
    expect(result.journey.events.map((event) => event.type)).toEqual([
      'flightTakeoff',
      'flightCruise',
      'flightTopOfDescent',
      'flightLanding'
    ]);
    expect(end.point.latitude).toBeCloseTo(segment.destination.latitude, 3);
    expect(end.point.longitude).toBeCloseTo(segment.destination.longitude, 3);
  });

  it('rejects unknown airport codes before entering replay', () => {
    expect(() =>
      buildPreloadedFlightJourney({
        flightNumber: 'XX1',
        originIata: 'ZZZ',
        destinationIata: 'HND',
        departureDate: '2026-07-11',
        departureTime: '09:30'
      })
    ).toThrow('ZZZ');
  });

  it('loads aviation context from transformed OurAirports frequency and navaid data', () => {
    const summary = getAirportIndexSummary();
    const tpeContext = findAirportContextByIata('TPE');

    expect(summary.airports).toBeGreaterThan(4_000);
    expect(summary.airportContexts).toBeGreaterThan(1_000);
    expect(summary.navaids).toBeGreaterThan(5_000);
    expect(tpeContext?.frequencies.length).toBeGreaterThan(0);
    expect(tpeContext?.frequencies.some((frequency) => frequency.type.length > 0)).toBe(true);
  });
});
