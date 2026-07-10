import * as THREE from 'three';
import type { GeographicPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';

export type CameraMode = 'global' | 'follow';

export class CameraController {
  mode: CameraMode = 'global';

  constructor(private readonly camera: THREE.PerspectiveCamera) {}

  setMode(mode: CameraMode): void {
    this.mode = mode;
  }

  update(point: GeographicPoint): void {
    if (this.mode === 'global') {
      this.camera.position.lerp(new THREE.Vector3(0, 2.45, 5.2), 0.035);
      this.camera.lookAt(0, 0, 0);
      return;
    }

    const aircraftPosition = geographicToVector3(point, 2, 700000);
    const target = new THREE.Vector3(aircraftPosition.x, aircraftPosition.y, aircraftPosition.z);
    const normal = target.clone().normalize();
    const desired = target.clone().add(normal.multiplyScalar(1.0)).add(new THREE.Vector3(0, 0.35, 0.18));

    this.camera.position.lerp(desired, 0.08);
    this.camera.lookAt(target);
  }
}
