import * as THREE from 'three';
import type { GeographicPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';

export type CameraMode = 'follow' | 'cockpit' | 'leftWindow' | 'rightWindow' | 'tail' | 'topDown' | 'global';

export class CameraController {
  mode: CameraMode = 'follow';
  private orbitYaw = 0;
  private orbitPitch = 0;
  private zoom = 1;
  private readonly target = new THREE.Vector3();
  private readonly desired = new THREE.Vector3();

  constructor(private readonly camera: THREE.PerspectiveCamera) {}

  setMode(mode: CameraMode): void {
    this.mode = mode;
  }

  rotate(deltaX: number, deltaY: number): void {
    this.orbitYaw += deltaX * 0.006;
    this.orbitPitch = THREE.MathUtils.clamp(this.orbitPitch + deltaY * 0.004, -0.75, 0.75);
  }

  zoomBy(delta: number): void {
    this.zoom = THREE.MathUtils.clamp(this.zoom * (1 + delta), 0.45, 2.2);
  }

  update(point: GeographicPoint, bearingDegrees: number): void {
    const aircraftPosition = geographicToVector3(point, 2, 700000);
    this.target.set(aircraftPosition.x, aircraftPosition.y, aircraftPosition.z);
    const normal = this.target.clone().normalize();
    const forward = this.forwardVector(normal, bearingDegrees);

    if (this.mode === 'global') {
      const distance = 5.2 * this.zoom;
      const base = new THREE.Vector3(0, 2.45, distance);
      base.applyAxisAngle(new THREE.Vector3(0, 1, 0), this.orbitYaw);
      base.applyAxisAngle(new THREE.Vector3(1, 0, 0), this.orbitPitch);
      this.camera.position.lerp(base, 0.06);
      this.camera.lookAt(0, 0, 0);
      return;
    }

    const profile = cameraProfiles[this.mode];
    const yawedForward = forward.clone().applyAxisAngle(normal, this.orbitYaw);
    const yawedRight = new THREE.Vector3().crossVectors(yawedForward, normal).normalize();
    const pitchedUp = normal.clone().multiplyScalar(profile.up + this.orbitPitch * 0.35);
    const distance = profile.distance * this.zoom;

    this.desired
      .copy(this.target)
      .add(yawedForward.multiplyScalar(profile.forward * distance))
      .add(yawedRight.multiplyScalar(profile.right * distance))
      .add(pitchedUp);

    this.camera.position.lerp(this.desired, 0.1);

    const lookAhead = this.target
      .clone()
      .add(forward.multiplyScalar(profile.lookAhead))
      .add(normal.multiplyScalar(profile.lookUp));
    this.camera.up.copy(normal);
    this.camera.lookAt(lookAhead);
  }

  private forwardVector(normal: THREE.Vector3, bearingDegrees: number): THREE.Vector3 {
    const north = new THREE.Vector3(0, 1, 0);
    const east = new THREE.Vector3().crossVectors(north, normal);
    if (east.lengthSq() < 0.000001) {
      east.set(1, 0, 0).cross(normal);
    }
    east.normalize();
    const localNorth = new THREE.Vector3().crossVectors(normal, east).normalize();
    const bearing = THREE.MathUtils.degToRad(bearingDegrees);
    return localNorth.multiplyScalar(Math.cos(bearing)).add(east.multiplyScalar(Math.sin(bearing))).normalize();
  }
}

const cameraProfiles: Record<
  Exclude<CameraMode, 'global'>,
  {
    forward: number;
    right: number;
    up: number;
    distance: number;
    lookAhead: number;
    lookUp: number;
  }
> = {
  follow: { forward: -0.9, right: 0, up: 0.48, distance: 1.15, lookAhead: 0.35, lookUp: 0.1 },
  cockpit: { forward: 0.18, right: 0, up: 0.16, distance: 0.56, lookAhead: 1.2, lookUp: 0.05 },
  leftWindow: { forward: -0.08, right: -0.7, up: 0.2, distance: 0.9, lookAhead: 0.28, lookUp: 0.04 },
  rightWindow: { forward: -0.08, right: 0.7, up: 0.2, distance: 0.9, lookAhead: 0.28, lookUp: 0.04 },
  tail: { forward: -1.45, right: 0, up: 0.3, distance: 1.35, lookAhead: 0.7, lookUp: 0.07 },
  topDown: { forward: -0.12, right: 0, up: 1.35, distance: 1.2, lookAhead: 0.18, lookUp: 0 }
};
