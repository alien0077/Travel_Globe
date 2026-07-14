import * as THREE from 'three';
import { CameraController, type CameraMode } from '../camera/CameraController';
import type { JourneySegment, LocationPoint } from '../data/types';
import type { FlightOverlay } from '../flight/flightAnalytics';
import { landmarkDisplayName, type GeographicFeature } from '../geo/landmarks';
import { EARTH_RADIUS_METERS, geographicToVector3, haversineDistanceMeters } from '../geo/geodesy';
import { createAircraftMarker, placeAircraftMarker } from '../models/createAircraftMarker';
import { createRouteTrack, updateRouteTrack, type RouteTrack } from '../route/createRouteLine';
import { createGlobe, createStarField, shouldRenderGlobeLabel } from './createGlobe';

interface GlobeDomLabel {
  element: HTMLSpanElement;
  feature: GeographicFeature;
  position: THREE.Vector3;
}

interface LabelCandidate {
  label: GlobeDomLabel;
  x: number;
  y: number;
  width: number;
  height: number;
  distanceMeters: number;
  opacity: number;
}

export class TravelGlobeScene {
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly cameraController: CameraController;
  private readonly aircraft: THREE.Group;
  private readonly earth: THREE.Mesh;
  private readonly clouds: THREE.Mesh;
  private readonly ambient: THREE.AmbientLight;
  private readonly sun: THREE.DirectionalLight;
  private readonly cityLights: THREE.Points;
  private readonly cityLightMaterial: THREE.PointsMaterial;
  private readonly labelLayer: HTMLDivElement;
  private readonly landmarkLabels: GlobeDomLabel[];
  private readonly routeTrack: RouteTrack;
  private readonly resizeObserver: ResizeObserver;
  private readonly activePointers = new Map<number, PointerEvent>();
  private currentCameraMode: CameraMode = 'flightPreview';
  private currentPoint?: LocationPoint;
  private previousCameraMode?: CameraMode;
  private suppressLabelsUntilMs = 0;
  private previousPinchDistance?: number;

