import type { Journey, JourneySegment, LocationPoint, PlaceReference, TimelineEvent } from '../data/types';
import {
  haversineDistanceMeters,
  initialBearingDegrees,
  interpolateGreatCircle
} from '../geo/geodesy';
import { findAirportByIata, normalizeIata, type AirportRecord } from './airportIndex';
import { findScheduleByFlightNumber, normalizeFlightNumber, normalizeOptionalIata } from './flightScheduleIndex';

export interface PreloadFlightRequest {
  flightNumber: string;
  originIata?: string;
  destinationIata?: string;
  departureDate: string;
  departureTime: string;
  durationMinutes?: number;
  aircraftType?: string;
}

export interface PreloadFlightResult {
  journey: Journey;
  source: 'offline-airport-index' | 'offline-schedule-index';
  warnings: string[];
}

const replayFractions = [0, 0.08, 0.24, 0.5, 0.76, 0.92, 1];
const processedFractions = [0, 0.25, 0.5, 0.75, 1];
const rawFractions = [0, 0.12, 0.5, 0.88, 1];

export function buildPreloadedFlightJourney(request: PreloadFlightRequest): PreloadFlightResult {
  const flightNumber = normalizeFlightNumber(request.flightNumber);
  if (!flightNumber) {
    throw new Error('請輸入航班號');
  }

  const schedule = findScheduleByFlightNumber(flightNumber);
  const originIata = normalizeOptionalIata(request.originIata) ?? schedule?.originIata;
  const destinationIata = normalizeOptionalIata(request.destinationIata) ?? schedule?.destinationIata;
  if (!originIata || !destinationIata) {
    throw new Error(`${flightNumber} 尚未有起飛/抵達機場資料，請手動輸入 IATA`);
  }

  const origin = findAirportByIata(originIata);
  const destination = findAirportByIata(destinationIata);
  if (!origin || !destination) {
    const missing = [origin ? '' : normalizeIata(originIata), destination ? '' : normalizeIata(destinationIata)]
      .filter(Boolean)
      .join(', ');
    throw new Error(`機場索引找不到 ${missing}`);
  }
  if (origin.iataCode === destination.iataCode) {
    throw new Error('起飛與抵達機場不可相同');
  }

  const startMs = parseDepartureTime(request.departureDate, request.departureTime);
  const distanceMeters = haversineDistanceMeters(origin, destination);
  const durationMinutes = request.durationMinutes ?? schedule?.defaultDurationMinutes ?? estimateDurationMinutes(distanceMeters);
  const durationSeconds = Math.max(30 * 60, Math.round(durationMinutes * 60));
  const endMs = startMs + durationSeconds * 1000;
  const journeyId = `journey-${flightNumber.toLowerCase()}-${origin.iataCode?.toLowerCase()}-${destination.iataCode?.toLowerCase()}-${request.departureDate}`;
  const segmentId = `segment-${flightNumber.toLowerCase()}-${request.departureDate}`;
  const preloadSource: PreloadFlightResult['source'] = schedule ? 'offline-schedule-index' : 'offline-airport-index';

  const derivedReplayRoute = {
    kind: 'derivedReplay' as const,
    points: replayFractions.map((fraction, index) =>
      routePoint({
        id: `replay-${index + 1}`,
        journeyId,
        segmentId,
        origin,
        destination,
        startMs,
        durationSeconds,
        fraction,
        source: index === 0 || index === replayFractions.length - 1 ? 'planned' : 'interpolated'
      })
    )
  };
  const processedRoute = {
    kind: 'processed' as const,
    points: processedFractions.map((fraction, index) =>
      routePoint({
        id: `processed-${index + 1}`,
        journeyId,
        segmentId,
        origin,
        destination,
        startMs,
        durationSeconds,
        fraction,
        source: 'planned'
      })
    )
  };
  const rawRoute = {
    kind: 'raw' as const,
    points: rawFractions.map((fraction, index) =>
      routePoint({
        id: `raw-${index + 1}`,
        journeyId,
        segmentId,
        origin,
        destination,
        startMs,
        durationSeconds,
        fraction,
        source: 'planned'
      })
    )
  };

  const events = createEvents({
    journeyId,
    segmentId,
    origin,
    destination,
    startMs,
    durationSeconds,
    flightNumber
  });

  const segment: JourneySegment = {
    id: segmentId,
    journeyId,
    type: 'flight',
    startTime: new Date(startMs).toISOString(),
    endTime: new Date(endMs).toISOString(),
    origin,
    destination,
    rawRoute,
    processedRoute,
    derivedReplayRoute,
    events: events.map((event) => event.id),
    statistics: {
      distanceMeters,
      durationSeconds,
      maxAltitudeMeters: cruiseAltitudeMeters(distanceMeters),
      maxSpeedMetersPerSecond: cruiseSpeedMetersPerSecond(distanceMeters)
    },
    metadata: {
      flightNumber,
      aircraftType: request.aircraftType?.trim() || 'Planned flight',
      preloadSource
    }
  };

  return {
    source: preloadSource,
    warnings: [buildPreloadWarning(flightNumber, origin, destination, Boolean(schedule))],
    journey: {
      schemaVersion: '1.0.0',
      appVersion: '0.1.0',
      id: journeyId,
      title: `${flightNumber} ${origin.iataCode} to ${destination.iataCode}`,
      subtitle: `${origin.municipality} to ${destination.municipality} planned preload`,
      startTime: segment.startTime,
      endTime: segment.endTime,
      status: 'planned',
      plans: [],
      segments: [segment],
      events,
      media: [],
      journal: [],
      statistics: {
        distanceMeters,
        durationSeconds,
        countriesVisited: [...new Set([origin.countryCode, destination.countryCode].filter(Boolean))],
        transportModes: ['flight']
      },
      settings: {
        preferredTheme: 'travel-atlas',
        defaultCameraMode: 'global'
      },
      metadata: {
        createdFor: 'Flight preload',
        preloadSource
      }
    }
  };
}

