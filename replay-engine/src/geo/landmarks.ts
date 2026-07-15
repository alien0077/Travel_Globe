import landmarksJson from '../../../shared/fixtures/landmarks.json';
import geographyRegionsJson from '../../../shared/offline-packs/core-global/geography-regions.json';
import populatedPlacesJson from '../../../shared/offline-packs/core-global/populated-places.json';
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
}

interface NaturalEarthPlace extends GeographicPoint {
  id: string;
  name: string;
  nameZh?: string;
  type: 'majorCity';
  countryCode?: string;
  admin1?: string;
  population?: number;
  scalerank: number;
  labelRank: number;
  minZoom: number;
  isCapital: boolean;
  isWorldCity: boolean;
  isMegaCity: boolean;
}

interface NaturalEarthRegion extends GeographicPoint {
  id: string;
  name: string;
  nameZh?: string;
  type: 'landmark';
  region?: string;
  subregion?: string;
  scalerank: number;
  minZoom: number;
}

export interface LandmarkProximity {
  feature: GeographicFeature;
  distanceMeters: number;
  bearingDegrees: number;
  relativeWindow: string;
}

export const curatedLandmarks = landmarksJson as GeographicFeature[];
export const naturalEarthPlaces = (populatedPlacesJson.places as NaturalEarthPlace[]).map(toGeographicFeature);
export const naturalEarthRegions = (geographyRegionsJson.regions as NaturalEarthRegion[]).map(toRegionFeature);
export const fixtureLandmarks = mergeGeographicFeatures([...curatedLandmarks, ...naturalEarthPlaces, ...naturalEarthRegions]);
const ROUTE_LANDMARK_SAMPLE_LIMIT = 96;
const ROUTE_LANDMARK_MAX_DISTANCE_METERS = 650_000;

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

  return fixtureLandmarks.filter((feature) =>
    sampledRoute.some((point) => haversineDistanceMeters(point, feature) <= maxDistanceMeters)
  );
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

function toGeographicFeature(place: NaturalEarthPlace): GeographicFeature {
  return {
    id: place.id,
    name: place.name,
    nameZh: place.nameZh,
    type: 'majorCity',
    minZoomRank: Math.max(0, Math.round(place.minZoom)),
    importance: importanceForPlace(place),
    population: place.population,
    countryCode: place.countryCode,
    admin1: place.admin1,
    latitude: place.latitude,
    longitude: place.longitude,
    tourismHint: place.isCapital ? '首都' : undefined
  };
}

function toRegionFeature(region: NaturalEarthRegion): GeographicFeature {
  return {
    id: region.id,
    name: region.name,
    nameZh: region.nameZh,
    type: 'landmark',
    minZoomRank: Math.max(0, Math.round(region.minZoom)),
    importance: Math.max(0.78, 1 - Math.min(8, region.scalerank) * 0.035),
    latitude: region.latitude,
    longitude: region.longitude,
    tourismHint: region.subregion || region.region
  };
}

function importanceForPlace(place: NaturalEarthPlace): number {
  if (place.isWorldCity || place.isMegaCity || place.isCapital) {
    return 0.96;
  }
  if ((place.population ?? 0) >= 3_000_000) {
    return 0.92;
  }
  if (place.labelRank <= 3 || place.scalerank <= 3) {
    return 0.88;
  }
  return 0.78;
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

function mergeGeographicFeatures(features: GeographicFeature[]): GeographicFeature[] {
  const seen = new Set<string>();
  const merged: GeographicFeature[] = [];
  for (const feature of features) {
    const key = [
      feature.countryCode ?? '',
      feature.nameZh ?? feature.name,
      feature.latitude.toFixed(2),
      feature.longitude.toFixed(2)
    ].join('|');
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    merged.push(feature);
  }
  return merged;
}
