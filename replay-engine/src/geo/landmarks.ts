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
}

export interface LandmarkProximity {
  feature: GeographicFeature;
  distanceMeters: number;
  bearingDegrees: number;
  relativeWindow: string;
}

export const fixtureLandmarks = landmarksJson as GeographicFeature[];

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
    .sort((a, b) => a.distanceMeters - b.distanceMeters)[0];
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