function buildPreloadWarning(
  flightNumber: string,
  origin: AirportRecord,
  destination: AirportRecord,
  usedSchedule: boolean
): string {
  const routeLabel = `${origin.iataCode} -> ${destination.iataCode}`;
  if (usedSchedule) {
    return `${flightNumber} 已由離線班表解析為 ${routeLabel}。目前使用 Great Circle 離線預估航線；實際 filed route 與航跡會等飛行中 GPS 或未來 API 校正。`;
  }
  return `目前使用 Great Circle 離線預估航線 ${routeLabel}；實際 filed route 與航跡會等飛行中 GPS 或未來 API 校正。`;
}

function routePoint(input: {
  id: string;
  journeyId: string;
  segmentId: string;
  origin: AirportRecord;
  destination: AirportRecord;
  startMs: number;
  durationSeconds: number;
  fraction: number;
  source: LocationPoint['source'];
}): LocationPoint {
  const point = interpolateGreatCircle(input.origin, input.destination, input.fraction);
  const next = interpolateGreatCircle(input.origin, input.destination, Math.min(1, input.fraction + 0.01));
  return {
    id: input.id,
    journeyId: input.journeyId,
    segmentId: input.segmentId,
    timestamp: new Date(input.startMs + input.durationSeconds * input.fraction * 1000).toISOString(),
    latitude: point.latitude,
    longitude: point.longitude,
    altitudeMeters: altitudeMetersAt(input.fraction, haversineDistanceMeters(input.origin, input.destination)),
    speedMetersPerSecond: speedMetersPerSecondAt(input.fraction, haversineDistanceMeters(input.origin, input.destination)),
    courseDegrees: initialBearingDegrees(point, next),
    source: input.source
  };
}

