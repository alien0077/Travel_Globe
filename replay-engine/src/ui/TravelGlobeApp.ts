import type { CameraMode } from '../camera/CameraController';
import {
  flightPlanPayloadFromJourney,
  exportBlob,
  parseNativePayload,
  postNativeMessage,
  type NativeExportDelivery,
  type NativeFlightPlanPayload,
  type NativeNotificationSchedulePayload,
  type NativeRecordingPayload,
  type NativeVisitPointPayload,
  type NativeVisitPointsPayload
} from '../bridge/nativeBridge';
import { BrowserRuntimeAdapter } from '../bridge/RuntimeAdapter';
import type { SavedJourneySummary } from '../bridge/RuntimeAdapter';
import type { Journey, JourneySegment, TimelineEvent } from '../data/types';
import { getPrimaryFlightSegment } from '../data/types';
import { createGpx, createKml } from '../export/geoExport';
import {
  buildFlightHudMetrics,
  buildFlightOverlay,
  calculateRouteDeviationMeters,
  getActualRouteThrough,
  landmarksForSegment,
  summarizeBelowMe,
  type FlightOverlay
} from '../flight/flightAnalytics';
import { AviationstackFlightPreloadProvider, readAviationstackApiKey, writeAviationstackApiKey } from '../flight-preload/aviationstackProvider';
import type { PreloadFlightRequest } from '../flight-preload/buildPreloadedFlightJourney';
import {
  findAirportByIata,
  findAirportContextByIata,
  getAirportIndexSummary,
  listAirportSuggestions,
  type AirportRecord
} from '../flight-preload/airportIndex';
import { findScheduleByFlightNumber } from '../flight-preload/flightScheduleIndex';
import { landmarkDisplayName, windowDirectionLabel, type GeographicFeature } from '../geo/landmarks';
import { formatDistance } from '../geo/geodesy';
import { TravelGlobeScene } from '../globe/TravelGlobeScene';
import { readJourneyFile } from '../import/readJourneyFile';
import { generateOfflineJournal } from '../journal/generateJournal';
import {
  LiveGpsTracker,
  liveGpsPointFromNativeMessage,
  type LiveGpsStatus
} from '../live/liveGps';
import { completeJourneyFromRecording } from '../live/completeJourneyFromRecording';
import { DEFAULT_AIRCRAFT_TYPE } from '../models/aircraftModelLibrary';
import { evaluateNotifications } from '../notifications/notificationRules';
import {
  coreOfflinePacks,
  deletePack,
  describeInstalledPacks,
  formatBytes,
  getInstalledSizeBytes,
  installPack,
  isPackInstalled,
  loadOfflinePackState,
  saveOfflinePackState,
  type OfflinePackState
} from '../offline/offlinePacks';
import { reduceAutoRecordingState, type AutoRecordingContext } from '../recording/autoRecorder';
import { ReplayClock } from '../replay/ReplayClock';
import { getRouteTimeBounds, sampleReplayAt, type ReplaySample } from '../replay/buildReplayFrames';
import { summarizeJourney } from '../statistics/journeyStatistics';
import { buildTimeMachineState } from '../time-machine/timeMachine';
import {
  buildTravelRecords,
  getRegionLabel,
  getTravelRegionOptions,
  summarizeTravelRecords,
  writeTravelRecordEdit,
  type TravelRecord,
  type TravelRegion
} from '../travel-records/travelRecords';
import type { TravelNotification } from '../notifications/notificationRules';
import { buildPlanSummary } from '../travel-plan/planEngine';

export class TravelGlobeApp {
  private readonly root: HTMLElement;
  private readonly adapter: BrowserRuntimeAdapter;
  private readonly flightPreloadProvider = new AviationstackFlightPreloadProvider();
  private journey?: Journey;
  private scene?: TravelGlobeScene;
  private clock?: ReplayClock;
  private segment?: JourneySegment;
  private flightOverlay?: FlightOverlay;
  private routeLandmarks: GeographicFeature[] = [];
  private cameraMode: CameraMode = 'flightPreview';
  private lastFrameMs?: number;
  private packState: OfflinePackState = loadOfflinePackState();
  private autoRecordingContext?: AutoRecordingContext;
  private travelRecords: TravelRecord[] = [];
  private activeRecordId?: string;
  private activeRegion: TravelRegion | 'all' = 'all';
  private liveGps = new LiveGpsTracker();
  private isLiveGpsMode = false;
  private savedJourneys: SavedJourneySummary[] = [];
  private recordEditUndoStack: Journey[] = [];
  private scheduledNotificationIds = new Set<string>();

  private readonly viewport = document.createElement('section');
  private readonly playButton = document.createElement('button');
  private readonly speedSelect = document.createElement('select');
  private readonly scrubber = document.createElement('input');
  private readonly hudTitle = document.createElement('div');
  private readonly hudRoute = document.createElement('div');
  private readonly hudStats = document.createElement('div');
  private readonly hudPoint = document.createElement('div');
  private readonly geoNotice = document.createElement('div');
  private readonly belowMe = document.createElement('div');
  private readonly capability = document.createElement('div');
  private readonly timelineList = document.createElement('div');
  private readonly recordFilterBar = document.createElement('div');
  private readonly recordPreview = document.createElement('article');
  private readonly viewRail = document.createElement('nav');
  private readonly pilotHud = document.createElement('div');
  private readonly productPanel = document.createElement('section');
  private readonly preloadPanel = document.createElement('section');
  private readonly aviationstackApiKeyInput = document.createElement('input');
  private readonly flightNumberInput = document.createElement('input');
  private readonly originInput = document.createElement('input');
  private readonly destinationInput = document.createElement('input');
  private readonly departureDateInput = document.createElement('input');
  private readonly departureTimeInput = document.createElement('input');
  private readonly durationInput = document.createElement('input');
  private readonly aircraftTypeSelect = document.createElement('select');
  private readonly preloadStatus = document.createElement('div');
  private readonly fileInput = document.createElement('input');
  private readonly mediaInput = document.createElement('input');

  constructor(root: HTMLElement, journey: Journey) {
    this.root = root;
    this.adapter = new BrowserRuntimeAdapter(journey);
    window.addEventListener('travelglobe:native', this.handleNativeEvent);
  }

  async start(): Promise<void> {
    const journey = await this.adapter.loadJourney();
    await this.loadJourney(journey);
  }

  private async loadJourney(journey: Journey): Promise<void> {
    this.journey = journey;
    this.segment = getPrimaryFlightSegment(journey);
    this.flightOverlay = buildFlightOverlay(journey, this.segment);
    this.routeLandmarks = landmarksForSegment(this.segment);
    this.travelRecords = buildTravelRecords(journey);
    this.activeRecordId = this.travelRecords[0]?.id;
    this.liveGps = new LiveGpsTracker();
    this.isLiveGpsMode = false;
    const bounds = getRouteTimeBounds(this.segment);
    this.clock = new ReplayClock(bounds.durationSeconds);
    this.lastFrameMs = undefined;
    await this.adapter.saveJourney(journey);
    this.savedJourneys = await this.adapter.listSavedJourneys();

    this.renderShell(journey, this.segment);
    this.scene?.dispose();
    this.scene = new TravelGlobeScene(
      this.viewport,
      this.segment,
      this.flightOverlay,
      this.routeLandmarks
    );
    this.scene.start((timeMs) => this.frame(timeMs));
  }

  private renderShell(journey: Journey, segment: JourneySegment): void {
    const isCompactViewport = window.matchMedia('(max-width: 720px)').matches;
    this.root.className = isCompactViewport ? 'app-shell flight-system-shell is-compact' : 'app-shell flight-system-shell';
    this.viewport.className = 'globe-viewport';

    const overlay = document.createElement('section');
    overlay.className = 'overlay';

    const hud = document.createElement('section');
    hud.className = 'hud';
    this.hudTitle.className = 'hud-title';
    this.hudRoute.className = 'hud-route';
    this.hudStats.className = 'hud-stats';
    this.hudPoint.className = 'hud-point';
    this.geoNotice.className = 'geo-notice';
    this.belowMe.className = 'below-me';
    this.capability.className = 'capability';
    hud.append(this.hudTitle, this.hudRoute, this.hudPoint, this.geoNotice);

    this.viewRail.className = 'view-rail';
    this.viewRail.setAttribute('aria-label', '飛行視角');
    const cameraOptions: Array<{ mode: CameraMode; icon: string; label: string }> = [
      { mode: 'flightPreview', icon: '追', label: '追機視角' },
      { mode: 'totalRoute', icon: '全', label: '完整航線' },
      { mode: 'midFlight', icon: '中', label: '中段飛行' },
      { mode: 'overhead', icon: '俯', label: '俯視航線' },
      { mode: 'commandCenter', icon: '塔', label: '塔台視角' },
      { mode: 'pilotView', icon: '駕', label: '飛行員視角' }
    ];
    this.viewRail.replaceChildren(
      ...cameraOptions.map(({ mode, icon, label }) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `view-mode-button${mode === this.cameraMode ? ' is-active' : ''}`;
        button.dataset.mode = mode;
        button.title = label;
        button.setAttribute('aria-label', label);
        button.textContent = icon;
        const activateViewMode = (event?: Event): void => {
          event?.preventDefault();
          event?.stopPropagation();
          this.cameraMode = mode;
          this.scene?.prepareForTimelineJump();
          this.syncViewRail();
        };
        button.addEventListener('pointerdown', (event) => {
          event.stopPropagation();
        });
        button.addEventListener('pointerup', activateViewMode);
        button.addEventListener('touchend', activateViewMode, { passive: false });
        button.addEventListener('click', activateViewMode);
        return button;
      })
    );

