import * as THREE from 'three';
import {
  CAMERA_ALTITUDE_SCALE_METERS,
  CameraController,
  INTERIOR_EYE_OUTWARD_OFFSET,
  type CameraMode
} from '../camera/CameraController';
import {
  altitudePerspectiveFactor,
  firstPersonRouteLookAheadMeters,
  sceneObjectScaleForAltitude
} from '../camera/flightPerspective';
import type { JourneySegment, LocationPoint, PlaceReference } from '../data/types';
import type { FlightOverlay } from '../flight/flightAnalytics';
import { landmarkDisplayName, type GeographicFeature } from '../geo/landmarks';
import {
  EARTH_RADIUS_METERS,
  geographicToVector3,
  haversineDistanceMeters,
  interpolateGreatCircle
} from '../geo/geodesy';
import { createAircraftMarker, placeAircraftMarker, type AircraftAttitude } from '../models/createAircraftMarker';
import { createRouteTrack, updateRouteTrack, type RouteTrack } from '../route/createRouteLine';
import { simulatedCloudCoverFraction } from '../weather/simulatedCloudCover';
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
  scale: number;
}

export class TravelGlobeScene {
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly cameraController: CameraController;
  private readonly aircraft: THREE.Group;
  private readonly earth: THREE.Mesh;
  private readonly earthMaterial: THREE.MeshStandardMaterial;
  private readonly cabinEarthMaterial: THREE.MeshBasicMaterial;
  private readonly boundaries: THREE.Group;
  private readonly clouds: THREE.Mesh;
  private readonly nightLights: THREE.Mesh;
  private readonly atmosphere: THREE.Mesh;
  private readonly skyDome: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>;
  private readonly starField: THREE.Points;
  private readonly nightSurfaceWash: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>;
  private readonly ambient: THREE.AmbientLight;
  private readonly sun: THREE.DirectionalLight;
  private readonly cityLights: THREE.InstancedMesh;
  private readonly cityLightMaterial: THREE.MeshBasicMaterial;
  private readonly airportMarkers: THREE.Group;
  private readonly labelLayer: HTMLDivElement;
  private readonly focusedAirportLabel: HTMLSpanElement;
  private readonly landmarkLabels: GlobeDomLabel[];
  private readonly routeTrack: RouteTrack;
  private readonly resizeObserver: ResizeObserver;
  private readonly activePointers = new Map<number, PointerEvent>();
  private currentCameraMode: CameraMode = 'flightPreview';
  private currentPoint?: LocationPoint;
  private previousCameraMode?: CameraMode;
  private suppressLabelsUntilMs = 0;
  private previousPinchDistance?: number;
  private snapInteriorCamera = false;

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
      alpha: false,
      preserveDrawingBuffer: true
    });
    // 截圖驗收時降低畫布 backing resolution，避免高 DPI WebGL 擷取逾時；
    // 正式 Web／iOS 不帶 proof-lowres，仍維持原本的裝置解析度。
    const proofLowResolution = new URLSearchParams(window.location.search).has('proof-lowres');
    this.renderer.setPixelRatio(proofLowResolution ? 1 : Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMappingExposure = 1.1;
    this.renderer.setClearColor(0x2a4d68, 1);
    this.container.appendChild(this.renderer.domElement);
    this.labelLayer = document.createElement('div');
    this.labelLayer.className = 'globe-label-layer';
    this.focusedAirportLabel = document.createElement('span');
    this.focusedAirportLabel.className = 'globe-place-label is-airport is-focused-airport is-hidden';
    this.landmarkLabels = createDomLandmarkLabels(this.labelLayer, [
      ...createAirportFeatures(segment.origin, segment.destination),
      ...routeLandmarks
    ]);
    this.labelLayer.appendChild(this.focusedAirportLabel);
    this.container.appendChild(this.labelLayer);
    this.bindInteraction();

    this.skyDome = createSkyDome();
    this.scene.background = new THREE.Color(0x2a4d68);
    this.scene.fog = new THREE.Fog(0x2a4d68, 9, 18);
    this.scene.add(this.skyDome);
    this.starField = createStarField(360, 46);
    this.scene.add(this.starField);

    const { globe, earth, boundaries, clouds, nightLights, atmosphere } = createGlobe(
      2,
      this.renderer.capabilities.getMaxAnisotropy(),
      this.renderer.capabilities.maxTextureSize
    );
    this.earth = earth;
    this.boundaries = boundaries;
    this.earthMaterial = earth.material as THREE.MeshStandardMaterial;
    this.cabinEarthMaterial = new THREE.MeshBasicMaterial({
      // 客艙視角直接顯示與 Web 全球視角相同的 Blue Marble 貼圖。
      // 不使用球面燈光、emissive 或 bump，避免低高度側視時把地表壓成
      // 一條灰色帶；天空亮度由場景背景處理，地表顏色由貼圖原值決定。
      color: new THREE.Color(0xffffff),
      map: this.earthMaterial.map ?? null,
      // 側窗視線會貼著球面掠過；在地平線附近，浮點誤差可能讓
      // 可見交點被判成背面。雙面只作用於客艙地表，不會讓天空變成地面，
      // 但能確保低空與高空的貼圖連續顯示。
      side: THREE.DoubleSide
    });
    this.clouds = clouds;
    this.nightLights = nightLights;
    this.atmosphere = atmosphere;
    this.scene.add(globe);
    this.nightSurfaceWash = createNightSurfaceWash();
    this.scene.add(this.nightSurfaceWash);
    this.airportMarkers = createAirportSurfaceMarkers(segment.origin, segment.destination);
    this.scene.add(this.airportMarkers);
    const cityLights = createRouteCityLights(routeLandmarks);
    this.cityLights = cityLights.mesh;
    this.cityLightMaterial = cityLights.material;
    this.scene.add(this.cityLights);
    this.routeTrack = createRouteTrack(segment.derivedReplayRoute.points, [segment.derivedReplayRoute.points[0]], 180000);
    this.scene.add(this.routeTrack);
    this.scene.add(this.aircraft);

    this.ambient = new THREE.AmbientLight(0xf5fbff, 3.6);
    this.sun = new THREE.DirectionalLight(0xffffff, 5.6);
    this.sun.position.set(-3, 4, 7);
    this.scene.add(this.ambient, this.sun);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.container);
    this.resize();
  }

  update(
    point: LocationPoint,
    bearingDegrees: number,
    cameraMode: CameraMode,
    actualRoutePoints: LocationPoint[],
    aircraftAttitude: AircraftAttitude = {}
  ): void {
    if (cameraMode !== this.currentCameraMode) {
      this.activePointers.clear();
      this.previousPinchDistance = undefined;
    }
    const snapCamera = shouldSnapCamera(this.currentPoint, point, this.previousCameraMode, cameraMode)
      || (isFirstPersonCameraMode(cameraMode) && this.snapInteriorCamera);
    if (snapCamera && this.currentPoint && !isFirstPersonCameraMode(cameraMode)) {
      this.suppressLabelsUntilMs = performance.now() + 180;
      this.hideAllLabels();
    }
    this.currentPoint = point;
    this.currentCameraMode = cameraMode;
    this.previousCameraMode = cameraMode;
    const airportFocus = airportFocusForPoint(point, this.segment);
    const nearGroundStrength = nearGroundAirportStrength(point, airportFocus.strength);
    this.container.dataset.airportFocus = airportFocus.strength.toFixed(3);
    this.container.dataset.nearGroundFocus = nearGroundStrength.toFixed(3);
    this.container.dataset.airportMarkerPlacement = 'surface-plane';
    this.container.dataset.cityLightPlacement = this.cityLights.userData.surfaceLocked === true ? 'surface-plane' : 'floating';
    const rollDegrees = THREE.MathUtils.clamp(aircraftAttitude.rollDegrees ?? 0, -18, 18);
    this.container.parentElement?.style.setProperty('--cabin-bank-angle', `${rollDegrees.toFixed(2)}deg`);
    placeAircraftMarker(this.aircraft, point, bearingDegrees, aircraftAttitude);
    const aircraftScale = cameraMode === 'flightPreview'
      ? 1.42
      : cameraMode === 'follow'
        ? 0.34
        : lerp(1, 0.095, nearGroundStrength);
    this.aircraft.scale.setScalar(aircraftScale);
    this.aircraft.visible = cameraMode !== 'pilotView' && !isInteriorCameraMode(cameraMode);
    this.updateAirportMarkers(point, nearGroundStrength, cameraMode);
    const visibleRoutePoints = visibleRouteWindowForCameraMode(
      this.segment.derivedReplayRoute.points,
      point,
      cameraMode
    );
    const visibleActualRoutePoints = isFirstPersonCameraMode(cameraMode) ? [point] : actualRoutePoints;
    updateRouteTrack(this.routeTrack, visibleRoutePoints, visibleActualRoutePoints, 180000);
    this.updateRouteAppearance(point, cameraMode);
    this.updateDayNight(point);
    this.setCockpitSceneVisibility(cameraMode);
    this.cameraController.setMode(cameraMode);
    const routeFocusPoint = this.segment.derivedReplayRoute.points[
      Math.floor(this.segment.derivedReplayRoute.points.length / 2)
    ];
    const sceneFocusPoint = cameraMode === 'global' || cameraMode === 'totalRoute'
      ? routeFocusPoint
      : cameraMode === 'flightPreview' || cameraMode === 'follow' || isInteriorCameraMode(cameraMode)
        ? point
        : airportFocus.point;
    this.cameraController.update(point, bearingDegrees, {
      snap: snapCamera,
      focusPoint: sceneFocusPoint,
      focusStrength: cameraMode === 'global' || cameraMode === 'totalRoute' ? 1 : airportFocus.strength,
      nearGroundStrength,
      aircraftRollDegrees: rollDegrees,
      aircraftPitchDegrees: aircraftAttitude.pitchDegrees
    });
    this.snapInteriorCamera = false;
    this.container.dataset.cameraRadius = this.camera.position.length().toFixed(3);
    this.container.dataset.cameraMode = cameraMode;
    const cameraDirection = new THREE.Vector3();
    this.camera.getWorldDirection(cameraDirection);
    this.container.dataset.cameraEarthDot = cameraDirection.dot(this.camera.position.clone().normalize()).toFixed(3);
    this.container.dataset.earthVisible = String(this.earth.visible);
  }

  start(onFrame: (timeMs: number) => void): void {
    // proof-freeze 只供截圖驗收；一般 proof-static／無參數網址仍保持互動。
    const staticProof = new URLSearchParams(window.location.search).has('proof-freeze');
    let proofFrames = 0;
    this.renderer.setAnimationLoop((timeMs) => {
      onFrame(timeMs);
      this.clouds.rotation.y = timeMs * 0.000012;
      this.updateLabelOverlay();
      this.syncCabinEarthMaterial();
      this.renderer.render(this.scene, this.camera);
      // 只供本機視覺驗收：先把 WebGL 畫面凍結成 PNG，再停止 render loop。
      // 這讓截圖工具擷取的是已渲染的實際畫面，而不是活動中的 WebGL buffer。
      if (staticProof && ++proofFrames >= 120) {
        // 驗收截圖只保留目前焦點地名；正式 render loop 不會移除任何標籤。
        for (const label of this.landmarkLabels) {
          label.element.remove();
        }
        const canvas = this.renderer.domElement;
        const proofImage = document.createElement('img');
        proofImage.src = canvas.toDataURL('image/png');
        proofImage.className = canvas.className;
        proofImage.setAttribute('aria-label', canvas.getAttribute('aria-label') ?? 'WebGL proof');
        proofImage.style.cssText = canvas.getAttribute('style') ?? 'display: block; width: 100%; height: 100%;';
        canvas.replaceWith(proofImage);
        this.renderer.setAnimationLoop(null);
      }
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
    // 艙內視角需要持續顯示窗外地名；拖曳模擬進度時不可先清空再淡入。
    this.suppressLabelsUntilMs = 0;
    // 拖曳進度或切換機內視角時，下一幀要把相機錨點直接放到新的航線點，
    // 不可沿用上一個位置慢慢追，否則使用者會以為相機沒有跟著飛機走。
    this.snapInteriorCamera = true;
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
    if (isInteractionLockedCamera(this.currentCameraMode)) {
      return;
    }
    this.renderer.domElement.setPointerCapture(event.pointerId);
    this.activePointers.set(event.pointerId, event);
    this.previousPinchDistance = this.currentPinchDistance();
  };

  private readonly handlePointerMove = (event: PointerEvent): void => {
    if (isInteractionLockedCamera(this.currentCameraMode)) {
      return;
    }
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
    if (isInteractionLockedCamera(this.currentCameraMode)) {
      return;
    }
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
    const sunVector = sunVectorAt(point.timestamp);
    this.sun.position.copy(sunVector.clone().multiplyScalar(8));
    const nightFactor = nightFactorAt(point, sunVector);
    const solarDay = localSolarDay(point);
    const sunDayFactor = 1 - nightFactor;
    const dayFactor = Number.isFinite(sunDayFactor) ? sunDayFactor : solarDay.factor;
    const nightAmount = 1 - dayFactor;
    this.container.dataset.dayFactor = dayFactor.toFixed(3);
    this.container.dataset.localSolarHour = solarDay.hour.toFixed(2);
    this.container.classList.toggle('is-daylight', dayFactor >= 0.55);
    this.container.parentElement?.classList.toggle('is-daylight-scene', dayFactor >= 0.55);
    this.renderer.toneMappingExposure = lerp(1.0, 1.36, dayFactor);
    const daySky = new THREE.Color(0xbfdff4);
    const nightSky = new THREE.Color(0x12324a);
    const sky = new THREE.Color().lerpColors(nightSky, daySky, dayFactor);
    this.scene.background = sky;
    this.renderer.setClearColor(sky, 1);
    this.skyDome.material.color.copy(sky);
    if (this.scene.fog) {
      this.scene.fog.color.copy(sky);
    }

    this.ambient.intensity = lerp(0.95, 4.05, dayFactor);
    this.sun.intensity = lerp(0.1, 5.8, dayFactor);
    this.earthMaterial.color.lerpColors(new THREE.Color(0x8aa5b8), new THREE.Color(0xffffff), dayFactor);
    this.earthMaterial.emissive.lerpColors(new THREE.Color(0x06131f), new THREE.Color(0x10202c), dayFactor);
    this.earthMaterial.emissiveIntensity = lerp(0.18, 0.16, dayFactor);
    this.cabinEarthMaterial.color.set(0xffffff);
    if (this.clouds.material instanceof THREE.Material) {
      const cloudCover = simulatedCloudCoverFraction(point, point.timestamp);
      this.container.dataset.simulatedCloudCover = cloudCover.toFixed(3);
      this.clouds.material.opacity = lerp(0.22, 0.5, cloudCover) * lerp(0.92, 1.08, dayFactor);
    }
    if (this.nightLights.material instanceof THREE.MeshBasicMaterial) {
      this.nightLights.material.color.set(0xff9a32);
      this.nightLights.material.opacity = lerp(0.0, 0.52, nightAmount);
    }
    this.nightSurfaceWash.material.opacity = lerp(0.12, 0.0, dayFactor);
    this.cityLightMaterial.opacity = lerp(0.0, 0.9, nightAmount);
    this.cityLights.visible = this.cityLightMaterial.opacity > 0.08;
  }

  private updateLabelOverlay(): void {
    const isInteriorView = isFirstPersonCameraMode(this.currentCameraMode);
    if (!isInteriorView && performance.now() < this.suppressLabelsUntilMs) {
      this.hideAllLabels();
      return;
    }

    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    this.camera.updateMatrixWorld();
    const candidates: LabelCandidate[] = [];
    const maxLabelDistance = this.currentPoint
      ? isInteriorView
        // 艙內窗戶只應標示視線內、且在飛行高度可合理辨識的附近地名。
        // 之前固定放寬到至少 650 km，會把遠方大陸／島嶼的名稱強制帶進窗內。
        ? interiorLabelDistanceLimitMeters(this.currentPoint)
        : labelDistanceLimitMeters(this.currentPoint, this.currentCameraMode)
      : 180000;

    for (const label of this.landmarkLabels) {
      hideLabel(label.element);
      // 艙內望出去要標示窗外城市，不讓起降機場的高權重標籤蓋住城市地名；
      // 需要時由 focused label 顯示一個清楚的最近地名。
      if (isInteriorView && label.feature.type === 'airport') {
        continue;
      }
      const distanceMeters = this.currentPoint ? haversineDistanceMeters(this.currentPoint, label.feature) : 0;
      const projected = label.position.clone().project(this.camera);
      if (
        projected.z <= -1 ||
        projected.z >= 1 ||
        projected.x < -1.12 ||
        projected.x > 1.12 ||
        projected.y < -1.12 ||
        projected.y > 1.12 ||
        // 艙內窗景已由相機投影與 WebGL 深度緩衝決定可見地表；再用球體射線
        // 做一次遮蔽判斷會把貼在窗內地表上的城市全部誤判成「地球背面」。
        (!isInteriorView && !isGroundPointVisibleFromCamera(this.camera.position, label.position))
      ) {
        continue;
      }

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
        // 窗外地名是艙內視角的主要導航資訊，不因距離淡出，避免城市光點在畫面移動時
        // 先消失、下一幀才重新出現。
        opacity: isInteriorView ? 1 : labelOpacityForDistance(distanceMeters, maxLabelDistance),
        scale: isInteriorView
          ? Math.max(0.92, labelScaleForFeature(label.feature, distanceMeters, this.currentPoint))
          : labelScaleForFeature(label.feature, distanceMeters, this.currentPoint)
      });
    }

    const visibleLabels = selectVisibleLabels(candidates, labelCountLimit(this.currentCameraMode));
    for (const candidate of visibleLabels) {
      candidate.label.element.classList.remove('is-hidden');
      candidate.label.element.style.opacity = candidate.opacity.toFixed(3);
      candidate.label.element.style.transform = `translate(${candidate.x}px, ${candidate.y}px) scale(${candidate.scale.toFixed(3)})`;
    }
    this.showFocusedAirportLabel(width, height);
  }

  private hideAllLabels(): void {
    for (const label of this.landmarkLabels) {
      hideLabel(label.element);
    }
    hideLabel(this.focusedAirportLabel);
  }

  private updateAirportMarkers(point: LocationPoint, nearGroundStrength: number, cameraMode: CameraMode): void {
    const altitudeMarkerScale = lerp(0.4, 0.28, altitudePerspectiveFactor(point));
    const nearScale = lerp(altitudeMarkerScale, 0.34, nearGroundStrength);
    const isFirstPerson = isFirstPersonCameraMode(cameraMode);
    const firstPersonVisibleMeters = firstPersonRouteLookAheadMeters(point) * 1.18;
    this.container.dataset.airportMarkerScale = nearScale.toFixed(3);
    for (const marker of this.airportMarkers.children) {
      if (!(marker instanceof THREE.Mesh)) {
        continue;
      }
      const baseScale = typeof marker.userData.baseScale === 'number' ? marker.userData.baseScale : 0.05;
      marker.scale.set(baseScale * nearScale, baseScale * nearScale, 1);
      let opacity = 1;
      if (isFirstPerson && marker.userData.kind === 'destination') {
        const destinationDistanceMeters = haversineDistanceMeters(point, this.segment.destination);
        opacity = 1 - smoothstep(firstPersonVisibleMeters, firstPersonVisibleMeters * 1.45, destinationDistanceMeters);
      }
      marker.visible = opacity > 0.04;
      if (marker.material instanceof THREE.MeshBasicMaterial) {
        marker.material.opacity = opacity;
      }
    }
  }

  private updateRouteAppearance(point: LocationPoint, cameraMode: CameraMode): void {
    const { flown, remaining } = this.routeTrack.userData.routeTrack;
    const isFirstPerson = isFirstPersonCameraMode(cameraMode);
    flown.visible = !isFirstPerson;
    remaining.visible = true;
    if (remaining.material instanceof THREE.MeshBasicMaterial) {
      remaining.material.opacity = isFirstPerson
        ? lerp(0.2, 0.44, altitudePerspectiveFactor(point))
        : 0.58;
    }
  }

  private setCockpitSceneVisibility(cameraMode: CameraMode): void {
    const isInterior = isFirstPersonCameraMode(cameraMode);
    this.renderer.domElement.classList.toggle('is-cockpit-render', isInterior);
    this.renderer.domElement.setAttribute('aria-label', isInterior ? '客艙窗外地表' : '地球地表');
    this.syncCabinEarthMaterial();
    this.container.dataset.cabinEarthMaterial = isInterior ? 'lit-satellite-detail' : 'lit-globe';
    this.earth.visible = true;
    // 雲層是遠景地球的裝飾；客艙窗要讓地表材質完整、連續地露出。
    this.clouds.visible = !isInterior;
    // 國界線是全球視角的輔助圖層；客艙窗只顯示地表材質與城市名稱，
    // 避免線段在地球邊緣或另一側形成紅圈中的「透視地球」假象。
    this.boundaries.visible = !isInterior;
    // 夜間全球貼圖是整張不透明底圖，近距離客艙視角會把紅圈地表整塊染暗；
    // 客艙改用獨立的城市光點標記，讓每一個可見地表面都露出原始材質。
    this.nightLights.visible = !isInterior;
    // 大氣層是遠景用的藍色邊緣光；近距離客艙視角若保留，會覆蓋真正地表。
    this.atmosphere.visible = !isInterior;
    // 機內窗外要看到真實地表材質；藍色 nightSurfaceWash 只適合遠景地球視角，
    // 在客艙視角會把綠色地表錯誤染成整片藍色。
    this.nightSurfaceWash.visible = !isInterior;
    // 客艙視角不能把包住整個場景的藍色 sky dome 當成窗外地面；
    // 同時移除夜間色彩乘色，讓窗外使用原始衛星地表貼圖的顏色。
    this.skyDome.visible = !isInterior;
    // 星點只屬於全球夜空。機內視角不應在白天的窗外出現黑夜星空，
    // 也不應讓星場和窗外地表重疊成黑色三角區。
    this.starField.visible = !isInterior;
    if (isInterior) {
      // updateDayNight() 已依航跡時間與位置設定正確日夜背景；這裡不能再
      // 覆寫成固定黑色，否則白天左右／駕駛艙視角會永遠像夜景。
      this.earth.material = this.cabinEarthMaterial;
    } else {
      this.earth.material = this.earthMaterial;
    }
    this.cityLights.visible = !isInterior && this.cityLightMaterial.opacity > 0.08;
    this.airportMarkers.visible = !isInterior;
    this.routeTrack.visible = !isInterior;
    this.updateInteriorTerrainClip(isInterior);
  }

  private updateInteriorTerrainClip(isInterior: boolean): void {
    if (!isInterior || !this.currentPoint) {
      this.camera.near = 0.1;
      this.camera.far = 100;
      this.camera.updateProjectionMatrix();
      return;
    }

    // 場景半徑為 2；相機高度換算到同一座標後，地平線弦長為
    // sqrt((R+h)^2 - R^2)。艙內不是把遠方地表霧化，而是直接不渲染
    // 超出客艙近景範圍的球面片段，讓窗外不會出現整片遠方大陸。
    const altitudeScene = Math.max(0, this.currentPoint.altitudeMeters ?? 0) / CAMERA_ALTITUDE_SCALE_METERS;
    const cameraRadius = 2 + altitudeScene + INTERIOR_EYE_OUTWARD_OFFSET;
    const horizonSceneDistance = Math.sqrt(Math.max(0, cameraRadius * cameraRadius - 4));
    // 不再用 0.2 的固定場景下限（那相當於約 637 公里）；
    // 只依當下高度的地平線比例裁切，避免高空仍看到遠方大陸。
    this.camera.near = 0.0001;
    this.camera.far = Math.max(0.018, horizonSceneDistance * 0.58);
    this.camera.updateProjectionMatrix();
  }

  private syncCabinEarthMaterial(): void {
    const earthMap = this.earthMaterial.map;
    if (this.cabinEarthMaterial.map !== earthMap) {
      // 貼圖是非同步載入；不能只在切換視角時複製一次，否則艙內會永久
      // 留在初始的暗色 fallback，而全球視角已經顯示出真實地表。
      this.cabinEarthMaterial.map = earthMap;
      this.cabinEarthMaterial.needsUpdate = true;
    }
    this.container.dataset.cabinEarthTexture = this.earthMaterial.userData.externalTextureLoaded === true
      ? 'loaded'
      : 'fallback';
    this.container.dataset.cabinEarthTextureFilename = this.earthMaterial.userData.earthTextureFilename ?? 'fallback-canvas';
    this.renderer.domElement.setAttribute(
      'aria-description',
      this.earthMaterial.userData.externalTextureLoaded === true
        ? `高解析衛星地表 ${this.earthMaterial.userData.earthTextureFilename ?? ''}`
        : '地表材質 fallback'
    );
  }

  private showFocusedAirportLabel(width: number, height: number): void {
    if (!this.currentPoint) {
      return;
    }
    const airportFocus = airportFocusForPoint(this.currentPoint, this.segment);
    let focusPoint = airportFocus.point;
    let focusStrength = airportFocus.strength;
    let focusText = focusPoint ? airportFocusLabel(focusPoint) : '';
    let isNearbyPlace = false;

    if (isFirstPersonCameraMode(this.currentCameraMode)) {
      const nearest = this.landmarkLabels
        .map((label) => ({
          feature: label.feature,
          distanceMeters: haversineDistanceMeters(this.currentPoint!, label.feature)
        }))
        .filter(({ feature, distanceMeters }) =>
          // 先選出最近城市，再由畫面投影決定位置；不能因為地名資料
          // 的稀疏度讓窗外完全沒有任何城市名稱。
          feature.type !== 'airport' && distanceMeters <= interiorLabelDistanceLimitMeters(this.currentPoint!)
        )
        .sort((a, b) => a.distanceMeters - b.distanceMeters)[0];
      if (nearest) {
        focusPoint = nearest.feature;
        focusStrength = Math.max(0.68, 1 - nearest.distanceMeters / interiorLabelDistanceLimitMeters(this.currentPoint));
        focusText = landmarkDisplayName(nearest.feature);
        isNearbyPlace = true;
      }
    }

    if (!focusPoint || focusStrength < 0.68) {
      return;
    }

    if (!isNearbyPlace) {
      for (const label of this.landmarkLabels) {
        if (
          label.feature.type === 'airport' &&
          haversineDistanceMeters(label.feature, focusPoint) < 1200
        ) {
          hideLabel(label.element);
        }
      }
    }

    const vector = geographicToVector3(focusPoint, 2.002, 900000);
    const projected = new THREE.Vector3(vector.x, vector.y, vector.z).project(this.camera);
    const isProjectedInside = projected.z > -1 && projected.z < 1 && projected.x >= -1.2 && projected.x <= 1.2 && projected.y >= -1.2 && projected.y <= 1.2;
    if (isFirstPersonCameraMode(this.currentCameraMode)) {
      const focusPosition = new THREE.Vector3(vector.x, vector.y, vector.z);
      if (
        (!isProjectedInside && !isNearbyPlace) ||
        (!isFirstPersonCameraMode(this.currentCameraMode) && !isGroundPointVisibleFromCamera(this.camera.position, focusPosition))
      ) {
        hideLabel(this.focusedAirportLabel);
        return;
      }
    }
    const x = isProjectedInside ? ((projected.x + 1) / 2) * width + 22 : width * 0.5 - 72;
    const y = isProjectedInside ? ((-projected.y + 1) / 2) * height - 18 : height * 0.62;
    this.focusedAirportLabel.classList.toggle('is-nearby-place', isNearbyPlace);
    this.focusedAirportLabel.textContent = focusText;
    this.focusedAirportLabel.classList.remove('is-hidden');
    this.focusedAirportLabel.style.opacity = '1';
    this.focusedAirportLabel.style.transform = `translate(${x}px, ${y}px) scale(${(1.16 + focusStrength * 0.2).toFixed(3)})`;
  }
}

