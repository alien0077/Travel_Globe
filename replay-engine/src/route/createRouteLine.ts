import * as THREE from 'three';
import type { LocationPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';

export interface RouteLineOptions {
  color?: number;
  opacity?: number;
  altitudeScaleMeters?: number;
}

export function createRouteLine(points: LocationPoint[], options: RouteLineOptions = {}): THREE.Line {
  const geometry = createRouteGeometry(points, options.altitudeScaleMeters);
  const material = new THREE.LineBasicMaterial({
    color: options.color ?? 0xf6d365,
    transparent: true,
    opacity: options.opacity ?? 0.96
  });

  return new THREE.Line(geometry, material);
}

export function updateRouteLine(line: THREE.Line, points: LocationPoint[], altitudeScaleMeters?: number): void {
  line.geometry.dispose();
  line.geometry = createRouteGeometry(points, altitudeScaleMeters);
}

export function createRouteEventMarkers(points: LocationPoint[], color = 0xffffff): THREE.Group {
  const group = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.35,
    roughness: 0.4
  });

  for (const point of points) {
    const marker = new THREE.Mesh(new THREE.SphereGeometry(0.026, 16, 12), material);
    const vector = geographicToVector3(point, 2, 620000);
    marker.position.set(vector.x, vector.y, vector.z);
    group.add(marker);
  }

  return group;
}

function createRouteGeometry(points: LocationPoint[], altitudeScaleMeters = 700000): THREE.BufferGeometry {
  const positions: number[] = [];

  for (const point of points) {
    const vector = geographicToVector3(point, 2, altitudeScaleMeters);
    positions.push(vector.x, vector.y, vector.z);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}
