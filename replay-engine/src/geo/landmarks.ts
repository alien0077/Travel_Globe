import landmarksJson from '../../../shared/fixtures/landmarks.json';
import type { GeographicPoint } from '../data/types';
import { haversineDistanceMeters, initialBearingDegrees } from './geodesy';

export interface GeographicFeature extends GeographicPoint {
  id: string;
  name: string;
  nameZh?: string;
  type: string;
  minZoomRank: number;
  importance: number;
  population?: number;
  countryCode?: string;
  admin1?: string;
  tourismHint?: string;
  source?: string;
}

export interface LandmarkProximity {
  feature: GeographicFeature;
  distanceMeters: number;
  bearingDegrees: number;
  relativeWindow: string;
}

interface GlobalPlacesIndex {
  features: GeographicFeature[];
}

interface SpatialIndex {
  cellDegrees: number;
  cells: Record<string, { features?: string[] }>;
}

export let fixtureLandmarks = landmarksJson as GeographicFeature[];
const ROUTE_LANDMARK_SAMPLE_LIMIT = 96;
const ROUTE_LANDMARK_MAX_DISTANCE_METERS = 650_000;
let spatialIndex: SpatialIndex | undefined;
let featuresById = new Map(fixtureLandmarks.map((feature) => [feature.id, feature]));
let globalLandmarkLoadPromise: Promise<void> | undefined;

export async function loadGlobalLandmarkIndex(): Promise<void> {
  if (globalLandmarkLoadPromise) {
    return globalLandmarkLoadPromise;
  }
  globalLandmarkLoadPromise = loadGlobalLandmarkIndexOnce();
  return globalLandmarkLoadPromise;
}

async function loadGlobalLandmarkIndexOnce(): Promise<void> {
  if (typeof fetch === 'undefined') {
    return;
  }
  const baseUrl = typeof document === 'undefined'
    ? './offline-packs/core-global/'
    : new URL('./offline-packs/core-global/', document.baseURI).toString();
  try {
    const [placesResponse, spatialResponse] = await Promise.all([
      fetch(new URL('global-places.json', baseUrl)),
      fetch(new URL('geo-spatial-index.json', baseUrl))
    ]);
    if (!placesResponse.ok || !spatialResponse.ok) {
      throw new Error(`Unable to load global place assets: ${placesResponse.status}/${spatialResponse.status}`);
    }
    const places = await placesResponse.json() as GlobalPlacesIndex;
    const nextSpatialIndex = await spatialResponse.json() as SpatialIndex;
    if (!Array.isArray(places.features) || !Number.isFinite(nextSpatialIndex.cellDegrees)) {
      throw new Error('Global place assets are malformed');
    }
    installLandmarkIndex(places.features, nextSpatialIndex);
  } catch (error) {
    console.warn(error instanceof Error ? error.message : 'Unable to load global place assets');
  }
}

export function installLandmarkIndex(features: GeographicFeature[], nextSpatialIndex?: SpatialIndex): void {
  fixtureLandmarks = features;
  spatialIndex = nextSpatialIndex;
  featuresById = new Map(fixtureLandmarks.map((feature) => [feature.id, feature]));
}

export function landmarkDisplayName(feature: GeographicFeature): string {
  return feature.nameZh ?? feature.name;
}

export function windowDirectionLabel(relativeWindow: string): string {
  switch (relativeWindow) {
    case 'front':
      return '正前方';
    case 'right-front':
      return '右前方';
    case 'right side':
      return '右側';
    case 'right-rear':
      return '右後方';
    case 'left-rear':
      return '左後方';
    case 'left side':
      return '左側';
    case 'left-front':
      return '左前方';
    default:
      return relativeWindow;
  }
}

export function landmarkWindowHint(proximity: LandmarkProximity): string {
  const name = landmarkDisplayName(proximity.feature);
  const direction = windowDirectionLabel(proximity.relativeWindow);
  const hint = proximity.feature.tourismHint ? `，${proximity.feature.tourismHint}` : '';
  return `${name}在你的${direction}${hint}`;
}

