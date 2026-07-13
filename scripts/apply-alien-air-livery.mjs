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
  scene.userData.aircraftSlug = target.slug;

  stripAnimationsAndCameras(gltf);
  orientNoseToPositiveZ(scene);
  applyAlienAirBaseMaterials(scene);
  retractLandingGear(scene);
  if (!skipSimplify) {
    simplifyIfNeeded(scene, 120000);
  }
  centerScene(scene);
  applyGeometricWhiteSurfaces(scene);
  applyAlienAirAccentMaterials(scene);
  addAlienAirFuselageWordMarks(scene);

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
  const black = new THREE.MeshStandardMaterial({
    name: 'Alien Air satin black fuselage',
    color: 0x070b10,
    emissive: 0x020406,
    emissiveIntensity: 0.08,
    roughness: 0.24,
    metalness: 0.18
  });
  const white = new THREE.MeshStandardMaterial({
    name: 'Alien Air aircraft white',
    color: 0xf6f8f8,
    roughness: 0.31,
    metalness: 0.08
  });
  scene.traverse((object) => {
    if (!object.isMesh) {
      return;
    }
    object.castShadow = false;
    object.receiveShadow = false;
    const name = `${object.name} ${object.material?.name ?? ''}`.toLowerCase();
    if (/window|glass|cockpit|windshield|door|exit/.test(name)) {
      return;
    }
    if (/tire|wheel|fan|black/.test(name)) {
      return;
    } else if (/wing|flap|slat|aileron|stabilizer|rudder|elevator|engine|nacelle|pylon|gear|strut/.test(name)) {
      object.material = white;
    } else {
      object.material = black;
    }
  });
}

function applyAlienAirAccentMaterials(scene) {
  const blackAccent = new THREE.MeshStandardMaterial({
    name: 'Alien Air satin black tail',
    color: 0x05080d,
    emissive: 0x020406,
    emissiveIntensity: 0.08,
    roughness: 0.24,
    metalness: 0.16
  });

  scene.traverse((object) => {
    if (!object.isMesh) {
      return;
    }
    const name = `${object.name} ${object.material?.name ?? ''}`.toLowerCase();
    if (/tail|fin|rudder/.test(name)) {
      object.material = blackAccent;
    }
  });
}

function applyGeometricWhiteSurfaces(scene) {
  scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(scene);
  const size = box.getSize(new THREE.Vector3());
  const axes = detectFuselageAxes(size);
  const fuselage = estimateFuselageBand(scene, box, size, axes);
  const white = new THREE.MeshStandardMaterial({
    name: 'Alien Air aircraft white',
    color: 0xf6f8f8,
    roughness: 0.31,
    metalness: 0.08
  });
  const candidates = [];
  scene.traverse((object) => {
    if (!object.visible || !object.isMesh || !object.geometry?.attributes?.position || Array.isArray(object.material)) {
      return;
    }
    const name = `${object.name} ${object.parent?.name ?? ''} ${object.material?.name ?? ''}`.toLowerCase();
    if (!/alien air satin black fuselage/.test(name) || /alien air embedded/.test(name)) {
      return;
    }
    candidates.push(object);
  });

  for (const object of candidates) {
    splitWhiteSurfaceTriangles(object, white, fuselage, axes);
  }
}