function createEvents(input: {
  journeyId: string;
  segmentId: string;
  origin: PlaceReference;
  destination: PlaceReference;
  startMs: number;
  durationSeconds: number;
  flightNumber: string;
}): TimelineEvent[] {
  const eventSpecs = [
    { id: 'departure', fraction: 0.05, type: 'flightTakeoff', title: `Departed ${input.origin.iataCode}` },
    { id: 'cruise', fraction: 0.5, type: 'flightCruise', title: `${input.flightNumber} cruise` },
    { id: 'descent', fraction: 0.86, type: 'flightTopOfDescent', title: `Descending toward ${input.destination.iataCode}` },
    { id: 'arrival', fraction: 1, type: 'flightLanding', title: `Arrived at ${input.destination.iataCode}` }
  ];

  return eventSpecs.map((spec) => {
    const location =
      spec.fraction === 1
        ? input.destination
        : interpolateGreatCircle(input.origin, input.destination, spec.fraction);
    return {
      id: `event-${input.segmentId}-${spec.id}`,
      journeyId: input.journeyId,
      segmentId: input.segmentId,
      timestamp: new Date(input.startMs + input.durationSeconds * spec.fraction * 1000).toISOString(),
      type: spec.type,
      title: spec.title,
      subtitle: `${input.origin.iataCode} to ${input.destination.iataCode}`,
      location: {
        latitude: location.latitude,
        longitude: location.longitude,
        altitudeMeters: altitudeMetersAt(spec.fraction, haversineDistanceMeters(input.origin, input.destination))
      },
      mediaIds: [],
      importance: spec.id === 'departure' || spec.id === 'arrival' ? 1 : 0.7,
      source: 'preload',
      metadata: {}
    };
  });
}

function parseDepartureTime(date: string, time: string): number {
  const normalizedDate = date.trim();
  const normalizedTime = time.trim() || '09:00';
  const parsed = new Date(`${normalizedDate}T${normalizedTime}`);
  if (Number.isNaN(parsed.getTime())) {
    throw new Error('出發日期或時間格式不正確');
  }
  return parsed.getTime();
}

function estimateDurationMinutes(distanceMeters: number): number {
  const airborneMinutes = (distanceMeters / 1000 / 810) * 60;
  return Math.round(Math.max(45, airborneMinutes + 28));
}

function altitudeMetersAt(fraction: number, distanceMeters: number): number {
  const cruiseAltitude = cruiseAltitudeMeters(distanceMeters);
  if (fraction <= 0.08) {
    return lerp(0, 3600, fraction / 0.08);
  }
  if (fraction <= 0.24) {
    return lerp(3600, cruiseAltitude, (fraction - 0.08) / 0.16);
  }
  if (fraction >= 0.86) {
    return lerp(cruiseAltitude, 0, (fraction - 0.86) / 0.14);
  }
  return cruiseAltitude;
}

function speedMetersPerSecondAt(fraction: number, distanceMeters: number): number {
  const cruiseSpeed = cruiseSpeedMetersPerSecond(distanceMeters);
  if (fraction <= 0.08) {
    return lerp(0, 145, fraction / 0.08);
  }
  if (fraction <= 0.24) {
    return lerp(145, cruiseSpeed, (fraction - 0.08) / 0.16);
  }
  if (fraction >= 0.86) {
    return lerp(cruiseSpeed, 0, (fraction - 0.86) / 0.14);
  }
  return cruiseSpeed;
}

function cruiseAltitudeMeters(distanceMeters: number): number {
  if (distanceMeters < 900_000) {
    return 8800;
  }
  if (distanceMeters < 2_500_000) {
    return 10_700;
  }
  return 11_600;
}

function cruiseSpeedMetersPerSecond(distanceMeters: number): number {
  return distanceMeters < 900_000 ? 210 : 245;
}

function lerp(start: number, end: number, fraction: number): number {
  return start + (end - start) * Math.min(1, Math.max(0, fraction));
}