    const dock = document.createElement('section');
    dock.className = 'info-dock';
    this.pilotHud.className = 'pilot-hud';
    this.pilotHud.setAttribute('aria-hidden', 'true');

    const timeline = document.createElement('details');
    timeline.className = 'dock-panel timeline-panel';
    timeline.open = false;
    const timelineTitle = document.createElement('summary');
    timelineTitle.className = 'panel-summary panel-title';
    timelineTitle.textContent = '旅遊紀錄';
    bindDetailsSummaryToggle(timelineTitle, timeline);
    this.recordFilterBar.className = 'record-filters';
    this.timelineList.className = 'timeline-list';
    this.recordPreview.className = 'record-preview';
    timeline.append(timelineTitle, this.recordFilterBar, this.timelineList, this.recordPreview);
    keepDetailsOpenDuringContentGestures(this.recordFilterBar, this.timelineList, this.recordPreview);

    this.productPanel.className = 'product-panel';
    const productShell = document.createElement('details');
    productShell.className = 'dock-panel product-panel-shell';
    productShell.open = false;
    const productSummary = document.createElement('summary');
    productSummary.className = 'panel-summary panel-title';
    productSummary.textContent = 'Travel Atlas';
    bindDetailsSummaryToggle(productSummary, productShell);
    productShell.append(productSummary, this.productPanel);
    keepDetailsOpenDuringContentGestures(this.productPanel);

    this.preloadPanel.className = 'preload-panel';
    const preloadShell = document.createElement('details');
    preloadShell.className = 'dock-panel preload-panel-shell';
    preloadShell.open = false;
    const preloadSummary = document.createElement('summary');
    preloadSummary.className = 'panel-summary panel-title';
    preloadSummary.textContent = '航班預載';
    bindDetailsSummaryToggle(preloadSummary, preloadShell, () => {
      dock.classList.toggle('has-open-preload', preloadShell.open);
    });
    preloadShell.append(preloadSummary, this.preloadPanel);
    preloadShell.addEventListener('toggle', () => {
      dock.classList.toggle('has-open-preload', preloadShell.open);
    });

    const controls = document.createElement('section');
    controls.className = 'controls';

    this.playButton.type = 'button';
    this.playButton.className = 'control-button';
    this.playButton.addEventListener('click', () => {
      this.clock?.togglePlayback();
      this.syncPlayButton();
    });

    this.speedSelect.className = 'control-select';
    for (const speed of [1, 5, 20, 100]) {
      const option = document.createElement('option');
      option.value = String(speed);
      option.textContent = `${speed}x`;
      this.speedSelect.appendChild(option);
    }
    this.speedSelect.value = '5';
    this.speedSelect.addEventListener('change', () => {
      this.clock?.setSpeed(Number(this.speedSelect.value));
    });

    this.scrubber.className = 'timeline-scrubber';
    this.scrubber.type = 'range';
    this.scrubber.min = '0';
    this.scrubber.max = '1000';
    this.scrubber.value = '0';
    this.scrubber.addEventListener('input', () => {
      this.scene?.prepareForTimelineJump();
      this.clock?.seekPercent(Number(this.scrubber.value) / 1000);
    });

    const importButton = document.createElement('button');
    importButton.type = 'button';
    importButton.className = 'control-button secondary-action';
    importButton.textContent = 'Import';
    bindTouchAction(importButton, () => this.fileInput.click());

    const exportButton = document.createElement('button');
    exportButton.type = 'button';
    exportButton.className = 'control-button secondary-action';
    exportButton.textContent = 'Export';
    bindTouchAction(exportButton, () => this.exportTravelGlobe());

    const shareButton = document.createElement('button');
    shareButton.type = 'button';
    shareButton.className = 'control-button secondary-action';
    shareButton.textContent = 'Share';
    bindTouchAction(shareButton, () => this.exportShareSafeJson());

    const manualLink = document.createElement('a');
    manualLink.className = 'control-button control-link secondary-action';
    manualLink.href = './readme.html';
    manualLink.textContent = '使用手冊';
    bindTouchAction(manualLink, () => {
      window.location.href = manualLink.href;
    });

    const gpxButton = document.createElement('button');
    gpxButton.type = 'button';
    gpxButton.className = 'control-button secondary-action';
    gpxButton.textContent = 'GPX';
    bindTouchAction(gpxButton, () => this.exportGpx());

    const kmlButton = document.createElement('button');
    kmlButton.type = 'button';
    kmlButton.className = 'control-button secondary-action';
    kmlButton.textContent = 'KML';
    bindTouchAction(kmlButton, () => this.exportKml());

    const journalButton = document.createElement('button');
    journalButton.type = 'button';
    journalButton.className = 'control-button secondary-action';
    journalButton.textContent = 'Journal';
    bindTouchAction(journalButton, () => this.exportJournalMarkdown());

    const packButton = document.createElement('button');
    packButton.type = 'button';
    packButton.className = 'control-button secondary-action';
    packButton.textContent = 'Pack';
    bindTouchAction(packButton, () => {
      this.installOfflinePack(coreOfflinePacks[0].id);
      this.renderProductPanel();
    });

    this.fileInput.type = 'file';
    this.fileInput.accept = '.json,.travelglobe,application/json,application/zip';
    this.fileInput.hidden = true;
    this.fileInput.addEventListener('change', () => {
      const file = this.fileInput.files?.[0];
      if (!file) {
        return;
      }
      void this.importJourney(file);
    });

    this.mediaInput.type = 'file';
    this.mediaInput.accept = 'image/*';
    this.mediaInput.hidden = true;
    this.mediaInput.addEventListener('change', () => {
      const file = this.mediaInput.files?.[0];
      if (!file) {
        return;
      }
      void this.attachMediaToActiveRecord(file);
    });

    const actionGrid = document.createElement('div');
    actionGrid.className = 'action-grid';
    actionGrid.append(importButton, exportButton, shareButton, manualLink, gpxButton, kmlButton, journalButton, packButton);

    const systemDrawer = document.createElement('section');
    systemDrawer.className = 'dock-panel system-drawer';
    const systemSummary = document.createElement('button');
    systemSummary.type = 'button';
    systemSummary.className = 'panel-summary panel-title';
    systemSummary.textContent = '更多';
    systemSummary.setAttribute('aria-expanded', 'false');
    const drawerBody = document.createElement('div');
    drawerBody.className = 'drawer-body';
    drawerBody.hidden = true;
    let lastSystemDrawerToggleMs = 0;
    const setSystemDrawerOpen = (isOpen: boolean): void => {
      systemDrawer.classList.toggle('is-open', isOpen);
      systemSummary.setAttribute('aria-expanded', String(isOpen));
      drawerBody.hidden = !isOpen;
    };
    const toggleSystemDrawer = (event?: Event): void => {
      event?.preventDefault();
      event?.stopPropagation();
      const now = performance.now();
      if (now - lastSystemDrawerToggleMs < 280) {
        return;
      }
      lastSystemDrawerToggleMs = now;
      setSystemDrawerOpen(!systemDrawer.classList.contains('is-open'));
    };
    systemSummary.addEventListener('pointerdown', (event) => event.stopPropagation());
    systemSummary.addEventListener('pointerup', toggleSystemDrawer);
    systemSummary.addEventListener('touchend', toggleSystemDrawer, { passive: false });
    systemSummary.addEventListener('click', toggleSystemDrawer);
    drawerBody.append(actionGrid, this.capability, this.belowMe, preloadShell, productShell, timeline);
    systemDrawer.append(systemSummary, drawerBody);

    controls.append(this.playButton, this.speedSelect, this.scrubber, this.hudStats);
    dock.append(systemDrawer);
    overlay.append(hud, this.viewRail, dock, this.pilotHud, controls);
    this.root.replaceChildren(this.viewport, overlay, this.fileInput, this.mediaInput);

