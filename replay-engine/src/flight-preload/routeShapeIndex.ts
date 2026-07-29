import type { AirgraphRoutePoint, AirgraphRouteResult } from './airgraphIndex';
import type { PlaceReference } from '../data/types';

type RuntimeRoutePoint = [string | null, number | null, number | null, string | null];

interface RuntimeRouteShape {
  m?: string;
  s?: number;
  d?: number;
  p?: RuntimeRoutePoint[];
}

interface RuntimeRouteShapePack {
  meta?: {
    schemaVersion?: number;
    generatedAt?: string;
    sourcePack?: string;
  };
  routes?: Record<string, RuntimeRouteShape>;
}

let packPromise: Promise<RuntimeRouteShapePack | undefined> | undefined;
let injectedPack: RuntimeRouteShapePack | undefined;

export async function findRouteShape(origin: PlaceReference, destination: PlaceReference): Promise<AirgraphRouteResult | undefined> {
  const runtimePack = await loadRouteShapePack();
  const originIata = origin.iataCode?.trim().toUpperCase();
  const destinationIata = destination.iataCode?.trim().toUpperCase();
  if (!originIata || !destinationIata) {
    return undefined;
  }
  const shape = runtimePack?.routes?.[`${originIata}-${destinationIata}`];
  if (!shape?.p || shape.p.length < 2) {
    return undefined;
  }
  const points = shape.p
    .map(toRoutePoint)
    .filter((point): point is AirgraphRoutePoint => Boolean(point));
  if (points.length < 2) {
    return undefined;
  }
  return {
    method: normalizeRouteShapeMethod(shape.m),
    region: 'global',
    source: 'aviationdb-route-shapes',
    distanceMeters: shape.d ?? 0,
    points,
    waypoints: points
      .filter((point) => point.pointType !== 'AIRPORT')
      .map((point) => point.ident),
    warnings: []
  };
}

export function injectRouteShapePackForTest(pack: RuntimeRouteShapePack | undefined): void {
  injectedPack = pack;
  packPromise = undefined;
}

async function loadRouteShapePack(): Promise<RuntimeRouteShapePack | undefined> {
  if (injectedPack) {
    return injectedPack;
  }
  packPromise ??= fetchRouteShapePack();
  return packPromise;
}

async function fetchRouteShapePack(): Promise<RuntimeRouteShapePack | undefined> {
  if (typeof fetch !== 'function' || typeof document === 'undefined') {
    return undefined;
  }
  const base = document.baseURI || window.location.href;
  const response = await fetch(new URL('./offline-packs/route-shapes/global.route-shapes.runtime.json', base).toString());
  if (!response.ok) {
    return undefined;
  }
  return await response.json() as RuntimeRouteShapePack;
}

function normalizeRouteShapeMethod(method: string | undefined): AirgraphRouteResult['method'] {
  return method === 'great_circle_waypoint_corridor' ? 'great_circle_waypoint_corridor' : 'great_circle_pair_fallback';
}

function toRoutePoint(point: RuntimeRoutePoint): AirgraphRoutePoint | undefined {
  const [ident, latitude, longitude, pointType] = point;
  if (!ident || typeof latitude !== 'number' || typeof longitude !== 'number') {
    return undefined;
  }
  return {
    ident,
    latitude,
    longitude,
    pointType: pointType ?? 'SIGNIFICANT_POINT'
  };
}
