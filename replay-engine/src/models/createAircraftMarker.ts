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
  aircraft.add(createEmergencyAircraftMarker());
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
      aircraft.add(createEmergencyAircraftMarker());

      const beacon = new THREE.PointLight(0x9addff, 0.85, 0.7);
      beacon.position.set(0, 0.072, -0.08);
      aircraft.add(beacon);
    },
    undefined,
    () => {
      aircraft.clear();
      aircraft.add(createEmergencyAircraftMarker());
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
  model.scale.setScalar(0.9 / longest);
  model.rotation.set(0, 0, 0);
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

function createEmergencyAircraftMarker(): THREE.Group {
  const marker = new THREE.Group();
  marker.name = 'Alien Air compact aircraft marker';

  const bodyMaterial = new THREE.MeshStandardMaterial({
    color: 0xf9fbff,
    emissive: 0x7a1010,
    emissiveIntensity: 0.12,
    roughness: 0.34,
    metalness: 0.16
  });
  const accentMaterial = new THREE.MeshStandardMaterial({
    color: 0xd71920,
    emissive: 0x8a0f12,
    emissiveIntensity: 0.24,
    roughness: 0.28,
    metalness: 0.08
  });
  const darkMaterial = new THREE.MeshStandardMaterial({
    color: 0x102331,
    emissive: 0x07131f,
    emissiveIntensity: 0.16,
    roughness: 0.4
  });

  const fuselage = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.055, 0.46, 16), bodyMaterial);
  fuselage.rotation.x = Math.PI / 2;
  marker.add(fuselage);

  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.052, 0.14, 18), accentMaterial);
  nose.rotation.x = Math.PI / 2;
  nose.position.z = 0.29;
  marker.add(nose);

  const leftWing = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.012, 0.085), accentMaterial);
  leftWing.position.set(-0.16, 0, 0.02);
  leftWing.rotation.z = -0.08;
  marker.add(leftWing);

  const rightWing = leftWing.clone();
  rightWing.position.x = 0.16;
  rightWing.rotation.z = 0.08;
  marker.add(rightWing);

  const tail = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.012, 0.07), accentMaterial);
  tail.position.z = -0.22;
  marker.add(tail);

  const fin = new THREE.Mesh(new THREE.BoxGeometry(0.018, 0.12, 0.07), accentMaterial);
  fin.position.set(0, 0.06, -0.2);
  marker.add(fin);

  const cockpit = new THREE.Mesh(new THREE.SphereGeometry(0.034, 12, 8), darkMaterial);
  cockpit.scale.set(1, 0.45, 0.8);
  cockpit.position.set(0, 0.035, 0.2);
  marker.add(cockpit);

  const beacon = new THREE.PointLight(0xfff2e6, 0.7, 0.55);
  beacon.position.set(0, 0.08, 0);
  marker.add(beacon);

  marker.scale.setScalar(0.36);
  return marker;
}
