import { describe, expect, it } from 'vitest';
import { getPrimaryFlightSegment } from '../data/types';
import { assertJourney } from '../data/validateJourney';
import { buildPreloadedFlightJourney } from '../flight-preload/buildPreloadedFlightJourney';
import { findAirportContextByIata, getAirportIndexSummary } from '../flight-preload/airportIndex';
import { getRouteTimeBounds, sampleReplayAt } from '../replay/buildReplayFrames';

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
    expect(result.warnings[0]).toContain('CI100 已由離線班表解析為 TPE -> NRT');
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

    expect(summary.airports).toBeGreaterThan(7_000);
    expect(summary.airportContexts).toBeGreaterThan(1_000);
    expect(summary.navaids).toBeGreaterThan(5_000);
    expect(tpeContext?.frequencies.length).toBeGreaterThan(0);
    expect(tpeContext?.frequencies.some((frequency) => frequency.type.length > 0)).toBe(true);
  });
});