function splitWhiteSurfaceTriangles(object, whiteMaterial, fuselage, axes) {
  const geometry = object.geometry;
  const position = geometry.attributes.position;
  const normal = geometry.attributes.normal;
  const uv = geometry.attributes.uv;
  const index = geometry.index;
  const blackPositions = [];
  const blackNormals = [];
  const blackUvs = [];
  const whitePositions = [];
  const whiteNormals = [];
  const whiteUvs = [];
  const local = new THREE.Vector3();
  const world = new THREE.Vector3();
  const worldTriangle = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  const localTriangle = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  const normalTriangle = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  const uvTriangle = [new THREE.Vector2(), new THREE.Vector2(), new THREE.Vector2()];
  const triangleCount = index ? index.count / 3 : position.count / 3;
  let whiteTriangles = 0;
  let blackTriangles = 0;

  for (let triangle = 0; triangle < triangleCount; triangle += 1) {
    const vertexIndices = index
      ? [index.getX(triangle * 3), index.getX(triangle * 3 + 1), index.getX(triangle * 3 + 2)]
      : [triangle * 3, triangle * 3 + 1, triangle * 3 + 2];
    const centroid = new THREE.Vector3();
    for (let corner = 0; corner < 3; corner += 1) {
      const vertexIndex = vertexIndices[corner];
      local.fromBufferAttribute(position, vertexIndex);
      localTriangle[corner].copy(local);
      world.copy(local).applyMatrix4(object.matrixWorld);
      worldTriangle[corner].copy(world);
      centroid.add(world);
      if (normal) {
        normalTriangle[corner].fromBufferAttribute(normal, vertexIndex);
      }
      if (uv) {
        uvTriangle[corner].fromBufferAttribute(uv, vertexIndex);
      }
    }
    centroid.multiplyScalar(1 / 3);
    const targetPositions = isWhiteAircraftSurface(centroid, worldTriangle, fuselage, axes) ? whitePositions : blackPositions;
    const targetNormals = targetPositions === whitePositions ? whiteNormals : blackNormals;
    const targetUvs = targetPositions === whitePositions ? whiteUvs : blackUvs;
    if (targetPositions === whitePositions) {
      whiteTriangles += 1;
    } else {
      blackTriangles += 1;
    }
    for (let corner = 0; corner < 3; corner += 1) {
      targetPositions.push(localTriangle[corner].x, localTriangle[corner].y, localTriangle[corner].z);
      if (normal) {
        targetNormals.push(normalTriangle[corner].x, normalTriangle[corner].y, normalTriangle[corner].z);
      }
      if (uv) {
        targetUvs.push(uvTriangle[corner].x, uvTriangle[corner].y);
      }
    }
  }

  if (whiteTriangles < 8 || blackTriangles < 8) {
    return;
  }

  object.geometry = buildSplitGeometry(blackPositions, blackNormals, blackUvs);
  const whiteMesh = new THREE.Mesh(buildSplitGeometry(whitePositions, whiteNormals, whiteUvs), whiteMaterial);
  whiteMesh.name = `${object.name || 'aircraft'} white wing and stabilizer surfaces`;
  whiteMesh.position.copy(object.position);
  whiteMesh.quaternion.copy(object.quaternion);
  whiteMesh.scale.copy(object.scale);
  whiteMesh.castShadow = false;
  whiteMesh.receiveShadow = false;
  object.parent?.add(whiteMesh);
}

function isWhiteAircraftSurface(centroid, triangle, fuselage, axes) {
  const sideDistance = Math.abs(centroid[axes.sideAxis] - fuselage.sideCenter);
  const wingSide = sideDistance > fuselage.halfWidth * 1.35;
  if (!wingSide) {
    return false;
  }
  const upValues = triangle.map((point) => point[axes.upAxis]);
  const upSpan = Math.max(...upValues) - Math.min(...upValues);
  const nearTailOrWing = centroid.z > fuselage.zMin - fuselage.bodyLength * 0.12 && centroid.z < fuselage.zMax + fuselage.bodyLength * 0.18;
  return nearTailOrWing && upSpan < fuselage.bodyHeight * 0.7;
}

function buildSplitGeometry(positions, normals, uvs) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  if (normals.length === positions.length) {
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  } else {
    geometry.computeVertexNormals();
  }
  if (uvs.length * 3 === positions.length * 2) {
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  }
  return geometry;
}