  constructor(
    private readonly container: HTMLElement,
    private readonly segment: JourneySegment,
    overlay: FlightOverlay,
    routeLandmarks: GeographicFeature[]
  ) {
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    this.camera.position.set(0, 2.45, 5.2);
    this.cameraController = new CameraController(this.camera);
    this.aircraft = createAircraftMarker(overlay.aircraftType);

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      preserveDrawingBuffer: true
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.container.appendChild(this.renderer.domElement);
    this.labelLayer = document.createElement('div');
    this.labelLayer.className = 'globe-label-layer';
    this.landmarkLabels = createDomLandmarkLabels(this.labelLayer, routeLandmarks);
    this.container.appendChild(this.labelLayer);
    this.bindInteraction();

    this.scene.background = new THREE.Color(0xd7e5e1);
    this.scene.fog = new THREE.Fog(0xd7e5e1, 9, 18);
    this.scene.add(createStarField(360, 46));

    const { globe, earth, clouds } = createGlobe();
    this.earth = earth;
    this.clouds = clouds;
    this.scene.add(globe);
    const cityLights = createRouteCityLights(routeLandmarks);
    this.cityLights = cityLights.points;
    this.cityLightMaterial = cityLights.material;
    this.scene.add(this.cityLights);
    this.routeTrack = createRouteTrack(segment.derivedReplayRoute.points, [segment.derivedReplayRoute.points[0]], 180000);
    this.scene.add(this.routeTrack);
    this.scene.add(this.aircraft);

    this.ambient = new THREE.AmbientLight(0xf5fbff, 3.2);
    this.sun = new THREE.DirectionalLight(0xffffff, 4.2);
    this.sun.position.set(-3, 4, 7);
    this.scene.add(this.ambient, this.sun);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.container);
    this.resize();
  }

  update(point: LocationPoint, bearingDegrees: number, cameraMode: CameraMode, actualRoutePoints: LocationPoint[]): void {
    const snapCamera = shouldSnapCamera(this.currentPoint, point, this.previousCameraMode, cameraMode);
    if (snapCamera && this.currentPoint) {
      this.suppressLabelsUntilMs = performance.now() + 180;
      this.hideAllLabels();
    }
    this.currentPoint = point;
    this.currentCameraMode = cameraMode;
    this.previousCameraMode = cameraMode;
    placeAircraftMarker(this.aircraft, point, bearingDegrees);
    this.aircraft.visible = cameraMode !== 'pilotView';
    updateRouteTrack(this.routeTrack, this.segment.derivedReplayRoute.points, actualRoutePoints, 180000);
    this.updateDayNight(point);
    this.cameraController.setMode(cameraMode);
    this.cameraController.update(point, bearingDegrees, { snap: snapCamera });
  }

  start(onFrame: (timeMs: number) => void): void {
    this.renderer.setAnimationLoop((timeMs) => {
      onFrame(timeMs);
      this.clouds.rotation.y = timeMs * 0.000012;
      this.updateLabelOverlay();
      this.renderer.render(this.scene, this.camera);
    });
  }

  dispose(): void {
    this.renderer.setAnimationLoop(null);
    this.resizeObserver.disconnect();
    this.unbindInteraction();
    this.scene.traverse((object) => {
      if (object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.Points) {
        object.geometry.dispose();
        disposeMaterial(object.material);
      }
    });
    this.renderer.dispose();
    this.labelLayer.remove();
    this.renderer.domElement.remove();
  }

  prepareForTimelineJump(): void {
    this.suppressLabelsUntilMs = performance.now() + 180;
    this.hideAllLabels();
    void this.labelLayer.offsetHeight;
  }

  private resize(): void {
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  private bindInteraction(): void {
    const canvas = this.renderer.domElement;
    canvas.addEventListener('pointerdown', this.handlePointerDown);
    canvas.addEventListener('pointermove', this.handlePointerMove);
    canvas.addEventListener('pointerup', this.handlePointerUp);
    canvas.addEventListener('pointercancel', this.handlePointerUp);
    canvas.addEventListener('wheel', this.handleWheel, { passive: false });
  }

  private unbindInteraction(): void {
    const canvas = this.renderer.domElement;
    canvas.removeEventListener('pointerdown', this.handlePointerDown);
    canvas.removeEventListener('pointermove', this.handlePointerMove);
    canvas.removeEventListener('pointerup', this.handlePointerUp);
    canvas.removeEventListener('pointercancel', this.handlePointerUp);
    canvas.removeEventListener('wheel', this.handleWheel);
    this.activePointers.clear();
  }

  private readonly handlePointerDown = (event: PointerEvent): void => {
    this.renderer.domElement.setPointerCapture(event.pointerId);
    this.activePointers.set(event.pointerId, event);
    this.previousPinchDistance = this.currentPinchDistance();
  };

  private readonly handlePointerMove = (event: PointerEvent): void => {
    const previous = this.activePointers.get(event.pointerId);
    if (!previous) {
      return;
    }

    this.activePointers.set(event.pointerId, event);

    if (this.activePointers.size >= 2) {
      const currentDistance = this.currentPinchDistance();
      if (currentDistance && this.previousPinchDistance) {
        const delta = (this.previousPinchDistance - currentDistance) / Math.max(160, this.previousPinchDistance);
        this.cameraController.zoomBy(delta);
      }
      this.previousPinchDistance = currentDistance;
      return;
    }

    this.cameraController.rotate(event.clientX - previous.clientX, event.clientY - previous.clientY);
  };

  private readonly handlePointerUp = (event: PointerEvent): void => {
    if (this.renderer.domElement.hasPointerCapture(event.pointerId)) {
      this.renderer.domElement.releasePointerCapture(event.pointerId);
    }
    this.activePointers.delete(event.pointerId);
    this.previousPinchDistance = this.currentPinchDistance();
  };

  private readonly handleWheel = (event: WheelEvent): void => {
    event.preventDefault();
    this.cameraController.zoomBy(event.deltaY * 0.002);
  };

  private currentPinchDistance(): number | undefined {
    const pointers = [...this.activePointers.values()];
    if (pointers.length < 2) {
      return undefined;
    }
    const [first, second] = pointers;
    return Math.hypot(first.clientX - second.clientX, first.clientY - second.clientY);
  }

  private updateDayNight(point: LocationPoint): void {
    const nightFactor = nightFactorAt(point.timestamp, point.longitude);
    const dayFactor = 1 - nightFactor;
    const daySky = new THREE.Color(0xd7e5e1);
    const nightSky = new THREE.Color(0x07111d);
    const sky = new THREE.Color().lerpColors(nightSky, daySky, dayFactor);
    this.scene.background = sky;
    if (this.scene.fog) {
      this.scene.fog.color.copy(sky);
    }

    this.ambient.intensity = lerp(0.72, 3.2, dayFactor);
    this.sun.intensity = lerp(0.28, 4.2, dayFactor);
    const earthMaterial = this.earth.material;
    if (earthMaterial instanceof THREE.MeshStandardMaterial) {
      earthMaterial.emissiveIntensity = lerp(0.1, 0.38, dayFactor);
    }
    if (this.clouds.material instanceof THREE.Material) {
      this.clouds.material.opacity = lerp(0.12, 0.22, dayFactor);
    }
    this.cityLightMaterial.opacity = lerp(0.02, 0.92, nightFactor);
    this.cityLights.visible = this.cityLightMaterial.opacity > 0.08;
  }

  private updateLabelOverlay(): void {
    if (performance.now() < this.suppressLabelsUntilMs) {
      this.hideAllLabels();
      return;
    }

    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    this.camera.updateMatrixWorld();
    const candidates: LabelCandidate[] = [];
    const maxLabelDistance = this.currentPoint
      ? labelDistanceLimitMeters(this.currentPoint, this.currentCameraMode)
      : 180000;

    for (const label of this.landmarkLabels) {
      hideLabel(label.element);
      const projected = label.position.clone().project(this.camera);
      if (
        projected.z <= -1 ||
        projected.z >= 1 ||
        projected.x < -1.12 ||
        projected.x > 1.12 ||
        projected.y < -1.12 ||
        projected.y > 1.12 ||
        !isGroundPointVisibleFromCamera(this.camera.position, label.position)
      ) {
        continue;
      }

      const distanceMeters = this.currentPoint ? haversineDistanceMeters(this.currentPoint, label.feature) : 0;
      if (distanceMeters > maxLabelDistance) {
        continue;
      }

      candidates.push({
        label,
        x: ((projected.x + 1) / 2) * width,
        y: ((-projected.y + 1) / 2) * height,
        width: Math.max(34, label.element.offsetWidth),
        height: Math.max(14, label.element.offsetHeight),
        distanceMeters,
        opacity: labelOpacityForDistance(distanceMeters, maxLabelDistance)
      });
    }

    const visibleLabels = selectVisibleLabels(candidates, labelCountLimit(this.currentCameraMode));
    for (const candidate of visibleLabels) {
      candidate.label.element.classList.remove('is-hidden');
      candidate.label.element.style.opacity = candidate.opacity.toFixed(3);
      candidate.label.element.style.transform = `translate(${candidate.x}px, ${candidate.y}px)`;
    }
  }

  private hideAllLabels(): void {
    for (const label of this.landmarkLabels) {
      hideLabel(label.element);
    }
  }
}

