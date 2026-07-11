import * as THREE from 'three';
import { CameraController, type CameraMode } from '../camera/CameraController';
import type { JourneySegment, LocationPoint } from '../data/types';
import { createGlobe, createStarField } from './createGlobe';
import { createAircraftMarker, placeAircraftMarker } from '../models/createAircraftMarker';
import { createRouteLine } from '../route/createRouteLine';

export class TravelGlobeScene {
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly cameraController: CameraController;
  private readonly aircraft = createAircraftMarker();
  private readonly clouds: THREE.Mesh;
  private readonly resizeObserver: ResizeObserver;

  constructor(private readonly container: HTMLElement, segment: JourneySegment) {
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    this.camera.position.set(0, 2.45, 5.2);
    this.cameraController = new CameraController(this.camera);

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      preserveDrawingBuffer: true
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.container.appendChild(this.renderer.domElement);

    this.scene.background = new THREE.Color(0x030914);
    this.scene.add(createStarField());

    const { globe, clouds } = createGlobe();
    this.clouds = clouds;
    this.scene.add(globe);
    this.scene.add(createRouteLine(segment.derivedReplayRoute.points));
    this.scene.add(this.aircraft);

    const ambient = new THREE.AmbientLight(0x8eb7ff, 1.4);
    const sun = new THREE.DirectionalLight(0xffffff, 2.8);
    sun.position.set(-4, 3, 7);
    this.scene.add(ambient, sun);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.container);
    this.resize();
  }

  update(point: LocationPoint, bearingDegrees: number, cameraMode: CameraMode): void {
    placeAircraftMarker(this.aircraft, point, bearingDegrees);
    this.cameraController.setMode(cameraMode);
    this.cameraController.update(point);
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
