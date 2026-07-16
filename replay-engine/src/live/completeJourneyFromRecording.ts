import type { Journey, LocationPoint, PlaceReference, TimelineEvent } from '../data/types';
import { getPrimaryFlightSegment } from '../data/types';
import { calculateRouteDistance } from '../replay/buildReplayFrames';
import {
  locationPointFromRecordingPayload,
  type NativeRecordingPayload
} from '../bridge/nativeBridge';
import { findAirportByIata } from '../flight-preload/airportIndex';

export function completeJourneyFromRecording(
  journey: Journey,
  payload: NativeRecordingPayload
): Journey {
  const segment = getPrimaryFlightSegment(journey);
  const points = recordingPoints(payload);
  const usableRoute = points.length >= 2 ? points : segment.derivedReplayRoute.points;
  const startTime = points[0]?.timestamp ?? payload.startedAt ?? segment.startTime;
  const endTime = points[points.length - 1]?.timestamp ?? payload.endedAt ?? segment.endTime;
  const completedSegment = {
    ...segment,
    startTime,
    endTime,
    rawRoute: {
      kind: 'raw' as const,
      points: usableRoute
    },
    processedRoute: {
      kind: 'processed' as const,
      points: usableRoute
    },
    derivedReplayRoute: {
      kind: 'derivedReplay' as const,
      points: usableRoute
    },
    metadata: {
      ...segment.metadata,
      nativeJourneyId: payload.nativeJourneyId,
      flightNumber: payload.flightNumber ?? segment.metadata.flightNumber,
      aircraftType: payload.aircraftType ?? segment.metadata.aircraftType,
      recordingSource: 'ios-core-location'
    },
    statistics: {
      ...segment.statistics,
      distanceMeters: calculateRouteDistance(usableRoute),
      gpsPointCount: points.length
    }
  };
  const recordingEvents = buildRecordingEvents(journey.id, completedSegment.id, payload, usableRoute);
  const existingEvents = journey.events.filter((event) => !recordingEvents.some((candidate) => candidate.id === event.id));

  return {
    ...journey,
    title: payload.flightNumber && payload.originIata && payload.destinationIata
      ? `${payload.flightNumber} ${payload.originIata} to ${payload.destinationIata}`
      : journey.title,
    startTime,
    endTime,
    status: 'completed',
    segments: journey.segments.map((candidate) => candidate.id === segment.id ? completedSegment : candidate),
    events: [...existingEvents, ...recordingEvents],
    statistics: {
      ...journey.statistics,
      distanceMeters: calculateRouteDistance(usableRoute),
      gpsPointCount: points.length
    },
    metadata: {
      ...journey.metadata,
      nativeJourneyId: payload.nativeJourneyId,
      recordingStatus: 'completed',
      recordingCompletedAt: new Date().toISOString()
    }
  };
}

export function createJourneyFromNativeRecording(payload: NativeRecordingPayload): Journey | undefined {
  const journeyId = payload.webJourneyId ?? `native-${payload.nativeJourneyId}`;
  const segmentId = payload.segmentId ?? `segment-${payload.nativeJourneyId}`;
  const normalizedPayload: NativeRecordingPayload = {
    ...payload,
    webJourneyId: journeyId,
    segmentId
  };
  const points = recordingPoints(normalizedPayload);
  const replayablePoints = makeReplayableRecordingPoints(normalizedPayload, points);
  if (!replayablePoints) {
    return undefined;
  }

  const startTime = replayablePoints[0].timestamp;
  const endTime = replayablePoints[replayablePoints.length - 1].timestamp;
  const origin = placeFromPoint(replayablePoints[0], 'origin', payload.originIata ?? 'GPS start');
  const destination = placeFromPoint(replayablePoints[replayablePoints.length - 1], 'destination', payload.destinationIata ?? 'GPS finish');
  const distanceMeters = calculateRouteDistance(replayablePoints);
  const events = buildRecordingEvents(journeyId, segmentId, normalizedPayload, replayablePoints, points.length);

  return {
    schemaVersion: '1.0.0',
    appVersion: '0.1.0',
    id: journeyId,
    title: journeyTitle(normalizedPayload, startTime),
    subtitle: 'Imported from iOS CoreLocation recording',
    startTime,
    endTime,
    status: 'completed',
    plans: [],
    segments: [
      {
        id: segmentId,
        journeyId,
        type: 'flight',
        startTime,
        endTime,
        origin,
        destination,
        rawRoute: {
          kind: 'raw',
          points: replayablePoints
        },
        processedRoute: {
          kind: 'processed',
          points: replayablePoints
        },
        derivedReplayRoute: {
          kind: 'derivedReplay',
          points: replayablePoints
        },
        events: events.map((event) => event.id),
        statistics: {
          distanceMeters,
          gpsPointCount: points.length
        },
        metadata: {
          nativeJourneyId: payload.nativeJourneyId,
          flightNumber: payload.flightNumber,
          aircraftType: payload.aircraftType,
          recordingSource: 'ios-core-location'
        }
      }
    ],
    events,
    media: [],
    journal: [],
    statistics: {
      distanceMeters,
      gpsPointCount: points.length
    },
    metadata: {
      nativeJourneyId: payload.nativeJourneyId,
      recordingStatus: 'completed',
      recordingCompletedAt: new Date().toISOString(),
      source: 'ios-core-location',
      replayRouteSynthetic: points.length < 2
    }
  };
}

