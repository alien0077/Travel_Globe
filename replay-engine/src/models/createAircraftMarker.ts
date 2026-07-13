import * as THREE from 'three';
import type { GeographicPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';
import {
  DEFAULT_AIRCRAFT_TYPE,
  normalizeAircraftType,
  type RequiredAircraftType
} from './aircraftModelLibrary';

export const AIRCRAFT_MODEL_TARGET_SIZE = 0.16;
export const AIRCRAFT_VISUAL_ALTITUDE_FLOOR_METERS = 3500;

interface ProceduralAircraftProfile {
  id: RequiredAircraftType;
  length: number;
  wingspan: number;
  bodyRadius: number;
  wingDepth: number;
  tailSpan: number;
  tailHeight: number;
  engines: 2 | 4;
  accentColor: number;
  doubleDeck?: boolean;
}

const AIRCRAFT_PROFILES: Record<RequiredAircraftType, ProceduralAircraftProfile> = {
  A320: {
    id: 'A320',
    length: 0.142,
    wingspan: 0.138,
    bodyRadius: 0.016,
    wingDepth: 0.024,
    tailSpan: 0.058,
    tailHeight: 0.04,
    engines: 2,
    accentColor: 0x2a817b
  },
  A321: {
    id: 'A321',
    length: 0.158,
    wingspan: 0.144,
    bodyRadius: 0.016,
    wingDepth: 0.025,
    tailSpan: 0.06,
    tailHeight: 0.042,
    engines: 2,
    accentColor: 0x2a817b
  },
  B737: {
    id: 'B737',
    length: 0.146,
    wingspan: 0.134,
    bodyRadius: 0.015,
    wingDepth: 0.024,
    tailSpan: 0.056,
    tailHeight: 0.04,
    engines: 2,
    accentColor: 0x366e99
  },
  B767: {
    id: 'B767',
    length: 0.17,
    wingspan: 0.172,
    bodyRadius: 0.019,
    wingDepth: 0.03,
    tailSpan: 0.072,
    tailHeight: 0.049,
    engines: 2,
    accentColor: 0x376f9c
  },
  B777: {
    id: 'B777',
    length: 0.188,
    wingspan: 0.196,
    bodyRadius: 0.021,
    wingDepth: 0.034,
    tailSpan: 0.082,
    tailHeight: 0.055,
    engines: 2,
    accentColor: 0x315f90
  },
  B787: {
    id: 'B787',
    length: 0.18,
    wingspan: 0.19,
    bodyRadius: 0.02,
    wingDepth: 0.032,
    tailSpan: 0.078,
    tailHeight: 0.052,
    engines: 2,
    accentColor: 0x337593
  },
  A350: {
    id: 'A350',
    length: 0.184,
    wingspan: 0.194,
    bodyRadius: 0.02,
    wingDepth: 0.033,
    tailSpan: 0.078,
    tailHeight: 0.053,
    engines: 2,
    accentColor: 0x2e7d89
  },
  A380: {
    id: 'A380',
    length: 0.2,
    wingspan: 0.224,
    bodyRadius: 0.026,
    wingDepth: 0.038,
    tailSpan: 0.092,
    tailHeight: 0.066,
    engines: 4,
    accentColor: 0x2f8c82,
    doubleDeck: true
  }
};

export function createAircraftMarker(aircraftType?: string): THREE.Group {
  const aircraft = new THREE.Group();
  const profile = aircraftProfileFor(aircraftType);
  aircraft.name = `Aircraft ${profile.id}`;
  aircraft.add(createProceduralAircraftModel(profile));
  return aircraft;
}

function aircraftProfileFor(aircraftType: string | undefined): ProceduralAircraftProfile {
  const normalized = normalizeAircraftType(aircraftType ?? DEFAULT_AIRCRAFT_TYPE);
  if (normalized in AIRCRAFT_PROFILES) {
    return AIRCRAFT_PROFILES[normalized as RequiredAircraftType];
  }
  return AIRCRAFT_PROFILES[DEFAULT_AIRCRAFT_TYPE];
}

function createProceduralAircraftModel(profile: ProceduralAircraftProfile): THREE.Group {
  const group = new THREE.Group();
  group.name = `${profile.id} procedural aircraft model`;
  const materials = createAircraftMaterials(profile.accentColor);

  const fuselage = new THREE.Mesh(
    new THREE.CapsuleGeometry(profile.bodyRadius, profile.length, 10, 20),
    materials.body
  );
  fuselage.rotation.x = Math.PI / 2;
  group.add(fuselage);

  const nose = new THREE.Mesh(
    new THREE.SphereGeometry(profile.bodyRadius * 0.92, 16, 12),
    materials.body
  );
  nose.scale.set(0.86, 0.74, 1.18);
  nose.position.z = -profile.length * 0.5;
  group.add(nose);

  const cockpit = new THREE.Mesh(
    new THREE.BoxGeometry(profile.bodyRadius * 1.3, profile.bodyRadius * 0.42, profile.bodyRadius * 0.48),
    materials.dark
  );
  cockpit.position.set(0, profile.bodyRadius * 0.72, -profile.length * 0.43);
  cockpit.rotation.x = -0.18;
  group.add(cockpit);

  if (profile.doubleDeck) {
    const upperDeck = new THREE.Mesh(
      new THREE.BoxGeometry(profile.bodyRadius * 1.15, profile.bodyRadius * 0.18, profile.length * 0.34),
      materials.body
    );
    upperDeck.position.set(0, profile.bodyRadius * 1.04, -profile.length * 0.16);
    group.add(upperDeck);
  }

  const wing = new THREE.Mesh(
    new THREE.BoxGeometry(profile.wingspan, 0.005, profile.wingDepth),
    materials.wing
  );
  wing.position.z = profile.length * 0.03;
  wing.rotation.z = 0.015;
  group.add(wing);

  const tailWing = new THREE.Mesh(
    new THREE.BoxGeometry(profile.tailSpan, 0.004, profile.wingDepth * 0.66),
    materials.wing
  );
  tailWing.position.z = profile.length * 0.46;
  group.add(tailWing);

  const verticalTail = new THREE.Mesh(
    new THREE.BoxGeometry(profile.bodyRadius * 0.52, profile.tailHeight, profile.wingDepth * 0.75),
    materials.accent
  );
  verticalTail.position.set(0, profile.tailHeight * 0.48, profile.length * 0.49);
  verticalTail.rotation.x = -0.08;
  group.add(verticalTail);

  const enginePositions = engineOffsets(profile);
  for (const offsetX of enginePositions) {
    const engine = new THREE.Mesh(
      new THREE.CapsuleGeometry(profile.bodyRadius * 0.38, profile.wingDepth * 0.74, 8, 12),
      materials.engine
    );
    engine.rotation.x = Math.PI / 2;
    engine.position.set(offsetX, -profile.bodyRadius * 0.82, profile.length * 0.005);
    group.add(engine);
  }

  const beacon = new THREE.PointLight(0x9addff, 0.72, 0.62);
  beacon.position.set(0, profile.bodyRadius * 1.6, profile.length * 0.15);
  group.add(beacon);

  normalizeProceduralAircraft(group);
  return group;
}

function engineOffsets(profile: ProceduralAircraftProfile): number[] {
  if (profile.engines === 4) {
    return [
      -profile.wingspan * 0.34,
      -profile.wingspan * 0.18,
      profile.wingspan * 0.18,
      profile.wingspan * 0.34
    ];
  }
  return [-profile.wingspan * 0.24, profile.wingspan * 0.24];
}

function createAircraftMaterials(accentColor: number): Record<'body' | 'wing' | 'engine' | 'dark' | 'accent', THREE.Material> {
  return {
    body: new THREE.MeshStandardMaterial({
      name: 'Travel Globe clean white fuselage',
      color: 0xf8fbff,
      emissive: 0x355a70,
      emissiveIntensity: 0.18,
      roughness: 0.3,
      metalness: 0.16
    }),
    wing: new THREE.MeshStandardMaterial({
      name: 'Travel Globe pale blue wing',
      color: 0xd7f2ff,
      emissive: 0x235f99,
      emissiveIntensity: 0.08,
      roughness: 0.34,
      metalness: 0.1,
      side: THREE.DoubleSide
    }),
    engine: new THREE.MeshStandardMaterial({
      name: 'Travel Globe neutral engine nacelle',
      color: 0xe8f7ff,
      roughness: 0.28,
      metalness: 0.18
    }),
    dark: new THREE.MeshStandardMaterial({
      name: 'Travel Globe cockpit and window dark',
      color: 0x23475f,
      emissive: 0x103048,
      emissiveIntensity: 0.2,
      roughness: 0.44
    }),
    accent: new THREE.MeshStandardMaterial({
      name: 'Travel Globe teal accent',
      color: accentColor,
      emissive: 0x145d58,
      emissiveIntensity: 0.18,
      roughness: 0.32
    })
  };
}

function normalizeProceduralAircraft(model: THREE.Group): void {
  const box = new THREE.Box3().setFromObject(model);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const longest = Math.max(size.x, size.y, size.z);
  if (longest <= 0) {
    return;
  }

  for (const child of model.children) {
    child.position.sub(center);
  }
  model.scale.setScalar(AIRCRAFT_MODEL_TARGET_SIZE / longest);
}

export function placeAircraftMarker(
  marker: THREE.Group,
  point: GeographicPoint,
  bearingDegrees: number
): void {
  const visualPoint = {
    ...point,
    altitudeMeters: Math.max(point.altitudeMeters ?? 0, AIRCRAFT_VISUAL_ALTITUDE_FLOOR_METERS)
  };
  const vector = geographicToVector3(visualPoint, 2, 180000);
  marker.position.set(vector.x, vector.y, vector.z);

  const normal = marker.position.clone().normalize();
  const forward = forwardVector(normal, bearingDegrees);
  marker.up.copy(normal);
  marker.lookAt(marker.position.clone().add(forward));
}

function forwardVector(normal: THREE.Vector3, bearingDegrees: number): THREE.Vector3 {
  const northPole = new THREE.Vector3(0, 1, 0);
  const east = new THREE.Vector3().crossVectors(northPole, normal);
  if (east.lengthSq() < 0.000001) {
    east.set(1, 0, 0).cross(normal);
  }
  east.normalize();

  const north = new THREE.Vector3().crossVectors(normal, east).normalize();
  const bearing = THREE.MathUtils.degToRad(bearingDegrees);
  return north.multiplyScalar(Math.cos(bearing)).add(east.multiplyScalar(Math.sin(bearing))).normalize();
}
