import * as THREE from 'three';

export interface GlobeObjects {
  globe: THREE.Group;
  earth: THREE.Mesh;
}

export function createGlobe(radius = 2): GlobeObjects {
  const globe = new THREE.Group();

  const earthGeometry = new THREE.SphereGeometry(radius, 96, 64);
  const earthMaterial = new THREE.MeshStandardMaterial({
    color: 0x0e5a78,
    roughness: 0.82,
    metalness: 0.05
  });
  const earth = new THREE.Mesh(earthGeometry, earthMaterial);
  globe.add(earth);

  const oceanGlow = new THREE.Mesh(
    new THREE.SphereGeometry(radius * 1.008, 96, 64),
    new THREE.MeshBasicMaterial({
      color: 0x43b8ce,
      transparent: true,
      opacity: 0.12,
      wireframe: true
    })
  );
  globe.add(oceanGlow);

  globe.add(createLatLongGrid(radius * 1.01));
  globe.add(createPlaceholderBorders(radius * 1.013));
  globe.add(createAtmosphere(radius));

  return { globe, earth };
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
    color: 0x9ad8e8,
    transparent: true,
    opacity: 0.16
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

function createPlaceholderBorders(radius: number): THREE.Group {
  const group = new THREE.Group();
  const material = new THREE.LineDashedMaterial({
    color: 0xffffff,
    transparent: true,
    opacity: 0.28,
    dashSize: 0.06,
    gapSize: 0.035
  });

  const arcs = [
    [
      [24.5, 118.2],
      [26.5, 122.3],
      [30.2, 128.1],
      [34.6, 138.2],
      [36.1, 140.8]
    ],
    [
      [22.5, 120.0],
      [25.1, 121.8],
      [28.5, 123.7],
      [31.2, 130.3],
      [35.2, 135.5]
    ]
  ];

  for (const arc of arcs) {
    const positions: number[] = [];
    for (const [lat, lon] of arc) {
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
    const line = new THREE.Line(geometry, material);
    line.computeLineDistances();
    group.add(line);
  }

  return group;
}

function createAtmosphere(radius: number): THREE.Mesh {
  return new THREE.Mesh(
    new THREE.SphereGeometry(radius * 1.035, 96, 64),
    new THREE.MeshBasicMaterial({
      color: 0x5ec8ff,
      transparent: true,
      opacity: 0.14,
      side: THREE.BackSide
    })
  );
}
