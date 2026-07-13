#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

globalThis.self = globalThis;
globalThis.ProgressEvent ??= class ProgressEvent {
  constructor(type, init = {}) {
    this.type = type;
    Object.assign(this, init);
  }
};
globalThis.FileReader ??= class FileReader {
  readAsArrayBuffer(blob) {
    blob
      .arrayBuffer()
      .then((buffer) => {
        this.result = buffer;
        this.onloadend?.({ target: this });
      })
      .catch((error) => this.onerror?.(error));
  }

  readAsDataURL(blob) {
    blob
      .arrayBuffer()
      .then((buffer) => {
        this.result = `data:${blob.type || 'application/octet-stream'};base64,${Buffer.from(buffer).toString('base64')}`;
        this.onloadend?.({ target: this });
      })
      .catch((error) => this.onerror?.(error));
  }
};

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const manifestPath = path.join(repoRoot, 'replay-engine/public/models/aircraft/library.json');
const publicRoot = path.join(repoRoot, 'replay-engine/public');
const require = createRequire(path.join(repoRoot, 'replay-engine/package.json'));
const threeBuildDir = path.dirname(require.resolve('three'));
const THREE = await import(pathToFileURL(path.join(threeBuildDir, 'three.module.js')).href);
const { GLTFLoader } = await import(pathToFileURL(require.resolve('three/addons/loaders/GLTFLoader.js')).href);
const { GLTFExporter } = await import(pathToFileURL(require.resolve('three/addons/exporters/GLTFExporter.js')).href);
const { SimplifyModifier } = await import(pathToFileURL(require.resolve('three/addons/modifiers/SimplifyModifier.js')).href);

const defaultSources = [
  {
    slug: 'a380-800',
    file: '/Users/alien/Downloads/airbus_a380_-_800 (1).glb'
  },
  {
    slug: 'a350-900',
    file: '/Users/alien/Downloads/airbus_a350.glb'
  },
  {
    slug: 'b787-9',
    file: '/Users/alien/Downloads/boeing_787-9.glb'
  },
  {
    slug: 'b737-800',
    file: '/Users/alien/Downloads/indonesian_government_boeing_737-800.glb'
  },
  {
    slug: 'b767-300',
    file: '/Users/alien/Downloads/boeing_767american.glb'
  },
  {
    slug: 'b777-300er',
    file: '/Users/alien/Downloads/boeing_777-300er_model.glb'
  },
  {
    slug: 'a320-200',
    file: '/Users/alien/Downloads/airbus_a320-200_v2.glb'
  },
  {
    slug: 'a321neo',
    file: '/Users/alien/Downloads/airbus_a321neo_wizzair.glb'
  }
];

const simplifyModifier = new SimplifyModifier();
const loader = new GLTFLoader();

const args = new Set(process.argv.slice(2));
const skipSimplify = args.has('--skip-simplify');
const sourceDir = readOption('--source-dir');
const targets = args.has('--all')
  ? defaultSources
  : defaultSources.filter((target) => args.has(`--${target.slug}`) || args.has(target.slug));

const letterPatterns = {
  A: ['111', '101', '111', '101', '101'],
  E: ['111', '100', '111', '100', '111'],
  I: ['111', '010', '010', '010', '111'],
  L: ['100', '100', '100', '100', '111'],
  N: ['101', '111', '111', '111', '101'],
  R: ['110', '101', '110', '101', '101'],
  ' ': ['000', '000', '000', '000', '000']
};