    this.hudTitle.textContent = 'FLIGHT REPLAY';
    this.hudRoute.textContent = `${journey.title} | ${segment.origin.iataCode ?? segment.origin.name} to ${segment.destination.iataCode ?? segment.destination.name}`;
    this.capability.textContent = this.adapter.getLocationCapability().reason ?? 'Standalone browser replay';
    this.renderRegionFilters();
    this.renderTimeline();
    this.renderRecordPreview();
    this.renderPreloadPanel(segment);
    this.renderProductPanel();
    this.syncViewRail();
    this.syncPlayButton();
  }

  private frame(timeMs: number): void {
    if (!this.clock || !this.scene || !this.segment) {
      return;
    }

    const previous = this.lastFrameMs ?? timeMs;
    const deltaSeconds = Math.min(0.08, (timeMs - previous) / 1000);
    this.lastFrameMs = timeMs;

    const liveSample = this.isLiveGpsMode ? this.liveGps.sample(timeMs, this.segment) : undefined;
    if (liveSample) {
      this.scene.update(liveSample.point, liveSample.bearingDegrees, this.cameraMode, liveSample.routePoints);
      this.scrubber.value = String(
        Math.round(Math.min(1, liveSample.distanceFlownMeters / Math.max(1, this.flightOverlay?.totalDistanceMeters ?? 1)) * 1000)
      );
      this.syncPlayButton();
      this.updateHud(liveSample, liveSample.elapsedSeconds, liveSample.status);
      return;
    }

    this.clock.update(deltaSeconds);
    const sample = sampleReplayAt(this.segment, this.clock.currentSeconds);
    const actualRoute = getActualRouteThrough(this.segment, this.clock.currentSeconds);
    this.scene.update(sample.point, sample.bearingDegrees, this.cameraMode, actualRoute);

    this.scrubber.value = String(Math.round(this.clock.progressPercent * 1000));
    this.syncPlayButton();
    this.updateHud(sample, this.clock.currentSeconds);
  }

  private updateHud(
    sample: ReplaySample,
    elapsedSeconds: number,
    liveStatus?: LiveGpsStatus
  ): void {
    const point = sample.point;
    if (!this.journey || !this.segment || !this.flightOverlay) {
      return;
    }
    const metrics = buildFlightHudMetrics(this.journey, this.segment, sample, elapsedSeconds);
    const elapsedMinutes = Math.floor(elapsedSeconds / 60);
    const elapsedRemainder = Math.floor(elapsedSeconds % 60).toString().padStart(2, '0');
    const deviationMeters = calculateRouteDeviationMeters(sample, this.flightOverlay.plannedRoute);

    this.hudTitle.textContent = metrics.flightNumber;
    this.hudRoute.textContent = `${metrics.flightNumber} | ${metrics.routeLabel}`;
    this.hudStats.replaceChildren(
      metricItem('剩餘距離', metrics.remainingDistanceLabel),
      metricItem('預計抵達', metrics.etaLabel),
      metricItem('飛行高度', metrics.altitudeFeet),
      metricItem('對氣速度', metrics.speedKmh)
    );

    this.hudPoint.textContent = [
      liveStatus ? liveGpsStatusLabel(liveStatus) : undefined,
      localizePhase(metrics.phaseLabel),
      metrics.verticalSpeedLabel,
      `航向 ${metrics.headingDegrees}`,
      `T+${elapsedMinutes}:${elapsedRemainder}`,
      `偏離 ${formatDistance(deviationMeters)}`
    ].filter(Boolean).join(' | ');
    this.renderPilotHud(metrics);

    this.renderBelowMe(sample);
    if (liveStatus === 'lost') {
      this.geoNotice.textContent = 'Live GPS：GPS signal lost，已停止外推並停在最後可信位置';
    } else if (liveStatus === 'estimated') {
      this.geoNotice.textContent = 'Live GPS：短暫斷訊，畫面以速度與航向暫時推算';
    } else if (liveStatus === 'live') {
      this.geoNotice.textContent = `Live GPS：recording | 真實 GPS 軌跡 ${formatDistance(sample.distanceFlownMeters)}`;
    }

    this.autoRecordingContext = reduceAutoRecordingState(
      this.autoRecordingContext ?? {
        home: this.journey.segments[0].origin,
        state: 'Idle'
      },
      {
        timestamp: point.timestamp,
        location: point,
        speedMetersPerSecond: point.speedMetersPerSecond ?? 0
      }
    );
    this.renderProductPanel(sample.point);
  }

  private syncPlayButton(): void {
    if (this.isLiveGpsMode) {
      this.playButton.textContent = 'LIVE';
      return;
    }
    this.playButton.textContent = this.clock?.isPlaying ? '暫停' : '播放';
  }

  private syncViewRail(): void {
    this.root.classList.toggle('is-pilot-view', this.cameraMode === 'pilotView');
    this.pilotHud.setAttribute('aria-hidden', String(this.cameraMode !== 'pilotView'));
    for (const button of this.viewRail.querySelectorAll<HTMLButtonElement>('.view-mode-button')) {
      const isActive = button.dataset.mode === this.cameraMode;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', String(isActive));
    }
  }

  private renderPilotHud(metrics: ReturnType<typeof buildFlightHudMetrics>): void {
    this.pilotHud.replaceChildren(
      pilotScale('Airspeed', metrics.speedKmh, 'left'),
      pilotScale('Altitude', metrics.altitudeFeet, 'right'),
      pilotReadout('GSPD', metrics.groundSpeedKmh),
      pilotReadout('HDG', metrics.headingDegrees),
      pilotReadout('VS', metrics.verticalSpeedLabel),
      pilotReadout('ALT', metrics.altitudeFeet),
      pilotHorizon()
    );
  }

  private renderPreloadPanel(segment: JourneySegment): void {
    const form = document.createElement('form');
    form.className = 'preload-form';

    const airportSuggestions = listAirportSuggestions();

    this.flightNumberInput.value = stringValue(segment.metadata.flightNumber, 'CI100');
    this.aviationstackApiKeyInput.value = readAviationstackApiKey();
    this.originInput.value = segment.origin.iataCode ?? '';
    this.destinationInput.value = segment.destination.iataCode ?? '';
    this.departureDateInput.value = toInputDate(segment.startTime);
    this.departureTimeInput.value = toInputTime(segment.startTime);
    this.durationInput.value = '';
    this.aircraftTypeSelect.replaceChildren(
      ...aircraftTypeOptions.map((aircraft) => {
        const option = document.createElement('option');
        option.value = aircraft.value;
        option.textContent = aircraft.label;
        return option;
      })
    );
    this.aircraftTypeSelect.value = normalizeAircraftSelectValue(stringValue(segment.metadata.aircraftType, DEFAULT_AIRCRAFT_TYPE));

    const submitButton = document.createElement('button');
    submitButton.type = 'submit';
    submitButton.className = 'preload-submit';
    submitButton.textContent = '套用航線';

    this.preloadStatus.className = 'preload-status';
    this.preloadStatus.textContent = '可輸入 aviationstack API key 自動查航班；查到後會存在本機，API 失敗時用歷史航班 fallback。';

    const markPending = (): void => {
      this.preloadStatus.textContent = '已修改設定，請按「套用航線」更新地球、時間與航跡。';
    };
    const applyKnownFlight = (): void => {
      const schedule = findScheduleByFlightNumber(this.flightNumberInput.value);
      const cached = this.flightPreloadProvider.getCachedFlight(this.flightNumberInput.value);
      if (!schedule && !cached) {
        markPending();
        return;
      }
      const known = cached ?? schedule;
      if (!known) {
        markPending();
        return;
      }
      this.originInput.value = known.originIata;
      this.destinationInput.value = known.destinationIata;
      const details = [`${known.originIata} -> ${known.destinationIata}`];
      const defaultDepartureTime = cached?.departureTime ?? schedule?.defaultDepartureTime;
      const defaultDurationMinutes = cached?.durationMinutes ?? schedule?.defaultDurationMinutes;
      const defaultAircraftType = cached?.aircraftType ?? schedule?.defaultAircraftType;
      if (defaultDepartureTime) {
        this.departureTimeInput.value = defaultDepartureTime;
        details.push(defaultDepartureTime);
      }
      if (defaultDurationMinutes) {
        this.durationInput.value = String(defaultDurationMinutes);
        details.push(`${defaultDurationMinutes} 分鐘`);
      }
      if (defaultAircraftType) {
        this.aircraftTypeSelect.value = normalizeAircraftSelectValue(defaultAircraftType);
        details.push(defaultAircraftType);
      }
      const sourceLabel = cached ? '本機歷史快取' : '離線 seed';
      this.preloadStatus.textContent = `${known.flightNumber} 已由${sourceLabel}帶入 ${details.join('、')}。請按「套用航線」更新地球與航跡。`;
    };
    for (const input of [
      this.flightNumberInput,
      this.originInput,
      this.destinationInput,
      this.departureDateInput,
      this.departureTimeInput,
      this.aircraftTypeSelect
    ]) {
      input.addEventListener('input', markPending);
      input.addEventListener('change', markPending);
    }
    this.aviationstackApiKeyInput.addEventListener('change', () => {
      writeAviationstackApiKey(this.aviationstackApiKeyInput.value);
      this.preloadStatus.textContent = this.aviationstackApiKeyInput.value.trim()
        ? 'aviationstack API key 已保存在本機。下次套用航線會先嘗試 API，成功後寫入航班快取。'
        : 'aviationstack API key 已清除；會使用本機快取或離線 seed。';
    });
    this.flightNumberInput.addEventListener('input', () => {
      if (findScheduleByFlightNumber(this.flightNumberInput.value)) {
        applyKnownFlight();
      }
    });
    this.flightNumberInput.addEventListener('change', applyKnownFlight);

    form.append(
      field('aviationstack API key', this.aviationstackApiKeyInput, {
        placeholder: '保存在本機',
        type: 'password',
        required: false
      }),
      field('航班號', this.flightNumberInput, { placeholder: 'CI100' }),
      airportField('起飛', this.originInput, airportSuggestions, markPending, {
        placeholder: 'TPE / Taipei'
      }),
      airportField('抵達', this.destinationInput, airportSuggestions, markPending, {
        placeholder: 'NRT / Tokyo'
      }),
      field('日期', this.departureDateInput, { type: 'date' }),
      field('時間', this.departureTimeInput, { type: 'time' }),
      selectField('機型', this.aircraftTypeSelect),
      submitButton
    );
    this.aviationstackApiKeyInput.classList.add('is-secret');
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      void this.preloadFlightFromForm();
    });

    this.preloadPanel.replaceChildren(form, this.preloadStatus);
  }

  private async preloadFlightFromForm(): Promise<void> {
    const request: PreloadFlightRequest = {
      flightNumber: this.flightNumberInput.value,
      originIata: this.originInput.value,
      destinationIata: this.destinationInput.value,
      departureDate: this.departureDateInput.value,
      departureTime: this.departureTimeInput.value,
      durationMinutes: Number(this.durationInput.value) || undefined,
      aircraftType: this.aircraftTypeSelect.value
    };
    writeAviationstackApiKey(this.aviationstackApiKeyInput.value);

    try {
      this.preloadStatus.textContent = '正在建立預載航線...';
      const result = await this.flightPreloadProvider.preloadFlight(request);
      await this.loadJourney(result.journey);
      const sentToNative = postNativeMessage('flightPlan.apply', flightPlanPayloadFromJourney(result.journey));
      const message = `${result.journey.title} 已預載。${result.warnings[0] ?? ''}`;
      const nativeHint = sentToNative
        ? '已送至 iOS，按 Start recording 會綁定這條航線。'
        : '瀏覽器模式只會預載航線；iOS GPS 綁定需在 app 內使用。';
      this.preloadStatus.textContent = `${message} ${nativeHint}`;
      this.capability.textContent = `${message} ${nativeHint}`;
    } catch (error) {
      this.preloadStatus.textContent = error instanceof Error ? error.message : '航班預載失敗';
    }
  }

  private renderTimeline(): void {
    const visibleRecords = this.travelRecords.filter(
      (record) => this.activeRegion === 'all' || record.region === this.activeRegion
    );
    const items = visibleRecords.map((record) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `timeline-item travel-record-item${record.id === this.activeRecordId ? ' is-active' : ''}`;
      button.style.setProperty('--record-accent', record.accent);

      const marker = document.createElement('span');
      marker.className = 'record-marker';
      marker.textContent = record.markerLabel;

      const body = document.createElement('span');
      body.className = 'record-body';
      const title = document.createElement('strong');
      title.textContent = record.title;
      const meta = document.createElement('span');
      meta.textContent = `${record.dateLabel} | ${record.regionLabel}`;
      const subtitle = document.createElement('span');
      subtitle.textContent = record.subtitle;
      body.append(title, meta, subtitle);

      button.append(marker, body);
      button.addEventListener('click', () => this.activateRecord(record.id, true));
      return button;
    });

    this.timelineList.replaceChildren(...items);
  }

  private renderRegionFilters(): void {
    const regions = new Set(this.travelRecords.map((record) => record.region));
    const options: Array<{ id: TravelRegion | 'all'; label: string }> = [
      { id: 'all', label: 'All' },
      ...[...regions].map((region) => ({ id: region, label: getRegionLabel(region) }))
    ];

    const buttons = options.map((option) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `record-filter${option.id === this.activeRegion ? ' is-active' : ''}`;
      button.textContent = option.label;
      button.addEventListener('click', () => {
        this.activeRegion = option.id;
        if (option.id !== 'all') {
          this.activeRecordId = this.travelRecords.find((record) => record.region === option.id)?.id ?? this.activeRecordId;
        }
        this.renderRegionFilters();
        this.renderTimeline();
        this.renderRecordPreview();
      });
      return button;
    });

    this.recordFilterBar.replaceChildren(...buttons);
  }

  private activateRecord(recordId: string, shouldSeek: boolean): void {
    const record = this.travelRecords.find((candidate) => candidate.id === recordId);
    if (!record) {
      return;
    }
    this.activeRecordId = record.id;
    if (shouldSeek) {
      this.seekToTimestamp(record.timestamp);
    }
    this.renderTimeline();
    this.renderRecordPreview();
  }

  private renderRecordPreview(): void {
    const record =
      this.travelRecords.find((candidate) => candidate.id === this.activeRecordId) ?? this.travelRecords[0];
    if (!record) {
      this.recordPreview.replaceChildren();
      return;
    }

    this.recordPreview.style.setProperty('--record-accent', record.accent);

    const image = document.createElement('div');
    image.className = 'record-photo';
    image.textContent = record.markerLabel;

    const content = document.createElement('div');
    content.className = 'record-preview-content';
    const meta = document.createElement('div');
    meta.className = 'record-preview-meta';
    meta.textContent = `${record.coordinateLabel} | ${record.regionLabel}`;
    const title = document.createElement('h2');
    title.textContent = record.title;
    const subtitle = document.createElement('p');
    subtitle.textContent = record.subtitle;
    const tags = document.createElement('div');
    tags.className = 'record-tags';
    tags.replaceChildren(...record.tags.map((tag) => tagPill(tag)));
    const mediaGallery = document.createElement('div');
    mediaGallery.className = 'record-media-gallery';
    if (record.mediaItems.length === 0) {
      mediaGallery.textContent = '尚未附加照片';
    } else {
      mediaGallery.replaceChildren(
        ...record.mediaItems.map((item) => {
          const media = document.createElement('figure');
          media.className = 'record-media-item';
          if (item.url && item.type.startsWith('image/')) {
            const image = document.createElement('img');
            image.src = item.url;
            image.alt = item.name;
            media.append(image);
          }
          const caption = document.createElement('figcaption');
          caption.textContent = `${item.name} | ${item.privacy === 'shareable' ? '可匯出' : '本機私有'}`;
          media.append(caption);
          return media;
        })
      );
    }
    const actions = document.createElement('div');
    actions.className = 'record-actions';
    actions.replaceChildren(
      recordActionButton('新增事件', () => void this.addManualTravelRecord()),
      recordActionButton('修改紀錄', () => void this.editActiveTravelRecord(record)),
      recordActionButton('分類/時間', () => void this.editRecordDetails(record)),
      recordActionButton('附加照片', () => this.mediaInput.click()),
      recordActionButton('復原上次', () => void this.undoRecordEdit()),
      recordActionButton('隱藏紀錄', () => void this.hideActiveTravelRecord(record)),
      recordActionButton('編輯航線摘要', () => void this.editFlightSummary())
    );
    content.append(meta, title, subtitle, tags, mediaGallery, actions);

    this.recordPreview.replaceChildren(image, content);
  }

  private async addManualTravelRecord(): Promise<void> {
    if (!this.journey || !this.segment || !this.clock) {
      return;
    }
    const title = window.prompt('新增旅遊紀錄標題', '人工打卡');
    if (!title?.trim()) {
      return;
    }
    const subtitle = window.prompt('備註', '手動新增') ?? '手動新增';
    const point = this.currentDisplayPoint();
    const event: TimelineEvent = {
      id: `event-${this.segment.id}-manual-${Date.now()}`,
      journeyId: this.journey.id,
      segmentId: this.segment.id,
      timestamp: point.timestamp,
      type: 'manualTravelRecord',
      title: title.trim(),
      subtitle: subtitle.trim(),
      location: {
        latitude: point.latitude,
        longitude: point.longitude,
        altitudeMeters: point.altitudeMeters
      },
      mediaIds: [],
      importance: 0.8,
      source: 'manual',
      metadata: {
        editable: true
      }
    };
    this.pushRecordUndo();
    await this.loadJourney({
      ...this.journey,
      events: [...this.journey.events, event],
      segments: this.journey.segments.map((segment) =>
        segment.id === this.segment?.id
          ? { ...segment, events: [...segment.events, event.id] }
          : segment
      )
    });
    this.activeRecordId = event.id;
    this.renderTimeline();
    this.renderRecordPreview();
  }

  private async editActiveTravelRecord(record: TravelRecord): Promise<void> {
    if (!this.journey) {
      return;
    }
    const title = window.prompt('旅遊紀錄標題', record.title);
    if (title === null) {
      return;
    }
    const subtitle = window.prompt('備註/副標題', record.subtitle) ?? record.subtitle;
    this.pushRecordUndo();
    const edited = writeTravelRecordEdit(this.journey, record.id, {
      title,
      subtitle,
      note: 'manual edit'
    });
    await this.loadJourney(edited);
    this.activeRecordId = record.id;
    this.renderTimeline();
    this.renderRecordPreview();
  }

  private async hideActiveTravelRecord(record: TravelRecord): Promise<void> {
    if (!this.journey) {
      return;
    }
    if (!window.confirm(`隱藏「${record.title}」？原始 GPS 與事件資料仍會保留。`)) {
      return;
    }
    this.pushRecordUndo();
    await this.loadJourney(writeTravelRecordEdit(this.journey, record.id, { hidden: true }));
  }

  private async editRecordDetails(record: TravelRecord): Promise<void> {
    if (!this.journey) {
      return;
    }
    const regionOptions = getTravelRegionOptions();
    const regionPrompt = regionOptions.map((option) => `${option.id}=${option.label}`).join(', ');
    const region = window.prompt(`區域分類：${regionPrompt}`, record.region);
    if (region === null) {
      return;
    }
    const timestamp = window.prompt('時間 ISO 8601', record.timestamp);
    if (timestamp === null) {
      return;
    }
    const normalizedRegion = regionOptions.some((option) => option.id === region)
      ? (region as TravelRegion)
      : record.region;
    const normalizedTimestamp = Number.isFinite(Date.parse(timestamp)) ? new Date(timestamp).toISOString() : record.timestamp;
    this.pushRecordUndo();
    await this.loadJourney(writeTravelRecordEdit(this.journey, record.id, {
      region: normalizedRegion,
      timestamp: normalizedTimestamp,
      note: 'details edit'
    }));
    this.activeRecordId = record.id;
    this.renderTimeline();
    this.renderRecordPreview();
  }

  private async attachMediaToActiveRecord(file: File): Promise<void> {
    if (!this.journey || !this.activeRecordId) {
      this.mediaInput.value = '';
      return;
    }
    try {
      const dataUrl = await readFileAsDataUrl(file);
      const mediaId = `media-${this.activeRecordId}-${Date.now()}`;
      const mediaItem = {
        id: mediaId,
        name: file.name || 'photo',
        type: file.type || 'image/jpeg',
        url: dataUrl,
        linkedRecordId: this.activeRecordId,
        privacy: 'private'
      };
      this.pushRecordUndo();
      const updatedEvents = this.journey.events.map((event) =>
        event.id === this.activeRecordId
          ? {
              ...event,
              mediaIds: [...new Set([...event.mediaIds, mediaId])],
              metadata: {
                ...event.metadata,
                mediaAttachedAt: new Date().toISOString()
              }
            }
          : event
      );
      await this.loadJourney({
        ...this.journey,
        events: updatedEvents,
        media: [...this.journey.media, mediaItem],
        metadata: {
          ...this.journey.metadata,
          mediaPrivacyDefault: 'private'
        }
      });
      this.activeRecordId = mediaItem.linkedRecordId;
      this.renderTimeline();
      this.renderRecordPreview();
      this.capability.textContent = `已將 ${mediaItem.name} 附加到旅遊紀錄；預設只存在本機 journey。`;
    } finally {
      this.mediaInput.value = '';
    }
  }

  private async undoRecordEdit(): Promise<void> {
    const previous = this.recordEditUndoStack.pop();
    if (!previous) {
      this.capability.textContent = '沒有可復原的旅遊紀錄編輯。';
      return;
    }
    await this.loadJourney(previous);
    this.capability.textContent = '已復原上一筆旅遊紀錄編輯。';
  }

  private pushRecordUndo(): void {
    if (!this.journey) {
      return;
    }
    this.recordEditUndoStack = [...this.recordEditUndoStack.slice(-7), structuredClone(this.journey)];
  }

  private async editFlightSummary(): Promise<void> {
    if (!this.journey || !this.segment) {
      return;
    }
    const currentFlight = stringValue(this.segment.metadata.flightNumber, '');
    const currentAircraft = stringValue(this.segment.metadata.aircraftType, DEFAULT_AIRCRAFT_TYPE);
    const flightNumber = window.prompt('航班號', currentFlight) ?? currentFlight;
    const aircraftType = window.prompt('機型', currentAircraft) ?? currentAircraft;
    const originIata = window.prompt('起飛機場 IATA', this.segment.origin.iataCode ?? '') ?? this.segment.origin.iataCode ?? '';
    const destinationIata = window.prompt('抵達機場 IATA', this.segment.destination.iataCode ?? '') ?? this.segment.destination.iataCode ?? '';
    const updatedSegment: JourneySegment = {
      ...this.segment,
      origin: { ...this.segment.origin, iataCode: originIata.trim().toUpperCase() || this.segment.origin.iataCode },
      destination: { ...this.segment.destination, iataCode: destinationIata.trim().toUpperCase() || this.segment.destination.iataCode },
      metadata: {
        ...this.segment.metadata,
        flightNumber: flightNumber.trim() || currentFlight,
        aircraftType: aircraftType.trim() || currentAircraft,
        summaryEditedAt: new Date().toISOString()
      }
    };
    await this.loadJourney({
      ...this.journey,
      title: `${updatedSegment.metadata.flightNumber} ${updatedSegment.origin.iataCode ?? updatedSegment.origin.name} to ${updatedSegment.destination.iataCode ?? updatedSegment.destination.name}`,
      segments: this.journey.segments.map((segment) => segment.id === updatedSegment.id ? updatedSegment : segment),
      metadata: {
        ...this.journey.metadata,
        summaryEditedAt: new Date().toISOString()
      }
    });
  }

  private currentDisplayPoint(): ReturnType<typeof sampleReplayAt>['point'] {
    if (!this.segment || !this.clock) {
      throw new Error('No active segment');
    }
    const liveSample = this.isLiveGpsMode ? this.liveGps.sample(performance.now(), this.segment) : undefined;
    return liveSample?.point ?? sampleReplayAt(this.segment, this.clock.currentSeconds).point;
  }

  private seekToTimestamp(timestamp: string): void {
    if (!this.segment || !this.clock) {
      return;
    }
    const bounds = getRouteTimeBounds(this.segment);
    const elapsedSeconds = (Date.parse(timestamp) - bounds.startMs) / 1000;
    this.clock.seekPercent(elapsedSeconds / bounds.durationSeconds);
  }

  private async importJourney(file: File): Promise<void> {
    try {
      const journey = await readJourneyFile(file);
      await this.loadJourney(journey);
    } catch (error) {
      this.capability.textContent = error instanceof Error ? error.message : 'Unable to import journey';
    } finally {
      this.fileInput.value = '';
    }
  }

  private async exportTravelGlobe(): Promise<void> {
    if (!this.journey) {
      return;
    }
    const filename = `${this.journey.id}.travelglobe`;
    await this.runExport(filename, () => this.adapter.exportJourney(this.journey!));
  }

  private async exportShareSafeJson(): Promise<void> {
    if (!this.journey) {
      return;
    }
    const filename = `${this.journey.id}.share-safe.json`;
    await this.runExport(filename, () => this.adapter.exportShareSafeJourney(this.journey!));
  }

  private async exportJournalMarkdown(): Promise<void> {
    if (!this.journey) {
      return;
    }
    const filename = `${this.journey.id}.journal.md`;
    const journal = generateOfflineJournal(this.journey);
    await this.runExport(filename, () => exportBlob(new Blob([journal.markdown], { type: 'text/markdown' }), filename, 'text/markdown'));
  }

  private async exportGpx(): Promise<void> {
    if (!this.journey) {
      return;
    }
    const filename = `${this.journey.id}.gpx`;
    await this.runExport(filename, () => exportBlob(new Blob([createGpx(this.journey!)], { type: 'application/gpx+xml' }), filename, 'application/gpx+xml'));
  }

  private async exportKml(): Promise<void> {
    if (!this.journey) {
      return;
    }
    const filename = `${this.journey.id}.kml`;
    await this.runExport(filename, () => exportBlob(new Blob([createKml(this.journey!)], { type: 'application/vnd.google-earth.kml+xml' }), filename, 'application/vnd.google-earth.kml+xml'));
  }

  private async runExport(filename: string, exporter: () => Promise<NativeExportDelivery>): Promise<void> {
    this.capability.textContent = `正在準備 ${filename}...`;
    try {
      const delivery = await exporter();
      this.capability.textContent = delivery === 'native-share'
        ? `${filename} 已開啟 iOS 分享/儲存，並暫存到 App Documents/Exports。`
        : `${filename} 已下載到瀏覽器下載資料夾。`;
    } catch (error) {
      this.capability.textContent = error instanceof Error ? `匯出失敗：${error.message}` : '匯出失敗。';
    }
  }

  private renderBelowMe(sample: ReturnType<typeof sampleReplayAt>): void {
    const summary = summarizeBelowMe(sample.point, sample.bearingDegrees, this.routeLandmarks);
    const nearby = summary.nearby
      .slice(0, 3)
      .map((item) => `${landmarkDisplayName(item.feature)} ${formatDistance(item.distanceMeters)}`)
      .join(' | ') || '航線附近沒有可用景點資料';
    const nextCity = summary.nextMajorCity
      ? `下一座主要城市：${landmarkDisplayName(summary.nextMajorCity.feature)} ${formatDistance(summary.nextMajorCity.distanceMeters)}`
      : '';
    const nearest = summary.nearby[0];
    const nearestLine = nearest
      ? `窗外提醒：${landmarkDisplayName(nearest.feature)}在你的${windowDirectionLabel(nearest.relativeWindow)}，距離 ${formatDistance(nearest.distanceMeters)}`
      : '窗外提醒：附近沒有可用景點資料';

    this.geoNotice.textContent = summary.windowHint
      ? `附近景點：${summary.windowHint}（${formatDistance(summary.nearby[0]?.distanceMeters ?? 0)}）`
      : '附近景點：等待航線附近資料';

    this.belowMe.replaceChildren(
      textLine(`下方：${summary.belowLabel}`),
      textLine(`穿越：${summary.crossingLabel}`),
      textLine(`附近：${nearby}`),
      textLine(nextCity || nearestLine)
    );
  }

  private renderProductPanel(currentPoint?: ReturnType<typeof sampleReplayAt>['point']): void {
    if (!this.journey) {
      return;
    }

    const summary = summarizeJourney(this.journey);
    const plan = buildPlanSummary(this.journey);
    const journal = generateOfflineJournal(this.journey);
    const timeMachine = buildTimeMachineState([this.journey]);
    const notifications = currentPoint ? evaluateNotifications(currentPoint, 2_000_000_000) : [];
    this.scheduleNativeNotifications(notifications);
    const atlas = summarizeTravelRecords(this.journey, this.travelRecords);
    const airportIndex = getAirportIndexSummary();
    const segment = getPrimaryFlightSegment(this.journey);
    const originContext = segment.origin.iataCode ? findAirportContextByIata(segment.origin.iataCode) : undefined;
    const destinationContext = segment.destination.iataCode ? findAirportContextByIata(segment.destination.iataCode) : undefined;
    const flightContextCount =
      (originContext?.frequencies.length ?? 0) +
      (originContext?.navaids.length ?? 0) +
      (destinationContext?.frequencies.length ?? 0) +
      (destinationContext?.navaids.length ?? 0);
    const rows = [
      ['Trips', String(atlas.totalTrips)],
      ['Countries', String(Math.max(atlas.countries.length, summary.countriesVisited.length))],
      ['Years', atlas.years.map((year) => year.year).join(', ') || timeMachine.years.join(', ')],
      ['Distance', formatDistance(summary.totalDistanceMeters)],
      ['Plan', `${plan.completedCount}/${plan.plannedPlaces.length} places completed`],
      ['Journal', `${journal.markdown.split('\n').length} markdown lines ready`],
      ['Offline', `${this.packState.packs.length} pack | ${formatBytes(getInstalledSizeBytes(this.packState))}`],
      ['Data', `${airportIndex.airports} airports | ${airportIndex.navaids} navaids`],
      ['Flight context', `${flightContextCount} radio/nav records`],
      ['Recording', this.autoRecordingContext?.state ?? 'Idle'],
      ['Notice', notifications.length > 0 ? notifications.map((item) => item.title).join(', ') : 'clear']
    ];

    const list = document.createElement('div');
    list.className = 'product-list';

    for (const [label, value] of rows) {
      const item = document.createElement('div');
      item.className = 'product-row';
      const key = document.createElement('span');
      key.textContent = label;
      const detail = document.createElement('strong');
      detail.textContent = value;
      item.append(key, detail);
      list.append(item);
    }

    const regionBars = document.createElement('div');
    regionBars.className = 'region-bars';
    for (const region of atlas.regions) {
      const row = document.createElement('div');
      row.className = 'region-bar-row';
      const label = document.createElement('span');
      label.textContent = region.label;
      const track = document.createElement('span');
      track.className = 'region-bar-track';
      const fill = document.createElement('span');
      fill.style.width = `${Math.max(12, (region.count / Math.max(1, this.travelRecords.length)) * 100)}%`;
      track.append(fill);
      const value = document.createElement('strong');
      value.textContent = String(region.count);
      row.append(label, track, value);
      regionBars.append(row);
    }

    const packDescription = document.createElement('div');
    packDescription.className = 'pack-description';
    packDescription.textContent = describeInstalledPacks(this.packState);

    const airportDetails = document.createElement('div');
    airportDetails.className = 'atlas-section-grid';
    airportDetails.replaceChildren(
      ...[
        segment.origin.iataCode ? this.renderAirportDetailCard(segment.origin.iataCode, '起飛機場') : undefined,
        segment.destination.iataCode ? this.renderAirportDetailCard(segment.destination.iataCode, '降落機場') : undefined
      ].filter((item): item is HTMLElement => Boolean(item))
    );

    const packControls = document.createElement('div');
    packControls.className = 'atlas-section';
    const packTitle = document.createElement('strong');
    packTitle.textContent = '離線資料包';
    const packList = document.createElement('div');
    packList.className = 'pack-control-list';
    packList.replaceChildren(
      ...coreOfflinePacks.map((pack) => {
        const installed = isPackInstalled(this.packState, pack.id);
        const row = document.createElement('div');
        row.className = 'pack-control-row';
        const body = document.createElement('span');
        body.textContent = `${pack.name} | ${formatBytes(pack.sizeBytes)} | ${pack.dataLayers.length} layers`;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'record-action-button';
        button.textContent = installed ? '刪除' : '安裝';
        button.addEventListener('click', () => {
          if (installed) {
            this.deleteOfflinePack(pack.id);
          } else {
            this.installOfflinePack(pack.id);
          }
        });
        row.append(body, button);
        return row;
      })
    );
    packControls.append(packTitle, packList);

    const savedJourneyList = document.createElement('div');
    savedJourneyList.className = 'atlas-section';
    const savedTitle = document.createElement('strong');
    savedTitle.textContent = '本機歷史旅程';
    const savedRows = document.createElement('div');
    savedRows.className = 'saved-journey-list';
    savedRows.replaceChildren(
      ...(this.savedJourneys.length > 0
        ? this.savedJourneys.slice(0, 6).map((summary) => this.renderSavedJourneyRow(summary))
        : [textLine('尚無本機歷史旅程')])
    );
    savedJourneyList.append(savedTitle, savedRows);

    const notificationList = document.createElement('div');
    notificationList.className = 'atlas-section';
    const notificationTitle = document.createElement('strong');
    notificationTitle.textContent = '通知';
    notificationList.append(
      notificationTitle,
      textLine(notifications.length > 0 ? notifications.map((item) => item.body).join(' | ') : '目前沒有需要提醒的事件')
    );

    this.productPanel.replaceChildren(
      list,
      regionBars,
      airportDetails,
      packControls,
      savedJourneyList,
      notificationList,
      packDescription
    );
  }

  private renderAirportDetailCard(iataCode: string, label: string): HTMLElement {
    const airport = findAirportByIata(iataCode);
    const context = findAirportContextByIata(iataCode);
    const card = document.createElement('div');
    card.className = 'airport-detail-card';
    const title = document.createElement('strong');
    title.textContent = `${label} ${iataCode}`;
    const summary = document.createElement('span');
    summary.textContent = airport
      ? `${airport.name} | ${airport.municipality}, ${airport.countryCode} | runways ${airport.runwayCount}`
      : '本機 airport index 尚無此機場 detail';
    const radio = document.createElement('small');
    const frequencies = context?.frequencies
      .slice(0, 3)
      .map((item) => `${item.type}${item.frequencyMhz ? ` ${item.frequencyMhz.toFixed(3)}` : ''}`)
      .join(', ') || '無頻率資料';
    const navaids = context?.navaids
      .slice(0, 3)
      .map((item) => `${item.ident} ${item.type}`)
      .join(', ') || '無 navaid 資料';
    radio.textContent = `FREQ: ${frequencies} | NAVAID: ${navaids}`;
    card.append(title, summary, radio);
    return card;
  }

  private renderSavedJourneyRow(summary: SavedJourneySummary): HTMLElement {
    const row = document.createElement('div');
    row.className = 'saved-journey-row';
    const body = document.createElement('span');
    body.textContent = `${summary.title} | ${summary.status} | ${formatShortDate(summary.startTime)}`;
    const loadButton = document.createElement('button');
    loadButton.type = 'button';
    loadButton.className = 'record-action-button';
    loadButton.textContent = '載入';
    loadButton.addEventListener('click', () => void this.loadSavedJourney(summary.id));
    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'record-action-button';
    deleteButton.textContent = '刪除';
    deleteButton.addEventListener('click', () => void this.deleteSavedJourney(summary.id));
    row.append(body, loadButton, deleteButton);
    return row;
  }

  private installOfflinePack(packId: string): void {
    const pack = coreOfflinePacks.find((candidate) => candidate.id === packId);
    if (!pack) {
      return;
    }
    this.packState = installPack(this.packState, pack);
    saveOfflinePackState(this.packState);
    this.capability.textContent = `${pack.name} 已安裝到本機離線資料狀態。`;
    this.renderProductPanel();
  }

  private deleteOfflinePack(packId: string): void {
    const pack = coreOfflinePacks.find((candidate) => candidate.id === packId);
    this.packState = deletePack(this.packState, packId);
    saveOfflinePackState(this.packState);
    this.capability.textContent = `${pack?.name ?? packId} 已從本機離線資料狀態移除。`;
    this.renderProductPanel();
  }

  private async loadSavedJourney(journeyId: string): Promise<void> {
    const journey = await this.adapter.loadJourneyById(journeyId);
    if (!journey) {
      this.capability.textContent = '找不到這筆本機歷史旅程。';
      return;
    }
    await this.loadJourney(journey);
    this.capability.textContent = `已載入本機歷史旅程：${journey.title}`;
  }

  private async deleteSavedJourney(journeyId: string): Promise<void> {
    if (this.journey?.id === journeyId) {
      this.capability.textContent = '目前播放中的 journey 不能直接刪除，請先載入其他旅程。';
      return;
    }
    if (!window.confirm('刪除此本機歷史 journey？匯出的 .travelglobe 檔不會受影響。')) {
      return;
    }
    await this.adapter.deleteJourney(journeyId);
    this.savedJourneys = await this.adapter.listSavedJourneys();
    this.renderProductPanel();
  }

  private scheduleNativeNotifications(notifications: TravelNotification[]): void {
    for (const notification of notifications) {
      const identifier = `travelglobe.${notification.id}`;
      if (this.scheduledNotificationIds.has(identifier)) {
        continue;
      }
      const payload: NativeNotificationSchedulePayload = {
        identifier,
        title: notification.title,
        body: notification.body
      };
      postNativeMessage('notification.schedule', payload);
      this.scheduledNotificationIds.add(identifier);
    }
  }

  private readonly handleNativeEvent = (event: Event): void => {
    if (!this.journey || !this.segment) {
      return;
    }
    const nativeMessage = (event as CustomEvent<unknown>).detail;
    const completed = parseNativePayload<NativeRecordingPayload>(nativeMessage, 'recording.completed');
    if (completed) {
      const completedJourney = completeJourneyFromRecording(this.journey, completed);
      void this.loadJourney(completedJourney);
      this.capability.textContent = 'Live GPS recording：已完成並寫入旅遊紀錄';
      return;
    }
    const started = parseNativePayload<NativeRecordingPayload>(nativeMessage, 'recording.started');
    if (started) {
      this.capability.textContent = `Live GPS recording：${started.flightNumber ?? 'GPS'} 已開始`;
      return;
    }
    const addedVisitPoint = parseNativePayload<NativeVisitPointsPayload>(nativeMessage, 'visitPoint.added');
    if (addedVisitPoint) {
      void this.applyNativeVisitPoints(addedVisitPoint, true);
      return;
    }
    const syncedVisitPoints = parseNativePayload<NativeVisitPointsPayload>(nativeMessage, 'visitPoints.sync');
    if (syncedVisitPoints) {
      void this.applyNativeVisitPoints(syncedVisitPoints, false);
      return;
    }
    const selected = parseNativePayload<NativeFlightPlanPayload>(nativeMessage, 'flightPlan.selected');
    if (selected) {
      void this.activateNativeFlightPlan(selected);
      return;
    }
    const ready = parseNativePayload<{ flightNumber?: string; originIata?: string; destinationIata?: string }>(
      nativeMessage,
      'flightPlan.ready'
    );
    if (ready) {
      this.capability.textContent = `iOS flight plan ready：${ready.flightNumber ?? ''} ${ready.originIata ?? ''} -> ${ready.destinationIata ?? ''}`;
      return;
    }
    const point = liveGpsPointFromNativeMessage(
      nativeMessage,
      this.journey.id,
      this.segment.id
    );
    if (!point) {
      return;
    }
    this.isLiveGpsMode = true;
    this.liveGps.ingest(point, performance.now());
    this.capability.textContent = 'Live GPS recording：已接收 iPhone CoreLocation 真實定位';
  };

  private async applyNativeVisitPoints(payload: NativeVisitPointsPayload, focusNewest: boolean): Promise<void> {
    const targetJourney = payload.webJourneyId && payload.webJourneyId !== this.journey?.id
      ? await this.adapter.loadJourneyById(payload.webJourneyId)
      : this.journey;
    if (!targetJourney) {
      this.capability.textContent = 'iOS 打卡點：找不到對應行程';
      return;
    }

    const segment = payload.segmentId
      ? targetJourney.segments.find((candidate) => candidate.id === payload.segmentId) ?? getPrimaryFlightSegment(targetJourney)
      : getPrimaryFlightSegment(targetJourney);
    const incomingEvents = payload.points.map((point) => visitPointToEvent(point, targetJourney.id, segment.id));
    const incomingIds = new Set(incomingEvents.map((event) => event.id));
    const mergedEvents = [
      ...targetJourney.events.filter((event) => !incomingIds.has(event.id)),
      ...incomingEvents
    ].sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp));
    const segmentEventIds = new Set(segment.events.filter((id) => !incomingIds.has(id)));
    for (const event of incomingEvents) {
      segmentEventIds.add(event.id);
    }
    const updatedJourney: Journey = {
      ...targetJourney,
      events: mergedEvents,
      segments: targetJourney.segments.map((candidate) =>
        candidate.id === segment.id
          ? { ...candidate, events: [...segmentEventIds] }
          : candidate
      ),
      metadata: {
        ...targetJourney.metadata,
        nativeVisitPointsSyncedAt: new Date().toISOString()
      }
    };
    await this.loadJourney(updatedJourney);
    if (focusNewest && incomingEvents.length > 0) {
      this.activeRecordId = incomingEvents[incomingEvents.length - 1].id;
      this.renderTimeline();
      this.renderRecordPreview();
    }
    const gpsCount = payload.points.filter((point) => point.source === 'quickGps' || point.source === 'recordingMarker').length;
    const photoCount = payload.points.filter((point) => point.source === 'photoGps').length;
    this.capability.textContent = `iOS 打卡點：GPS打卡 ${gpsCount} 筆，照片打卡 ${photoCount} 筆`;
  }

  private async activateNativeFlightPlan(plan: NativeFlightPlanPayload): Promise<void> {
    const storedJourney = await this.adapter.loadJourneyById(plan.webJourneyId);
    if (storedJourney) {
      await this.loadJourney(storedJourney);
      this.capability.textContent = `iOS selected flight plan：${plan.flightNumber} ${plan.originIata} -> ${plan.destinationIata}`;
      return;
    }

    const departure = plan.departureTime && Number.isFinite(Date.parse(plan.departureTime))
      ? new Date(plan.departureTime)
      : new Date();
    const result = await this.flightPreloadProvider.preloadFlight({
      flightNumber: plan.flightNumber,
      originIata: plan.originIata,
      destinationIata: plan.destinationIata,
      departureDate: toInputDate(departure.toISOString()),
      departureTime: toInputTime(departure.toISOString()),
      durationMinutes: plan.durationMinutes,
      aircraftType: plan.aircraftType
    });
    await this.loadJourney(result.journey);
    this.capability.textContent = `iOS selected flight plan：${plan.flightNumber} ${plan.originIata} -> ${plan.destinationIata}`;
  }
}

