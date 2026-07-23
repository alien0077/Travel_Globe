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
import type { Journey, JourneySegment, LocationPoint, TimelineEvent } from '../data/types';
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
  searchAirports,
  type AirportRecord
} from '../flight-preload/airportIndex';
import { findScheduleByFlightNumber } from '../flight-preload/flightScheduleIndex';
import { landmarkDisplayName, loadGlobalLandmarkIndex, windowDirectionLabel, type GeographicFeature } from '../geo/landmarks';
import { formatDistance } from '../geo/geodesy';
import { TravelGlobeScene } from '../globe/TravelGlobeScene';
import { readJourneyFile } from '../import/readJourneyFile';
import { generateOfflineJournal } from '../journal/generateJournal';
import {
  LiveGpsTracker,
  liveGpsPointFromNativeMessage,
  type LiveGpsStatus
} from '../live/liveGps';
import {
  completeJourneyFromRecording,
  createJourneyFromNativeRecording
} from '../live/completeJourneyFromRecording';
import { DEFAULT_AIRCRAFT_TYPE } from '../models/aircraftModelLibrary';
import { evaluateNotifications } from '../notifications/notificationRules';
import {
  coreOfflinePacks,
  formatBytes,
  getBundledOfflinePackSizeBytes
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
  private autoRecordingContext?: AutoRecordingContext;
  private travelRecords: TravelRecord[] = [];
  private activeRecordId?: string;
  private activeRegion: TravelRegion | 'all' = 'all';
  private liveGps = new LiveGpsTracker();
  private isLiveGpsMode = false;
  private savedJourneys: SavedJourneySummary[] = [];
  private recordEditUndoStack: Journey[] = [];
  private scheduledNotificationIds = new Set<string>();
  private airportBrowserQuery = '';
  private airportBrowserScheduledOnly = true;
  private pendingSavedJourneyDeleteId?: string;
  private shellEventController?: AbortController;
  private isPilotHudEnabled = true;
  private isPilotViewRailExpanded = false;

  private readonly viewport = document.createElement('section');
  private readonly cockpitWindow = document.createElement('section');
  private readonly pilotHudToggle = document.createElement('button');
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
  private readonly recordPanelActions = document.createElement('div');
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
    await loadGlobalLandmarkIndex();
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
    this.shellEventController?.abort();
    this.shellEventController = new AbortController();
    const renderSignal = this.shellEventController.signal;
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

    this.cockpitWindow.className = 'cockpit-window';
    this.cockpitWindow.setAttribute('aria-hidden', 'true');
    this.cockpitWindow.replaceChildren(
      Object.assign(document.createElement('div'), { className: 'cockpit-sky' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-terrain' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-clouds' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-horizon-line' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-ceiling' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-left-post' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-center-post' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-right-post' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-glare-shield' })
    );

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
        let lastViewActivationMs = 0;
        const activateViewMode = (event?: Event): void => {
          event?.preventDefault();
          event?.stopPropagation();
          const now = performance.now();
          if (now - lastViewActivationMs < 220) {
            return;
          }
          lastViewActivationMs = now;
          if (this.cameraMode === 'pilotView' && mode === 'pilotView') {
            this.isPilotViewRailExpanded = !this.isPilotViewRailExpanded;
            this.syncViewRail();
            return;
          }
          this.cameraMode = mode;
          this.isPilotViewRailExpanded = false;
          this.scene?.prepareForTimelineJump();
          this.syncViewRail();
        };
        button.addEventListener('pointerdown', (event) => {
          event.stopPropagation();
        }, { signal: renderSignal });
        button.addEventListener('pointerup', activateViewMode, { signal: renderSignal });
        button.addEventListener('touchend', activateViewMode, { passive: false, signal: renderSignal });
        button.addEventListener('click', activateViewMode, { signal: renderSignal });
        return button;
      })
    );

    const dock = document.createElement('section');
    dock.className = 'info-dock';
    this.pilotHud.className = 'pilot-hud';
    this.pilotHud.setAttribute('aria-hidden', 'true');
    this.pilotHudToggle.type = 'button';
    this.pilotHudToggle.className = 'pilot-hud-toggle';
    this.pilotHudToggle.addEventListener('click', () => {
      this.isPilotHudEnabled = !this.isPilotHudEnabled;
      this.syncViewRail();
    }, { signal: renderSignal });

    const timeline = document.createElement('details');
    timeline.className = 'dock-panel timeline-panel';
    timeline.open = false;
    const timelineTitle = document.createElement('summary');
    timelineTitle.className = 'panel-summary panel-title';
    timelineTitle.textContent = '旅遊紀錄';
    this.recordFilterBar.className = 'record-filters';
    this.recordPanelActions.className = 'record-panel-actions record-actions';
    this.timelineList.className = 'timeline-list';
    this.recordPreview.className = 'record-preview';
    timeline.append(timelineTitle, this.recordFilterBar, this.recordPanelActions, this.timelineList, this.recordPreview);
    keepDetailsOpenDuringContentGestures(renderSignal, this.recordFilterBar, this.recordPanelActions, this.timelineList, this.recordPreview);

    this.productPanel.className = 'product-panel';
    const productShell = document.createElement('details');
    productShell.className = 'dock-panel product-panel-shell';
    productShell.open = false;
    const productSummary = document.createElement('summary');
    productSummary.className = 'panel-summary panel-title';
    productSummary.textContent = 'Travel Atlas';
    productShell.append(productSummary, this.productPanel);
    keepDetailsOpenDuringContentGestures(renderSignal, this.productPanel);

    this.preloadPanel.className = 'preload-panel';
    const preloadShell = document.createElement('details');
    preloadShell.className = 'dock-panel preload-panel-shell';
    preloadShell.open = isCompactViewport;
    const preloadSummary = document.createElement('summary');
    preloadSummary.className = 'panel-summary panel-title';
    preloadSummary.textContent = '航班預載 / API key';
    preloadShell.append(preloadSummary, this.preloadPanel);
    const syncDrawerPanelState = (activePanel?: HTMLDetailsElement): void => {
      const openPanels = [preloadShell, productShell, timeline].filter((panel) => panel.open);
      const primaryPanel = activePanel?.open ? activePanel : openPanels[0];
      if (primaryPanel) {
        for (const panel of [preloadShell, productShell, timeline]) {
          if (panel !== primaryPanel) {
            panel.open = false;
          }
        }
      }
      dock.classList.toggle('has-open-preload', preloadShell.open);
      dock.classList.toggle('has-open-product', productShell.open);
      dock.classList.toggle('has-open-timeline', timeline.open);
    };
    bindDetailsSummaryToggle(timelineTitle, timeline, () => syncDrawerPanelState(timeline), renderSignal);
    bindDetailsSummaryToggle(productSummary, productShell, () => syncDrawerPanelState(productShell), renderSignal);
    bindDetailsSummaryToggle(preloadSummary, preloadShell, () => syncDrawerPanelState(preloadShell), renderSignal);
    timeline.addEventListener('toggle', () => requestAnimationFrame(() => syncDrawerPanelState(timeline)), { signal: renderSignal });
    productShell.addEventListener('toggle', () => requestAnimationFrame(() => syncDrawerPanelState(productShell)), { signal: renderSignal });
    preloadShell.addEventListener('toggle', () => requestAnimationFrame(() => syncDrawerPanelState(preloadShell)), { signal: renderSignal });

    const controls = document.createElement('section');
    controls.className = 'controls';

    this.playButton.type = 'button';
    this.playButton.className = 'control-button';
    this.playButton.addEventListener('click', () => {
      this.clock?.togglePlayback();
      this.syncPlayButton();
    }, { signal: renderSignal });

    this.speedSelect.className = 'control-select';
    this.speedSelect.replaceChildren();
    for (const speed of [1, 5, 20, 100]) {
      const option = document.createElement('option');
      option.value = String(speed);
      option.textContent = `${speed}x`;
      this.speedSelect.appendChild(option);
    }
    this.speedSelect.value = '5';
    this.speedSelect.addEventListener('change', () => {
      this.clock?.setSpeed(Number(this.speedSelect.value));
    }, { signal: renderSignal });

    this.scrubber.className = 'timeline-scrubber';
    this.scrubber.type = 'range';
    this.scrubber.min = '0';
    this.scrubber.max = '1000';
    this.scrubber.value = '0';
    this.scrubber.addEventListener('input', () => {
      this.scene?.prepareForTimelineJump();
      this.clock?.seekPercent(Number(this.scrubber.value) / 1000);
    }, { signal: renderSignal });

    const importButton = document.createElement('button');
    importButton.type = 'button';
    importButton.className = 'control-button secondary-action';
    importButton.textContent = 'Import';
    bindTouchAction(importButton, () => this.fileInput.click(), renderSignal);

    const exportButton = document.createElement('button');
    exportButton.type = 'button';
    exportButton.className = 'control-button secondary-action';
    exportButton.textContent = 'Export';
    bindTouchAction(exportButton, () => this.exportTravelGlobe(), renderSignal);

    const shareButton = document.createElement('button');
    shareButton.type = 'button';
    shareButton.className = 'control-button secondary-action';
    shareButton.textContent = 'Share';
    bindTouchAction(shareButton, () => this.exportShareSafeJson(), renderSignal);

    const manualLink = document.createElement('a');
    manualLink.className = 'control-button control-link secondary-action';
    manualLink.href = './readme.html';
    manualLink.textContent = '使用手冊';
    bindTouchAction(manualLink, () => {
      window.location.href = manualLink.href;
    }, renderSignal);

    const gpxButton = document.createElement('button');
    gpxButton.type = 'button';
    gpxButton.className = 'control-button secondary-action';
    gpxButton.textContent = 'GPX';
    bindTouchAction(gpxButton, () => this.exportGpx(), renderSignal);

    const kmlButton = document.createElement('button');
    kmlButton.type = 'button';
    kmlButton.className = 'control-button secondary-action';
    kmlButton.textContent = 'KML';
    bindTouchAction(kmlButton, () => this.exportKml(), renderSignal);

    const journalButton = document.createElement('button');
    journalButton.type = 'button';
    journalButton.className = 'control-button secondary-action';
    journalButton.textContent = 'Journal';
    bindTouchAction(journalButton, () => this.exportJournalMarkdown(), renderSignal);

    const packButton = document.createElement('button');
    packButton.type = 'button';
    packButton.className = 'control-button secondary-action';
    packButton.textContent = 'Pack';
    bindTouchAction(packButton, () => {
      productShell.open = true;
      syncDrawerPanelState(productShell);
      this.capability.textContent = '離線資料已內建在目前 Replay build / iOS bundle；不需要另外啟用或取消。';
      this.renderProductPanel();
    }, renderSignal);

    this.fileInput.type = 'file';
    this.fileInput.accept = '.json,.travelglobe,application/json,application/zip';
    this.fileInput.hidden = true;
    this.fileInput.addEventListener('change', () => {
      const file = this.fileInput.files?.[0];
      if (!file) {
        return;
      }
      void this.importJourney(file);
    }, { signal: renderSignal });

    this.mediaInput.type = 'file';
    this.mediaInput.accept = 'image/*';
    this.mediaInput.hidden = true;
    this.mediaInput.addEventListener('change', () => {
      const file = this.mediaInput.files?.[0];
      if (!file) {
        return;
      }
      void this.attachMediaToActiveRecord(file);
    }, { signal: renderSignal });

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
    systemSummary.addEventListener('pointerdown', (event) => event.stopPropagation(), { signal: renderSignal });
    systemSummary.addEventListener('pointerup', toggleSystemDrawer, { signal: renderSignal });
    systemSummary.addEventListener('touchend', toggleSystemDrawer, { passive: false, signal: renderSignal });
    systemSummary.addEventListener('click', toggleSystemDrawer, { signal: renderSignal });
    syncDrawerPanelState(preloadShell.open ? preloadShell : undefined);
    drawerBody.append(actionGrid, this.capability, this.belowMe, preloadShell, productShell, timeline);
    systemDrawer.append(systemSummary, drawerBody);

    controls.append(this.playButton, this.speedSelect, this.scrubber, this.hudStats);
    dock.append(systemDrawer);
    overlay.append(this.cockpitWindow, hud, this.viewRail, dock, this.pilotHud, this.pilotHudToggle, controls);
    this.root.replaceChildren(this.viewport, overlay, this.fileInput, this.mediaInput);

    this.hudTitle.textContent = 'FLIGHT REPLAY';
    this.hudRoute.textContent = `${journey.title} | ${segment.origin.iataCode ?? segment.origin.name} to ${segment.destination.iataCode ?? segment.destination.name}`;
    this.capability.textContent = this.adapter.getLocationCapability().reason ?? 'Standalone browser replay';
    this.renderRegionFilters();
    this.renderTimeline();
    this.renderRecordPreview();
    this.renderPreloadPanel(segment, renderSignal);
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
    this.hudRoute.textContent = `${metrics.routeLabel} | ${localizePhase(metrics.phaseLabel)} | ETA ${metrics.etaLabel}`;
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
    this.renderPilotHud(metrics, sample);

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
    const isPilotView = this.cameraMode === 'pilotView';
    this.root.classList.toggle('is-pilot-view', isPilotView);
    this.root.classList.toggle('is-pilot-hud-off', isPilotView && !this.isPilotHudEnabled);
    this.viewRail.classList.toggle('is-expanded', isPilotView && this.isPilotViewRailExpanded);
    this.viewRail.setAttribute('aria-expanded', String(!isPilotView || this.isPilotViewRailExpanded));
    this.cockpitWindow.setAttribute('aria-hidden', String(!isPilotView));
    this.pilotHud.setAttribute('aria-hidden', String(!isPilotView || !this.isPilotHudEnabled));
    this.pilotHudToggle.hidden = !isPilotView;
    this.pilotHudToggle.textContent = this.isPilotHudEnabled ? 'HUD' : 'HUD off';
    this.pilotHudToggle.setAttribute('aria-pressed', String(this.isPilotHudEnabled));
    for (const button of this.viewRail.querySelectorAll<HTMLButtonElement>('.view-mode-button')) {
      const isActive = button.dataset.mode === this.cameraMode;
      button.classList.toggle('is-active', isActive);
      button.classList.toggle('is-hidden-in-pilot-menu', isPilotView && !this.isPilotViewRailExpanded && !isActive);
      button.setAttribute('aria-pressed', String(isActive));
    }
  }

  private renderPilotHud(metrics: ReturnType<typeof buildFlightHudMetrics>, sample: ReplaySample): void {
    const attitude = buildPilotAttitude(this.segment, sample);
    this.pilotHud.replaceChildren(
      pilotScale('IAS EST', attitude.iasKnots, 'left', attitude.iasTicks),
      pilotScale('ALT', metrics.altitudeFeet, 'right', altitudeTicks(sample.point.altitudeMeters ?? 0)),
      pilotHorizon(attitude),
      pilotHeading(attitude.headingLabel),
      pilotVerticalSpeed(metrics.verticalSpeedLabel)
    );
  }

  private renderPreloadPanel(segment: JourneySegment, renderSignal: AbortSignal): void {
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
    this.aircraftTypeSelect.value = normalizeAircraftSelectValue(stringValue(segment.metadata.aircraftType, ''));

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
      const defaultAircraftType = cached?.aircraftType;
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
      } else {
        this.aircraftTypeSelect.value = '';
      }
      if (!cached && schedule?.defaultAircraftType) {
        details.push(`seed 機型 ${schedule.defaultAircraftType}`);
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
      this.durationInput,
      this.aircraftTypeSelect
    ]) {
      input.addEventListener('input', markPending, { signal: renderSignal });
      input.addEventListener('change', markPending, { signal: renderSignal });
    }
    this.aviationstackApiKeyInput.addEventListener('change', () => {
      writeAviationstackApiKey(this.aviationstackApiKeyInput.value);
      this.preloadStatus.textContent = this.aviationstackApiKeyInput.value.trim()
        ? 'aviationstack API key 已保存在本機。下次套用航線會先嘗試 API，成功後寫入航班快取。'
        : 'aviationstack API key 已清除；會使用本機快取或離線 seed。';
    }, { signal: renderSignal });
    this.flightNumberInput.addEventListener('input', () => {
      if (findScheduleByFlightNumber(this.flightNumberInput.value)) {
        applyKnownFlight();
      }
    }, { signal: renderSignal });
    this.flightNumberInput.addEventListener('change', applyKnownFlight, { signal: renderSignal });

    const apiKeyField = field('aviationstack API key（保存在本機）', this.aviationstackApiKeyInput, {
        placeholder: '保存在本機',
        type: 'password',
        required: false
      });
    apiKeyField.classList.add('preload-api-key-field');
    form.append(
      apiKeyField,
      field('航班號', this.flightNumberInput, { placeholder: 'CI100' }),
      airportField('起飛', this.originInput, airportSuggestions, markPending, {
        placeholder: 'TPE / Taipei',
        signal: renderSignal
      }),
      airportField('抵達', this.destinationInput, airportSuggestions, markPending, {
        placeholder: 'NRT / Tokyo',
        signal: renderSignal
      }),
      field('日期', this.departureDateInput, { type: 'date' }),
      field('時間', this.departureTimeInput, { type: 'time' }),
      field('航程分鐘', this.durationInput, {
        placeholder: '自動',
        type: 'number',
        min: '1',
        step: '1',
        required: false
      }),
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
      aircraftType: this.aircraftTypeSelect.value || undefined
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
      this.renderRecordPanelActions();
      this.recordPreview.replaceChildren();
      return;
    }

    this.renderRecordPanelActions(record);
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
      recordActionButton('新增事件', () => this.showAddTravelRecordForm()),
      recordActionButton('修改紀錄', () => this.showEditActiveTravelRecordForm(record)),
      recordActionButton('分類/時間', () => this.showRecordDetailsForm(record)),
      recordActionButton('附加照片', () => this.mediaInput.click()),
      recordActionButton('載入最新', () => this.requestLatestNativeJourney()),
      recordActionButton('復原上次', () => void this.undoRecordEdit()),
      recordActionButton('隱藏紀錄', () => this.showHideRecordConfirmation(record)),
      recordActionButton('編輯航線摘要', () => this.showFlightSummaryForm())
    );
    content.append(meta, title, subtitle, tags, mediaGallery, actions, this.renderSavedJourneySection('record-history-section'));

    this.recordPreview.replaceChildren(image, content);
  }

  private requestLatestNativeJourney(): void {
    const requested = postNativeMessage('recording.loadLatest', { requestedAt: new Date().toISOString() });
    this.capability.textContent = requested
      ? '已要求 iOS 載入 SQLite 最新旅程；收到 native 回傳後會更新旅遊紀錄。'
      : '瀏覽器模式沒有 iOS SQLite；請用下方本機歷史旅程載入已保存 journey。';
  }

  private renderRecordPanelActions(record?: TravelRecord): void {
    const buttons = [
      recordActionButton('新增', () => this.showAddTravelRecordForm()),
      recordActionButton('載入最新', () => this.requestLatestNativeJourney())
    ];
    if (record) {
      buttons.splice(
        1,
        0,
        recordActionButton('修改', () => this.showEditActiveTravelRecordForm(record)),
        recordActionButton('分類/時間', () => this.showRecordDetailsForm(record)),
        recordActionButton('附加照片', () => this.mediaInput.click()),
        recordActionButton('隱藏/刪除', () => this.showHideRecordConfirmation(record))
      );
    }
    buttons.push(
      recordActionButton('復原', () => void this.undoRecordEdit()),
      recordActionButton('編輯航線', () => this.showFlightSummaryForm())
    );
    this.recordPanelActions.replaceChildren(...buttons);
  }

  private showAddTravelRecordForm(): void {
    if (!this.journey || !this.segment || !this.clock) {
      this.capability.textContent = '目前沒有可新增事件的 active journey。';
      return;
    }
    const form = recordEditorForm('新增旅遊紀錄');
    const title = recordTextInput('標題', '人工打卡');
    const subtitle = recordTextInput('備註', '手動新增');
    form.body.append(title.field, subtitle.field);
    form.submit.textContent = '新增';
    form.submit.addEventListener('click', () => {
      void this.addManualTravelRecord(title.input.value, subtitle.input.value);
    });
    form.cancel.addEventListener('click', () => this.renderRecordPreview());
    this.recordPreview.replaceChildren(form.element);
  }

  private async addManualTravelRecord(titleValue: string, subtitleValue: string): Promise<void> {
    if (!this.journey || !this.segment || !this.clock) {
      return;
    }
    const title = titleValue.trim();
    if (!title) {
      this.capability.textContent = '請先輸入旅遊紀錄標題。';
      return;
    }
    const subtitle = subtitleValue.trim() || '手動新增';
    const point = this.currentDisplayPoint();
    const event: TimelineEvent = {
      id: `event-${this.segment.id}-manual-${Date.now()}`,
      journeyId: this.journey.id,
      segmentId: this.segment.id,
      timestamp: point.timestamp,
      type: 'manualTravelRecord',
      title,
      subtitle,
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
    this.capability.textContent = `已新增旅遊紀錄：${event.title}`;
  }

  private showEditActiveTravelRecordForm(record: TravelRecord): void {
    if (!this.journey) {
      this.capability.textContent = '目前沒有可修改的 active journey。';
      return;
    }
    const form = recordEditorForm('修改旅遊紀錄');
    const title = recordTextInput('標題', record.title);
    const subtitle = recordTextInput('備註/副標題', record.subtitle);
    form.body.append(title.field, subtitle.field);
    form.submit.textContent = '儲存';
    form.submit.addEventListener('click', () => {
      void this.editActiveTravelRecord(record, title.input.value, subtitle.input.value);
    });
    form.cancel.addEventListener('click', () => this.renderRecordPreview());
    this.recordPreview.replaceChildren(form.element);
  }

  private async editActiveTravelRecord(record: TravelRecord, titleValue: string, subtitleValue: string): Promise<void> {
    if (!this.journey) {
      return;
    }
    const title = titleValue.trim();
    if (!title) {
      this.capability.textContent = '旅遊紀錄標題不可空白。';
      return;
    }
    const subtitle = subtitleValue.trim() || record.subtitle;
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
    this.capability.textContent = `已修改旅遊紀錄：${title}`;
  }

  private showHideRecordConfirmation(record: TravelRecord): void {
    if (!this.journey) {
      this.capability.textContent = '目前沒有可隱藏的 active journey。';
      return;
    }
    const form = recordEditorForm('隱藏旅遊紀錄');
    const message = document.createElement('p');
    message.className = 'record-editor-note';
    message.textContent = `隱藏「${record.title}」只會從旅遊紀錄清單移除，原始 GPS 與事件資料仍保留，可用「復原」取回。`;
    form.body.append(message);
    form.submit.textContent = '確認隱藏';
    form.submit.addEventListener('click', () => void this.hideActiveTravelRecord(record));
    form.cancel.addEventListener('click', () => this.renderRecordPreview());
    this.recordPreview.replaceChildren(form.element);
  }

  private async hideActiveTravelRecord(record: TravelRecord): Promise<void> {
    if (!this.journey) {
      return;
    }
    this.pushRecordUndo();
    await this.loadJourney(writeTravelRecordEdit(this.journey, record.id, { hidden: true }));
    this.capability.textContent = `已隱藏旅遊紀錄：${record.title}`;
  }

  private showRecordDetailsForm(record: TravelRecord): void {
    if (!this.journey) {
      this.capability.textContent = '目前沒有可分類的 active journey。';
      return;
    }
    const form = recordEditorForm('分類與時間');
    const regionField = document.createElement('label');
    regionField.className = 'record-editor-field';
    const regionLabel = document.createElement('span');
    regionLabel.textContent = '區域分類';
    const regionSelect = document.createElement('select');
    regionSelect.className = 'record-editor-input';
    regionSelect.replaceChildren(
      ...getTravelRegionOptions().map((option) => {
        const item = document.createElement('option');
        item.value = option.id;
        item.textContent = option.label;
        return item;
      })
    );
    regionSelect.value = record.region;
    regionField.append(regionLabel, regionSelect);
    const date = recordTextInput('日期', toInputDate(record.timestamp), 'date');
    const time = recordTextInput('時間', toInputTime(record.timestamp), 'time');
    form.body.append(regionField, date.field, time.field);
    form.submit.textContent = '套用';
    form.submit.addEventListener('click', () => {
      void this.editRecordDetails(record, regionSelect.value as TravelRegion, date.input.value, time.input.value);
    });
    form.cancel.addEventListener('click', () => this.renderRecordPreview());
    this.recordPreview.replaceChildren(form.element);
  }

  private async editRecordDetails(record: TravelRecord, region: TravelRegion, dateValue: string, timeValue: string): Promise<void> {
    if (!this.journey) {
      return;
    }
    const regionOptions = getTravelRegionOptions();
    const normalizedRegion = regionOptions.some((option) => option.id === region)
      ? region
      : record.region;
    const normalizedTimestamp = timestampFromDateTimeInputs(record.timestamp, dateValue, timeValue);
    this.pushRecordUndo();
    await this.loadJourney(writeTravelRecordEdit(this.journey, record.id, {
      region: normalizedRegion,
      timestamp: normalizedTimestamp,
      note: 'details edit'
    }));
    this.activeRecordId = record.id;
    this.renderTimeline();
    this.renderRecordPreview();
    this.capability.textContent = `已更新 ${record.title} 的分類與時間。`;
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

  private showFlightSummaryForm(): void {
    if (!this.journey || !this.segment) {
      this.capability.textContent = '目前沒有可編輯的航線摘要。';
      return;
    }
    const currentFlight = stringValue(this.segment.metadata.flightNumber, '');
    const currentAircraft = stringValue(this.segment.metadata.aircraftType, DEFAULT_AIRCRAFT_TYPE);
    const form = recordEditorForm('編輯航線摘要');
    const flightNumber = recordTextInput('航班號', currentFlight);
    const aircraftType = recordTextInput('機型', currentAircraft);
    const originIata = recordTextInput('起飛機場 IATA', this.segment.origin.iataCode ?? '');
    const destinationIata = recordTextInput('抵達機場 IATA', this.segment.destination.iataCode ?? '');
    form.body.append(flightNumber.field, aircraftType.field, originIata.field, destinationIata.field);
    form.submit.textContent = '儲存';
    form.submit.addEventListener('click', () => {
      void this.editFlightSummary(
        flightNumber.input.value,
        aircraftType.input.value,
        originIata.input.value,
        destinationIata.input.value
      );
    });
    form.cancel.addEventListener('click', () => this.renderRecordPreview());
    this.recordPreview.replaceChildren(form.element);
  }

  private async editFlightSummary(
    flightNumberValue: string,
    aircraftTypeValue: string,
    originIataValue: string,
    destinationIataValue: string
  ): Promise<void> {
    if (!this.journey || !this.segment) {
      return;
    }
    const currentFlight = stringValue(this.segment.metadata.flightNumber, '');
    const currentAircraft = stringValue(this.segment.metadata.aircraftType, DEFAULT_AIRCRAFT_TYPE);
    const flightNumber = flightNumberValue.trim() || currentFlight;
    const aircraftType = aircraftTypeValue.trim() || currentAircraft;
    const originIata = originIataValue.trim().toUpperCase() || (this.segment.origin.iataCode ?? '');
    const destinationIata = destinationIataValue.trim().toUpperCase() || (this.segment.destination.iataCode ?? '');
    const updatedSegment: JourneySegment = {
      ...this.segment,
      origin: { ...this.segment.origin, iataCode: originIata || this.segment.origin.iataCode },
      destination: { ...this.segment.destination, iataCode: destinationIata || this.segment.destination.iataCode },
      metadata: {
        ...this.segment.metadata,
        flightNumber,
        aircraftType,
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
    this.capability.textContent = `已更新航線摘要：${flightNumber || '未命名航班'}`;
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
    const activeElement = document.activeElement;
    const shouldRestoreAirportSearch =
      activeElement instanceof HTMLInputElement &&
      activeElement.classList.contains('airport-browser-search');
    const airportSearchSelection = shouldRestoreAirportSearch
      ? {
          start: activeElement.selectionStart ?? activeElement.value.length,
          end: activeElement.selectionEnd ?? activeElement.value.length
        }
      : undefined;

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
      ['Offline', `Bundled | ${coreOfflinePacks.length} packs | ${formatBytes(getBundledOfflinePackSizeBytes())}`],
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
    packDescription.textContent = 'Core Global Atlas 與 FlightGear Global Airway Graph 已隨目前 Replay build / iOS bundle 內建；離線時直接可用。';

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
        const row = document.createElement('div');
        row.className = 'pack-control-row';
        const body = document.createElement('span');
        const name = document.createElement('strong');
        name.textContent = `${pack.name} | ${formatBytes(pack.sizeBytes)} | ${pack.dataLayers.length} layers`;
        const description = document.createElement('small');
        description.textContent = offlinePackPurpose(pack.id);
        body.replaceChildren(name, description);
        const status = document.createElement('strong');
        status.className = 'pack-status-pill';
        status.textContent = '已內建';
        row.append(body, status);
        return row;
      })
    );
    packControls.append(packTitle, packList);

    const savedJourneyList = this.renderSavedJourneySection();

    const notificationList = document.createElement('div');
    notificationList.className = 'atlas-section';
    const notificationTitle = document.createElement('strong');
    notificationTitle.textContent = '通知';
    notificationList.append(
      notificationTitle,
      textLine(notifications.length > 0 ? notifications.map((item) => item.body).join(' | ') : '目前沒有需要提醒的事件')
    );
    const airportBrowser = this.renderAirportBrowser();

    this.productPanel.replaceChildren(
      list,
      regionBars,
      airportDetails,
      airportBrowser,
      packControls,
      savedJourneyList,
      notificationList,
      packDescription
    );
    if (shouldRestoreAirportSearch) {
      const searchInput = this.productPanel.querySelector<HTMLInputElement>('.airport-browser-search');
      searchInput?.focus();
      if (airportSearchSelection && searchInput) {
        searchInput.setSelectionRange(airportSearchSelection.start, airportSearchSelection.end);
      }
    }
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

  private renderAirportBrowser(): HTMLElement {
    const section = document.createElement('div');
    section.className = 'atlas-section airport-browser';
    const title = document.createElement('strong');
    title.textContent = '機場資料庫';
    const note = document.createElement('p');
    note.className = 'atlas-section-note';
    note.textContent = '查詢本機離線機場索引、頻率、導航台與航線圖；若要建立航線，請用下方按鈕帶入航班預載欄位。';

    const controls = document.createElement('div');
    controls.className = 'airport-browser-controls';
    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'airport-browser-search';
    search.placeholder = '搜尋 IATA / ICAO / 城市 / 國家';
    search.value = this.airportBrowserQuery;
    const resultList = document.createElement('div');
    resultList.className = 'airport-browser-results';
    const renderResults = (): void => {
      const results = searchAirports(this.airportBrowserQuery, {
        limit: 16,
        scheduledOnly: this.airportBrowserScheduledOnly
      });
      resultList.replaceChildren(
        ...(results.length > 0
          ? results.map((airport) => this.renderAirportBrowserRow(airport, (code) => {
              this.airportBrowserQuery = code;
              search.value = code;
              this.capability.textContent = `${code} 已選取；可設為航班預載的起飛或抵達機場。`;
              renderResults();
            }))
          : [textLine('找不到符合條件的機場')])
      );
    };
    search.addEventListener('input', () => {
      this.airportBrowserQuery = search.value;
      renderResults();
    });
    const scheduledToggle = document.createElement('label');
    scheduledToggle.className = 'airport-browser-toggle';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = this.airportBrowserScheduledOnly;
    checkbox.addEventListener('change', () => {
      this.airportBrowserScheduledOnly = checkbox.checked;
      renderResults();
    });
    const toggleText = document.createElement('span');
    toggleText.textContent = '只看定期航班';
    scheduledToggle.append(checkbox, toggleText);
    controls.append(search, scheduledToggle);

    renderResults();
    section.append(title, note, controls, resultList);
    return section;
  }

  private renderAirportBrowserRow(airport: AirportRecord, selectAirport: (code: string) => void): HTMLElement {
    const row = document.createElement('div');
    row.className = 'airport-browser-row';
    row.tabIndex = 0;
    row.setAttribute('role', 'button');
    const context = airport.iataCode ? findAirportContextByIata(airport.iataCode) : undefined;
    const code = document.createElement('strong');
    code.textContent = airportDisplayCode(airport);
    const body = document.createElement('span');
    body.textContent = `${airport.name} | ${airport.municipality}, ${airport.countryCode}`;
    const detail = document.createElement('small');
    const routeGraph = context?.routeGraph;
    const routeSummary = routeGraph
      ? `${routeGraph.outgoingRoutes} outgoing | top ${routeGraph.topDestinations.slice(0, 4).map((item) => item.code).join(', ')}`
      : 'no route graph';
    detail.textContent = `${airport.type} | runways ${airport.runwayCount} | ${context?.frequencies.length ?? 0} freq | ${context?.navaids.length ?? 0} navaids | ${routeSummary}`;
    const actions = document.createElement('div');
    actions.className = 'airport-browser-actions';
    actions.replaceChildren(
      recordActionButton('設為起飛', () => this.applyAirportToPreload(airport, 'origin')),
      recordActionButton('設為抵達', () => this.applyAirportToPreload(airport, 'destination'))
    );
    row.append(code, body, detail, actions);
    row.addEventListener('click', () => {
      selectAirport(airportDisplayCode(airport));
    });
    row.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') {
        return;
      }
      event.preventDefault();
      selectAirport(airportDisplayCode(airport));
    });
    return row;
  }

  private applyAirportToPreload(airport: AirportRecord, target: 'origin' | 'destination'): void {
    const code = airportDisplayCode(airport);
    if (!code) {
      this.capability.textContent = '此機場沒有可帶入的 IATA / ICAO / ident 代碼。';
      return;
    }
    if (target === 'origin') {
      this.originInput.value = code;
    } else {
      this.destinationInput.value = code;
    }
    const preloadShell = this.preloadPanel.closest('details');
    const productShell = this.productPanel.closest('details');
    if (preloadShell instanceof HTMLDetailsElement) {
      preloadShell.open = true;
    }
    if (productShell instanceof HTMLDetailsElement) {
      productShell.open = false;
    }
    this.preloadStatus.textContent = `${code} 已帶入${target === 'origin' ? '起飛' : '抵達'}欄位，請確認日期時間後按「套用航線」。`;
    this.capability.textContent = `${airport.name} 已帶入航班預載。`;
    this.preloadPanel.scrollIntoView({ block: 'nearest' });
  }

  private renderSavedJourneyRow(summary: SavedJourneySummary): HTMLElement {
    const row = document.createElement('div');
    row.className = 'saved-journey-row';
    const isCurrentJourney = this.journey?.id === summary.id;
    const isConfirmingDelete = this.pendingSavedJourneyDeleteId === summary.id;
    const body = document.createElement('span');
    body.textContent = `${summary.title} | ${summary.status} | ${formatShortDate(summary.startTime)}`;
    const actions = document.createElement('div');
    actions.className = 'saved-journey-actions';
    const loadButton = document.createElement('button');
    loadButton.type = 'button';
    loadButton.className = 'record-action-button';
    loadButton.textContent = '載入';
    bindTouchAction(loadButton, () => void this.loadSavedJourney(summary.id));
    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'record-action-button';
    if (isCurrentJourney) {
      deleteButton.textContent = '使用中';
      deleteButton.disabled = true;
    } else if (isConfirmingDelete) {
      deleteButton.textContent = '確認刪除';
      bindTouchAction(deleteButton, () => void this.deleteSavedJourney(summary.id));
      const cancelButton = document.createElement('button');
      cancelButton.type = 'button';
      cancelButton.className = 'record-action-button';
      cancelButton.textContent = '取消';
      bindTouchAction(cancelButton, () => {
        this.pendingSavedJourneyDeleteId = undefined;
        this.renderProductPanel();
        this.renderRecordPreview();
      });
      actions.append(loadButton, deleteButton, cancelButton);
      row.append(body, actions);
      return row;
    } else {
      deleteButton.textContent = '刪除';
      bindTouchAction(deleteButton, () => {
        this.pendingSavedJourneyDeleteId = summary.id;
        this.capability.textContent = `請再按一次「確認刪除」移除本機歷史旅程：${summary.title}`;
        this.renderProductPanel();
        this.renderRecordPreview();
      });
    }
    actions.append(loadButton, deleteButton);
    row.append(body, actions);
    return row;
  }

  private renderSavedJourneySection(extraClass?: string): HTMLElement {
    const savedJourneyList = document.createElement('div');
    savedJourneyList.className = `atlas-section${extraClass ? ` ${extraClass}` : ''}`;
    const savedTitle = document.createElement('strong');
    savedTitle.textContent = '本機歷史旅程';
    const savedRows = document.createElement('div');
    savedRows.className = 'saved-journey-list';
    savedRows.replaceChildren(
      ...(this.savedJourneys.length > 0
        ? this.savedJourneys.slice(0, 8).map((summary) => this.renderSavedJourneyRow(summary))
        : [textLine('尚無本機歷史旅程')])
    );
    savedJourneyList.append(savedTitle, savedRows);
    return savedJourneyList;
  }

  private async loadSavedJourney(journeyId: string): Promise<void> {
    const journey = await this.adapter.loadJourneyById(journeyId);
    if (!journey) {
      this.capability.textContent = '找不到這筆本機歷史旅程。';
      return;
    }
    this.pendingSavedJourneyDeleteId = undefined;
    await this.loadJourney(journey);
    this.capability.textContent = `已載入本機歷史旅程：${journey.title}`;
  }

  private async deleteSavedJourney(journeyId: string): Promise<void> {
    if (this.journey?.id === journeyId) {
      this.capability.textContent = '目前播放中的 journey 不能直接刪除，請先載入其他旅程。';
      return;
    }
    await this.adapter.deleteJourney(journeyId);
    this.pendingSavedJourneyDeleteId = undefined;
    this.savedJourneys = await this.adapter.listSavedJourneys();
    this.renderProductPanel();
    this.renderRecordPreview();
    this.capability.textContent = '已刪除本機歷史旅程；匯出的 .travelglobe 檔不受影響。';
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
      const completedJourney = completed.webJourneyId === this.journey.id
        ? completeJourneyFromRecording(this.journey, completed)
        : createJourneyFromNativeRecording(completed);
      if (!completedJourney) {
        this.capability.textContent = 'Live GPS recording：GPS 點不足，無法建立 replay journey';
        return;
      }
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

interface PilotAttitude {
  pitchDegrees: number;
  rollDegrees: number;
  headingLabel: string;
  iasKnots: string;
  iasTicks: string[];
}

function pilotScale(label: string, value: string, side: 'left' | 'right', ticks: string[]): HTMLElement {
  const item = document.createElement('div');
  item.className = `pilot-scale pilot-scale-${side}`;
  const title = document.createElement('span');
  title.textContent = label;
  const readout = document.createElement('strong');
  readout.textContent = value.replace(' ft', '');
  const ladder = document.createElement('i');
  ladder.replaceChildren(...ticks.map((tick) => Object.assign(document.createElement('span'), { textContent: tick })));
  item.append(title, ladder, readout);
  return item;
}

function pilotHeading(value: string): HTMLElement {
  const item = document.createElement('div');
  item.className = 'pilot-heading';
  item.textContent = value;
  return item;
}

function pilotVerticalSpeed(value: string): HTMLElement {
  const item = document.createElement('div');
  item.className = 'pilot-vs';
  item.textContent = `VS ${value}`;
  return item;
}

function pilotHorizon(attitude: PilotAttitude): HTMLElement {
  const horizon = document.createElement('div');
  horizon.className = 'pilot-horizon';
  horizon.style.setProperty('--pilot-bank-angle', `${attitude.rollDegrees.toFixed(2)}deg`);
  horizon.style.setProperty('--pilot-pitch-offset', `${(-attitude.pitchDegrees * 5).toFixed(1)}px`);
  horizon.replaceChildren(
    Object.assign(document.createElement('span'), { className: 'pilot-horizon-line' }),
    pilotPitchLadder(),
    Object.assign(document.createElement('span'), { className: 'pilot-reticle' }),
    Object.assign(document.createElement('span'), { className: 'pilot-bank' })
  );
  return horizon;
}

function pilotPitchLadder(): HTMLElement {
  const ladder = document.createElement('span');
  ladder.className = 'pilot-pitch-ladder';
  for (const [index, pitch] of [-10, -5, 0, 5, 10].entries()) {
    const line = document.createElement('span');
    line.className = `pilot-pitch-line${pitch === 0 ? ' is-zero' : ''}`;
    line.style.setProperty('--pitch-index', String(index - 2));
    line.textContent = pitch === 0 ? '' : String(Math.abs(pitch));
    ladder.appendChild(line);
  }
  return ladder;
}

function buildPilotAttitude(segment: JourneySegment | undefined, sample: ReplaySample): PilotAttitude {
  const headingDegrees = Math.round(sample.bearingDegrees);
  const point = sample.point;
  const speedMetersPerSecond = point.speedMetersPerSecond ?? 0;
  const altitudeMeters = point.altitudeMeters ?? 0;
  const adjacent = segment ? adjacentReplayPoints(segment, point.timestamp) : undefined;
  const verticalSpeedMetersPerSecond = adjacent
    ? ((adjacent.next.altitudeMeters ?? altitudeMeters) - (adjacent.previous.altitudeMeters ?? altitudeMeters)) /
      Math.max(1, (Date.parse(adjacent.next.timestamp) - Date.parse(adjacent.previous.timestamp)) / 1000)
    : 0;
  const pitchDegrees = clamp(Math.atan2(verticalSpeedMetersPerSecond, Math.max(52, speedMetersPerSecond)) * 180 / Math.PI, -8, 10);
  const rollDegrees = adjacent
    ? clamp(-angleDeltaDegrees(adjacent.previous.courseDegrees ?? sample.bearingDegrees, adjacent.next.courseDegrees ?? sample.bearingDegrees) * 1.6, -22, 22)
    : 0;
  const ias = estimatedIasKnots(speedMetersPerSecond, altitudeMeters);

  return {
    pitchDegrees,
    rollDegrees,
    headingLabel: `HDG ${headingDegrees.toString().padStart(3, '0')}`,
    iasKnots: Math.round(ias).toString(),
    iasTicks: speedTicks(ias)
  };
}

function adjacentReplayPoints(segment: JourneySegment, timestamp: string): { previous: LocationPoint; next: LocationPoint } | undefined {
  const points = segment.derivedReplayRoute.points;
  if (points.length < 2) {
    return undefined;
  }
  const targetMs = Date.parse(timestamp);
  for (let index = 0; index < points.length - 1; index += 1) {
    if (targetMs <= Date.parse(points[index + 1].timestamp)) {
      return { previous: points[index], next: points[index + 1] };
    }
  }
  return { previous: points[points.length - 2], next: points[points.length - 1] };
}

function estimatedIasKnots(speedMetersPerSecond: number, altitudeMeters: number): number {
  const densityRatio = Math.exp(-Math.max(0, altitudeMeters) / 8500);
  return Math.max(0, speedMetersPerSecond * 1.94384 * Math.sqrt(Math.max(0.24, densityRatio)));
}

function speedTicks(iasKnots: number): string[] {
  const center = Math.round(iasKnots / 10) * 10;
  return [center + 20, center + 10, center, center - 10, center - 20].map((tick) => Math.max(0, tick).toString());
}

function altitudeTicks(altitudeMeters: number): string[] {
  const altitudeHundreds = Math.round(altitudeMeters * 3.28084 / 100);
  return [altitudeHundreds + 4, altitudeHundreds + 2, altitudeHundreds, altitudeHundreds - 2, altitudeHundreds - 4]
    .map((tick) => Math.max(0, tick).toString());
}

function angleDeltaDegrees(fromDegrees: number, toDegrees: number): number {
  return ((((toDegrees - fromDegrees + 540) % 360) - 180) + 360) % 360 - 180;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
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
  bindTouchAction(button, onClick);
  return button;
}

function recordEditorForm(title: string): {
  element: HTMLFormElement;
  body: HTMLDivElement;
  submit: HTMLButtonElement;
  cancel: HTMLButtonElement;
} {
  const form = document.createElement('form');
  form.className = 'record-editor-form';
  const heading = document.createElement('strong');
  heading.textContent = title;
  const body = document.createElement('div');
  body.className = 'record-editor-body';
  const actions = document.createElement('div');
  actions.className = 'record-editor-actions';
  const submit = document.createElement('button');
  submit.type = 'button';
  submit.className = 'record-action-button is-primary';
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'record-action-button';
  cancel.textContent = '取消';
  actions.append(submit, cancel);
  form.addEventListener('submit', (event) => event.preventDefault());
  form.append(heading, body, actions);
  return { element: form, body, submit, cancel };
}

function recordTextInput(
  label: string,
  value: string,
  type: 'text' | 'date' | 'time' = 'text'
): { field: HTMLLabelElement; input: HTMLInputElement } {
  const field = document.createElement('label');
  field.className = 'record-editor-field';
  const text = document.createElement('span');
  text.textContent = label;
  const input = document.createElement('input');
  input.className = 'record-editor-input';
  input.type = type;
  input.value = value;
  field.append(text, input);
  return { field, input };
}

function timestampFromDateTimeInputs(fallbackTimestamp: string, dateValue: string, timeValue: string): string {
  const fallback = new Date(fallbackTimestamp);
  if (!dateValue) {
    return Number.isFinite(fallback.getTime()) ? fallback.toISOString() : new Date().toISOString();
  }
  const time = timeValue || '00:00';
  const parsed = new Date(`${dateValue}T${time}:00`);
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString() : fallbackTimestamp;
}

function offlinePackPurpose(packId: string): string {
  if (packId === 'core-global') {
    return '地圖、國界、城市、機場、跑道、頻率與導航台資料，供 Travel Atlas 與機場查詢離線使用。';
  }
  return '全球航路、航路點與 airway graph，供預載航線和航路查找在離線時使用。';
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
  { value: '', label: '自動' },
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
  if (!normalized) {
    return '';
  }
  const match = aircraftTypeOptions.find((option) => option.value && normalized.includes(option.value));
  return match?.value ?? '';
}

function airportField(
  label: string,
  input: HTMLInputElement,
  airports: AirportRecord[],
  onSelect: () => void,
  options: { placeholder?: string; list?: string; signal?: AbortSignal } = {}
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
      button.addEventListener('touchstart', selectAirport, { passive: false, signal: options.signal });
      button.addEventListener('mousedown', selectAirport, { signal: options.signal });
      button.addEventListener('pointerdown', selectAirport, { signal: options.signal });
      button.addEventListener('click', selectAirport, { signal: options.signal });
      return button;
    });

    menu.replaceChildren(...buttons);
    menu.hidden = buttons.length === 0;
  };

  input.addEventListener('focus', showMatches, { signal: options.signal });
  input.addEventListener('input', showMatches, { signal: options.signal });
  input.addEventListener('blur', () => {
    window.setTimeout(() => {
      closeMenu();
    }, 120);
  }, { signal: options.signal });

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

