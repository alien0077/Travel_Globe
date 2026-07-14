import type { Journey, TimelineEvent } from '../data/types';
import { getPrimaryFlightSegment } from '../data/types';
import { calculateRouteDistance } from '../replay/buildReplayFrames';
import {
  locationPointFromRecordingPayload,
  type NativeRecordingPayload
} from '../bridge/nativeBridge';

export function completeJourneyFromRecording(
  journey: Journey,
  payload: NativeRecordingPayload
): Journey {
  const segment = getPrimaryFlightSegment(journey);
  const points = (payload.points ?? [])
    .map((point, index) => locationPointFromRecordingPayload(payload, point, index))
    .filter((point) => point.source === 'gps')
    .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp));
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

function buildRecordingEvents(
  journeyId: string,
  segmentId: string,
  payload: NativeRecordingPayload,
  points: ReturnType<typeof locationPointFromRecordingPayload>[]
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
      subtitle: `${points.length} real GPS points`,
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