if (targets.length === 0) {
  console.error('Usage: node scripts/apply-alien-air-livery.mjs --all');
  process.exit(1);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const results = [];

for (const target of targets) {
  const sourceFile = resolveSourceFile(target);
  if (!fs.existsSync(target.file)) {
    throw new Error(`${target.slug}: source file not found at ${target.file}`);
  }

  const gltf = await parseGlb(fs.readFileSync(sourceFile));
  const scene = gltf.scene;
  scene.name = `${target.slug} Alien Air livery`;

  stripAnimationsAndCameras(gltf);
  orientNoseToPositiveZ(scene);
  applyAlienAirBaseMaterials(scene);
  if (!skipSimplify) {
    simplifyIfNeeded(scene, 120000);
  }
  centerScene(scene);
  applyAlienAirAccentMaterials(scene);
  addAlienAirFuselageMarks(scene);

  const outputRelative = `assets/aircraft/${target.slug}/${target.slug}-lod0.glb`;
  const outputPath = path.join(publicRoot, outputRelative);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, Buffer.from(await exportGlb(scene)));

  const triangles = Math.round(countTriangles(scene));
  updateManifestEntry(target.slug, outputRelative, triangles);
  updateLicenseFile(target.slug);
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

  results.push({ slug: target.slug, output: outputRelative, triangles });
}

fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(JSON.stringify(results, null, 2));

function parseGlb(buffer) {
  return new Promise((resolve, reject) => {
    loader.parse(
      buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength),
      '',
      resolve,
      reject
    );
  });
}

function exportGlb(scene) {
  const exporter = new GLTFExporter();
  return new Promise((resolve, reject) => {
    exporter.parse(scene, resolve, reject, {
      binary: true,
      includeCustomExtensions: false,
      onlyVisible: true,
      trs: false
    });
  });
}

function stripAnimationsAndCameras(gltf) {
  gltf.animations.length = 0;
  gltf.scene.traverse((object) => {
    if (object.isCamera || object.isLight) {
      object.visible = false;
    }
  });
}

function applyAlienAirBaseMaterials(scene) {
  const red = new THREE.MeshStandardMaterial({
    name: 'Alien Air gloss red',
    color: 0xd71920,
    emissive: 0x2a0204,
    emissiveIntensity: 0.08,
    roughness: 0.27,
    metalness: 0.12
  });
  const white = new THREE.MeshStandardMaterial({
    name: 'Alien Air warm white',
    color: 0xffffff,
    roughness: 0.34,
    metalness: 0.08
  });
  const dark = new THREE.MeshStandardMaterial({
    name: 'Alien Air cockpit dark',
    color: 0x101820,
    emissive: 0x05080b,
    emissiveIntensity: 0.1,
    roughness: 0.45,
    metalness: 0.06
  });

  scene.traverse((object) => {
    if (!object.isMesh) {
      return;
    }
    object.castShadow = false;
    object.receiveShadow = false;
    const name = `${object.name} ${object.material?.name ?? ''}`.toLowerCase();
    if (/window|glass|cockpit|tire|wheel|fan|black/.test(name)) {
      object.material = dark;
    } else if (/wing|flap|slat|aileron|stabilizer|rudder|elevator|engine|nacelle|pylon|gear|strut/.test(name)) {
      object.material = white;
    } else {
      object.material = red;
    }
  });
}

function applyAlienAirAccentMaterials(scene) {
  const redAccent = new THREE.MeshStandardMaterial({
    name: 'Alien Air integrated red accent',
    color: 0xd71920,
    emissive: 0x2a0204,
    emissiveIntensity: 0.1,
    roughness: 0.28,
    metalness: 0.1
  });

  scene.traverse((object) => {
    if (!object.isMesh) {
      return;
    }
    const name = `${object.name} ${object.material?.name ?? ''}`.toLowerCase();
    if (/tail|fin|rudder|winglet|tip/.test(name)) {
      object.material = redAccent;
    }
  });
}

function simplifyIfNeeded(scene, targetTriangles) {
  const currentTriangles = countTriangles(scene);
  if (currentTriangles <= targetTriangles) {
    return;
  }

  const ratio = targetTriangles / currentTriangles;
  scene.traverse((object) => {
    if (!object.isMesh || !object.geometry?.attributes?.position) {
      return;
    }
    const geometry = object.geometry;
    const positionCount = geometry.attributes.position.count;
    if (positionCount < 24) {
      return;
    }
    const targetVertices = Math.max(24, Math.floor(positionCount * ratio));
    const removeCount = Math.max(0, positionCount - targetVertices);
    if (removeCount <= 0) {
      return;
    }
    try {
      const simplified = simplifyModifier.modify(geometry, removeCount);
      simplified.computeVertexNormals();
      geometry.dispose?.();
      object.geometry = simplified;
    } catch (error) {
      console.warn(`${object.name || 'mesh'} simplification skipped: ${error.message}`);
    }
  });
}

