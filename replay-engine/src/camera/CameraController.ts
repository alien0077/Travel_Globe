import * as THREE from 'three';
import type { GeographicPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';
import { altitudePerspectiveFactor, pilotViewPerspective } from './flightPerspective';

export type FlightSystemCameraMode = 'flightPreview' | 'totalRoute' | 'midFlight' | 'overhead' | 'commandCenter' | 'pilotView';
export type LegacyCameraMode = 'global' | 'follow' | 'orbit' | 'cockpit' | 'leftWindow' | 'rightWindow' | 'tail' | 'topDown';
export type CameraMode = FlightSystemCameraMode | LegacyCameraMode;

// 地球半徑在場景中是 2；高度必須使用相同比例，否則 36,000 呎會被
// 放大成數百公里，客艙窗就會看到不應出現的遠方大陸。
export const CAMERA_ALTITUDE_SCALE_METERS = 6371008.8 / 2;
// 客艙相機必須跟著飛機實際高度走；相機本身另以 eye offset 保持在地表外側，
// 不可把起飛 0% 的畫面墊到高空，否則左右窗會變成俯視地圖。
const INTERIOR_ALTITUDE_FLOOR_METERS = 0;
// 只留極小的球面外偏移避免 FrontSide 在地表零高度時被剔除；
// 0.00025 約 0.8 公里，不再把相機墊到 95 公里外。
// 客艙相機要離開球面一小段距離，否則側視光線會在球面切線上
// 只取到極少數像素，地表會塌成單色帶。這仍是近地平線的人眼視角，
// 不是把相機拉到地球外圍。
export const INTERIOR_EYE_OUTWARD_OFFSET = 0.005;

export interface CameraUpdateOptions {
  snap?: boolean;
  focusPoint?: GeographicPoint;
  focusStrength?: number;
  nearGroundStrength?: number;
  aircraftRollDegrees?: number;
  aircraftPitchDegrees?: number;
}

export class CameraController {
  mode: CameraMode = 'global';
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
    this.orbitPitch = THREE.MathUtils.clamp(this.orbitPitch + deltaY * 0.004, -1.18, 1.18);
  }

  zoomBy(delta: number): void {
    this.zoom = THREE.MathUtils.clamp(this.zoom * (1 + delta), 0.16, 2.8);
  }

  update(point: GeographicPoint, bearingDegrees: number, options: CameraUpdateOptions = {}): void {
    const lerpAmount = options.snap ? 1 : undefined;
    const aircraftPosition = geographicToVector3(point, 2, CAMERA_ALTITUDE_SCALE_METERS);
    const aircraftDisplayPoint = {
      ...point,
      altitudeMeters: Math.max(point.altitudeMeters ?? 0, INTERIOR_ALTITUDE_FLOOR_METERS)
    };
    const interiorAircraftPosition = geographicToVector3(aircraftDisplayPoint, 2, CAMERA_ALTITUDE_SCALE_METERS);
    this.target.set(aircraftPosition.x, aircraftPosition.y, aircraftPosition.z);
    const focusStrength = THREE.MathUtils.clamp(options.focusStrength ?? 0, 0, 1);
    const nearGroundStrength = THREE.MathUtils.clamp(options.nearGroundStrength ?? focusStrength, 0, 1);
    if (options.focusPoint && focusStrength > 0) {
      const focusPosition = geographicToVector3(options.focusPoint, 2, CAMERA_ALTITUDE_SCALE_METERS);
      this.target.lerp(new THREE.Vector3(focusPosition.x, focusPosition.y, focusPosition.z), focusStrength);
    }
    const normal = this.target.clone().normalize();
    const forward = this.forwardVector(normal, bearingDegrees);
    if (this.mode !== 'pilotView') {
      this.setFieldOfView(45);
    }

    if (this.mode === 'totalRoute') {
      const yawedForward = forward.clone().applyAxisAngle(normal, this.orbitYaw);
      const right = new THREE.Vector3().crossVectors(yawedForward, normal).normalize();
      const distance = THREE.MathUtils.clamp(1.95 * this.zoom, 1.35, 4.2);
      const routeElevation = THREE.MathUtils.clamp(1.2 + this.orbitPitch * 0.72, 0.62, 2.45);
      this.desired
        .copy(this.target)
        .add(yawedForward.clone().multiplyScalar(-distance))
        .add(right.multiplyScalar(0.36 * distance))
        .add(normal.clone().multiplyScalar(routeElevation * this.zoom));
      this.camera.position.lerp(this.desired, lerpAmount ?? 0.1);
      this.camera.up.copy(normal);
      this.camera.lookAt(
        this.target
          .clone()
          .add(yawedForward.clone().multiplyScalar(0.28))
          .add(normal.clone().multiplyScalar(0.28))
      );
      return;
    }

    if (this.mode === 'overhead') {
      const right = new THREE.Vector3().crossVectors(forward, normal).normalize();
      const airportZoom = THREE.MathUtils.lerp(1.18, 0.38, nearGroundStrength) * this.zoom;
      this.desired
        .copy(this.target)
        .add(normal.clone().multiplyScalar(airportZoom))
        .add(right.multiplyScalar(THREE.MathUtils.lerp(0.09, 0.018, nearGroundStrength)))
        .add(forward.clone().multiplyScalar(THREE.MathUtils.lerp(-0.08, -0.012, nearGroundStrength)));
      this.camera.position.lerp(this.desired, lerpAmount ?? 0.12);
      this.camera.up.copy(forward);
      this.camera.lookAt(this.target);
      return;
    }

    if (this.mode === 'pilotView') {
      // 駕駛艙不是全球地球相機；必須和左右客艙窗一樣掛在飛機上。
      // 舊分支使用數十公里的固定 eyeHeightOffset，配合客艙近景裁切後
      // 只剩天空，且不會隨飛機高度正確看到日本地表。
      const pilotOrigin = new THREE.Vector3(
        interiorAircraftPosition.x,
        interiorAircraftPosition.y,
        interiorAircraftPosition.z
      );
      const pilotNormal = pilotOrigin.clone().normalize();
      const pilotForward = this.forwardVector(pilotNormal, bearingDegrees);
      const pilotPerspective = pilotViewPerspective(point);
      this.setFieldOfView(pilotPerspective.fieldOfViewDegrees);
      this.desired
        .copy(pilotOrigin)
        .add(pilotNormal.clone().multiplyScalar(INTERIOR_EYE_OUTWARD_OFFSET))
        .add(pilotForward.clone().multiplyScalar(0.018));
      // 進度條／50x 模擬可能一次跳過很長航段；機內相機不能沿用上一個
      // 航點的平滑位置，否則新的水平基準會和舊位置混合，造成中段斜視。
      this.camera.position.copy(this.desired);
      const horizonLookTarget = this.camera.position
        .clone()
        .add(pilotForward.clone().multiplyScalar(0.8))
        .add(pilotNormal.clone().multiplyScalar(
          THREE.MathUtils.lerp(-0.08, -0.24, pilotPerspective.altitudeFactor)
        ));
      const pilotDirection = horizonLookTarget.clone().sub(this.camera.position).normalize();
      // 向下看時不能直接把地表法線當 camera.up，否則 lookAt 會在
      // 每個航向重新扭轉畫面，造成直飛時 HUD／地平線持續左斜右斜。
      const pilotLevelUp = pilotNormal.clone()
        .addScaledVector(pilotDirection, -pilotNormal.dot(pilotDirection))
        .normalize();
      this.camera.up.copy(pilotLevelUp);
      this.camera.lookAt(horizonLookTarget);
      return;
    }

    if (this.mode === 'flightPreview') {
      // 飛機 360°是「看飛機本體」的最大化視角，不是地球追蹤視角。
      const yawedForward = forward.clone().applyAxisAngle(normal, this.orbitYaw * 0.22);
      const yawedRight = new THREE.Vector3().crossVectors(yawedForward, normal).normalize();
      const distance = THREE.MathUtils.clamp(0.34 * this.zoom, 0.26, 0.46);
      this.setFieldOfView(42);
      this.desired
        .copy(this.target)
        .add(yawedForward.multiplyScalar(-distance))
        .add(yawedRight.multiplyScalar(-distance * 0.08))
        .add(normal.clone().multiplyScalar(distance * 0.16));
      this.camera.position.lerp(this.desired, lerpAmount ?? 0.16);
      this.camera.up.copy(normal);
      this.camera.lookAt(this.target.clone().add(forward.multiplyScalar(0.015)));
      return;
    }

    if (isInteriorCameraMode(this.mode)) {
      // 機內相機必須掛在飛機，而不是掛在地球球面或附近城市的 focusPoint。
      // 先建立飛機自身的 forward/right/up，再套用俯仰與滾轉，三個視角共用
      // 同一個沿航線移動的 camera origin。
      const altitudeFactor = altitudePerspectiveFactor(point);
      const aircraftOrigin = new THREE.Vector3(
        interiorAircraftPosition.x,
        interiorAircraftPosition.y,
        interiorAircraftPosition.z
      );
      const aircraftNormal = aircraftOrigin.clone().normalize();
      const aircraftForward = this.forwardVector(aircraftNormal, bearingDegrees);
      const aircraftRight = new THREE.Vector3().crossVectors(aircraftForward, aircraftNormal).normalize();
      // Three.js 的局部右軸方向與航空姿態的 pitch 正方向相反；
      // 不反轉時，起飛爬升會被渲染成機頭朝下，地表也會被推到窗戶上緣。
      const pitchRadians = -THREE.MathUtils.degToRad(
        THREE.MathUtils.clamp(options.aircraftPitchDegrees ?? 0, -10, 12)
      );
      const rollRadians = THREE.MathUtils.degToRad(
        THREE.MathUtils.clamp(options.aircraftRollDegrees ?? 0, -18, 18)
      );
      const pitchedForward = aircraftForward.clone().applyAxisAngle(aircraftRight, pitchRadians).normalize();
      const pitchedUp = aircraftNormal.clone().applyAxisAngle(aircraftRight, pitchRadians).normalize();
      const pitchedRight = new THREE.Vector3().crossVectors(pitchedForward, pitchedUp).normalize();
      const cabinRight = pitchedRight.clone().applyAxisAngle(pitchedForward, rollRadians).normalize();
      const cabinUp = pitchedUp.clone().applyAxisAngle(pitchedForward, rollRadians).normalize();
      const forwardOffset = THREE.MathUtils.lerp(0.025, 0.08, altitudeFactor);

      if (this.mode === 'leftWindow' || this.mode === 'rightWindow') {
        const lateral = this.mode === 'leftWindow' ? -1 : 1;
        // 客艙側窗是「側向看出去」，不是把鏡頭對準地心的俯視圖。
        // 以切線需求計算最低向內量，再加一點人眼自然下看的角度，
        // 讓窗內大致保持上半天空、下半地表；高空才逐步增加下視量。
        const cameraRadius = Math.hypot(
          interiorAircraftPosition.x,
          interiorAircraftPosition.y,
          interiorAircraftPosition.z
        ) + INTERIOR_EYE_OUTWARD_OFFSET;
        const tangentDrop = Math.sqrt(Math.max(0, 1 - (2.001 / cameraRadius) ** 2));
        // 人眼只略微朝下；固定在接近一半天空、一半地表的地平線，
        // 不讓側窗變成從高空俯視地球的畫面。
        // 在起飛與低空階段，視線只比幾何地平線略微向下；原本的
        // 0.16 最小值會讓鏡頭直接穿過近地表，形成整片斜切的地表／藍色
        // 背景。高度升高後才逐步增加下視量。
        const inwardAmount = THREE.MathUtils.clamp(tangentDrop + 0.015, 0.04, 0.36);
        // 俯仰／滾轉後的 cabinRight 可能混入少量地心方向；
        // 先投影回地表切平面，確保左右窗的地平線完全對稱。
        const sideAxis = cabinRight.clone()
          .add(aircraftNormal.clone().multiplyScalar(-cabinRight.dot(aircraftNormal)))
          .normalize();
        this.setFieldOfView(58);
        this.desired.copy(aircraftOrigin)
          // 起飛 0% 時飛機就在地球半徑上；相機必須明確位於球面外，
          // 否則 FrontSide 地表材質會被當成背面剔除，留下淡藍背景與斜帶。
          .add(aircraftNormal.clone().multiplyScalar(INTERIOR_EYE_OUTWARD_OFFSET))
          .add(cabinRight.clone().multiplyScalar(lateral * 0.012))
          .add(cabinUp.clone().multiplyScalar(INTERIOR_EYE_OUTWARD_OFFSET));
        // 姿態向量可能在低空把相機微量推入球面；只做球面外校正，
        // 不增加可視半徑，避免 FrontSide 背面剔除造成錯誤地表。
        if (this.desired.length() <= 2) {
          this.desired.setLength(2.0001);
        }
        this.camera.position.copy(this.desired);
        const sideViewDirection = sideAxis.multiplyScalar(lateral)
          .add(pitchedForward.clone().multiplyScalar(0.05))
          .add(aircraftNormal.clone().multiplyScalar(-inwardAmount))
          .normalize();
        const sideLookTarget = this.camera.position.clone().add(sideViewDirection.multiplyScalar(4));
        // 機身 pitch/roll 是飛行姿態，不是客艙畫面的螢幕水平基準。
        // 以當地地表法線投影到視線法平面，讓直飛時地平線保持水平；
        // 只有真正的轉彎才由視線方向自然產生小幅傾斜。
        const sideLevelUp = aircraftNormal.clone()
          .addScaledVector(sideViewDirection, -aircraftNormal.dot(sideViewDirection))
          .normalize();
        this.camera.up.copy(sideLevelUp);
        this.camera.lookAt(sideLookTarget);
        return;
      }

      // 駕駛艙視角保持水平：飛機的爬升／滾轉只屬於飛行資料與 HUD，
      // 不應把整個乘客看到的地平線一起翻斜。相機以當地地表法線為上方，
      // 沿航線前進並略微朝下，維持自然的人眼視線。
      const cockpitDirection = aircraftForward.clone()
        // 駕駛艙人眼略微朝下；在接近目的地的低高度也要讓窗內
        // 同時保留天空與前方地表，不能只剩一整片天空。
        .add(aircraftNormal.clone().multiplyScalar(-1.5))
        .normalize();
      this.setFieldOfView(55);
      this.desired.copy(aircraftOrigin)
        .add(aircraftForward.clone().multiplyScalar(forwardOffset))
        .add(aircraftNormal.clone().multiplyScalar(INTERIOR_EYE_OUTWARD_OFFSET));
      this.camera.position.copy(this.desired);
      const cockpitLevelUp = aircraftNormal.clone()
        .addScaledVector(cockpitDirection, -aircraftNormal.dot(cockpitDirection))
        .normalize();
      this.camera.up.copy(cockpitLevelUp);
      this.camera.lookAt(this.camera.position.clone().add(cockpitDirection));
      return;
    }

    if (this.mode === 'global') {
      const distance = THREE.MathUtils.clamp(2.8 * this.zoom, 1.65, 5.8);
      const yaw = this.orbitYaw;
      const pitch = 0.45 + this.orbitPitch;
      const orbitDirection = new THREE.Vector3(
        Math.sin(yaw) * Math.cos(pitch),
        Math.sin(pitch),
        Math.cos(yaw) * Math.cos(pitch)
      ).normalize();
      const focusVector = options.focusPoint && focusStrength > 0
        ? geographicToVector3(options.focusPoint, 1, 900000)
        : undefined;
      const focusDirection = focusVector
        ? new THREE.Vector3(focusVector.x, focusVector.y, focusVector.z).normalize()
        : undefined;
      const baseDirection = focusDirection
        ? focusDirection.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw * 0.45)
        : orbitDirection;
      const base = baseDirection.normalize().multiplyScalar(distance);
      this.camera.position.lerp(base, lerpAmount ?? 0.08);
      this.camera.up.set(0, 1, 0);
      this.camera.lookAt(0, 0, 0);
      return;
    }

    if (this.mode === 'orbit') {
      const orbitAngle = performance.now() * 0.00022 + this.orbitYaw;
      const orbitRight = new THREE.Vector3().crossVectors(forward, normal).normalize();
      const cinematicOffset = forward
        .clone()
        .multiplyScalar(Math.cos(orbitAngle) * -1.1)
        .add(orbitRight.multiplyScalar(Math.sin(orbitAngle) * 1.1))
        .add(normal.clone().multiplyScalar(0.5 + this.orbitPitch * 0.28))
        .multiplyScalar(this.zoom);
      this.camera.position.lerp(this.target.clone().add(cinematicOffset), lerpAmount ?? 0.08);
      this.camera.up.copy(normal);
      this.camera.lookAt(this.target.clone().add(normal.clone().multiplyScalar(0.08)));
      return;
    }

    const profile = cameraProfiles[this.mode];
    const yawedForward = forward.clone().applyAxisAngle(normal, this.orbitYaw);
    const yawedRight = new THREE.Vector3().crossVectors(yawedForward, normal).normalize();
    const nearGroundZoom = THREE.MathUtils.lerp(1, 0.42, nearGroundStrength);
    const nearGroundLook = THREE.MathUtils.lerp(1, 0.72, nearGroundStrength);
    const pitchedUp = normal.clone().multiplyScalar(profile.up * nearGroundZoom + this.orbitPitch * 0.35);
    const distance = profile.distance * this.zoom * nearGroundZoom;

    this.desired
      .copy(this.target)
      .add(yawedForward.multiplyScalar(profile.forward * distance))
      .add(yawedRight.multiplyScalar(profile.right * distance))
      .add(pitchedUp);

    this.camera.position.lerp(this.desired, lerpAmount ?? 0.1);

    const lookAhead = this.target
      .clone()
      .add(forward.multiplyScalar(profile.lookAhead * nearGroundLook))
      .add(normal.multiplyScalar(profile.lookUp * nearGroundZoom));
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

  private setFieldOfView(fieldOfViewDegrees: number): void {
    if (Math.abs(this.camera.fov - fieldOfViewDegrees) < 0.05) {
      return;
    }
    this.camera.fov = fieldOfViewDegrees;
    this.camera.updateProjectionMatrix();
  }
}

