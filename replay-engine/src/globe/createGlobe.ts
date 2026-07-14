import * as THREE from 'three';
import boundariesIndex from '../../../shared/offline-packs/core-global/geo-boundaries.json';
import { resolveBundledAsset } from '../assets/resolveBundledAsset';
import type { GeographicFeature } from '../geo/landmarks';

export interface GlobeObjects {
  globe: THREE.Group;
  earth: THREE.Mesh;
  clouds: THREE.Mesh;
}

const BLUE_MARBLE_FILENAME = 'blue-marble-land-ocean-ice-2048.jpg';

export function createGlobe(radius = 2): GlobeObjects {
  const globe = new THREE.Group();

  const earthTexture = createFallbackEarthTexture();
  new THREE.TextureLoader().load(
    resolveBundledAsset(BLUE_MARBLE_FILENAME),
    (loadedTexture) => {
      loadedTexture.colorSpace = THREE.SRGBColorSpace;
      loadedTexture.anisotropy = 8;
      loadedTexture.wrapS = THREE.RepeatWrapping;
      loadedTexture.offset.x = 0.25;
      earthMaterial.map = loadedTexture;
      earthMaterial.bumpMap = loadedTexture;
      earthMaterial.emissiveMap = loadedTexture;
      earthMaterial.needsUpdate = true;
    }
  );
  earthTexture.colorSpace = THREE.SRGBColorSpace;
  earthTexture.anisotropy = 8;
  earthTexture.wrapS = THREE.RepeatWrapping;
  earthTexture.offset.x = 0.25;

  const earthGeometry = new THREE.SphereGeometry(radius, 96, 64);
  const earthMaterial = new THREE.MeshStandardMaterial({
    map: earthTexture,
    bumpMap: earthTexture,
    bumpScale: 0.018,
    color: 0xffffff,
    emissive: 0x446676,
    emissiveMap: earthTexture,
    emissiveIntensity: 0.38,
    roughness: 0.92,
    metalness: 0.0
  });
  const earth = new THREE.Mesh(earthGeometry, earthMaterial);
  globe.add(earth);

  const clouds = new THREE.Mesh(
    new THREE.SphereGeometry(radius * 1.012, 96, 64),
    new THREE.MeshLambertMaterial({
      map: createCloudTexture(),
      color: 0xffffff,
      transparent: true,
      opacity: 0.22,
      depthWrite: false
    })
  );
  globe.add(clouds);

  globe.add(createNaturalEarthBoundaries(radius * 1.0004));
  globe.add(createAtmosphere(radius));

  return { globe, earth, clouds };
}

function createFallbackEarthTexture(): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 512;
  const context = canvas.getContext('2d');
  if (!context) {
    return new THREE.CanvasTexture(canvas);
  }

  const ocean = context.createLinearGradient(0, 0, 0, canvas.height);
  ocean.addColorStop(0, '#0d2f54');
  ocean.addColorStop(0.48, '#123f67');
  ocean.addColorStop(1, '#06172d');
  context.fillStyle = ocean;
  context.fillRect(0, 0, canvas.width, canvas.height);

  context.globalAlpha = 0.86;
  context.fillStyle = '#2e6f3e';
  drawLand(context, [
    [70, 180], [135, 112], [220, 126], [292, 186], [270, 278], [188, 330], [96, 292]
  ]);
  drawLand(context, [
    [380, 118], [482, 92], [578, 132], [612, 224], [554, 302], [448, 288], [362, 214]
  ]);
  drawLand(context, [
    [620, 92], [722, 86], [820, 122], [864, 196], [812, 254], [684, 238], [604, 166]
  ]);
  drawLand(context, [
    [700, 292], [812, 278], [936, 324], [978, 410], [884, 466], [746, 430], [650, 360]
  ]);
  drawLand(context, [
    [246, 346], [344, 324], [426, 362], [454, 448], [358, 486], [260, 448]
  ]);

  context.globalAlpha = 0.22;
  context.fillStyle = '#a7d484';
  for (let index = 0; index < 42; index += 1) {
    const x = (index * 151) % canvas.width;
    const y = 70 + ((index * 83) % 350);
    context.beginPath();
    context.ellipse(x, y, 46, 15, index * 0.47, 0, Math.PI * 2);
    context.fill();
  }
  context.globalAlpha = 1;

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.offset.x = 0.25;
  return texture;
}

function drawLand(context: CanvasRenderingContext2D, points: Array<[number, number]>): void {
  context.beginPath();
  points.forEach(([x, y], index) => {
    if (index === 0) {
      context.moveTo(x, y);
      return;
    }
    context.lineTo(x, y);
  });
  context.closePath();
  context.fill();
}

