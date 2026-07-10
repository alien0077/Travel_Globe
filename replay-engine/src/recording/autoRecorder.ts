import type { GeographicPoint } from '../data/types';
import { haversineDistanceMeters } from '../geo/geodesy';

export type AutoRecordingState =
  | 'Idle'
  | 'PossibleJourney'
  | 'JourneyRecording'
  | 'TemporarilyStationary'
  | 'JourneyCompleted';

export interface AutoRecordingSignal {
  timestamp: string;
  location: GeographicPoint;
  speedMetersPerSecond: number;
}

export interface AutoRecordingContext {
  home: GeographicPoint;
  state: AutoRecordingState;
  lastMovedAt?: string;
}

export function reduceAutoRecordingState(
  context: AutoRecordingContext,
  signal: AutoRecordingSignal
): AutoRecordingContext {
  const distanceFromHome = haversineDistanceMeters(context.home, signal.location);
  const moving = signal.speedMetersPerSecond > 2;

  if (context.state === 'Idle' && distanceFromHome > 1200 && moving) {
    return { ...context, state: 'PossibleJourney', lastMovedAt: signal.timestamp };
  }

  if (context.state === 'PossibleJourney' && distanceFromHome > 2500 && moving) {
    return { ...context, state: 'JourneyRecording', lastMovedAt: signal.timestamp };
  }

  if (context.state === 'JourneyRecording' && !moving) {
    return { ...context, state: 'TemporarilyStationary' };
  }

  if (context.state === 'TemporarilyStationary' && moving) {
    return { ...context, state: 'JourneyRecording', lastMovedAt: signal.timestamp };
  }

  if ((context.state === 'JourneyRecording' || context.state === 'TemporarilyStationary') && distanceFromHome < 300) {
    return { ...context, state: 'JourneyCompleted' };
  }

  return context;
}
