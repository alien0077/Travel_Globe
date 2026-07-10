import type { Journey } from '../data/types';
import { summarizeLifetime } from '../statistics/journeyStatistics';

export interface TimeMachineState {
  years: number[];
  countries: string[];
  selectedJourneyIds: string[];
  lifetimeDistanceMeters: number;
}

export function buildTimeMachineState(journeys: Journey[]): TimeMachineState {
  const lifetime = summarizeLifetime(journeys);
  return {
    years: [...new Set(journeys.map((journey) => new Date(journey.startTime).getUTCFullYear()))].sort(),
    countries: lifetime.countriesVisited,
    selectedJourneyIds: journeys.map((journey) => journey.id),
    lifetimeDistanceMeters: lifetime.totalDistanceMeters
  };
}

export function filterJourneysByYear(journeys: Journey[], year: number): Journey[] {
  return journeys.filter((journey) => new Date(journey.startTime).getUTCFullYear() === year);
}