function bindTouchAction(
  element: HTMLElement,
  action: (event: Event) => void | Promise<void>,
  signal?: AbortSignal
): void {
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
  }, { signal });
  element.addEventListener('pointerup', activate, { signal });
  element.addEventListener('touchend', activate, { passive: false, signal });
  element.addEventListener('click', activate, { signal });
}

function bindDetailsSummaryToggle(
  summary: HTMLElement,
  details: HTMLDetailsElement,
  onToggle?: () => void,
  signal?: AbortSignal
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
  }, { signal });
  summary.addEventListener('pointercancel', () => {
    pointerStart = undefined;
  }, { signal });
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
  }, { signal });
  summary.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
  }, { signal });
  summary.addEventListener('touchend', (event) => {
    event.preventDefault();
    event.stopPropagation();
  }, { passive: false, signal });
  summary.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    toggle();
  }, { signal });
}

function keepDetailsOpenDuringContentGestures(signal: AbortSignal, ...elements: HTMLElement[]): void {
  for (const element of elements) {
    element.addEventListener('pointerdown', (event) => event.stopPropagation(), { signal });
    element.addEventListener('pointerup', (event) => event.stopPropagation(), { signal });
    element.addEventListener('touchstart', (event) => event.stopPropagation(), { passive: true, signal });
    element.addEventListener('touchend', (event) => event.stopPropagation(), { passive: true, signal });
    element.addEventListener('click', (event) => event.stopPropagation(), { signal });
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