function retractLandingGear(scene) {
  scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(scene);
  const size = box.getSize(new THREE.Vector3());
  const axes = detectFuselageAxes(size);
  const fuselage = estimateFuselageBand(scene, box, size, axes);
  const candidates = [];
  const slug = scene.userData.aircraftSlug;

  scene.traverse((object) => {
    if (!object.isMesh) {
      return;
    }
    const materialName = Array.isArray(object.material)
      ? object.material.map((material) => material?.name ?? '').join(' ')
      : object.material?.name ?? '';
    const name = `${object.name} ${object.parent?.name ?? ''} ${materialName}`.toLowerCase();
    const knownB777Gear =
      slug === 'b777-300er' &&
      /(cylinder0(63|66|67|68|69|70|73|82|86|87)|cube0(28|32|34|36)|nurbspath0(06|07|08|15|16|18|26|27))/.test(name);
    const knownA321Gear = slug === 'a321neo' && /(mesh(7|8|35|36|51|52)|bmwx_tyre)/.test(name);
    if (/landing.?gear|gear|undercarriage|strut|wheel|tire|tyre|bogie|brake/.test(name) || knownB777Gear || knownA321Gear) {
      object.visible = false;
      return;
    }
    if (/engine|nacelle|fan|window|glass|cockpit|windshield|door|exit|alien air embedded/.test(name)) {
      return;
    }
    candidates.push(object);
  });

  for (const object of candidates) {
    const objectBox = new THREE.Box3().setFromObject(object);
    const objectSize = objectBox.getSize(new THREE.Vector3());
    const objectCenter = objectBox.getCenter(new THREE.Vector3());
    const low = objectCenter[axes.upAxis] < fuselage.upMin - fuselage.bodyHeight * 0.05;
    const compact =
      objectSize[axes.sideAxis] < fuselage.bodyHeight * 0.95 &&
      objectSize[axes.upAxis] < fuselage.bodyHeight * 0.75 &&
      objectSize.z < fuselage.bodyLength * 0.16;
    const inGearBayZone =
      objectCenter.z > fuselage.zMin - fuselage.bodyLength * 0.08 &&
      objectCenter.z < fuselage.zMax + fuselage.bodyLength * 0.08;
    const sceneLow = (objectCenter[axes.upAxis] - box.min[axes.upAxis]) / Math.max(size[axes.upAxis], 0.0001) < 0.24;
    const sceneCompact =
      objectSize[axes.sideAxis] < size[axes.sideAxis] * 0.16 &&
      objectSize[axes.upAxis] < size[axes.upAxis] * 0.16 &&
      objectSize.z < size.z * 0.14;
    const slugNeedsGeometricGearRetraction = slug === 'b777-300er' || slug === 'a321neo';
    if ((low && compact && inGearBayZone) || (slugNeedsGeometricGearRetraction && sceneLow && sceneCompact)) {
      object.visible = false;
    }
  }
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

function addAlienAirFuselageWordMarks(scene) {
  scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(scene);
  const size = box.getSize(new THREE.Vector3());
  const axes = detectFuselageAxes(size);
  const fuselage = estimateFuselageBand(scene, box, size, axes);
  const side = fuselage.halfWidth * 0.98;
  const scale = fuselage.scale;
  const white = new THREE.MeshStandardMaterial({
    name: 'Alien Air embedded white fuselage lettering',
    color: 0xffffff,
    emissive: 0xffffff,
    emissiveIntensity: 0.06,
    roughness: 0.32,
    metalness: 0.02
  });

  scene.add(
    createEmbeddedWordMark({
      side: 1,
      sidePosition: fuselage.sideCenter + side,
      centerUp: fuselage.centerUp,
      centerZ: fuselage.centerZ,
      scale,
      strokeWidth: fuselage.strokeWidth,
      axes,
      root: scene,
      material: white
    })
  );
  scene.add(
    createEmbeddedWordMark({
      side: -1,
      sidePosition: fuselage.sideCenter - side,
      centerUp: fuselage.centerUp,
      centerZ: fuselage.centerZ,
      scale,
      strokeWidth: fuselage.strokeWidth,
      axes,
      root: scene,
      material: white
    })
  );
}

function detectFuselageAxes(size) {
  const sideAxis = size.x >= size.y ? 'x' : 'y';
  const upAxis = sideAxis === 'x' ? 'y' : 'x';
  return { sideAxis, upAxis };
}

function estimateFuselageBand(scene, box, size, axes) {
  const bodyPoints = collectFuselageBodyPoints(scene, box, size, axes);
  const sideValues = bodyPoints.map((point) => point[axes.sideAxis]).sort((left, right) => left - right);
  const upValues = bodyPoints.map((point) => point[axes.upAxis]).sort((left, right) => left - right);
  const zValues = bodyPoints.map((point) => point.z).sort((left, right) => left - right);
  const sideMin = percentile(sideValues, 0.12);
  const sideMax = percentile(sideValues, 0.88);
  const upMin = percentile(upValues, 0.12);
  const upMax = percentile(upValues, 0.88);
  const zMin = percentile(zValues, 0.1);
  const zMax = percentile(zValues, 0.9);
  const modelCenter = box.getCenter(new THREE.Vector3());
  const sideCenter = modelCenter[axes.sideAxis];
  const halfWidth = THREE.MathUtils.clamp((sideMax - sideMin) * 0.5, size[axes.upAxis] * 0.035, size[axes.upAxis] * 0.18);
  const bodyHeight = Math.max(0.001, upMax - upMin);
  const bodyLength = Math.max(0.001, zMax - zMin);
  const centerUp = percentile(upValues, 0.72);
  const centerZ = percentile(zValues, 0.62);
  const wordLength = THREE.MathUtils.clamp(bodyLength * 0.36, size.z * 0.14, size.z * 0.25);
  const scale = Math.min(wordLength / 5.7, (bodyHeight * 0.46) / 0.6);
  const strokeWidth = Math.max(scale * 0.3, bodyHeight * 0.05, 0.035);
  return {
    centerUp,
    centerZ,
    halfWidth,
    sideCenter,
    strokeWidth,
    scale,
    bodyHeight,
    bodyLength,
    upMin,
    upMax,
    zMin,
    zMax
  };
}

function collectFuselageBodyPoints(scene, box, size, axes) {
  const bodyPoints = [];
  const fallbackPoints = [];
  const scratch = new THREE.Vector3();
  const zMin = box.min.z + size.z * 0.24;
  const zMax = box.max.z - size.z * 0.24;
  scene.updateMatrixWorld(true);
  scene.traverse((object) => {
    if (!object.isMesh || !object.geometry?.attributes?.position) {
      return;
    }
    const materialName = Array.isArray(object.material)
      ? object.material.map((material) => material?.name ?? '').join(' ')
      : object.material?.name ?? '';
    const objectName = `${object.name} ${materialName}`.toLowerCase();
    if (
      /alien air embedded|wing|flap|slat|aileron|stabilizer|rudder|elevator|tail|fin|engine|nacelle|pylon|gear|strut|wheel|tire|fan|cockpit|window|glass/.test(
        objectName
      )
    ) {
      return;
    }
    const isBodyMaterial = isAlienAirBodyMaterial(materialName);
    const position = object.geometry.attributes.position;
    const stride = Math.max(1, Math.ceil(position.count / 1800));
    for (let index = 0; index < position.count; index += stride) {
      scratch.fromBufferAttribute(position, index).applyMatrix4(object.matrixWorld);
      if (scratch.z < zMin || scratch.z > zMax) {
        continue;
      }
      fallbackPoints.push(scratch.clone());
      if (isBodyMaterial) {
        bodyPoints.push(scratch.clone());
      }
    }
  });

  if (bodyPoints.length >= 16) {
    return bodyPoints;
  }
  if (fallbackPoints.length >= 16) {
    return fallbackPoints;
  }

  const center = box.getCenter(new THREE.Vector3());
  const sideRadius = Math.max(0.08, Math.min(size[axes.upAxis] * 0.07, size.z * 0.018));
  const upRadius = Math.max(0.08, size[axes.upAxis] * 0.18);
  const bodyLength = size.z * 0.5;
  return [
    makePoint(axes, center[axes.sideAxis] - sideRadius, center[axes.upAxis] - upRadius, center.z - bodyLength * 0.5),
    makePoint(axes, center[axes.sideAxis] + sideRadius, center[axes.upAxis] + upRadius, center.z + bodyLength * 0.5),
    makePoint(axes, center[axes.sideAxis], center[axes.upAxis], center.z)
  ];
}

function isAlienAirBodyMaterial(materialName) {
  return /alien air (gloss red|satin black fuselage|satin black tail)/i.test(materialName);
}

function makePoint(axes, side, up, z) {
  const point = new THREE.Vector3(0, 0, z);
  point[axes.sideAxis] = side;
  point[axes.upAxis] = up;
  return point;
}

function percentile(sortedValues, ratio) {
  if (sortedValues.length === 0) {
    return 0;
  }
  const index = THREE.MathUtils.clamp(Math.round((sortedValues.length - 1) * ratio), 0, sortedValues.length - 1);
  return sortedValues[index];
}

function createEmbeddedWordMark({ side, sidePosition, centerUp, centerZ, scale, strokeWidth, axes, root, material }) {
  const group = new THREE.Group();
  group.name = `Alien Air embedded ${side > 0 ? 'right' : 'left'} fuselage wordmark`;
  const width = scale * 5.7;
  const height = scale * 0.6;
  const strokes = buildAlienAirScriptStrokes();
  for (const stroke of strokes) {
    const worldPoints = stroke.map(([x, y]) => mapScriptPoint({ x, y, width, height, side, sidePosition, centerUp, centerZ, axes }));
    const geometry = createRibbonStrokeGeometry(worldPoints, strokeWidth, axes, root);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = 'Alien Air embedded fuselage lettering';
    mesh.renderOrder = 5;
    group.add(mesh);
  }
  return group;
}

function mapScriptPoint({ x, y, width, height, side, sidePosition, centerUp, centerZ, axes }) {
  const horizontal = (x - 0.5) * width;
  const vertical = (y - 0.5) * height;
  const point = new THREE.Vector3(0, 0, centerZ + horizontal * side);
  point[axes.sideAxis] = sidePosition;
  point[axes.upAxis] = centerUp + vertical;
  return point;
}

function createRibbonStrokeGeometry(worldPoints, strokeWidth, axes, root) {
  const vertices = [];
  const indices = [];
  const half = strokeWidth * 0.5;
  const rootInverse = root.matrixWorld.clone().invert();
  const localPoint = new THREE.Vector3();
  const planeNormal = axisVector(axes.sideAxis);

  for (let index = 0; index < worldPoints.length; index += 1) {
    const previous = worldPoints[Math.max(0, index - 1)];
    const current = worldPoints[index];
    const next = worldPoints[Math.min(worldPoints.length - 1, index + 1)];
    const tangent = next.clone().sub(previous).normalize();
    if (tangent.lengthSq() < 0.000001) {
      tangent.set(0, 0, 1);
    }
    const perpendicular = new THREE.Vector3().crossVectors(planeNormal, tangent).normalize();
    if (perpendicular.lengthSq() < 0.000001) {
      perpendicular.copy(axisVector(axes.upAxis));
    }
    const left = current.clone().add(perpendicular.clone().multiplyScalar(half));
    const right = current.clone().add(perpendicular.clone().multiplyScalar(-half));
    for (const point of [left, right]) {
      localPoint.copy(point).applyMatrix4(rootInverse);
      vertices.push(localPoint.x, localPoint.y, localPoint.z);
    }
  }

  for (let index = 0; index < worldPoints.length - 1; index += 1) {
    const offset = index * 2;
    indices.push(offset, offset + 1, offset + 2, offset + 1, offset + 3, offset + 2);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function buildAlienAirScriptStrokes() {
  return [
    [
      [0.02, 0.12],
      [0.05, 0.38],
      [0.08, 0.72],
      [0.12, 0.92],
      [0.16, 0.48],
      [0.2, 0.16],
      [0.23, 0.48],
      [0.17, 0.5]
    ],
    [
      [0.22, 0.22],
      [0.25, 0.52],
      [0.27, 0.76],
      [0.29, 0.2],
      [0.32, 0.2],
      [0.34, 0.55],
      [0.36, 0.22],
      [0.39, 0.22],
      [0.42, 0.56],
      [0.46, 0.5],
      [0.43, 0.32],
      [0.4, 0.2],
      [0.47, 0.2],
      [0.5, 0.56],
      [0.55, 0.2],
      [0.58, 0.2],
      [0.6, 0.48],
      [0.63, 0.5],
      [0.64, 0.22]
    ],
    [
      [0.69, 0.12],
      [0.72, 0.38],
      [0.75, 0.72],
      [0.79, 0.92],
      [0.83, 0.48],
      [0.87, 0.16],
      [0.9, 0.48],
      [0.84, 0.5]
    ],
    [
      [0.89, 0.22],
      [0.91, 0.58],
      [0.93, 0.22],
      [0.96, 0.22],
      [0.98, 0.54],
      [1.0, 0.46]
    ],
    [
      [0.31, 0.83],
      [0.32, 0.86],
      [0.33, 0.83]
    ],
    [
      [0.91, 0.83],
      [0.92, 0.86],
      [0.93, 0.83]
    ]
  ];
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
    ...removeObsoleteLiveryNotes(entry.modifications ?? []),
    'Repainted as Alien Air black and white livery',
    'Removed original airline livery',
    'Retracted landing gear for in-flight display',
    'Preserved original window, cockpit, and door meshes where available',
    'Preserved complete mesh geometry to avoid fragmented fuselages',
    'Embedded flat white Alien Air lettering into both fuselage sides'
  ]);
}

function updateLicenseFile(slug) {
  const licensePath = path.join(publicRoot, `assets/aircraft/${slug}/license.json`);
  if (!fs.existsSync(licensePath)) {
    return;
  }
  const license = JSON.parse(fs.readFileSync(licensePath, 'utf8'));
  license.modifications = unique([
    ...removeObsoleteLiveryNotes(license.modifications ?? []),
    'Repainted as Alien Air black and white livery',
    'Removed original airline livery',
    'Retracted landing gear for in-flight display',
    'Preserved original window, cockpit, and door meshes where available',
    'Preserved complete mesh geometry to avoid fragmented fuselages',
    'Embedded flat white Alien Air lettering into both fuselage sides'
  ]);
  fs.writeFileSync(licensePath, `${JSON.stringify(license, null, 2)}\n`);
}

function removeObsoleteLiveryNotes(values) {
  return values.filter(
    (value) =>
      !/floating decal|fuselage, wing, and tail Alien Air markings|cursive Alien Air fuselage script|thick cursive Alien Air script|embedded flat white Alien Air lettering|repainted as Alien Air red and white livery|retracted landing gear|embedded passenger and cockpit window geometry|embedded white passenger door outlines|preserved original window, cockpit, and door meshes/i.test(
        value
      )
  );
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