function visitPointToEvent(point: NativeVisitPointPayload, journeyId: string, segmentId: string): TimelineEvent {
  const sourceLabel = visitPointSourceLabel(point.source);
  const timestamp = Number.isFinite(Date.parse(point.timestamp))
    ? new Date(point.timestamp).toISOString()
    : new Date().toISOString();
  return {
    id: `visit-${point.id}`,
    journeyId,
    segmentId,
    timestamp,
    type: 'visitPoint',
    title: sourceLabel,
    subtitle: point.note?.trim() || sourceLabel,
    location: {
      latitude: point.latitude,
      longitude: point.longitude,
      altitudeMeters: finiteNumber(point.altitudeMeters ?? undefined)
    },
    mediaIds: [],
    importance: point.source === 'photoGps' ? 0.78 : 0.74,
    source: point.source,
    metadata: {
      editable: true,
      visitPointId: point.id,
      visitPointSource: point.source,
      sourceId: point.sourceId ?? undefined,
      horizontalAccuracyMeters: finiteNumber(point.horizontalAccuracyMeters ?? undefined)
    }
  };
}

function visitPointSourceLabel(source: string): string {
  switch (source) {
    case 'photoGps':
      return '照片打卡';
    case 'quickGps':
    case 'recordingMarker':
      return 'GPS打卡';
    default:
      return '到此一遊';
  }
}