function isInteractionLockedCamera(mode: CameraMode): boolean {
  return mode === 'pilotView' || mode === 'cockpit' || mode === 'leftWindow' || mode === 'rightWindow';
}

function createSkyDome(): THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial> {
  const geometry = new THREE.SphereGeometry(58, 48, 24);
  const material = new THREE.MeshBasicMaterial({
    color: 0x2a4d68,
    side: THREE.BackSide,
    depthWrite: false,
    fog: false
  });
  return new THREE.Mesh(geometry, material);
}

function createNightSurfaceWash(): THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial> {
  const material = new THREE.MeshBasicMaterial({
    color: 0x4f7f9a,
    transparent: true,
    opacity: 0.34,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(2.018, 96, 64), material);
  mesh.renderOrder = 1;
  return mesh;
}

function createAirportSurfaceMarkers(origin: PlaceReference, destination: PlaceReference): THREE.Group {
  const group = new THREE.Group();
  for (const [index, place] of [origin, destination].entries()) {
    const marker = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({
      map: createAirportMarkerTexture(index === 1),
      transparent: true,
      depthTest: true,
      depthWrite: false
    }));
    const vector = geographicToVector3(place, 2.006, 900000);
    marker.position.set(vector.x, vector.y, vector.z);
    orientSurfacePlane(marker);
    marker.userData.kind = index === 1 ? 'destination' : 'origin';
    marker.userData.baseScale = index === 1 ? 0.082 : 0.068;
    marker.scale.set(marker.userData.baseScale, marker.userData.baseScale, 1);
    marker.renderOrder = 8;
    group.add(marker);
  }
  return group;
}

