import type { Journey, LocationPoint } from '../data/types';
import { getPrimaryFlightSegment } from '../data/types';
import { downloadBlob } from '../export/travelglobePackage';

export interface NativeBridgeEnvelope<TPayload = unknown> {
  version: '1.0';
  type: string;
  requestId?: string;
  payload: TPayload;
}

export interface NativeFlightPlanPayload {
  webJourneyId: string;
  segmentId: string;
  flightNumber: string;
  originIata: string;
  destinationIata: string;
  departureTime?: string;
  durationMinutes?: number;
  aircraftType?: string;
  plannedRoute: Array<{
    timestamp: string;
    latitude: number;
    longitude: number;
    altitudeMeters?: number;
  }>;
}

export interface NativeRecordingPayload {
  nativeJourneyId: string;
  webJourneyId?: string;
  segmentId?: string;
  flightNumber?: string;
  originIata?: string;
  destinationIata?: string;
  aircraftType?: string;
  status: string;
  startedAt: string;
  endedAt?: string;
  points?: Array<{
    timestamp: string;
    latitude: number;
    longitude: number;
    altitudeMeters?: number | null;
    speedMetersPerSecond?: number | null;
    courseDegrees?: number | null;
    horizontalAccuracyMeters: number;
    verticalAccuracyMeters?: number | null;
    source: 'gps';
  }>;
}

export interface NativeVisitPointPayload {
  id: string;
  timestamp: string;
  latitude: number;
  longitude: number;
  altitudeMeters?: number | null;
  horizontalAccuracyMeters?: number | null;
  title: string;
  note?: string | null;
  source: 'photoGps' | 'quickGps' | 'recordingMarker' | 'manual' | string;
  sourceId?: string | null;
}

export interface NativeVisitPointsPayload {
  nativeJourneyId: string;
  webJourneyId?: string;
  segmentId?: string;
  status: string;
  points: NativeVisitPointPayload[];
}

export interface NativeNotificationSchedulePayload {
  identifier: string;
  title: string;
  body: string;
}

export interface NativeFileExportPayload {
  filename: string;
  mimeType: string;
  base64: string;
}

export type NativeExportDelivery = 'native-share' | 'browser-download';

declare global {
  interface Window {
    TravelGlobeNative?: {
      post?: (message: NativeBridgeEnvelope) => void;
    };
  }
}

export function postNativeMessage<TPayload>(type: string, payload: TPayload): boolean {
  const post = window.TravelGlobeNative?.post;
  if (!post) {
    return false;
  }
  post({
    version: '1.0',
    requestId: `${type}-${Date.now()}`,
    type,
    payload
  });
  return true;
}

export async function exportBlob(blob: Blob, filename: string, mimeType = blob.type || 'application/octet-stream'): Promise<NativeExportDelivery> {
  if (window.TravelGlobeNative?.post) {
    try {
      const base64 = arrayBufferToBase64(await blob.arrayBuffer());
      if (postNativeMessage<NativeFileExportPayload>('file.export', { filename, mimeType, base64 })) {
        return 'native-share';
      }
    } catch {
      // Fall through to browser download if native export bridge is unavailable or rejects the payload.
    }
  }
  downloadBlob(blob, filename);
  return 'browser-download';
}

export function flightPlanPayloadFromJourney(journey: Journey): NativeFlightPlanPayload {
  const segment = getPrimaryFlightSegment(journey);
  const startMs = Date.parse(segment.startTime);
  const endMs = Date.parse(segment.endTime);
  const durationMinutes = Number.isFinite(startMs) && Number.isFinite(endMs)
    ? Math.max(1, Math.round((endMs - startMs) / 60_000))
    : undefined;
  return {
    webJourneyId: journey.id,
    segmentId: segment.id,
    flightNumber: stringMetadata(segment.metadata.flightNumber, journey.title),
    originIata: segment.origin.iataCode ?? segment.origin.name,
    destinationIata: segment.destination.iataCode ?? segment.destination.name,
    departureTime: segment.startTime,
    durationMinutes,
    aircraftType: stringMetadata(segment.metadata.aircraftType),
    plannedRoute: segment.derivedReplayRoute.points.map((point) => ({
      timestamp: point.timestamp,
      latitude: point.latitude,
      longitude: point.longitude,
      altitudeMeters: point.altitudeMeters
    }))
  };
}

export function parseNativePayload<TPayload>(message: unknown, type: string): TPayload | undefined {
  if (!isEnvelope(message) || message.type !== type) {
    return undefined;
  }
  if (typeof message.payload === 'string') {
    try {
      return JSON.parse(message.payload) as TPayload;
    } catch {
      return undefined;
    }
  }
  return message.payload as TPayload;
}

export function locationPointFromRecordingPayload(
  payload: NativeRecordingPayload,
  point: NonNullable<NativeRecordingPayload['points']>[number],
  index: number
): LocationPoint {
  return {
    id: `native-recording-${payload.nativeJourneyId}-${index}`,
    journeyId: payload.webJourneyId ?? payload.nativeJourneyId,
    segmentId: payload.segmentId,
    timestamp: new Date(point.timestamp).toISOString(),
    latitude: point.latitude,
    longitude: point.longitude,
    altitudeMeters: finiteOrUndefined(point.altitudeMeters ?? null),
    speedMetersPerSecond: finiteOrUndefined(point.speedMetersPerSecond ?? null),
    courseDegrees: finiteOrUndefined(point.courseDegrees ?? null),
    horizontalAccuracyMeters: point.horizontalAccuracyMeters,
    verticalAccuracyMeters: finiteOrUndefined(point.verticalAccuracyMeters ?? null),
    source: 'gps'
  };
}

function isEnvelope(value: unknown): value is NativeBridgeEnvelope {
  return typeof value === 'object' && value !== null && 'type' in value && 'payload' in value;
}

function stringMetadata(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim().length > 0 ? value.trim() : fallback;
}

function finiteOrUndefined(value: number | null): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}