function finiteNumber(value: number | undefined): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function metricItem(label: string, value: string): HTMLElement {
  const item = document.createElement('div');
  item.className = 'hud-metric';
  const key = document.createElement('span');
  key.textContent = label;
  const detail = document.createElement('strong');
  detail.textContent = value;
  item.append(key, detail);
  return item;
}

function pilotScale(label: string, value: string, side: 'left' | 'right'): HTMLElement {
  const item = document.createElement('div');
  item.className = `pilot-scale pilot-scale-${side}`;
  const title = document.createElement('span');
  title.textContent = label;
  const readout = document.createElement('strong');
  readout.textContent = value.replace(' km/h', '').replace(' ft', '');
  const ladder = document.createElement('i');
  item.append(title, ladder, readout);
  return item;
}

function pilotReadout(label: string, value: string): HTMLElement {
  const item = document.createElement('div');
  item.className = 'pilot-readout';
  const title = document.createElement('span');
  title.textContent = label;
  const readout = document.createElement('strong');
  readout.textContent = value;
  item.append(title, readout);
  return item;
}

function pilotHorizon(): HTMLElement {
  const horizon = document.createElement('div');
  horizon.className = 'pilot-horizon';
  horizon.replaceChildren(
    Object.assign(document.createElement('span'), { className: 'pilot-horizon-line' }),
    Object.assign(document.createElement('span'), { className: 'pilot-reticle' }),
    Object.assign(document.createElement('span'), { className: 'pilot-bank' })
  );
  return horizon;
}

