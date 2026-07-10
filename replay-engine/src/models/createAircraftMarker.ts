import * as THREE from 'three';
import type { GeographicPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';

export function createAircraftMarker(): THREE.Group {
  const aircraft = new THREE.Group();

  const body = new THREE.Mesh(
    new THREE.ConeGeometry(0.055, 0.22, 4),
    new THREE.MeshStandardMaterial({
      color: 0xffffff,
      emissive: 0x4f8cff,
      emissiveIntensity: 0.35,
      roughness: 0.35
    })
  );
  body.rotation.x = Math.PI / 2;
  aircraft.add(body);

  const wing = new THREE.Mesh(
    new THREE.BoxGeometry(0.19, 0.012, 0.035),
    new THREE.MeshStandardMaterial({
      color: 0xaedcff,
      emissive: 0x2d6cdf,
      emissiveIntensity: 0.2
    })
  );
  aircraft.add(wing);

  return aircraft;
}

export function placeAircraftMarker(
  marker: THREE.Group,
  point: GeographicPoint,
  bearingDegrees: number
): void {
  const vector = geographicToVector3(point, 2, 700000);
  marker.position.set(vector.x, vector.y, vector.z);

  const normal = marker.position.clone().normalize();
  const tangent = new THREE.Vector3(1, 0, 0).applyAxisAngle(normal, THREE.MathUtils.degToRad(bearingDegrees));
  marker.lookAt(marker.position.clone().add(tangent));
  marker.up.copy(normal);
}
