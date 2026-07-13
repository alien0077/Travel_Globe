import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { resolveBundledAsset } from '../assets/resolveBundledAsset';
import type { GeographicPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';
import {
  DEFAULT_AIRCRAFT_TYPE,
  REQUIRED_AIRCRAFT_TYPES,
  normalizeAircraftType,
  selectAircraftModel,
  type AircraftModelLibrary,
  type RequiredAircraftType
} from './aircraftModelLibrary';

export const AIRCRAFT_MODEL_TARGET_SIZE = 0.16;
export const AIRCRAFT_VISUAL_ALTITUDE_FLOOR_METERS = 3500;

interface AircraftModelCorrection {
  rotation?: [number, number, number];
  scaleMultiplier?: number;
  yOffset?: number;
}

const AIRCRAFT_MODEL_CORRECTIONS: Partial<Record<RequiredAircraftType, AircraftModelCorrection>> = {
  A321: { scaleMultiplier: 0.9 },
  B767: { rotation: [0, Math.PI / 2, 0], scaleMultiplier: 0.88 },
  B777: { scaleMultiplier: 0.82 },
  A380: { rotation: [0, Math.PI / 2, 0], scaleMultiplier: 0.9 }
};

const aircraftModelCache = new Map<string, Promise<THREE.Group | undefined>>();

export function createAircraftMarker(aircraftType?: string): THREE.Group {
  const aircraft = new THREE.Group();
  const normalizedType = normalizeRequestedAircraftType(aircraftType);
  aircraft.name = `Aircraft ${normalizedType}`;
  aircraft.add(createLoadingAircraftSilhouette());
  void loadExternalAircraftModel(aircraft, aircraftType);
  return aircraft;
}

function normalizeRequestedAircraftType(aircraftType: string | undefined): RequiredAircraftType {
  const normalized = normalizeAircraftType(aircraftType ?? DEFAULT_AIRCRAFT_TYPE);
  return REQUIRED_AIRCRAFT_TYPES.includes(normalized as RequiredAircraftType)
    ? (normalized as RequiredAircraftType)
    : DEFAULT_AIRCRAFT_TYPE;
}

async function loadExternalAircraftModel(aircraft: THREE.Group, aircraftType: string | undefined): Promise<void> {
  const library = await readAircraftModelLibrary();
  const selected = library ? selectAircraftModel(library, aircraftType ?? DEFAULT_AIRCRAFT_TYPE) : undefined;
  if (!selected) {
    return;
  }

  const model = await cachedAircraftModel(selected.id, selected.modelUrl, selected.neutralizeLivery);
  if (!model) {
    return;
  }

  aircraft.clear();
  aircraft.name = `Aircraft ${selected.id}`;
  aircraft.add(model);

  const beacon = new THREE.PointLight(0x9addff, 0.85, 0.7);
  beacon.position.set(0, 0.07, -0.08);
  aircraft.add(beacon);
}

function cachedAircraftModel(
  aircraftType: RequiredAircraftType,
  modelPath: string,
  neutralizeLivery: boolean
): Promise<THREE.Group | undefined> {
  const cacheKey = `${aircraftType}:${modelPath}:${neutralizeLivery ? 'neutral' : 'original'}`;
  const existing = aircraftModelCache.get(cacheKey);
  if (existing) {
    return existing.then((model) => model?.clone(true));
  }

  const promise = loadAircraftModel(aircraftType, modelPath, neutralizeLivery);
  aircraftModelCache.set(cacheKey, promise);
  return promise.then((model) => model?.clone(true));
}

async function loadAircraftModel(
  aircraftType: RequiredAircraftType,
  modelPath: string,
  neutralizeLivery: boolean
): Promise<THREE.Group | undefined> {
  return new Promise((resolve) => {
    const loader = new GLTFLoader();
    loader.load(
      resolveBundledAsset(modelPath),
      (gltf) => {
        const model = gltf.scene;
        model.name = `${aircraftType} external aircraft model`;
        if (neutralizeLivery) {
          neutralizeAircraftLivery(model);
        }
        prepareAircraftMeshes(model);
        normalizeExternalModel(model, aircraftType);
        resolve(model);
      },
      undefined,
      () => resolve(undefined)
    );
  });
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

function prepareAircraftMeshes(root: THREE.Object3D): void {
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) {
      return;
    }

    object.castShadow = false;
    object.receiveShadow = false;
    object.frustumCulled = false;
    forceDoubleSidedMaterial(object.material);
  });
}

function forceDoubleSidedMaterial(material: THREE.Material | THREE.Material[]): void {
  const materials = Array.isArray(material) ? material : [material];
  for (const item of materials) {
    item.side = THREE.DoubleSide;
    item.needsUpdate = true;
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

function normalizeExternalModel(model: THREE.Group, aircraftType: RequiredAircraftType): void {
  const correction = AIRCRAFT_MODEL_CORRECTIONS[aircraftType] ?? {};
  model.position.set(0, 0, 0);
  model.scale.setScalar(1);
  model.rotation.set(...(correction.rotation ?? [0, 0, 0]));
  model.updateMatrixWorld(true);

  const box = new THREE.Box3().setFromObject(model);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const longest = Math.max(size.x, size.y, size.z);
  if (longest <= 0) {
    return;
  }

  const scale = (AIRCRAFT_MODEL_TARGET_SIZE * (correction.scaleMultiplier ?? 1)) / longest;
  model.scale.setScalar(scale);
  model.position.set(
    -center.x * scale,
    -center.y * scale + (correction.yOffset ?? 0),
    -center.z * scale
  );
}

function createLoadingAircraftSilhouette(): THREE.Group {
  const group = new THREE.Group();
  group.name = `${DEFAULT_AIRCRAFT_TYPE} loading aircraft silhouette`;
  const bodyMaterial = new THREE.MeshStandardMaterial({
    color: 0xf8fbff,
    emissive: 0x5f8fb3,
    emissiveIntensity: 0.18,
    roughness: 0.34,
    metalness: 0.1
  });
  const wingMaterial = new THREE.MeshStandardMaterial({
    color: 0xd7f2ff,
    emissive: 0x2a6f9d,
    emissiveIntensity: 0.16,
    roughness: 0.36,
    metalness: 0.08,
    side: THREE.DoubleSide
  });

  const fuselage = new THREE.Mesh(new THREE.CapsuleGeometry(0.012, 0.1, 8, 14), bodyMaterial);
  fuselage.rotation.x = Math.PI / 2;
  group.add(fuselage);

  const wing = new THREE.Mesh(new THREE.BoxGeometry(0.096, 0.003, 0.018), wingMaterial);
  wing.position.z = 0.006;
  group.add(wing);

  const tailWing = new THREE.Mesh(new THREE.BoxGeometry(0.044, 0.003, 0.012), wingMaterial);
  tailWing.position.z = 0.052;
  group.add(tailWing);

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
