import globalAirgraph from '../../../shared/offline-packs/aviation/regions/global.airgraph.json';
import type { GeographicPoint, PlaceReference } from '../data/types';
import { haversineDistanceMeters } from '../geo/geodesy';

export interface AirgraphRoutePoint extends GeographicPoint {
  ident: string;
  pointType: string;
}

export interface AirgraphRouteResult {
  method: 'airway_graph' | 'great_circle_fallback';
  region: string;
  source: string;
  distanceMeters: number;
  points: AirgraphRoutePoint[];
  waypoints: string[];
  warnings: string[];
}

type AirgraphAirportRow = [string | null, string | null, string, number, number, string | null];
type AirgraphPointRow = [string, number, number, string, string];
type AirgraphAirwayRow = [string, string | null, string];
type AirgraphSegmentRow = [number, number, number, number, string];

interface AirgraphPack {
  schemaVersion: number;
  region: string;
  airports: AirgraphAirportRow[];
  points: AirgraphPointRow[];
  airways: AirgraphAirwayRow[];
  segments: AirgraphSegmentRow[];
}

const packs = [globalAirgraph as unknown as AirgraphPack];

// Spatial grid index for fast nearest-point lookup
interface GridPoint { index: number; lat: number; lon: number }
const GRID_SIZE = 5;
let spatialIndex: Map<string, GridPoint[]>;

function ensureSpatialIndex(pack: AirgraphPack): Map<string, GridPoint[]> {
  if (spatialIndex) return spatialIndex;
  spatialIndex = new Map();
  for (const [from, to] of pack.segments) {
    for (const idx of [from, to]) {
      const lat = pack.points[idx][1];
      const lon = pack.points[idx][2];
      const key = `${Math.floor(lat / GRID_SIZE)},${Math.floor(lon / GRID_SIZE)}`;
      const cell = spatialIndex.get(key) ?? [];
      cell.push({ index: idx, lat, lon });
      spatialIndex.set(key, cell);
    }
  }
  return spatialIndex;
}

function nearestPointSpatial(pack: AirgraphPack, target: GeographicPoint): { index: number; distanceMeters: number } | undefined {
  const index = ensureSpatialIndex(pack);
  const tLat = target.latitude;
  const tLon = target.longitude;
  const cLat = Math.floor(tLat / GRID_SIZE);
  const cLon = Math.floor(tLon / GRID_SIZE);

  for (let ring = 0; ring < 3; ring++) {
    let best: { index: number; distanceMeters: number } | undefined;
    for (let dLat = -ring; dLat <= ring; dLat++) {
      for (let dLon = -ring; dLon <= ring; dLon++) {
        if (ring > 0 && Math.abs(dLat) < ring && Math.abs(dLon) < ring) continue;
        const cell = index.get(`${cLat + dLat},${cLon + dLon}`);
        if (!cell) continue;
        for (const pt of cell) {
          const dist = haversineDistanceMeters(target, { latitude: pt.lat, longitude: pt.lon });
          if (!best || dist < best.distanceMeters) {
            best = { index: pt.index, distanceMeters: dist };
          }
        }
      }
    }
    if (best) return best;
  }
  return undefined;
}

export function findAirgraphRoute(
  origin: PlaceReference,
  destination: PlaceReference
): AirgraphRouteResult | undefined {
  for (const pack of packs) {
    // Try all packs; use nearest-waypoint routing for global pack
    const result = routeInPack(pack, origin, destination);
    if (result.method === 'airway_graph') {
      return result;
    }
  }
  return undefined;
}

function routeInPack(
  pack: AirgraphPack,
  origin: PlaceReference,
  destination: PlaceReference
): AirgraphRouteResult {
  const graph = new Map<number, Array<{ to: number; distanceMeters: number }>>();
  for (let index = 0; index < pack.points.length; index += 1) {
    graph.set(index, []);
  }
  for (const [from, to, , distanceNm] of pack.segments) {
    const distanceMeters = distanceNm * 1852;
    graph.get(from)?.push({ to, distanceMeters });
    graph.get(to)?.push({ to: from, distanceMeters });
  }

  const originConnector = nearestPointSpatial(pack, origin);
  const destinationConnector = nearestPointSpatial(pack, destination);
  if (!originConnector || !destinationConnector) {
    return fallback(pack, origin, destination, 'airgraph connector missing');
  }

  const path = shortestPath(graph, originConnector.index, destinationConnector.index);
  if (!path) {
    return fallback(pack, origin, destination, 'airgraph path missing');
  }

  const routePoints = path.map((pointIndex) => toRoutePoint(pack.points[pointIndex]));
  const points = [placeRoutePoint(origin), ...routePoints, placeRoutePoint(destination)];
  return {
    method: 'airway_graph',
    region: pack.region,
    source: 'aviationdb-airgraph',
    distanceMeters: polylineDistanceMeters(points),
    points,
    waypoints: routePoints.map((point) => point.ident),
    warnings: []
  };
}

function shortestPath(
  graph: Map<number, Array<{ to: number; distanceMeters: number }>>,
  start: number,
  goal: number
): number[] | undefined {
  const distances = new Map<number, number>([[start, 0]]);
  const previous = new Map<number, number | undefined>([[start, undefined]]);
  const queue: Array<{ node: number; distance: number }> = [{ node: start, distance: 0 }];

  while (queue.length > 0) {
    queue.sort((left, right) => left.distance - right.distance);
    const current = queue.shift();
    if (!current) {
      break;
    }
    if (current.node === goal) {
      break;
    }
    if (current.distance > (distances.get(current.node) ?? Number.POSITIVE_INFINITY)) {
      continue;
    }
    for (const edge of graph.get(current.node) ?? []) {
      const candidate = current.distance + edge.distanceMeters;
      if (candidate < (distances.get(edge.to) ?? Number.POSITIVE_INFINITY)) {
        distances.set(edge.to, candidate);
        previous.set(edge.to, current.node);
        queue.push({ node: edge.to, distance: candidate });
      }
    }
  }

  if (!previous.has(goal)) {
    return undefined;
  }
  const path: number[] = [];
  let cursor: number | undefined = goal;
  while (cursor !== undefined) {
    path.push(cursor);
    cursor = previous.get(cursor);
  }
  return path.reverse();
}

function toRoutePoint(row: AirgraphPointRow): AirgraphRoutePoint {
  return {
    ident: row[0],
    latitude: row[1],
    longitude: row[2],
    pointType: row[3]
  };
}

function placeRoutePoint(place: PlaceReference): AirgraphRoutePoint {
  return {
    ident: place.iataCode ?? place.id,
    latitude: place.latitude,
    longitude: place.longitude,
    pointType: 'AIRPORT'
  };
}

function fallback(pack: AirgraphPack, origin: PlaceReference, destination: PlaceReference, reason: string): AirgraphRouteResult {
  const points = [placeRoutePoint(origin), placeRoutePoint(destination)];
  return {
    method: 'great_circle_fallback',
    region: pack.region,
    source: 'aviationdb-airgraph',
    distanceMeters: polylineDistanceMeters(points),
    points,
    waypoints: [],
    warnings: [reason]
  };
}

function polylineDistanceMeters(points: GeographicPoint[]): number {
  return points.reduce(
    (total, point, index) => total + (index === 0 ? 0 : haversineDistanceMeters(points[index - 1], point)),
    0
  );
}


