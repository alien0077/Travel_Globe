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
  applyAlienAirBaseMaterials(scene);
  if (!skipSimplify) {
    simplifyIfNeeded(scene, 33000);
  }
  forceTriangleBudget(scene, 33000);
  centerScene(scene);
  applyAlienAirAccentMaterials(scene);

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

function forceTriangleBudget(scene, targetTriangles) {
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
    const triangles = triangleCount(geometry);
    if (triangles < 12) {
      return;
    }

    const keepTriangles = Math.max(4, Math.floor(triangles * ratio));
    if (keepTriangles >= triangles) {
      return;
    }

    const reduced = reduceGeometryTriangles(geometry, keepTriangles);
    reduced.computeVertexNormals();
    geometry.dispose?.();
    object.geometry = reduced;
  });
}

function triangleCount(geometry) {
  return geometry.index ? geometry.index.count / 3 : geometry.attributes.position.count / 3;
}

function reduceGeometryTriangles(geometry, keepTriangles) {
  const position = geometry.attributes.position;
  const index = geometry.index;
  const sourceTriangles = Math.floor(triangleCount(geometry));
  const step = sourceTriangles / keepTriangles;
  const positions = [];
  const uvs = [];
  const hasUv = Boolean(geometry.attributes.uv);

  for (let kept = 0; kept < keepTriangles; kept += 1) {
    const triangleIndex = Math.min(sourceTriangles - 1, Math.floor(kept * step));
    for (let corner = 0; corner < 3; corner += 1) {
      const vertexIndex = index ? index.getX(triangleIndex * 3 + corner) : triangleIndex * 3 + corner;
      positions.push(position.getX(vertexIndex), position.getY(vertexIndex), position.getZ(vertexIndex));
      if (hasUv) {
        const uv = geometry.attributes.uv;
        uvs.push(uv.getX(vertexIndex), uv.getY(vertexIndex));
      }
    }
  }

  const reduced = new THREE.BufferGeometry();
  reduced.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  if (hasUv) {
    reduced.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  }
  return reduced;
}

function centerScene(scene) {
  const box = new THREE.Box3().setFromObject(scene);
  const center = box.getCenter(new THREE.Vector3());
  scene.position.sub(center);
  scene.updateMatrixWorld(true);
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

  entry.status = triangles <= manifest.policy.polygonBudget.max ? 'ready' : 'candidate';
  entry.modelUrl = modelUrl;
  entry.format = 'glb';
  entry.actualTriangles = triangles;
  entry.polygonBudget.actual = triangles;
  entry.neutralizeLivery = false;
  entry.modifications = unique([
    ...(entry.modifications ?? []),
    'Repainted as Alien Air red and white livery',
    'Removed original airline livery',
    'Replaced floating decal panels with integrated material livery'
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
    'Replaced floating decal panels with integrated material livery'
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
