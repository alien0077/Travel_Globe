import * as THREE from 'three';
import boundariesIndex from '../../../shared/offline-packs/core-global/geo-boundaries.json';
import { resolveBundledAsset } from '../assets/resolveBundledAsset';
import { fixtureLandmarks } from '../geo/landmarks';
import { geographicToVector3 } from '../geo/geodesy';

export interface GlobeObjects {
  globe: THREE.Group;
  earth: THREE.Mesh;
  clouds: THREE.Mesh;
}

const BLUE_MARBLE_FILENAME = 'blue-marble-land-ocean-ice-2048.jpg';

export function createGlobe(radius = 2): GlobeObjects {
  const globe = new THREE.Group();

  const earthTexture = new THREE.TextureLoader().load(resolveBundledAsset(BLUE_MARBLE_FILENAME));
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
    emissiveIntensity: 0.18,
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

  globe.add(createLatLongGrid(radius * 1.014));
  globe.add(createNaturalEarthBoundaries(radius * 1.018));
  globe.add(createCityLights(radius * 1.024));
  globe.add(createAtmosphere(radius));
  globe.add(createTerminatorShade(radius));

  return { globe, earth, clouds };
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

function createLatLongGrid(radius: number): THREE.Group {
  const group = new THREE.Group();
  const material = new THREE.LineBasicMaterial({
    color: 0xb7e8ff,
    transparent: true,
    opacity: 0.08
  });

  for (let lat = -60; lat <= 60; lat += 30) {
    group.add(createLatitudeLine(lat, radius, material));
  }

  for (let lon = -150; lon <= 180; lon += 30) {
    group.add(createLongitudeLine(lon, radius, material));
  }

  return group;
}

function createLatitudeLine(latitude: number, radius: number, material: THREE.LineBasicMaterial): THREE.Line {
  const positions: number[] = [];
  const lat = THREE.MathUtils.degToRad(latitude);

  for (let lon = -180; lon <= 180; lon += 4) {
    const lonRad = THREE.MathUtils.degToRad(lon);
    positions.push(
      radius * Math.cos(lat) * Math.sin(lonRad),
      radius * Math.sin(lat),
      radius * Math.cos(lat) * Math.cos(lonRad)
    );
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return new THREE.Line(geometry, material);
}

function createLongitudeLine(longitude: number, radius: number, material: THREE.LineBasicMaterial): THREE.Line {
  const positions: number[] = [];
  const lon = THREE.MathUtils.degToRad(longitude);

  for (let lat = -90; lat <= 90; lat += 4) {
    const latRad = THREE.MathUtils.degToRad(lat);
    positions.push(
      radius * Math.cos(latRad) * Math.sin(lon),
      radius * Math.sin(latRad),
      radius * Math.cos(latRad) * Math.cos(lon)
    );
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return new THREE.Line(geometry, material);
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

function createCityLights(radius: number): THREE.Points {
  const positions: number[] = [];
  const colors: number[] = [];
  const color = new THREE.Color();

  for (const feature of fixtureLandmarks) {
    if (feature.type !== 'majorCity') {
      continue;
    }
    const vector = geographicToVector3(feature, radius, 900000);
    positions.push(vector.x, vector.y, vector.z);
    color.set(feature.countryCode === 'JP' ? 0xfff1b0 : 0x9ed8ff);
    colors.push(color.r, color.g, color.b);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

  return new THREE.Points(
    geometry,
    new THREE.PointsMaterial({
      size: 0.075,
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    })
  );
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

function createTerminatorShade(radius: number): THREE.Mesh {
  const shade = new THREE.Mesh(
    new THREE.SphereGeometry(radius * 1.006, 96, 64),
    new THREE.ShaderMaterial({
      uniforms: {
        lightDirection: { value: new THREE.Vector3(-0.45, 0.32, 0.83).normalize() }
      },
      vertexShader: `
        varying vec3 vWorldNormal;
        void main() {
          vWorldNormal = normalize(mat3(modelMatrix) * normal);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        uniform vec3 lightDirection;
        varying vec3 vWorldNormal;
        void main() {
          float night = smoothstep(0.18, -0.42, dot(normalize(vWorldNormal), lightDirection));
          gl_FragColor = vec4(0.01, 0.025, 0.055, night * 0.24);
        }
      `,
      transparent: true,
      depthWrite: false
    })
  );
  shade.renderOrder = 2;
  return shade;
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