function hideLabel(element: HTMLSpanElement): void {
  element.classList.add('is-hidden');
  element.style.opacity = '0';
  element.style.transform = 'translate(-9999px, -9999px)';
}

function createDomLandmarkLabels(layer: HTMLDivElement, features: GeographicFeature[]): GlobeDomLabel[] {
  const labels: GlobeDomLabel[] = [];
  for (const feature of features) {
    if (!shouldRenderGlobeLabel(feature)) {
      continue;
    }

    const element = document.createElement('span');
    element.className = `globe-place-label ${feature.type === 'majorCity' ? 'is-city' : 'is-landmark'} is-hidden`;
    element.textContent = landmarkDisplayName(feature);
    layer.appendChild(element);

    const vector = geographicToVector3(feature, 2.006, 900000);
    labels.push({
      element,
      feature,
      position: new THREE.Vector3(vector.x, vector.y, vector.z)
    });
  }
  return labels;
}

function selectVisibleLabels(candidates: LabelCandidate[], maxCount: number): LabelCandidate[] {
  const occupied: Array<{ left: number; right: number; top: number; bottom: number }> = [];
  const selected: LabelCandidate[] = [];
  const sorted = [...candidates].sort((a, b) => labelPriority(b) - labelPriority(a));

  for (const candidate of sorted) {
    const box = labelCollisionBox(candidate);
    if (occupied.some((existing) => boxesOverlap(existing, box))) {
      continue;
    }
    occupied.push(box);
    selected.push(candidate);
    if (selected.length >= maxCount) {
      break;
    }
  }

  return selected;
}