function textLine(value: string): HTMLElement {
  const line = document.createElement('div');
  line.textContent = value;
  return line;
}

function tagPill(value: string): HTMLElement {
  const tag = document.createElement('span');
  tag.textContent = value;
  return tag;
}

function recordActionButton(label: string, onClick: () => void): HTMLElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'record-action-button';
  button.textContent = label;
  button.addEventListener('click', onClick);
  return button;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result ?? '')));
    reader.addEventListener('error', () => reject(reader.error ?? new Error('Unable to read media file')));
    reader.readAsDataURL(file);
  });
}

function formatShortDate(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }
  return new Intl.DateTimeFormat('en', {
    month: 'short',
    day: '2-digit',
    year: 'numeric',
    timeZone: 'UTC'
  }).format(date);
}

function localizePhase(value: string): string {
  switch (value) {
    case 'Takeoff':
      return '起飛';
    case 'Top of Climb':
    case 'Climb':
      return '上升';
    case 'Cruise':
      return '巡航';
    case 'Top of Descent':
    case 'Descent':
      return '下降';
    case 'Approach':
      return '進場';
    case 'Landing':
      return '降落';
    default:
      return value;
  }
}

function liveGpsStatusLabel(status: LiveGpsStatus): string {
  switch (status) {
    case 'live':
      return 'Live GPS';
    case 'estimated':
      return 'GPS 推算';
    case 'lost':
      return 'GPS signal lost';
  }
}

