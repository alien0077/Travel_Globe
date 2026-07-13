import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { resolveBundledAsset } from '../assets/resolveBundledAsset';
import type { GeographicPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';
import {
  selectAircraftModel,
  type AircraftModelLibrary
} from './aircraftModelLibrary';

export function createAircraftMarker(aircraftType?: string): THREE.Group {
  const aircraft = new THREE.Group();
  aircraft.name = aircraftType ? `Aircraft ${aircraftType}` : 'Aircraft library marker';
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
    () => {
      aircraft.clear();
    }
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
      color: 0x142c44,
      emissive: 0x07131f,
      emissiveIntensity: 0.14,
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
  model.scale.setScalar(0.18 / longest);
  model.rotation.set(0, 0, 0);
}

export function placeAircraftMarker(
  marker: THREE.Group,
  point: GeographicPoint,
  bearingDegrees: number
): void {
  const visualPoint = {
    ...point,
    altitudeMeters: Math.max(point.altitudeMeters ?? 0, 120000)
  };
  const vector = geographicToVector3(visualPoint, 2, 700000);
  marker.position.set(vector.x, vector.y, vector.z);

  const normal = marker.position.clone().normalize();
  const tangent = new THREE.Vector3(1, 0, 0).applyAxisAngle(normal, THREE.MathUtils.degToRad(bearingDegrees));
  marker.lookAt(marker.position.clone().add(tangent));
  marker.up.copy(normal);
}
