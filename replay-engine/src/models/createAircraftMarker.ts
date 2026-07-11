import * as THREE from 'three';
import type { GeographicPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';

export function createAircraftMarker(): THREE.Group {
  const aircraft = new THREE.Group();

  const fuselageMaterial = new THREE.MeshStandardMaterial({
    color: 0xf8fbff,
    emissive: 0x2b6fff,
    emissiveIntensity: 0.18,
    roughness: 0.34,
    metalness: 0.12
  });
  const wingMaterial = new THREE.MeshStandardMaterial({
    color: 0xb9e7ff,
    emissive: 0x1a5fbb,
    emissiveIntensity: 0.2,
    roughness: 0.42,
    metalness: 0.08
  });
  const engineMaterial = new THREE.MeshStandardMaterial({
    color: 0xd9f3ff,
    emissive: 0x184f9f,
    emissiveIntensity: 0.18,
    roughness: 0.36
  });

  const fuselage = new THREE.Mesh(new THREE.CylinderGeometry(0.026, 0.032, 0.32, 18), fuselageMaterial);
  fuselage.rotation.x = Math.PI / 2;
  aircraft.add(fuselage);

  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.026, 0.07, 18), fuselageMaterial);
  nose.rotation.x = -Math.PI / 2;
  nose.position.z = -0.195;
  aircraft.add(nose);

  const mainWing = new THREE.Mesh(
    new THREE.BoxGeometry(0.34, 0.012, 0.052),
    wingMaterial
  );
  mainWing.position.z = -0.02;
  aircraft.add(mainWing);

  const wingSweepLeft = new THREE.Mesh(
    new THREE.BoxGeometry(0.17, 0.01, 0.036),
    wingMaterial
  );
  wingSweepLeft.position.set(-0.08, 0, 0.005);
  wingSweepLeft.rotation.y = -0.22;
  aircraft.add(wingSweepLeft);

  const wingSweepRight = wingSweepLeft.clone();
  wingSweepRight.position.x = 0.08;
  wingSweepRight.rotation.y = 0.22;
  aircraft.add(wingSweepRight);

  const tailPlane = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.01, 0.032), wingMaterial);
  tailPlane.position.z = 0.135;
  aircraft.add(tailPlane);

  const verticalTail = new THREE.Mesh(new THREE.BoxGeometry(0.018, 0.075, 0.04), wingMaterial);
  verticalTail.position.set(0, 0.042, 0.145);
  verticalTail.rotation.x = -0.18;
  aircraft.add(verticalTail);

  for (const x of [-0.135, -0.068, 0.068, 0.135]) {
    const engine = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.034, 14), engineMaterial);
    engine.rotation.x = Math.PI / 2;
    engine.position.set(x, -0.026, -0.035);
    aircraft.add(engine);
  }

  const beacon = new THREE.PointLight(0x8fd8ff, 0.65, 0.55);
  beacon.position.set(0, 0.04, -0.08);
  aircraft.add(beacon);

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