function field(
  label: string,
  input: HTMLInputElement,
  options: { placeholder?: string; type?: string; min?: string; step?: string; list?: string; required?: boolean } = {}
): HTMLElement {
  const wrapper = document.createElement('label');
  wrapper.className = 'preload-field';
  const text = document.createElement('span');
  text.textContent = label;
  input.type = options.type ?? 'text';
  input.placeholder = options.placeholder ?? '';
  input.autocomplete = 'off';
  input.required = options.required ?? true;
  input.className = 'preload-input';
  if (options.min) {
    input.min = options.min;
  }
  if (options.step) {
    input.step = options.step;
  }
  if (options.list) {
    input.setAttribute('list', options.list);
  }
  wrapper.append(text, input);
  return wrapper;
}

function selectField(label: string, select: HTMLSelectElement): HTMLElement {
  const wrapper = document.createElement('label');
  wrapper.className = 'preload-field';
  const text = document.createElement('span');
  text.textContent = label;
  select.className = 'preload-input';
  wrapper.append(text, select);
  return wrapper;
}

const aircraftTypeOptions = [
  { value: 'A320', label: 'A320' },
  { value: 'A321', label: 'A321' },
  { value: 'B737', label: 'B737' },
  { value: 'B767', label: 'B767' },
  { value: 'B777', label: 'B777' },
  { value: 'B787', label: 'B787' },
  { value: 'A350', label: 'A350' },
  { value: 'A380', label: 'A380' }
];
const AIRPORT_MATCH_LIMIT = 12;