function labelPriority(candidate: LabelCandidate): number {
  const typeBoost = candidate.label.feature.type === 'landmark' ? 1.15 : 1;
  const distancePenalty = Math.min(1.8, candidate.distanceMeters / 450000);
  return candidate.label.feature.importance * typeBoost - distancePenalty;
}

function labelCollisionBox(candidate: LabelCandidate): { left: number; right: number; top: number; bottom: number } {
  const padding = 8;
  return {
    left: candidate.x - 8 - padding,
    right: candidate.x + candidate.width + padding,
    top: candidate.y - candidate.height * 0.65 - padding,
    bottom: candidate.y + candidate.height * 0.65 + padding
  };
}

function boxesOverlap(
  a: { left: number; right: number; top: number; bottom: number },
  b: { left: number; right: number; top: number; bottom: number }
): boolean {
  return Math.max(a.left, b.left) < Math.min(a.right, b.right) && Math.max(a.top, b.top) < Math.min(a.bottom, b.bottom);
}

function isGroundPointVisibleFromCamera(cameraPosition: THREE.Vector3, pointPosition: THREE.Vector3): boolean {
  const toPoint = pointPosition.clone().sub(cameraPosition);
  const distance = toPoint.length();
  if (distance <= 0.0001) {
    return true;
  }

  const direction = toPoint.divideScalar(distance);
  const cameraRadius = cameraPosition.length();
  const surfaceRadius = 2.0;
  if (cameraRadius <= surfaceRadius + 0.004) {
    return cameraPosition.clone().normalize().dot(pointPosition.clone().normalize()) > 0.04;
  }

  const closest = cameraPosition.dot(direction);
  const discriminant = closest * closest - (cameraRadius * cameraRadius - surfaceRadius * surfaceRadius);
  if (discriminant < 0) {
    return true;
  }

  const firstHitDistance = -closest - Math.sqrt(discriminant);
  return firstHitDistance >= distance - 0.018;
}

function labelDistanceLimitMeters(point: LocationPoint, cameraMode: CameraMode): number {
  const altitudeMeters = Math.max(0, point.altitudeMeters ?? 0);
  const horizonMeters = Math.sqrt(2 * EARTH_RADIUS_METERS * altitudeMeters + altitudeMeters * altitudeMeters);
  const dynamicLimit = Math.min(520000, Math.max(85000, horizonMeters + 80000));
  switch (cameraMode) {
    case 'totalRoute':
      return Math.min(900000, Math.max(420000, horizonMeters + 260000));
    case 'overhead':
    case 'commandCenter':
      return Math.min(680000, Math.max(180000, horizonMeters + 160000));
    case 'pilotView':
    case 'cockpit':
      return Math.min(420000, Math.max(65000, horizonMeters + 60000));
    case 'global':
    case 'orbit':
      return Math.min(1100000, Math.max(500000, horizonMeters + 320000));
    default:
      return dynamicLimit;
  }
}

