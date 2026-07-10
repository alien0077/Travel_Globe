import type { Journey } from '../data/types';
import { calculateRouteDistance } from '../replay/buildReplayFrames';

export interface JourneyStatisticsSummary {
  journeyCount: number;
  segmentCount: number;
  eventCount: number;
  mediaCount: number;
  totalDistanceMeters: number;
  transportModes: string[];
  countriesVisited: string[];
}

export function summarizeJourney(journey: Journey): JourneyStatisticsSummary {
  const totalDistanceMeters = journey.segments.reduce(
    (total, segment) => total + calculateRouteDistance(segment.derivedReplayRoute.points),
    0
  );

  return {
    journeyCount: 1,
    segmentCount: journey.segments.length,
    eventCount: journey.events.length,
    mediaCount: journey.media.length,
    totalDistanceMeters,
    transportModes: [...new Set(journey.segments.map((segment) => segment.type))],
    countriesVisited: [
      ...new Set(
        journey.segments.flatMap((segment) => [
          segment.origin.countryCode ?? '',
          segment.destination.countryCode ?? ''
        ]).filter(Boolean)
      )
    ]
  };
}

export function summarizeLifetime(journeys: Journey[]): JourneyStatisticsSummary {
  const summaries = journeys.map(summarizeJourney);
  return {
    journeyCount: journeys.length,
    segmentCount: summaries.reduce((total, summary) => total + summary.segmentCount, 0),
    eventCount: summaries.reduce((total, summary) => total + summary.eventCount, 0),
    mediaCount: summaries.reduce((total, summary) => total + summary.mediaCount, 0),
    totalDistanceMeters: summaries.reduce((total, summary) => total + summary.totalDistanceMeters, 0),
    transportModes: [...new Set(summaries.flatMap((summary) => summary.transportModes))],
    countriesVisited: [...new Set(summaries.flatMap((summary) => summary.countriesVisited))]
  };
}
