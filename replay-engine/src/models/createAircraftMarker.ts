import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { resolveBundledAsset } from '../assets/resolveBundledAsset';
import type { GeographicPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';
import {
  selectAircraftModel,
  type AircraftModelLibrary
} from './aircraftModelLibrary';

export const AIRCRAFT_MODEL_TARGET_SIZE = 0.16;
export const AIRCRAFT_VISUAL_ALTITUDE_FLOOR_METERS = 3500;

export function createAircraftMarker(aircraftType?: string): THREE.Group {
  const aircraft = new THREE.Group();
  aircraft.name = aircraftType ? `Aircraft ${aircraftType}` : 'Aircraft library marker';
  aircraft.add(createFallbackAircraftModel());
  void loadExternalAircraftModel(aircraft, aircraftType);
  return aircraft;
}

async function loadExternalAircraftModel(aircraft: THREE.Group, aircraftType: string | undefined): Promise<void> {
  const library = await readAircraftModelLibrary();
  const selected = library ? selectAircraftModel(library, aircraftType) : undefined;
  if (!selected) {
    return;
  }

  const modelUrl = resolveBundledAsset(selected.modelUrl);
  const loader = new GLTFLoader();
  loader.load(
    modelUrl,
    (gltf) => {
      const model = gltf.scene;
      model.name = `${selected.id} external aircraft model`;
      if (selected.neutralizeLivery) {
        neutralizeAircraftLivery(model);
      }
      normalizeExternalModel(model);
      aircraft.clear();
      aircraft.add(model);

      const beacon = new THREE.PointLight(0x9addff, 0.85, 0.7);
      beacon.position.set(0, 0.072, -0.08);
      aircraft.add(beacon);
    },
    undefined,
    () => undefined
  );
}

async function readAircraftModelLibrary(): Promise<AircraftModelLibrary | undefined> {
  try {
    const response = await fetch(resolveBundledAsset('models/aircraft/library.json'));
    if (!response.ok) {
      return undefined;
    }
    return (await response.json()) as AircraftModelLibrary;
  } catch {
    return undefined;
  }
}

function neutralizeAircraftLivery(root: THREE.Object3D): void {
  const materials = createNeutralLiveryMaterials();
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) {
      return;
    }

    const name = `${object.name} ${object.material instanceof THREE.Material ? object.material.name : ''}`.toLowerCase();
    object.material = chooseNeutralMaterial(name, materials);
    object.castShadow = false;
    object.receiveShadow = false;
  });
}

function createNeutralLiveryMaterials(): Record<'body' | 'wing' | 'engine' | 'dark' | 'accent', THREE.Material> {
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
      color: 0x2a817b,
      emissive: 0x145d58,
      emissiveIntensity: 0.18,
      roughness: 0.32
    })
  };
}

function chooseNeutralMaterial(
  name: string,
  materials: Record<'body' | 'wing' | 'engine' | 'dark' | 'accent', THREE.Material>
): THREE.Material {
  if (/window|glass|cockpit|tire|wheel|fan|inlet|black/.test(name)) {
    return materials.dark;
  }
  if (/engine|nacelle|turbine|pylon/.test(name)) {
    return materials.engine;
  }
  if (/wing|flap|slat|aileron|stabilizer|tail|rudder|elevator/.test(name)) {
    return materials.wing;
  }
  if (/stripe|logo|livery|paint|decal/.test(name)) {
    return materials.accent;
  }
  return materials.body;
}

function normalizeExternalModel(model: THREE.Object3D): void {
  const box = new THREE.Box3().setFromObject(model);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const longest = Math.max(size.x, size.y, size.z);
  if (longest <= 0) {
    return;
  }

  model.position.sub(center);
  model.scale.setScalar(AIRCRAFT_MODEL_TARGET_SIZE / longest);
  model.rotation.set(0, 0, 0);
}

function createFallbackAircraftModel(): THREE.Group {
  const group = new THREE.Group();
  group.name = 'fallback visible aircraft model';
  const bodyMaterial = new THREE.MeshStandardMaterial({
    color: 0xf8fbff,
    emissive: 0x5f8fb3,
    emissiveIntensity: 0.22,
    roughness: 0.32,
    metalness: 0.12
  });
  const wingMaterial = new THREE.MeshStandardMaterial({
    color: 0xd7f2ff,
    emissive: 0x2a6f9d,
    emissiveIntensity: 0.2,
    roughness: 0.36,
    metalness: 0.08,
    side: THREE.DoubleSide
  });
  const accentMaterial = new THREE.MeshStandardMaterial({
    color: 0x2a817b,
    emissive: 0x1f7779,
    emissiveIntensity: 0.24,
    roughness: 0.34
  });

  const fuselage = new THREE.Mesh(new THREE.CapsuleGeometry(0.018, 0.13, 8, 16), bodyMaterial);
  fuselage.rotation.x = Math.PI / 2;
  group.add(fuselage);

  const wing = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.004, 0.024), wingMaterial);
  wing.position.z = -0.01;
  group.add(wing);

  const tailWing = new THREE.Mesh(new THREE.BoxGeometry(0.062, 0.004, 0.016), wingMaterial);
  tailWing.position.z = -0.07;
  group.add(tailWing);

  const verticalTail = new THREE.Mesh(new THREE.BoxGeometry(0.008, 0.044, 0.022), accentMaterial);
  verticalTail.position.set(0, 0.022, -0.077);
  group.add(verticalTail);

  return group;
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