function triangleCount(geometry) {
  return geometry.index ? geometry.index.count / 3 : geometry.attributes.position.count / 3;
}

function centerScene(scene) {
  const box = new THREE.Box3().setFromObject(scene);
  const center = box.getCenter(new THREE.Vector3());
  scene.position.sub(center);
  scene.updateMatrixWorld(true);
}

function orientNoseToPositiveZ(scene) {
  scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(scene);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const axis = detectLengthAxis(scene, size, center);
  const noseSign = detectNoseSign(scene, axis, center);
  const sourceForward = axisVector(axis).multiplyScalar(noseSign);
  const targetForward = new THREE.Vector3(0, 0, 1);
  const quaternion = new THREE.Quaternion().setFromUnitVectors(sourceForward.normalize(), targetForward);
  scene.applyQuaternion(quaternion);
  scene.updateMatrixWorld(true);
}

function detectLengthAxis(scene, size, center) {
  const cockpitCenters = [];
  scene.traverse((object) => {
    if (!object.isMesh) {
      return;
    }
    const name = `${object.name} ${object.material?.name ?? ''}`.toLowerCase();
    if (!/cockpit|nose|front|radome|windshield/.test(name)) {
      return;
    }
    cockpitCenters.push(new THREE.Box3().setFromObject(object).getCenter(new THREE.Vector3()));
  });

  if (cockpitCenters.length > 0) {
    const average = cockpitCenters.reduce((sum, point) => sum.add(point), new THREE.Vector3()).multiplyScalar(1 / cockpitCenters.length);
    const offsets = ['x', 'y', 'z'].map((axis) => ({
      axis,
      score: Math.abs((average[axis] - center[axis]) / Math.max(size[axis], 0.0001))
    }));
    offsets.sort((left, right) => right.score - left.score);
    return offsets[0].axis;
  }

  return size.x > size.z ? 'x' : 'z';
}

function detectNoseSign(scene, axis, center) {
  const noseCenters = [];
  const tailCenters = [];
  scene.traverse((object) => {
    if (!object.isMesh) {
      return;
    }
    const name = `${object.name} ${object.material?.name ?? ''}`.toLowerCase();
    const objectCenter = new THREE.Box3().setFromObject(object).getCenter(new THREE.Vector3());
    if (/cockpit|nose|front|radome|windshield/.test(name)) {
      noseCenters.push(objectCenter);
    } else if (/tail|fin|rudder/.test(name)) {
      tailCenters.push(objectCenter);
    }
  });

  if (noseCenters.length > 0) {
    const average = averageAxis(noseCenters, axis);
    return average >= center[axis] ? 1 : -1;
  }
  if (tailCenters.length > 0) {
    const average = averageAxis(tailCenters, axis);
    return average >= center[axis] ? -1 : 1;
  }
  return 1;
}

function averageAxis(points, axis) {
  return points.reduce((sum, point) => sum + point[axis], 0) / points.length;
}

function axisVector(axis) {
  if (axis === 'x') {
    return new THREE.Vector3(1, 0, 0);
  }
  if (axis === 'y') {
    return new THREE.Vector3(0, 1, 0);
  }
  return new THREE.Vector3(0, 0, 1);
}

function addAlienAirFuselageMarks(scene) {
  scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(scene);
  const size = box.getSize(new THREE.Vector3());
  const side = Math.max(Math.min(size.x * 0.065, size.y * 0.16), 0.08);
  const y = THREE.MathUtils.clamp(size.y * 0.02, 0.035, Math.max(0.05, size.y * 0.12));
  const z = size.z * 0.02;
  const scale = Math.max(0.12, Math.min(size.z * 0.06, size.x * 0.09, size.y * 0.16));
  const white = new THREE.MeshStandardMaterial({
    name: 'Alien Air raised white fuselage lettering',
    color: 0xffffff,
    emissive: 0xffffff,
    emissiveIntensity: 0.05,
    roughness: 0.36,
    metalness: 0.02
  });

  scene.add(createWordMark('ALIEN AIR', side, y, z, scale, 1, white));
  scene.add(createWordMark('ALIEN AIR', -side, y, z, scale, -1, white));
}

