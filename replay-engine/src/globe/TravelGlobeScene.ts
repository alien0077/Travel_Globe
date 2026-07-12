import * as THREE from 'three';
import { CameraController, type CameraMode } from '../camera/CameraController';
import type { GeographicPoint, JourneySegment, LocationPoint } from '../data/types';
import type { FlightOverlay } from '../flight/flightAnalytics';
import { createGlobe, createStarField } from './createGlobe';
import { createAircraftMarker, placeAircraftMarker } from '../models/createAircraftMarker';
import { createRouteEventMarkers, createRouteLine, updateRouteLine } from '../route/createRouteLine';

export class TravelGlobeScene {
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly cameraController: CameraController;
  private readonly aircraft: THREE.Group;
  private readonly clouds: THREE.Mesh;
  private readonly actualRouteLine: THREE.Line;
  private readonly resizeObserver: ResizeObserver;
  private readonly activePointers = new Map<number, PointerEvent>();
  private previousPinchDistance?: number;

  constructor(
    private readonly container: HTMLElement,
    segment: JourneySegment,
    overlay: FlightOverlay,
    travelRecordPoints: GeographicPoint[] = []
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
    this.bindInteraction();

    this.scene.background = new THREE.Color(0xf6fbf7);
    this.scene.fog = new THREE.Fog(0xf6fbf7, 8, 15);
    this.scene.add(createStarField(360, 46));

    const { globe, clouds } = createGlobe();
    this.clouds = clouds;
    this.scene.add(globe);
    this.scene.add(createRouteLine(overlay.plannedRoute, { color: 0xf3b342, opacity: 0.82, altitudeScaleMeters: 650000 }));
    this.actualRouteLine = createRouteLine([segment.derivedReplayRoute.points[0]], {
      color: 0x2bdc70,
      opacity: 0.98,
      altitudeScaleMeters: 600000
    });
    this.scene.add(this.actualRouteLine);
    this.scene.add(createRouteEventMarkers(overlay.events.map((event) => event.point), 0x18a999));
    this.scene.add(createRouteEventMarkers(travelRecordPoints, 0xf08c42));
    this.scene.add(this.aircraft);

    const ambient = new THREE.AmbientLight(0xeaf8ff, 2.2);
    const sun = new THREE.DirectionalLight(0xffffff, 3.4);
    sun.position.set(-3, 4, 7);
    this.scene.add(ambient, sun);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.container);
    this.resize();
  }

  update(point: LocationPoint, bearingDegrees: number, cameraMode: CameraMode, actualRoutePoints: LocationPoint[]): void {
    placeAircraftMarker(this.aircraft, point, bearingDegrees);
    updateRouteLine(this.actualRouteLine, actualRoutePoints, 600000);
    this.cameraController.setMode(cameraMode);
    this.cameraController.update(point, bearingDegrees);
  }

  start(onFrame: (timeMs: number) => void): void {
    this.renderer.setAnimationLoop((timeMs) => {
      onFrame(timeMs);
      this.clouds.rotation.y = timeMs * 0.000012;
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
    this.renderer.domElement.remove();
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
}

function disposeMaterial(material: THREE.Material | THREE.Material[]): void {
  if (Array.isArray(material)) {
    for (const item of material) {
      item.dispose();
    }
    return;
  }
  material.dispose();
}