function createAirportMarkerTexture(isDestination: boolean): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext('2d');
  if (!context) {
    return new THREE.CanvasTexture(canvas);
  }

  context.clearRect(0, 0, canvas.width, canvas.height);
  const glow = context.createRadialGradient(64, 64, 3, 64, 64, 42);
  glow.addColorStop(0, isDestination ? 'rgba(255, 205, 105, 0.58)' : 'rgba(144, 235, 255, 0.46)');
  glow.addColorStop(0.48, isDestination ? 'rgba(255, 157, 58, 0.16)' : 'rgba(86, 190, 255, 0.12)');
  glow.addColorStop(1, 'rgba(255,255,255,0)');
  context.fillStyle = glow;
  context.fillRect(0, 0, canvas.width, canvas.height);

  context.save();
  context.translate(64, 64);
  context.rotate(-0.64);
  context.strokeStyle = isDestination ? 'rgba(255, 245, 205, 0.95)' : 'rgba(214, 249, 255, 0.9)';
  context.lineWidth = 4;
  context.lineCap = 'round';
  context.beginPath();
  context.moveTo(-30, 0);
  context.lineTo(30, 0);
  context.stroke();
  context.setLineDash([7, 7]);
  context.lineWidth = 2;
  context.strokeStyle = 'rgba(10, 22, 30, 0.62)';
  context.beginPath();
  context.moveTo(-23, 0);
  context.lineTo(23, 0);
  context.stroke();
  context.restore();

  context.strokeStyle = isDestination ? 'rgba(255, 224, 142, 0.9)' : 'rgba(144, 235, 255, 0.72)';
  context.lineWidth = 2.4;
  context.beginPath();
  context.arc(64, 64, 29, 0, Math.PI * 2);
  context.stroke();

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