export function createStarField(count = 900, radius = 52): THREE.Points {
  const positions: number[] = [];
  const colors: number[] = [];
  const color = new THREE.Color();
  const random = createSeededRandom(20260710);

  for (let index = 0; index < count; index += 1) {
    const theta = random() * Math.PI * 2;
    const phi = Math.acos(2 * random() - 1);
    positions.push(
      radius * Math.sin(phi) * Math.cos(theta),
      radius * Math.sin(phi) * Math.sin(theta),
      radius * Math.cos(phi)
    );

    color.setHSL(0.58 + random() * 0.1, 0.45, 0.72 + random() * 0.2);
    colors.push(color.r, color.g, color.b);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

  return new THREE.Points(
    geometry,
    new THREE.PointsMaterial({
      size: 0.05,
      vertexColors: true,
      transparent: true,
      opacity: 0.88
    })
  );
}

function createSeededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (1664525 * state + 1013904223) >>> 0;
    return state / 0xffffffff;
  };
}

interface BoundaryLine {
  kind: 'coastline' | 'country-border';
  coordinates: Array<[number, number]>;
}

function createNaturalEarthBoundaries(radius: number): THREE.Group {
  const group = new THREE.Group();
  const coastlineMaterial = new THREE.LineBasicMaterial({
    color: 0xffffff,
    transparent: true,
    opacity: 0.36
  });
  const borderMaterial = new THREE.LineBasicMaterial({
    color: 0xe7fbff,
    transparent: true,
    opacity: 0.2
  });

  for (const line of boundariesIndex.lines as BoundaryLine[]) {
    const positions: number[] = [];
    for (const [lat, lon] of line.coordinates) {
      const latRad = THREE.MathUtils.degToRad(lat);
      const lonRad = THREE.MathUtils.degToRad(lon);
      positions.push(
        radius * Math.cos(latRad) * Math.sin(lonRad),
        radius * Math.sin(latRad),
        radius * Math.cos(latRad) * Math.cos(lonRad)
      );
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    group.add(new THREE.Line(geometry, line.kind === 'coastline' ? coastlineMaterial : borderMaterial));
  }

  return group;
}

export function shouldRenderGlobeLabel(feature: GeographicFeature): boolean {
  if (feature.type === 'majorCity') {
    return feature.importance >= 0.76 && feature.minZoomRank <= 8;
  }
  return feature.importance >= 0.9 && feature.minZoomRank <= 1;
}

function createAtmosphere(radius: number): THREE.Mesh {
  return new THREE.Mesh(
    new THREE.SphereGeometry(radius * 1.045, 96, 64),
    new THREE.ShaderMaterial({
      uniforms: {
        glowColor: { value: new THREE.Color(0x56c7ff) }
      },
      vertexShader: `
        varying vec3 vNormal;
        void main() {
          vNormal = normalize(normalMatrix * normal);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        uniform vec3 glowColor;
        varying vec3 vNormal;
        void main() {
          float rim = pow(0.66 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.0);
          gl_FragColor = vec4(glowColor, clamp(rim, 0.0, 0.36));
        }
      `,
      transparent: true,
      blending: THREE.AdditiveBlending,
      side: THREE.BackSide,
      depthWrite: false
    })
  );
}

function createCloudTexture(): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 512;
  const context = canvas.getContext('2d');
  if (!context) {
    return new THREE.CanvasTexture(canvas);
  }

  context.clearRect(0, 0, canvas.width, canvas.height);
  const random = createSeededRandom(20260711);

  for (let band = 0; band < 7; band += 1) {
    const centerY = canvas.height * (0.18 + band * 0.11 + (random() - 0.5) * 0.03);
    const bandHeight = 18 + random() * 34;
    for (let index = 0; index < 85; index += 1) {
      const x = random() * canvas.width;
      const y = centerY + (random() - 0.5) * bandHeight;
      const width = 34 + random() * 110;
      const height = 5 + random() * 18;
      const alpha = 0.025 + random() * 0.075;
      const gradient = context.createRadialGradient(x, y, 1, x, y, width * 0.55);
      gradient.addColorStop(0, `rgba(255,255,255,${alpha})`);
      gradient.addColorStop(1, 'rgba(255,255,255,0)');
      context.fillStyle = gradient;
      context.beginPath();
      context.ellipse(x, y, width, height, random() * Math.PI, 0, Math.PI * 2);
      context.fill();
    }
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  return texture;
}
