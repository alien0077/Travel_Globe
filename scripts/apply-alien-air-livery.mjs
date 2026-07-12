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

const blockFont = {
  A: ['01110', '10001', '10001', '11111', '10001', '10001', '10001'],
  E: ['11111', '10000', '10000', '11110', '10000', '10000', '11111'],
  I: ['111', '010', '010', '010', '010', '010', '111'],
  L: ['10000', '10000', '10000', '10000', '10000', '10000', '11111'],
  N: ['10001', '11001', '10101', '10011', '10001', '10001', '10001'],
  R: ['11110', '10001', '10001', '11110', '10100', '10010', '10001'],
  '?': ['111', '001', '010', '010', '000', '010', '000']
};

const defaultSources = [
  {
    slug: 'a380-800',
    file: '/Users/alien/Downloads/airbus_a380_-_800 (1).glb',
    lengthAxis: 'z'
  },
  {
    slug: 'a350-900',
    file: '/Users/alien/Downloads/airbus_a350.glb',
    lengthAxis: 'z'
  },
  {
    slug: 'b787-9',
    file: '/Users/alien/Downloads/boeing_787-9.glb',
    lengthAxis: 'z'
  },
  {
    slug: 'b737-800',
    file: '/Users/alien/Downloads/indonesian_government_boeing_737-800.glb',
    lengthAxis: 'x'
  },
  {
    slug: 'b767-300',
    file: '/Users/alien/Downloads/boeing_767american.glb',
    lengthAxis: 'x'
  },
  {
    slug: 'b777-300er',
    file: '/Users/alien/Downloads/boeing_777-300er_model.glb',
    lengthAxis: 'x'
  },
  {
    slug: 'a320-200',
    file: '/Users/alien/Downloads/airbus_a320-200_v2.glb',
    lengthAxis: 'z'
  },
  {
    slug: 'a321neo',
    file: '/Users/alien/Downloads/airbus_a321neo_wizzair.glb',
    lengthAxis: 'z'
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
  addAlienAirDecals(scene, target.lengthAxis);

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
    color: 0xe21725,
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
    } else if (/engine|nacelle|pylon|gear|strut/.test(name)) {
      object.material = white;
    } else {
      object.material = red;
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

function addAlienAirDecals(scene, lengthAxisName) {
  const box = new THREE.Box3().setFromObject(scene);
  const size = box.getSize(new THREE.Vector3());
  const lengthAxis = axisVector(lengthAxisName);
  const verticalAxis = axisVector('y');
  const sideAxisName = lengthAxisName === 'x' ? 'z' : 'x';
  const sideAxis = axisVector(sideAxisName);
  const length = axisSize(size, lengthAxisName);
  const side = axisSize(size, sideAxisName);
  const height = size.y;
  const sideOffset = Math.max(side * 0.12, height * 0.2);
  const topY = box.max.y + height * 0.018;

  for (const sign of [-1, 1]) {
    const normal = sideAxis.clone().multiplyScalar(sign);
    const panel = createTextPanel({
      text: 'ALIEN AIR',
      width: length * 0.48,
      height: height * 0.18,
      fontSize: height * 0.08,
      normal,
      u: lengthAxis,
      v: verticalAxis,
      panelColor: 0xc90012,
      textColor: 0xffffff
    });
    panel.position.copy(normal.clone().multiplyScalar(sideOffset));
    panel.position.y += height * 0.06;
    scene.add(panel);
  }

  for (const sign of [-1, 1]) {
    const normal = verticalAxis.clone();
    const u = sideAxis.clone().multiplyScalar(sign);
    const wing = createTextPanel({
      text: 'ALIEN',
      width: side * 0.32,
      height: length * 0.09,
      fontSize: Math.min(side, length) * 0.035,
      normal,
      u,
      v: lengthAxis,
      panelColor: 0xc90012,
      textColor: 0xffffff
    });
    wing.position.copy(sideAxis.clone().multiplyScalar(sign * side * 0.28));
    wing.position.add(lengthAxis.clone().multiplyScalar(-length * 0.04));
    wing.position.y = topY;
    scene.add(wing);
  }

  for (const sign of [-1, 1]) {
    const normal = lengthAxis.clone().multiplyScalar(sign);
    const tail = createTextPanel({
      text: 'AA',
      width: side * 0.2,
      height: height * 0.26,
      fontSize: height * 0.12,
      normal,
      u: sideAxis,
      v: verticalAxis,
      panelColor: 0xc90012,
      textColor: 0xffffff
    });
    tail.position.copy(lengthAxis.clone().multiplyScalar(sign * length * 0.42));
    tail.position.y += height * 0.16;
    scene.add(tail);
  }
}

function createTextPanel({ text, width, height, fontSize, normal, u, v, panelColor, textColor }) {
  const group = new THREE.Group();
  group.name = `Alien Air ${text} decal`;

  const panelMaterial = new THREE.MeshStandardMaterial({
    name: 'Alien Air decal red field',
    color: panelColor,
    emissive: 0x260000,
    emissiveIntensity: 0.08,
    roughness: 0.32,
    metalness: 0.06,
    side: THREE.DoubleSide
  });
  const textMaterial = new THREE.MeshStandardMaterial({
    name: 'Alien Air decal white lettering',
    color: textColor,
    emissive: 0xffffff,
    emissiveIntensity: 0.04,
    roughness: 0.28,
    metalness: 0.02,
    side: THREE.DoubleSide
  });

  const panel = new THREE.Mesh(new THREE.PlaneGeometry(width, height), panelMaterial);
  panel.name = `${text} red background`;
  group.add(panel);

  const label = createBlockText(text, fontSize, textMaterial);
  label.name = `${text} white block lettering`;
  label.position.z = Math.max(fontSize * 0.018, 0.003);
  group.add(label);

  const outline = new THREE.Mesh(
    new THREE.PlaneGeometry(width * 1.035, height * 1.12),
    new THREE.MeshStandardMaterial({
      name: 'Alien Air white decal trim',
      color: 0xffffff,
      roughness: 0.35,
      metalness: 0.04,
      side: THREE.DoubleSide
    })
  );
  outline.name = `${text} white trim`;
  outline.position.z = -Math.max(fontSize * 0.012, 0.001);
  group.add(outline);
  outline.renderOrder = -1;

  const basisU = u.clone().normalize();
  const basisV = v.clone().normalize();
  const basisN = normal.clone().normalize();
  if (new THREE.Vector3().crossVectors(basisU, basisV).dot(basisN) < 0) {
    basisU.multiplyScalar(-1);
  }
  const matrix = new THREE.Matrix4().makeBasis(basisU, basisV, basisN);
  group.applyMatrix4(matrix);
  return group;
}

function createBlockText(text, height, material) {
  const group = new THREE.Group();
  const scale = height / 7;
  let cursor = 0;
  const gap = scale;

  for (const char of text.toUpperCase()) {
    if (char === ' ') {
      cursor += scale * 3;
      continue;
    }

    const pattern = blockFont[char] ?? blockFont['?'];
    const width = pattern[0].length;
    for (let row = 0; row < pattern.length; row += 1) {
      for (let column = 0; column < width; column += 1) {
        if (pattern[row][column] !== '1') {
          continue;
        }
        const pixel = new THREE.Mesh(new THREE.PlaneGeometry(scale * 0.88, scale * 0.88), material);
        pixel.position.set(cursor + column * scale, (6 - row) * scale, 0);
        group.add(pixel);
      }
    }
    cursor += width * scale + gap;
  }

  const box = new THREE.Box3().setFromObject(group);
  const center = box.getCenter(new THREE.Vector3());
  group.position.sub(center);
  return group;
}

function axisVector(axisName) {
  if (axisName === 'x') return new THREE.Vector3(1, 0, 0);
  if (axisName === 'y') return new THREE.Vector3(0, 1, 0);
  return new THREE.Vector3(0, 0, 1);
}

function axisSize(size, axisName) {
  if (axisName === 'x') return size.x;
  if (axisName === 'y') return size.y;
  return size.z;
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
  entry.neutralizeLivery = false;
  entry.modifications = unique([
    ...(entry.modifications ?? []),
    'Repainted as Alien Air red and white livery',
    'Removed original airline livery',
    'Added fuselage, wing, and tail Alien Air markings'
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
    'Added fuselage, wing, and tail Alien Air markings'
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