function normalizeAircraftSelectValue(value: string): string {
  const normalized = value.toUpperCase().replace(/[^A-Z0-9]/g, '');
  const match = aircraftTypeOptions.find((option) => normalized.includes(option.value));
  return match?.value ?? DEFAULT_AIRCRAFT_TYPE;
}

function airportField(
  label: string,
  input: HTMLInputElement,
  airports: AirportRecord[],
  onSelect: () => void,
  options: { placeholder?: string; list?: string } = {}
): HTMLElement {
  const wrapper = document.createElement('div');
  wrapper.className = 'preload-field airport-picker';
  const text = document.createElement('span');
  text.textContent = label;
  input.type = 'text';
  input.placeholder = options.placeholder ?? '';
  input.autocomplete = 'off';
  input.required = false;
  input.className = 'preload-input';
  input.setAttribute('aria-label', label);
  if (options.list) {
    input.setAttribute('list', options.list);
  }

  const menu = document.createElement('div');
  menu.className = 'airport-picker-menu';
  menu.hidden = true;
  wrapper.append(text, input, menu);

  let suppressMenuUntil = 0;
  const closeMenu = (): void => {
    suppressMenuUntil = performance.now() + 220;
    menu.hidden = true;
    menu.replaceChildren();
  };

  const showMatches = (): void => {
    if (performance.now() < suppressMenuUntil) {
      return;
    }
    const query = input.value.trim().toUpperCase();
    const matches = matchAirportSuggestions(airports, query, AIRPORT_MATCH_LIMIT);

    const buttons = matches.map((airport) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'airport-option';
      const code = document.createElement('strong');
      code.textContent = airportDisplayCode(airport);
      const name = document.createElement('span');
      name.textContent = airport.name;
      const place = document.createElement('small');
      place.textContent = `${airport.municipality}, ${airport.countryCode}`;
      button.append(code, name, place);
      const selectAirport = (event: Event): void => {
        event.preventDefault();
        event.stopPropagation();
        input.value = airportDisplayCode(airport);
        closeMenu();
        if (document.activeElement instanceof HTMLElement) {
          document.activeElement.blur();
        }
        onSelect();
      };
      button.addEventListener('touchstart', selectAirport, { passive: false });
      button.addEventListener('mousedown', selectAirport);
      button.addEventListener('pointerdown', selectAirport);
      button.addEventListener('click', selectAirport);
      return button;
    });

    menu.replaceChildren(...buttons);
    menu.hidden = buttons.length === 0;
  };

  input.addEventListener('focus', showMatches);
  input.addEventListener('input', showMatches);
  input.addEventListener('blur', () => {
    window.setTimeout(() => {
      closeMenu();
    }, 120);
  });

  return wrapper;
}

export function matchAirportSuggestions(
  airports: AirportRecord[],
  query: string,
  limit = AIRPORT_MATCH_LIMIT
): AirportRecord[] {
  const normalizedQuery = query.trim().toUpperCase();
  return airports
    .map((airport) => ({
      airport,
      rank: airportMatchRank(airport, normalizedQuery)
    }))
    .filter((match) => match.rank >= 0)
    .sort((a, b) =>
      a.rank - b.rank ||
      airportSortKey(a.airport).localeCompare(airportSortKey(b.airport))
    )
    .slice(0, limit)
    .map((match) => match.airport);
}

function airportMatchRank(airport: AirportRecord, query: string): number {
  const iata = airport.iataCode?.toUpperCase() ?? '';
  const icao = airport.icaoCode?.toUpperCase() ?? '';
  const ident = airport.ident?.toUpperCase() ?? '';
  const name = airport.name.toUpperCase();
  const municipality = airport.municipality.toUpperCase();
  const country = airport.countryCode?.toUpperCase() ?? '';

  if (query.length === 0) {
    if (airport.scheduledService && airport.type === 'large_airport') {
      return 60;
    }
    if (airport.scheduledService && airport.type === 'medium_airport') {
      return 70;
    }
    if (airport.scheduledService) {
      return 80;
    }
    return 95;
  }
  if (iata === query) {
    return 0;
  }
  if (icao === query) {
    return 1;
  }
  if (ident === query) {
    return 2;
  }
  if (iata.startsWith(query)) {
    return 10;
  }
  if (icao.startsWith(query)) {
    return 12;
  }
  if (ident.startsWith(query)) {
    return 14;
  }
  if (name.startsWith(query) || municipality.startsWith(query)) {
    return 20;
  }
  if (name.includes(query) || municipality.includes(query) || country.includes(query)) {
    return 30;
  }
  return -1;
}

function airportSortKey(airport: AirportRecord): string {
  const scheduledRank = airport.scheduledService ? '0' : '1';
  const typeRank = airport.type === 'large_airport' ? '0' : airport.type === 'medium_airport' ? '1' : '2';
  return `${scheduledRank}-${typeRank}-${airportDisplayCode(airport)}-${airport.name}`;
}

function airportDisplayCode(airport: AirportRecord): string {
  return airport.iataCode ?? airport.icaoCode ?? airport.ident ?? '';
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : fallback;
}

function bindTouchAction(element: HTMLElement, action: (event: Event) => void | Promise<void>): void {
  let lastActivationMs = 0;
  const activate = (event: Event): void => {
    event.preventDefault();
    event.stopPropagation();
    const now = performance.now();
    if (now - lastActivationMs < 280) {
      return;
    }
    lastActivationMs = now;
    void action(event);
  };
  element.addEventListener('pointerdown', (event) => {
    event.stopPropagation();
  });
  element.addEventListener('pointerup', activate);
  element.addEventListener('touchend', activate, { passive: false });
  element.addEventListener('click', activate);
}

function bindDetailsSummaryToggle(
  summary: HTMLElement,
  details: HTMLDetailsElement,
  onToggle?: () => void
): void {
  let pointerStart: { x: number; y: number; timeMs: number } | undefined;

  const toggle = (): void => {
    details.open = !details.open;
    onToggle?.();
  };

  summary.addEventListener('pointerdown', (event) => {
    pointerStart = {
      x: event.clientX,
      y: event.clientY,
      timeMs: performance.now()
    };
    event.stopPropagation();
  });
  summary.addEventListener('pointercancel', () => {
    pointerStart = undefined;
  });
  summary.addEventListener('pointerup', (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!pointerStart) {
      return;
    }
    const travel = Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y);
    const durationMs = performance.now() - pointerStart.timeMs;
    pointerStart = undefined;
    if (travel <= 12 && durationMs <= 700) {
      toggle();
    }
  });
  summary.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  summary.addEventListener('touchend', (event) => {
    event.preventDefault();
    event.stopPropagation();
  }, { passive: false });
  summary.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    toggle();
  });
}

function keepDetailsOpenDuringContentGestures(...elements: HTMLElement[]): void {
  for (const element of elements) {
    element.addEventListener('pointerdown', (event) => event.stopPropagation());
    element.addEventListener('pointerup', (event) => event.stopPropagation());
    element.addEventListener('touchstart', (event) => event.stopPropagation(), { passive: true });
    element.addEventListener('touchend', (event) => event.stopPropagation(), { passive: true });
    element.addEventListener('click', (event) => event.stopPropagation());
  }
}

function toInputDate(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return [
    date.getFullYear(),
    padDatePart(date.getMonth() + 1),
    padDatePart(date.getDate())
  ].join('-');
}

function toInputTime(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return `${padDatePart(date.getHours())}:${padDatePart(date.getMinutes())}`;
}

function padDatePart(value: number): string {
  return String(value).padStart(2, '0');
}