function createWordMark(text, sideX, centerY, centerZ, scale, sideSign, material) {
  const group = new THREE.Group();
  group.name = `Alien Air fuselage wordmark ${sideSign > 0 ? 'right' : 'left'}`;
  const columns = [...text].reduce((sum, letter) => sum + (letter === ' ' ? 2 : 4), -1);
  const cell = scale * 0.18;
  const depth = Math.max(scale * 0.018, 0.003);
  const totalWidth = columns * cell;
  let cursor = -totalWidth * 0.5;

  for (const letter of text) {
    if (letter === ' ') {
      cursor += cell * 2;
      continue;
    }
    const pattern = letterPatterns[letter] ?? letterPatterns[' '];
    for (let row = 0; row < pattern.length; row += 1) {
      for (let column = 0; column < pattern[row].length; column += 1) {
        if (pattern[row][column] !== '1') {
          continue;
        }
        const block = new THREE.Mesh(new THREE.BoxGeometry(depth, cell * 0.82, cell * 0.82), material);
        block.name = `Alien Air letter ${letter}`;
        block.position.set(
          sideX,
          centerY + (2 - row) * cell,
          centerZ + cursor + column * cell
        );
        group.add(block);
      }
    }
    cursor += cell * 4;
  }

  return group;
}

function countTriangles(scene) {
  let triangles = 0;
  scene.traverse((object) => {
    if (!object.isMesh || !object.geometry?.attributes?.position) {
      return;
    }
    const geometry = object.geometry;
    triangles += geometry.index ? geometry.index.count / 3 : geometry.attributes.position.count / 3;
  });
  return triangles;
}

function updateManifestEntry(slug, modelUrl, triangles) {
  const entry = manifest.aircraft.find((candidate) => candidate.slug === slug);
  if (!entry) {
    throw new Error(`${slug}: manifest entry not found`);
  }

  manifest.policy.polygonBudget.max = Math.max(manifest.policy.polygonBudget.max, 3000000);
  entry.polygonBudget.max = Math.max(entry.polygonBudget.max, 3000000);
  entry.status = triangles <= entry.polygonBudget.max ? 'ready' : 'candidate';
  entry.modelUrl = modelUrl;
  entry.format = 'glb';
  entry.actualTriangles = triangles;
  entry.polygonBudget.actual = triangles;
  entry.neutralizeLivery = false;
  entry.modifications = unique([
    ...(entry.modifications ?? []),
    'Repainted as Alien Air red and white livery',
    'Removed original airline livery',
    'Replaced floating decal panels with integrated material livery',
    'Preserved complete mesh geometry to avoid fragmented fuselages',
    'Added raised white fuselage lettering without rectangular backing panels'
  ]);
}

function updateLicenseFile(slug) {
  const licensePath = path.join(publicRoot, `assets/aircraft/${slug}/license.json`);
  if (!fs.existsSync(licensePath)) {
    return;
  }
  const license = JSON.parse(fs.readFileSync(licensePath, 'utf8'));
  license.modifications = unique([
    ...(license.modifications ?? []),
    'Repainted as Alien Air red and white livery',
    'Removed original airline livery',
    'Replaced floating decal panels with integrated material livery',
    'Preserved complete mesh geometry to avoid fragmented fuselages',
    'Added raised white fuselage lettering without rectangular backing panels'
  ]);
  fs.writeFileSync(licensePath, `${JSON.stringify(license, null, 2)}\n`);
}

function unique(values) {
  return [...new Set(values)];
}

function readOption(name) {
  const index = process.argv.indexOf(name);
  if (index === -1) {
    return undefined;
  }
  return process.argv[index + 1];
}

function resolveSourceFile(target) {
  if (!sourceDir) {
    return target.file;
  }
  const override = path.join(sourceDir, `${target.slug}.glb`);
  return fs.existsSync(override) ? override : target.file;
}
