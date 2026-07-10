import * as THREE from 'three';
import type { LocationPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';

export function createRouteLine(points: LocationPoint[]): THREE.Line {
  const positions: number[] = [];

  for (const point of points) {
    const vector = geographicToVector3(point, 2, 700000);
    positions.push(vector.x, vector.y, vector.z);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));

  const material = new THREE.LineBasicMaterial({
    color: 0xf6d365,
    transparent: true,
    opacity: 0.96
  });

  return new THREE.Line(geometry, material);
}