export function findNearestLandmark(
  point: GeographicPoint,
  headingDegrees: number,
  features = fixtureLandmarks
): LandmarkProximity | undefined {
  return features
    .map((feature) => {
      const bearingDegrees = initialBearingDegrees(point, feature);
      return {
        feature,
        distanceMeters: haversineDistanceMeters(point, feature),
        bearingDegrees,
        relativeWindow: relativeWindowDirection(headingDegrees, bearingDegrees)
      };
    })
    .sort((a, b) => landmarkProximityScore(a) - landmarkProximityScore(b))[0];
}

export function landmarksNearRoute(
  route: GeographicPoint[],
  maxDistanceMeters = ROUTE_LANDMARK_MAX_DISTANCE_METERS
): GeographicFeature[] {
  if (route.length === 0) {
    return [];
  }

  const step = Math.max(1, Math.ceil(route.length / ROUTE_LANDMARK_SAMPLE_LIMIT));
  const sampledRoute = route.filter((_, index) => index % step === 0);
  const last = route[route.length - 1];
  if (sampledRoute[sampledRoute.length - 1] !== last) {
    sampledRoute.push(last);
  }

  const candidates = landmarkCandidatesForRoute(sampledRoute);
  return candidates.filter((feature) =>
    sampledRoute.some((point) => haversineDistanceMeters(point, feature) <= maxDistanceMeters)
  );
}

function landmarkCandidatesForRoute(route: GeographicPoint[]): GeographicFeature[] {
  const ids = new Set<string>();
  if (!spatialIndex) {
    return fixtureLandmarks;
  }
  for (const point of route) {
    for (const key of nearbyCellKeys(point)) {
      const cell = spatialIndex.cells[key];
      for (const id of cell?.features ?? []) {
        ids.add(id);
      }
    }
  }
  const candidates = [...ids]
    .map((id) => featuresById.get(id))
    .filter((feature): feature is GeographicFeature => feature !== undefined);
  return candidates.length > 0 ? candidates : fixtureLandmarks;
}

function nearbyCellKeys(point: GeographicPoint): string[] {
  const cellDegrees = spatialIndex?.cellDegrees ?? 5;
  const latCell = Math.max(0, Math.min(35, Math.floor((point.latitude + 90) / cellDegrees)));
  const lonCell = Math.max(0, Math.min(71, Math.floor((point.longitude + 180) / cellDegrees)));
  const keys: string[] = [];
  for (let lat = latCell - 2; lat <= latCell + 2; lat += 1) {
    for (let lon = lonCell - 2; lon <= lonCell + 2; lon += 1) {
      if (lat >= 0 && lat <= 35 && lon >= 0 && lon <= 71) {
        keys.push(`${lat}:${lon}`);
      }
    }
  }
  return keys;
}

export function relativeWindowDirection(headingDegrees: number, bearingDegrees: number): string {
  const relative = ((((bearingDegrees - headingDegrees + 540) % 360) - 180) + 360) % 360;
  if (relative < 30 || relative >= 330) {
    return 'front';
  }
  if (relative < 75) {
    return 'right-front';
  }
  if (relative < 120) {
    return 'right side';
  }
  if (relative < 180) {
    return 'right-rear';
  }
  if (relative < 240) {
    return 'left-rear';
  }
  if (relative < 285) {
    return 'left side';
  }
  return 'left-front';
}

function landmarkProximityScore(proximity: LandmarkProximity): number {
  const typeBonus = proximity.feature.type === 'airport'
    ? 60_000
    : proximity.feature.type === 'majorCity'
      ? 0
      : 150_000;
  const importanceBonus = proximity.feature.importance * 24_000;
  return proximity.distanceMeters - typeBonus - importanceBonus;
}
