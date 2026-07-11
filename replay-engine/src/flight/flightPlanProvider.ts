import type { JourneySegment } from '../data/types';

export interface FlightPlanLookupResult {
  flightNumber: string;
  source: 'offline-fixture' | 'network-provider';
  route: JourneySegment['processedRoute'];
  waypoints: string[];
}

export interface FlightPlanProvider {
  lookupFlightPlan(flightNumber: string): Promise<FlightPlanLookupResult | undefined>;
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
