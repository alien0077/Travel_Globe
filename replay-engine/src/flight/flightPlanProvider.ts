import type { JourneySegment } from '../data/types';
import {
  buildPreloadedFlightJourney,
  type PreloadFlightRequest,
  type PreloadFlightResult
} from '../flight-preload/buildPreloadedFlightJourney';

export interface FlightPlanLookupResult {
  flightNumber: string;
  source: 'offline-fixture' | 'network-provider';
  route: JourneySegment['processedRoute'];
  waypoints: string[];
}

export interface FlightPlanProvider {
  lookupFlightPlan(flightNumber: string): Promise<FlightPlanLookupResult | undefined>;
}

export interface FlightPreloadProvider {
  preloadFlight(request: PreloadFlightRequest): Promise<PreloadFlightResult>;
}

export class OfflineFixtureFlightPlanProvider implements FlightPlanProvider {
  constructor(private readonly segment: JourneySegment) {}

  async lookupFlightPlan(flightNumber: string): Promise<FlightPlanLookupResult | undefined> {
    const fixtureFlightNumber = this.segment.metadata.flightNumber;
    if (typeof fixtureFlightNumber !== 'string' || fixtureFlightNumber.toUpperCase() !== flightNumber.toUpperCase()) {
      return undefined;
    }

    return {
      flightNumber: fixtureFlightNumber,
      source: 'offline-fixture',
      route: this.segment.processedRoute,
      waypoints: this.segment.processedRoute.points.map((point) => point.id)
    };
  }
}

export class OfflineAirportFlightPreloadProvider implements FlightPreloadProvider {
  async preloadFlight(request: PreloadFlightRequest): Promise<PreloadFlightResult> {
    return buildPreloadedFlightJourney(request);
  }
}