function hideLabel(element: HTMLSpanElement): void {
  element.classList.add('is-hidden');
  element.style.opacity = '0';
  element.style.transform = 'translate(-9999px, -9999px)';
}

function createDomLandmarkLabels(layer: HTMLDivElement, features: GeographicFeature[]): GlobeDomLabel[] {
  const labels: GlobeDomLabel[] = [];
  for (const feature of mergeSceneFeatures(features)) {
    if (!shouldRenderGlobeLabel(feature)) {
      continue;
    }

    const element = document.createElement('span');
    element.className = `globe-place-label ${labelClassForFeature(feature)} is-hidden`;
    element.textContent = landmarkDisplayName(feature);
    layer.appendChild(element);

    // 標籤錨點直接放在地球表面，只留極小偏移避免 z-fighting；
    // 不再用 2.03 的大浮高，讓城市名稱像貼紙一樣跟著地表移動。
    const vector = geographicToVector3(feature, 2.002, 900000);
    labels.push({
      element,
      feature,
      position: new THREE.Vector3(vector.x, vector.y, vector.z)
    });
  }
  return labels;
}

function createAirportFeatures(origin: PlaceReference, destination: PlaceReference): GeographicFeature[] {
  return [origin, destination].map((place, index) => ({
    id: `airport-${place.iataCode ?? place.name}-${index}`,
    name: `${place.iataCode ?? place.name} ${place.name}`,
    nameZh: place.iataCode ? `${place.iataCode} ${place.name}` : undefined,
    type: 'airport',
    minZoomRank: 0,
    importance: 1.25,
    latitude: place.latitude,
    longitude: place.longitude,
    countryCode: place.countryCode,
    tourismHint: index === 0 ? '起飛機場' : '降落機場'
  }));
}

