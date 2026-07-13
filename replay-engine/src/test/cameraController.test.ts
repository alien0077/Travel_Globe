import * as THREE from 'three';
import { describe, expect, it } from 'vitest';
import { CameraController } from '../camera/CameraController';

describe('camera controller interaction', () => {
  it('zooms global view toward the globe while keeping free orbit control', () => {
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    const controller = new CameraController(camera);
    const point = { latitude: 35.7, longitude: 140.0, altitudeMeters: 10_000 };

    for (let index = 0; index < 24; index += 1) {
      controller.update(point, 60);
    }
    const initialDistance = camera.position.length();

    controller.zoomBy(-0.82);
    for (let index = 0; index < 32; index += 1) {
      controller.update(point, 60);
    }

    expect(camera.position.length()).toBeLessThan(initialDistance);
    expect(camera.position.length()).toBeGreaterThan(1.6);
    expect(camera.position.distanceTo(new THREE.Vector3(0, 0, 0))).toBeLessThan(initialDistance);
  });

  it('uses drag deltas in the same direction as the gesture', () => {
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    const controller = new CameraController(camera);
    const point = { latitude: 35.7, longitude: 140.0, altitudeMeters: 10_000 };

    controller.zoomBy(-0.82);
    for (let index = 0; index < 24; index += 1) {
      controller.update(point, 60);
    }
    const before = camera.position.clone();

    controller.rotate(90, 60);
    for (let index = 0; index < 24; index += 1) {
      controller.update(point, 60);
    }

    expect(camera.position.x).toBeGreaterThan(before.x);
    expect(camera.position.y).toBeGreaterThan(before.y);
  });
});
