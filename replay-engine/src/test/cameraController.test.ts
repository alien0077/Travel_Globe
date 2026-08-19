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

  it('allows total route view to orbit with drag gestures', () => {
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    const controller = new CameraController(camera);
    const point = { latitude: 22.6, longitude: 120.3, altitudeMeters: 9_500 };
    controller.setMode('totalRoute');

    for (let index = 0; index < 36; index += 1) {
      controller.update(point, 35);
    }
    const before = camera.position.clone();

    controller.rotate(100, 45);
    for (let index = 0; index < 36; index += 1) {
      controller.update(point, 35);
    }

    expect(camera.position.distanceTo(before)).toBeGreaterThan(0.2);
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

  it('keeps the cockpit horizon level while aircraft pitch and roll change', () => {
    const levelCamera = new THREE.PerspectiveCamera(55, 1, 0.1, 100);
    const bankedCamera = new THREE.PerspectiveCamera(55, 1, 0.1, 100);
    const levelController = new CameraController(levelCamera);
    const bankedController = new CameraController(bankedCamera);
    const point = { latitude: 25.1, longitude: 121.6, altitudeMeters: 5_000 };

    levelController.setMode('pilotView');
    bankedController.setMode('pilotView');
    levelController.update(point, 52, { snap: true, aircraftPitchDegrees: 0, aircraftRollDegrees: 0 });
    bankedController.update(point, 52, { snap: true, aircraftPitchDegrees: 8, aircraftRollDegrees: 18 });

    expect(levelCamera.up.dot(bankedCamera.up)).toBeGreaterThan(0.999);
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

  it('keeps both cabin side cameras outside the globe and aimed at the surface at every flight height', () => {
    for (const mode of ['leftWindow', 'rightWindow'] as const) {
      for (const altitudeMeters of [0, 500, 5_000, 11_000, 50_000]) {
        const camera = new THREE.PerspectiveCamera(58, 1, 0.1, 100);
        const controller = new CameraController(camera);
        controller.setMode(mode);
        controller.update(
          { latitude: 25.1, longitude: 121.6, altitudeMeters },
          52,
          { snap: true, aircraftPitchDegrees: 6, aircraftRollDegrees: 8 }
        );

        const surfaceNormal = camera.position.clone().normalize();
        const direction = new THREE.Vector3();
        camera.getWorldDirection(direction);
        expect(camera.position.length()).toBeGreaterThan(2);
        // 側窗視線只需略朝地表，不能像 global/overhead 一樣直指地心。
        expect(direction.dot(surfaceNormal)).toBeLessThan(-0.03);
        expect(direction.dot(surfaceNormal)).toBeGreaterThan(-0.8);
      }
    }
  });
});
