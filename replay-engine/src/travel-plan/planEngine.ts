import type { Journey, TimelineEvent } from '../data/types';
import { haversineDistanceMeters } from '../geo/geodesy';

export interface PlannedPlace {
  id: string;
  title: string;
  latitude: number;
  longitude: number;
  priority: 'must' | 'should' | 'optional';
  status: 'planned' | 'completed' | 'skipped';
}

export interface TravelPlanSummary {
  title: string;
  plannedPlaces: PlannedPlace[];
  completedCount: number;
}

export function buildPlanSummary(journey: Journey): TravelPlanSummary {
  const origin = journey.segments[0].origin;
  const destination = journey.segments[0].destination;
  const plannedPlaces: PlannedPlace[] = [
    {
      id: origin.id,
      title: origin.name,
      latitude: origin.latitude,
      longitude: origin.longitude,
      priority: 'must',
      status: 'completed'
    },
    {
      id: destination.id,
      title: destination.name,
      latitude: destination.latitude,
      longitude: destination.longitude,
      priority: 'must',
      status: hasArrivalEvent(journey.events) ? 'completed' : 'planned'
    }
  ];

  return {
    title: `${journey.title} plan`,
    plannedPlaces,
    completedCount: plannedPlaces.filter((place) => place.status === 'completed').length
  };
}

export function matchEventsToPlan(events: TimelineEvent[], plannedPlaces: PlannedPlace[]): PlannedPlace[] {
  return plannedPlaces.map((place) => {
    const matched = events.some((event) => {
      if (!event.location) {
        return false;
      }
      return haversineDistanceMeters(place, event.location) < 8000;
    });
    return { ...place, status: matched ? 'completed' : place.status };
  });
}

function hasArrivalEvent(events: TimelineEvent[]): boolean {
  return events.some((event) => event.type === 'flightLanding' || event.type === 'journeyEnded');
}