function labelOpacityForDistance(distanceMeters: number, maxDistanceMeters: number): number {
  const fadeStart = maxDistanceMeters * 0.72;
  if (distanceMeters <= fadeStart) {
    return 1;
  }
  return 0.18 + 0.82 * (1 - smoothstep(fadeStart, maxDistanceMeters, distanceMeters));
}

function labelCountLimit(cameraMode: CameraMode): number {
  switch (cameraMode) {
    case 'pilotView':
    case 'cockpit':
      return 7;
    case 'flightPreview':
    case 'midFlight':
    case 'follow':
      return 8;
    case 'totalRoute':
    case 'global':
    case 'orbit':
      return 18;
    default:
      return 12;
  }
}

function shouldSnapCamera(
  previousPoint: LocationPoint | undefined,
  currentPoint: LocationPoint,
  previousMode: CameraMode | undefined,
  currentMode: CameraMode
): boolean {
  if (!previousPoint || previousMode !== currentMode) {
    return true;
  }

  const previousMs = Date.parse(previousPoint.timestamp);
  const currentMs = Date.parse(currentPoint.timestamp);
  if (Number.isFinite(previousMs) && Number.isFinite(currentMs) && currentMs < previousMs - 1000) {
    return true;
  }

  return haversineDistanceMeters(previousPoint, currentPoint) > 15000;
}

function createRouteCityLights(features: GeographicFeature[]): { points: THREE.Points; material: THREE.PointsMaterial } {
  const positions: number[] = [];
  const colors: number[] = [];
  const lightFeatures = features
    .filter((feature) => feature.type === 'majorCity' && feature.importance >= 0.76)
    .sort((a, b) => (b.population ?? 0) - (a.population ?? 0))
    .slice(0, 96);

  for (const feature of lightFeatures) {
    const vector = geographicToVector3(feature, 2.018, 900000);
    positions.push(vector.x, vector.y, vector.z);
    const warm = Math.min(1, 0.55 + Math.log10(Math.max(10_000, feature.population ?? 80_000)) / 12);
    colors.push(1, warm, 0.48);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  const material = new THREE.PointsMaterial({
    size: 0.028,
    map: createCityLightSpriteTexture(),
    vertexColors: true,
    transparent: true,
    opacity: 0.02,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    alphaTest: 0.08
  });

  return {
    points: new THREE.Points(geometry, material),
    material
  };
}

function createCityLightSpriteTexture(): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 64;
  canvas.height = 64;
  const context = canvas.getContext('2d');
  if (!context) {
    return new THREE.CanvasTexture(canvas);
  }

  const glow = context.createRadialGradient(32, 32, 0, 32, 32, 31);
  glow.addColorStop(0, 'rgba(255, 250, 214, 1)');
  glow.addColorStop(0.28, 'rgba(255, 216, 119, 0.92)');
  glow.addColorStop(0.62, 'rgba(255, 183, 77, 0.32)');
  glow.addColorStop(1, 'rgba(255, 183, 77, 0)');
  context.fillStyle = glow;
  context.fillRect(0, 0, canvas.width, canvas.height);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

function nightFactorAt(timestamp: string, longitude: number): number {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return 0;
  }
  const utcHour =
    date.getUTCHours() +
    date.getUTCMinutes() / 60 +
    date.getUTCSeconds() / 3600;
  const localHour = positiveModulo(utcHour + longitude / 15, 24);
  const dayScore = (Math.cos(((localHour - 12) / 12) * Math.PI) + 1) / 2;
  return 1 - smoothstep(0.18, 0.55, dayScore);
}

function positiveModulo(value: number, divisor: number): number {
  return ((value % divisor) + divisor) % divisor;
}

function smoothstep(edge0: number, edge1: number, value: number): number {
  const t = Math.min(1, Math.max(0, (value - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

function lerp(a: number, b: number, fraction: number): number {
  return a + (b - a) * fraction;
}

function disposeMaterial(material: THREE.Material | THREE.Material[]): void {
  if (Array.isArray(material)) {
    for (const item of material) {
      item.dispose();
    }
    return;
  }
  if ('map' in material && material.map instanceof THREE.Texture) {
    material.map.dispose();
  }
  material.dispose();
}