function recordingPoints(payload: NativeRecordingPayload): LocationPoint[] {
  return (payload.points ?? [])
    .map((point, index) => locationPointFromRecordingPayload(payload, point, index))
    .filter((point) => point.source === 'gps')
    .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp));
}

function placeFromPoint(point: LocationPoint, suffix: 'origin' | 'destination', name: string): PlaceReference {
  const place: PlaceReference = {
    id: `${point.journeyId}-${suffix}`,
    name,
    latitude: point.latitude,
    longitude: point.longitude,
    altitudeMeters: point.altitudeMeters
  };
  if (/^[A-Z0-9]{3,4}$/.test(name)) {
    place.iataCode = name;
  }
  return place;
}

function makeReplayableRecordingPoints(
  payload: NativeRecordingPayload,
  points: LocationPoint[]
): LocationPoint[] | undefined {
  if (points.length >= 2) {
    return points;
  }
  if (points.length === 1) {
    return [points[0], syntheticPointNear(points[0], payload, 1)];
  }

  const fallbackAirport =
    (payload.originIata ? findAirportByIata(payload.originIata) : undefined) ??
    (payload.destinationIata ? findAirportByIata(payload.destinationIata) : undefined);
  if (!fallbackAirport) {
    return undefined;
  }

  const journeyId = payload.webJourneyId ?? `native-${payload.nativeJourneyId}`;
  const timestamp = payload.startedAt ?? payload.endedAt ?? new Date().toISOString();
  const anchor: LocationPoint = {
    id: `${journeyId}-gps-anchor`,
    journeyId,
    segmentId: payload.segmentId,
    timestamp,
    latitude: fallbackAirport.latitude,
    longitude: fallbackAirport.longitude,
    altitudeMeters: fallbackAirport.altitudeMeters,
    source: 'estimated'
  };
  return [anchor, syntheticPointNear(anchor, payload, 1)];
}

function syntheticPointNear(point: LocationPoint, payload: NativeRecordingPayload, index: number): LocationPoint {
  const pointTime = Date.parse(point.timestamp);
  const timestamp = payload.endedAt && Date.parse(payload.endedAt) > pointTime
    ? payload.endedAt
    : new Date(pointTime + 60_000).toISOString();
  return {
    ...point,
    id: `${point.id}-synthetic-${index}`,
    timestamp,
    latitude: point.latitude + 0.0001,
    longitude: point.longitude + 0.0001,
    speedMetersPerSecond: 0,
    source: 'estimated'
  };
}

function journeyTitle(payload: NativeRecordingPayload, startTime: string): string {
  if (payload.flightNumber && payload.originIata && payload.destinationIata) {
    return `${payload.flightNumber} ${payload.originIata} to ${payload.destinationIata}`;
  }
  return `GPS Recording ${startTime.slice(0, 10)}`;
}

function buildRecordingEvents(
  journeyId: string,
  segmentId: string,
  payload: NativeRecordingPayload,
  points: ReturnType<typeof locationPointFromRecordingPayload>[],
  gpsPointCount = points.length
): TimelineEvent[] {
  const first = points[0];
  const last = points[points.length - 1] ?? first;
  const routeLabel = [payload.originIata, payload.destinationIata].filter(Boolean).join(' to ');
  const flightNumber = payload.flightNumber ?? 'Flight';
  return [
    {
      id: `event-${segmentId}-gps-start`,
      journeyId,
      segmentId,
      timestamp: first?.timestamp ?? payload.startedAt,
      type: 'gpsRecordingStart',
      title: `${flightNumber} GPS recording started`,
      subtitle: routeLabel || 'iOS CoreLocation recording',
      location: first,
      mediaIds: [],
      importance: 1,
      source: 'gps',
      metadata: {
        nativeJourneyId: payload.nativeJourneyId
      }
    },
    {
      id: `event-${segmentId}-gps-stop`,
      journeyId,
      segmentId,
      timestamp: last?.timestamp ?? payload.endedAt ?? payload.startedAt,
      type: 'gpsRecordingStop',
      title: `${flightNumber} GPS recording completed`,
      subtitle: gpsPointCount >= 2 ? `${gpsPointCount} real GPS points` : `${gpsPointCount} real GPS point(s); replay route estimated`,
      location: last,
      mediaIds: [],
      importance: 1,
      source: 'gps',
      metadata: {
        nativeJourneyId: payload.nativeJourneyId
      }
    }
  ];
}
