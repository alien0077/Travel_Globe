import * as THREE from 'three';
import { describe, expect, it } from 'vitest';
import { CameraController, type CameraMode } from '../camera/CameraController';
import { firstPersonRouteLookAheadMeters, sceneObjectScaleForAltitude } from '../camera/flightPerspective';

describe('camera controller interaction', () => {
  it('zooms global view toward the globe while keeping free orbit control', () => {
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    const controller = new CameraController(camera);
    const point = { latitude: 35.7, longitude: 140.0, altitudeMeters: 10_000 };
    controller.setMode('global');

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

  it('keeps the flight-system presets in usable viewing ranges', () => {
    const point = { latitude: 35.7, longitude: 140.0, altitudeMeters: 10_000 };
    const modes: CameraMode[] = ['flightPreview', 'totalRoute', 'midFlight', 'overhead', 'commandCenter', 'pilotView'];
    const distances = new Map<CameraMode, number>();

    for (const mode of modes) {
      const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
      const controller = new CameraController(camera);
      controller.setMode(mode);
      for (let index = 0; index < 36; index += 1) {
        controller.update(point, 60);
      }
      expect(Number.isFinite(camera.position.x)).toBe(true);
      expect(Number.isFinite(camera.position.y)).toBe(true);
      expect(Number.isFinite(camera.position.z)).toBe(true);
      expect(camera.position.length()).toBeGreaterThan(1.6);
      expect(camera.position.length()).toBeLessThan(8.9);
      distances.set(mode, camera.position.length());
    }

    expect(distances.get('totalRoute')).toBeGreaterThan(distances.get('flightPreview') ?? 0);
  });

  it('keeps low-altitude pilot view close to the horizon with a narrow local scale', () => {
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    const controller = new CameraController(camera);
    const point = { latitude: 25.1, longitude: 121.6, altitudeMeters: 450 };
    controller.setMode('pilotView');

    for (let index = 0; index < 48; index += 1) {
      controller.update(point, 52);
    }

    const normal = camera.position.clone().normalize();
    const direction = new THREE.Vector3();
    camera.getWorldDirection(direction);
    const horizonBias = direction.dot(normal);

    expect(horizonBias).toBeGreaterThan(-0.12);
    expect(horizonBias).toBeLessThan(-0.02);
    expect(camera.fov).toBeLessThan(43);
  });

  it('widens pilot view and shrinks scene objects as altitude increases', () => {
    const lowCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    const highCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    const lowController = new CameraController(lowCamera);
    const highController = new CameraController(highCamera);
    const lowPoint = { latitude: 25.1, longitude: 121.6, altitudeMeters: 450 };
    const highPoint = { latitude: 25.1, longitude: 121.6, altitudeMeters: 11_200 };

    lowController.setMode('pilotView');
    highController.setMode('pilotView');
    lowController.update(lowPoint, 52, { snap: true });
    highController.update(highPoint, 52, { snap: true });

    expect(highCamera.fov).toBeGreaterThan(lowCamera.fov + 10);
    expect(firstPersonRouteLookAheadMeters(highPoint)).toBeGreaterThan(firstPersonRouteLookAheadMeters(lowPoint) * 10);
    expect(sceneObjectScaleForAltitude(highPoint)).toBeLessThan(sceneObjectScaleForAltitude(lowPoint));
  });
});
