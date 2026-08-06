import type { GeographicPoint, PlaceReference } from '../data/types';

export interface AirgraphRoutePoint extends GeographicPoint {
  ident: string;
  pointType: string;
}

export interface AirgraphRouteResult {
  method:
    | 'directed_airway_graph'
    | 'airway_graph'
    | 'great_circle_fallback'
    | 'great_circle_waypoint_corridor'
    | 'great_circle_pair_fallback'
    | 'approximate_direct_fallback'
    | 'observed_adsb_mapped';
  region: string;
  source: string;
  distanceMeters: number;
  points: AirgraphRoutePoint[];
  waypoints: string[];
  warnings: string[];
}

export function findAirgraphRoute(
  origin: PlaceReference,
  destination: PlaceReference
): AirgraphRouteResult | undefined {
  void origin;
  void destination;
  return undefined;
}