function isInteriorCameraMode(mode: CameraMode): boolean {
  return mode === 'cockpit' || mode === 'leftWindow' || mode === 'rightWindow';
}

const cameraProfiles: Record<
  Exclude<CameraMode, 'global' | 'orbit' | 'totalRoute' | 'overhead' | 'pilotView'>,
  {
    forward: number;
    right: number;
    up: number;
    distance: number;
    lookAhead: number;
    lookUp: number;
  }
> = {
  flightPreview: { forward: -0.9, right: -0.72, up: 0.46, distance: 0.82, lookAhead: 0.24, lookUp: 0.06 },
  midFlight: { forward: -0.95, right: -0.5, up: 0.52, distance: 1.42, lookAhead: 0.42, lookUp: 0.1 },
  commandCenter: { forward: -1.12, right: 0.82, up: 0.82, distance: 1.58, lookAhead: 0.62, lookUp: 0.08 },
  follow: { forward: -0.9, right: 0, up: 0.48, distance: 1.15, lookAhead: 0.35, lookUp: 0.1 },
  cockpit: { forward: 0.18, right: 0, up: 0.16, distance: 0.56, lookAhead: 1.2, lookUp: 0.05 },
  leftWindow: { forward: -0.08, right: -0.7, up: 0.2, distance: 0.9, lookAhead: 0.28, lookUp: 0.04 },
  rightWindow: { forward: -0.08, right: 0.7, up: 0.2, distance: 0.9, lookAhead: 0.28, lookUp: 0.04 },
  tail: { forward: -1.45, right: 0, up: 0.3, distance: 1.35, lookAhead: 0.7, lookUp: 0.07 },
  topDown: { forward: -0.12, right: 0, up: 1.35, distance: 1.2, lookAhead: 0.18, lookUp: 0 }
};