function airportFocusLabel(place: PlaceReference): string {
  const shortName = place.name
    .replace(/\s+International\s+Airport$/i, '')
    .replace(/\s+Airport$/i, '');
  return place.iataCode ? `${place.iataCode} ${shortName}` : shortName;
}

function mergeSceneFeatures(features: GeographicFeature[]): GeographicFeature[] {
  const seen = new Set<string>();
  return features.filter((feature) => {
    const key = `${feature.type}:${feature.id}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function labelClassForFeature(feature: GeographicFeature): string {
  if (feature.type === 'airport') {
    return 'is-airport';
  }
  return feature.type === 'majorCity' ? 'is-city' : 'is-landmark';
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
  const typeBoost = candidate.label.feature.type === 'airport' ? 1.55 : candidate.label.feature.type === 'landmark' ? 1.15 : 1;
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
    case 'leftWindow':
    case 'rightWindow':
      return Math.min(360000, Math.max(18000, firstPersonRouteLookAheadMeters(point) * 0.86));
    case 'global':
    case 'orbit':
      return Math.min(1100000, Math.max(500000, horizonMeters + 320000));
    default:
      return dynamicLimit;
  }
}

function interiorLabelDistanceLimitMeters(point: LocationPoint): number {
  const altitudeMeters = Math.max(0, point.altitudeMeters ?? 0);
  // 地平線距離 d = sqrt(2Rh + h²)。機上視角不應等到城市已經貼近飛機
  // 才顯示；取地平線約一半作為「可辨識地名半徑」，讓遠方城市提前出現，
  // 同時仍不會把整個地平線外的大陸地名全部帶入窗內。
  // 不設固定最小／最大公里數：起飛低空幾乎只能看近處，高度上升才自然看得更遠。
  const horizonMeters = Math.sqrt(2 * EARTH_RADIUS_METERS * altitudeMeters + altitudeMeters * altitudeMeters);
  return horizonMeters * 0.5;
}

function labelScaleForFeature(feature: GeographicFeature, distanceMeters: number, point?: LocationPoint): number {
  if (feature.type !== 'airport') {
    return 1;
  }
  const altitudeMeters = Math.max(0, point?.altitudeMeters ?? 0);
  const distanceScale = 1 - Math.min(0.46, distanceMeters / 180000);
  const altitudeScale = point ? sceneObjectScaleForAltitude(point) : 1 - Math.min(0.34, altitudeMeters / 14000);
  return Math.max(0.52, Math.min(1.65, 1.22 * distanceScale * altitudeScale));
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
    case 'leftWindow':
    case 'rightWindow':
      return 16;
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

export function visibleRouteWindowForCameraMode(
  fullRoute: LocationPoint[],
  current: LocationPoint,
  cameraMode: CameraMode
): LocationPoint[] {
  if (!isFirstPersonCameraMode(cameraMode)) {
    return fullRoute;
  }
  return routeWindowAhead(fullRoute, current, firstPersonRouteLookAheadMeters(current));
}

function routeWindowAhead(fullRoute: LocationPoint[], current: LocationPoint, maxDistanceMeters: number): LocationPoint[] {
  const currentMs = Date.parse(current.timestamp);
  const futurePoints = fullRoute.filter((point) => Date.parse(point.timestamp) > currentMs);
  const window: LocationPoint[] = [current];
  let previous = current;
  let distanceMeters = 0;

  for (const point of futurePoints) {
    const segmentDistanceMeters = haversineDistanceMeters(previous, point);
    if (distanceMeters + segmentDistanceMeters > maxDistanceMeters) {
      const remainingMeters = Math.max(0, maxDistanceMeters - distanceMeters);
      if (segmentDistanceMeters > 1 && remainingMeters > 200) {
        window.push(interpolateLocationPoint(previous, point, remainingMeters / segmentDistanceMeters));
      }
      break;
    }
    window.push(point);
    distanceMeters += segmentDistanceMeters;
    previous = point;
  }

  return window;
}

function interpolateLocationPoint(a: LocationPoint, b: LocationPoint, fraction: number): LocationPoint {
  const point = interpolateGreatCircle(a, b, fraction);
  const startMs = Date.parse(a.timestamp);
  const endMs = Date.parse(b.timestamp);
  const timestamp = Number.isFinite(startMs) && Number.isFinite(endMs)
    ? new Date(startMs + (endMs - startMs) * fraction).toISOString()
    : a.timestamp;
  return {
    ...a,
    id: `${a.id}-${b.id}-visible-cutoff`,
    timestamp,
    latitude: point.latitude,
    longitude: point.longitude,
    altitudeMeters: point.altitudeMeters,
    speedMetersPerSecond: lerp(a.speedMetersPerSecond ?? 0, b.speedMetersPerSecond ?? 0, fraction),
    courseDegrees: b.courseDegrees ?? a.courseDegrees
  };
}

function isFirstPersonCameraMode(cameraMode: CameraMode): boolean {
  return cameraMode === 'pilotView' || cameraMode === 'cockpit' || cameraMode === 'leftWindow' || cameraMode === 'rightWindow';
}

function isInteriorCameraMode(cameraMode: CameraMode): boolean {
  return cameraMode === 'cockpit' || cameraMode === 'leftWindow' || cameraMode === 'rightWindow';
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

function createRouteCityLights(features: GeographicFeature[]): { mesh: THREE.InstancedMesh; material: THREE.MeshBasicMaterial } {
  const points: Array<{ position: THREE.Vector3; size: number; color: THREE.Color }> = [];
  const lightFeatures = features
    .filter((feature) => feature.type === 'majorCity' && feature.importance >= 0.76)
    .sort((a, b) => (b.population ?? 0) - (a.population ?? 0))
    .slice(0, 96);

  for (const feature of lightFeatures) {
    const population = Math.max(12_000, feature.population ?? 120_000);
    const count = Math.min(26, Math.max(6, Math.round(Math.log10(population) * 3.15)));
    const spreadMeters = Math.min(22000, Math.max(4200, Math.sqrt(population) * 11));
    const random = createSeededRandom(hashString(feature.id));
    for (let index = 0; index < count; index += 1) {
      const angle = random() * Math.PI * 2;
      const radius = spreadMeters * Math.sqrt(random());
      const latitudeOffset = Math.cos(angle) * radius / 111320;
      const longitudeOffset = Math.sin(angle) * radius / Math.max(28000, 111320 * Math.cos(THREE.MathUtils.degToRad(feature.latitude)));
      const vector = geographicToVector3({
        ...feature,
        latitude: feature.latitude + latitudeOffset,
        longitude: feature.longitude + longitudeOffset
      }, 2.004, 900000);
      const amber = 0.42 + random() * 0.18;
      const brightness = 0.78 + random() * 0.34;
      const size = 0.008 + random() * 0.008;
      const color = new THREE.Color(brightness, brightness * amber, brightness * (0.025 + random() * 0.035));
      points.push({ position: new THREE.Vector3(vector.x, vector.y, vector.z), size, color });
    }
  }

  const geometry = new THREE.CircleGeometry(1, 18);
  const material = new THREE.MeshBasicMaterial({
    map: createCityLightSpriteTexture(),
    transparent: true,
    opacity: 0,
    blending: THREE.AdditiveBlending,
    depthTest: true,
    depthWrite: false,
    alphaTest: 0.04,
    side: THREE.DoubleSide
  });
  const mesh = new THREE.InstancedMesh(geometry, material, Math.max(1, points.length));
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  for (const [index, point] of points.entries()) {
    const matrix = surfacePlaneMatrix(point.position, point.size);
    mesh.setMatrixAt(index, matrix);
    mesh.setColorAt(index, point.color);
  }
  mesh.count = points.length;
  mesh.renderOrder = 3;
  mesh.userData.surfaceLocked = true;

  return {
    mesh,
    material
  };
}

function orientSurfacePlane(mesh: THREE.Mesh): void {
  const normal = mesh.position.clone().normalize();
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
}

function surfacePlaneMatrix(position: THREE.Vector3, size: number): THREE.Matrix4 {
  const matrix = new THREE.Matrix4();
  const normal = position.clone().normalize();
  const quaternion = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
  matrix.compose(position, quaternion, new THREE.Vector3(size, size, 1));
  return matrix;
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
  glow.addColorStop(0, 'rgba(255, 187, 74, 0.96)');
  glow.addColorStop(0.2, 'rgba(255, 132, 35, 0.68)');
  glow.addColorStop(0.5, 'rgba(255, 92, 18, 0.18)');
  glow.addColorStop(1, 'rgba(255, 130, 32, 0)');
  context.fillStyle = glow;
  context.fillRect(0, 0, canvas.width, canvas.height);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

function airportFocusForPoint(point: LocationPoint, segment: JourneySegment): { point?: PlaceReference; strength: number } {
  const originStrength = airportProximityStrength(point, segment.origin);
  const destinationStrength = airportProximityStrength(point, segment.destination);
  return destinationStrength >= originStrength
    ? { point: segment.destination, strength: destinationStrength }
    : { point: segment.origin, strength: originStrength };
}

function airportProximityStrength(point: LocationPoint, airport: PlaceReference): number {
  const distanceMeters = haversineDistanceMeters(point, airport);
  const altitudeMeters = Math.max(0, point.altitudeMeters ?? 0);
  const distanceStrength = 1 - smoothstep(9000, 95000, distanceMeters);
  const altitudeStrength = 1 - smoothstep(1200, 9800, altitudeMeters);
  return THREE.MathUtils.clamp(distanceStrength * altitudeStrength, 0, 1);
}

function nearGroundAirportStrength(point: LocationPoint, airportFocusStrength: number): number {
  const altitudeMeters = Math.max(0, point.altitudeMeters ?? 0);
  const altitudeStrength = 1 - smoothstep(260, 6200, altitudeMeters);
  return THREE.MathUtils.clamp(airportFocusStrength * altitudeStrength, 0, 1);
}

function createSeededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (1664525 * state + 1013904223) >>> 0;
    return state / 0xffffffff;
  };
}

function hashString(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function nightFactorAt(point: LocationPoint, sunVector: THREE.Vector3): number {
  const vector = geographicToVector3(point, 1, 0);
  const surface = new THREE.Vector3(vector.x, vector.y, vector.z).normalize();
  const sunScore = surface.dot(sunVector);
  return 1 - smoothstep(-0.1, 0.18, sunScore);
}

function localSolarDay(point: LocationPoint): { factor: number; hour: number } {
  const date = new Date(point.timestamp);
  if (Number.isNaN(date.getTime())) {
    return { factor: 0, hour: 0 };
  }
  const utcHour =
    date.getUTCHours() +
    date.getUTCMinutes() / 60 +
    date.getUTCSeconds() / 3600;
  const localSolarHour = positiveModulo(utcHour + point.longitude / 15, 24);
  return {
    factor: smoothstep(5.5, 7.5, localSolarHour) * (1 - smoothstep(18.25, 20.25, localSolarHour)),
    hour: localSolarHour
  };
}

function sunVectorAt(timestamp: string): THREE.Vector3 {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return new THREE.Vector3(-3, 4, 7).normalize();
  }
  const startOfYear = Date.UTC(date.getUTCFullYear(), 0, 0);
  const dayOfYear = Math.floor((date.getTime() - startOfYear) / 86400000);
  const utcHour =
    date.getUTCHours() +
    date.getUTCMinutes() / 60 +
    date.getUTCSeconds() / 3600;
  const declination = 23.44 * Math.sin(THREE.MathUtils.degToRad((360 / 365) * (dayOfYear - 81)));
  const subsolarLongitude = normalizeLongitude((12 - utcHour) * 15);
  const vector = geographicToVector3({ latitude: declination, longitude: subsolarLongitude }, 1, 0);
  return new THREE.Vector3(vector.x, vector.y, vector.z).normalize();
}

function normalizeLongitude(longitude: number): number {
  return positiveModulo(longitude + 180, 360) - 180;
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
