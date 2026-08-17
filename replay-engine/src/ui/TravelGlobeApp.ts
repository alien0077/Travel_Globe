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
import {
  AviationstackFlightPreloadProvider,
  readAviationstackApiKey,
  writeAviationstackApiKey,
  type CachedFlightRecord
} from '../flight-preload/aviationstackProvider';
import type { PreloadFlightRequest } from '../flight-preload/buildPreloadedFlightJourney';
import {
  findAirportByIata,
  findAirportContextByIata,
  getAirportIndexSummary,
  listAirportSuggestions,
  searchAirports,
  type AirportRecord
} from '../flight-preload/airportIndex';
import { findScheduleByFlightNumber, normalizeFlightNumber, normalizeOptionalIata } from '../flight-preload/flightScheduleIndex';
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

type FlightMode = 'live' | 'simulation';

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
  private travelRecords: TravelRecord[] = [];
  private activeRecordId?: string;
  private activeRegion: TravelRegion | 'all' = 'all';
  private liveGps = new LiveGpsTracker();
  private flightMode: FlightMode = 'simulation';
  private initialFlightMode: FlightMode = 'simulation';
  private savedJourneys: SavedJourneySummary[] = [];
  private recordEditUndoStack: Journey[] = [];
  private scheduledNotificationIds = new Set<string>();
  private airportBrowserQuery = '';
  private airportBrowserScheduledOnly = true;
  private pendingSavedJourneyDeleteId?: string;
  private shellEventController?: AbortController;
  private isPilotHudEnabled = true;
  private isPilotViewRailExpanded = false;
  private isReferenceMenuOpen = false;
  private pilotHudPreviousBearingDegrees?: number;
  private pilotHudSmoothedRollDegrees = 0;

  private readonly viewport = document.createElement('section');
  private readonly cockpitWindow = document.createElement('section');
  private readonly gpsButton = document.createElement('button');
  private readonly pilotHudToggle = document.createElement('button');
  private readonly playButton = document.createElement('button');
  private readonly modeSelect = document.createElement('select');
  private readonly speedSelect = document.createElement('select');
  private readonly scrubber = document.createElement('input');
  private readonly progressLabel = document.createElement('span');
  private readonly speedCard = document.createElement('section');
  private readonly speedRange = document.createElement('input');
  private readonly speedLabel = document.createElement('strong');
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
  private readonly referenceTopbar = document.createElement('header');
  private readonly referenceClock = document.createElement('span');
  private readonly referenceSeat = document.createElement('strong');
  private readonly referenceRoute = document.createElement('span');
  private readonly referenceViewTitle = document.createElement('div');
  private readonly referenceSidePanel = document.createElement('aside');
  private readonly referenceBottomNav = document.createElement('nav');
  private readonly referenceMenu = document.createElement('section');
  private readonly referenceMenuButton = document.createElement('button');
  private readonly modalLayer = document.createElement('section');
  private readonly modalCard = document.createElement('section');
  private readonly modalTitle = document.createElement('h2');
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
  private activeModal: 'flight-info' | 'api-key' | 'flight-data' | undefined;
  private playLongPressTimer?: number;
  private suppressNextPlayClick = false;
  private selectedFlightCandidate?: CachedFlightRecord;
  private flightCandidateSelectionRequired = false;
  private flightCandidateLookupGeneration = 0;
  private flightCandidateLookupTimer?: number;
  private activeFlightCandidateSelection?: {
    key: string;
    promise: Promise<CachedFlightRecord | undefined>;
    cancel: () => void;
  };

  constructor(root: HTMLElement, journey: Journey) {
    this.root = root;
    this.adapter = new BrowserRuntimeAdapter(journey);
    const nativeInitialMode = (window as Window & { __TRAVEL_GLOBE_INITIAL_FLIGHT_MODE__?: string }).__TRAVEL_GLOBE_INITIAL_FLIGHT_MODE__;
    this.initialFlightMode = nativeInitialMode === 'live' ? 'live' : 'simulation';
    this.flightMode = this.initialFlightMode;
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
    this.flightMode = this.initialFlightMode;
    this.pilotHudPreviousBearingDegrees = undefined;
    this.pilotHudSmoothedRollDegrees = 0;
    const bounds = getRouteTimeBounds(this.segment);
    this.clock = new ReplayClock(bounds.durationSeconds);
    if (this.flightMode === 'simulation') {
      this.clock.setSpeed(50);
      this.clock.isPlaying = false;
    }
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
    void this.renderLegacyShell;
    this.renderNewFlightShell(journey, segment);
  }

  private renderNewFlightShell(journey: Journey, segment: JourneySegment): void {
    this.shellEventController?.abort();
    this.shellEventController = new AbortController();
    const signal = this.shellEventController.signal;
    this.activeModal = undefined;
    this.root.className = 'app-shell inflight-shell';
    this.root.classList.toggle('is-compact', window.matchMedia('(max-width: 720px)').matches);
    this.viewport.className = 'globe-viewport inflight-viewport';
    this.referenceTopbar.className = 'inflight-topbar';
    this.referenceClock.className = 'inflight-eta';
    this.referenceSeat.className = 'inflight-seat';
    this.referenceRoute.className = 'inflight-route';
    this.referenceViewTitle.className = 'inflight-view-title';
    this.referenceSidePanel.className = 'inflight-flight-info';
    this.referenceSidePanel.hidden = true;
    this.referenceBottomNav.className = 'inflight-bottom-nav';
    this.referenceMenu.hidden = true;
    this.referenceMenuButton.hidden = true;
    this.cockpitWindow.className = 'cockpit-window';
    this.cockpitWindow.replaceChildren(
      Object.assign(document.createElement('div'), { className: 'cockpit-sky' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-terrain' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-clouds' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-horizon-line' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-ceiling' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-left-post' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-right-post' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-glare-shield' })
    );

    const summary = document.createElement('div');
    summary.className = 'inflight-summary';
    summary.append(this.referenceClock, this.referenceSeat, this.referenceRoute);
    const topActions = document.createElement('nav');
    topActions.className = 'inflight-top-actions';
    const addTopButton = (icon: string, label: string, action: () => void, existingButton?: HTMLButtonElement): HTMLButtonElement => {
      const button = existingButton ?? document.createElement('button');
      button.type = 'button';
      button.className = 'inflight-top-button';
      button.replaceChildren();
      button.title = label;
      button.setAttribute('aria-label', label);
      button.append(referenceMenuIcon(icon), Object.assign(document.createElement('span'), { textContent: label }));
      button.addEventListener('click', action, { signal });
      topActions.append(button);
      return button;
    };
    addTopButton('GPS', 'GPS', () => {
      this.setFlightMode(this.flightMode === 'live' ? 'simulation' : 'live', true);
    }, this.gpsButton);
    addTopButton('▶', '播放', () => {
      if (this.suppressNextPlayClick) {
        this.suppressNextPlayClick = false;
        return;
      }
      if (this.flightMode === 'live') return;
      this.clock?.togglePlayback();
      this.syncPlayButton();
    }, this.playButton);
    addTopButton('✈', '航班資訊', () => this.openModal('flight-info'));
    addTopButton('⌁', 'AviationStack API', () => this.openModal('api-key'));
    addTopButton('▣', '輸入航班', () => this.openModal('flight-data'));
    addTopButton('▥', '駕駛艙視角', () => this.activateCameraMode('pilotView'));
    addTopButton('◐', '左方視角', () => this.activateCameraMode('leftWindow'));
    addTopButton('◑', '右方視角', () => this.activateCameraMode('rightWindow'));
    addTopButton('✈', '飛機視角', () => this.activateCameraMode('follow'));
    addTopButton('⌁', '飛行路線', () => this.activateCameraMode('totalRoute'));
    this.referenceTopbar.replaceChildren(summary, topActions);

    this.scrubber.className = 'inflight-progress-range';
    this.scrubber.type = 'range';
    this.scrubber.min = '0';
    this.scrubber.max = '1000';
    this.scrubber.value = '0';
    this.scrubber.addEventListener('input', () => {
      if (this.flightMode === 'live') return;
      this.scene?.prepareForTimelineJump();
      this.clock?.seekPercent(Number(this.scrubber.value) / 1000);
      this.syncProgressDisplay();
    }, { signal });
    this.progressLabel.className = 'inflight-progress-label';
    this.progressLabel.textContent = '0%';
    const progressBar = document.createElement('section');
    progressBar.className = 'inflight-progress-bar';
    progressBar.append(this.progressLabel, this.scrubber);

    this.speedCard.className = 'inflight-speed-card';
    this.speedCard.hidden = true;
    this.speedRange.type = 'range';
    this.speedRange.min = '1';
    this.speedRange.max = '100';
    this.speedRange.step = '1';
    this.speedRange.value = '50';
    this.speedRange.addEventListener('input', () => {
      const value = nearestSimulationSpeed(Number(this.speedRange.value));
      this.speedRange.value = String(value);
      this.speedLabel.textContent = `${value}×`;
      this.speedSelect.value = String(value);
      this.clock?.setSpeed(value);
    }, { signal });
    this.speedLabel.textContent = '50×';
    const closeSpeedCard = document.createElement('button');
    closeSpeedCard.type = 'button';
    closeSpeedCard.className = 'inflight-speed-card-close';
    closeSpeedCard.textContent = '×';
    closeSpeedCard.setAttribute('aria-label', '關閉模擬速度卡片');
    closeSpeedCard.addEventListener('click', () => {
      this.speedCard.hidden = true;
    }, { signal });
    this.speedCard.replaceChildren(
      Object.assign(document.createElement('span'), { textContent: '模擬速度' }),
      this.speedLabel,
      closeSpeedCard,
      this.speedRange
    );
    const startPlayLongPress = (): void => {
      if (this.flightMode === 'live') return;
      window.clearTimeout(this.playLongPressTimer);
      this.playLongPressTimer = window.setTimeout(() => {
        this.suppressNextPlayClick = true;
        this.speedCard.hidden = false;
      }, 550);
    };
    const cancelPlayLongPress = (): void => {
      window.clearTimeout(this.playLongPressTimer);
      this.playLongPressTimer = undefined;
    };
    this.playButton.addEventListener('pointerdown', startPlayLongPress, { signal });
    this.playButton.addEventListener('pointerup', cancelPlayLongPress, { signal });
    this.playButton.addEventListener('pointercancel', cancelPlayLongPress, { signal });
    this.playButton.addEventListener('pointerleave', cancelPlayLongPress, { signal });

    this.referenceViewTitle.textContent = referenceViewLabel(this.cameraMode);
    const bottomButton = (icon: string, label: string, mode: CameraMode): HTMLButtonElement => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'inflight-bottom-button';
      button.dataset.mode = mode;
      button.append(referenceMenuIcon(icon), Object.assign(document.createElement('span'), { textContent: label }));
      button.addEventListener('click', () => this.activateCameraMode(mode), { signal });
      return button;
    };
    this.referenceBottomNav.replaceChildren(
      bottomButton('◉', '瀏覽世界', 'global'),
      bottomButton('✈', '飛機 360°', 'flightPreview')
    );

    this.viewRail.hidden = true;
    this.pilotHudToggle.hidden = true;
    this.pilotHud.className = 'pilot-hud';
    this.pilotHud.hidden = false;
    this.hudTitle.className = 'inflight-hidden-data';
    this.hudRoute.className = 'inflight-hidden-data';
    this.hudStats.className = 'inflight-hidden-data';
    this.hudPoint.className = 'inflight-hidden-data';
    this.geoNotice.className = 'inflight-status';
    this.geoNotice.textContent = '';
    this.belowMe.className = 'inflight-hidden-data';
    this.capability.className = 'inflight-hidden-data';

    this.modalLayer.className = 'inflight-modal-layer';
    this.modalLayer.hidden = true;
    this.modalCard.className = 'inflight-modal-card';
    this.modalTitle.className = 'inflight-modal-title';
    this.modalCard.replaceChildren(this.modalTitle);
    this.modalLayer.replaceChildren(this.modalCard);
    this.modalLayer.addEventListener('click', (event) => {
      if (event.target === this.modalLayer) this.closeModal();
    }, { signal });

    this.fileInput.hidden = true;
    this.mediaInput.hidden = true;
    this.renderPreloadPanel(segment, signal);
    this.syncPlayButton();
    this.syncViewRail();
    this.root.replaceChildren(
      this.viewport,
      this.referenceTopbar,
      progressBar,
      this.speedCard,
      this.referenceViewTitle,
      this.referenceSidePanel,
      this.referenceBottomNav,
      this.cockpitWindow,
      this.pilotHud,
      this.geoNotice,
      this.modalLayer,
      this.fileInput,
      this.mediaInput
    );
    this.renderReferenceFlightCards(buildFlightHudMetrics(
      journey,
      segment,
      sampleReplayAt(segment, 0),
      0
    ));
    void referenceInfoCard;
  }

  private renderLegacyShell(journey: Journey, segment: JourneySegment): void {
    this.shellEventController?.abort();
    this.shellEventController = new AbortController();
    const renderSignal = this.shellEventController.signal;
    const isCompactViewport = window.matchMedia('(max-width: 720px)').matches;
    this.root.className = isCompactViewport ? 'app-shell flight-system-shell is-compact' : 'app-shell flight-system-shell';
    this.root.classList.add('reference-flight-ui');
    this.isReferenceMenuOpen = false;
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
      Object.assign(document.createElement('div'), { className: 'cockpit-right-post' }),
      Object.assign(document.createElement('div'), { className: 'cockpit-glare-shield' })
    );

    this.referenceTopbar.className = 'reference-topbar';
    this.referenceClock.className = 'reference-clock';
    this.referenceSeat.className = 'reference-seat';
    this.referenceRoute.className = 'reference-route';
    this.referenceViewTitle.className = 'reference-view-title';
    const flightSummary = document.createElement('div');
    flightSummary.className = 'reference-flight-summary';
    flightSummary.append(this.referenceClock, this.referenceSeat, this.referenceRoute);
    const headerActions = document.createElement('div');
    headerActions.className = 'reference-header-actions';
    for (const item of [
      ['☾', '夜間模式'], ['♧', '服務'], ['♙', '座位資訊'], ['⌖', '目的地'],
      ['✈', '飛行360°'], ['♡', '收藏'], ['⚙', '設定'], ['⏻', '離開']
    ]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'reference-header-action';
      button.textContent = item[0];
      button.title = item[1];
      button.setAttribute('aria-label', item[1]);
      if (item[1] === '飛行360°') {
        button.addEventListener('click', () => this.activateCameraMode('flightPreview'), { signal: renderSignal });
      } else if (item[1] === '設定') {
        button.addEventListener('click', () => this.setReferenceMenuOpen(true), { signal: renderSignal });
      }
      headerActions.append(button);
    }
    this.referenceTopbar.replaceChildren(flightSummary, headerActions);

    this.referenceSidePanel.className = 'reference-side-panel';
    this.referenceBottomNav.className = 'reference-bottom-nav';
    this.referenceMenu.className = 'reference-menu';
    this.referenceMenu.setAttribute('aria-label', '飛行功能選單');
    this.referenceMenu.hidden = true;
    this.referenceMenuButton.type = 'button';
    this.referenceMenuButton.className = 'reference-menu-button';
    this.referenceMenuButton.textContent = '☰';
    this.referenceMenuButton.setAttribute('aria-label', '開啟飛行功能選單');
    this.referenceMenuButton.setAttribute('aria-expanded', 'false');
    this.referenceMenuButton.addEventListener('click', () => {
      this.setReferenceMenuOpen(!this.isReferenceMenuOpen);
    }, { signal: renderSignal });
    this.referenceBottomNav.append(
      referenceNavButton('◉', '探索世界', () => this.activateCameraMode('global')),
      referenceNavButton('✈', '飛機360°', () => this.activateCameraMode('flightPreview')),
      referenceNavButton('⌖', '目的地指南', () => this.setReferenceMenuOpen(true)),
      this.referenceMenuButton
    );
    this.referenceViewTitle.textContent = '飛機360°';
    this.referenceMenu.replaceChildren(this.renderReferenceMenu(renderSignal));

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
          this.activateCameraMode(mode);
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
    preloadShell.open = true;
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
    productShell.addEventListener('toggle', () => {
      requestAnimationFrame(() => {
        if (productShell.open) {
          this.renderProductPanel();
        }
        syncDrawerPanelState(productShell);
      });
    }, { signal: renderSignal });
    preloadShell.addEventListener('toggle', () => requestAnimationFrame(() => syncDrawerPanelState(preloadShell)), { signal: renderSignal });

    const controls = document.createElement('section');
    controls.className = 'controls';

    this.playButton.type = 'button';
    this.playButton.className = 'control-button';
    this.playButton.addEventListener('click', () => {
      if (this.flightMode === 'live') {
        return;
      }
      this.clock?.togglePlayback();
      this.syncPlayButton();
    }, { signal: renderSignal });

    this.modeSelect.className = 'control-select flight-mode-select';
    this.modeSelect.replaceChildren();
    for (const mode of [
      { value: 'live', label: 'Live GPS' },
      { value: 'simulation', label: '模擬航線' }
    ] as const) {
      const option = document.createElement('option');
      option.value = mode.value;
      option.textContent = mode.label;
      this.modeSelect.appendChild(option);
    }
    this.modeSelect.value = this.flightMode;
    this.modeSelect.addEventListener('change', () => {
      this.setFlightMode(this.modeSelect.value as FlightMode, true);
    }, { signal: renderSignal });

    this.speedSelect.className = 'control-select flight-speed-select';
    this.speedSelect.replaceChildren();
    for (const speed of [1, 5, 20, 50, 100]) {
      const option = document.createElement('option');
      option.value = String(speed);
      option.textContent = `${speed}x`;
      this.speedSelect.appendChild(option);
    }
    this.speedSelect.value = '1';
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
      this.capability.textContent = '離線資料已內建在目前 Flight build / iOS bundle；不需要另外啟用或取消。';
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

    controls.append(this.modeSelect, this.playButton, this.speedSelect, this.scrubber, this.hudStats);
    dock.append(systemDrawer);
    overlay.append(
      this.cockpitWindow,
      this.referenceTopbar,
      this.referenceViewTitle,
      this.referenceSidePanel,
      this.referenceBottomNav,
      this.referenceMenu,
      hud,
      this.viewRail,
      dock,
      this.pilotHud,
      this.pilotHudToggle,
      controls
    );
    this.root.replaceChildren(this.viewport, overlay, this.fileInput, this.mediaInput);

    this.hudTitle.textContent = 'FLIGHT';
    this.hudRoute.textContent = `${journey.title} | ${segment.origin.iataCode ?? segment.origin.name} to ${segment.destination.iataCode ?? segment.destination.name}`;
    this.referenceSeat.textContent = stringValue(segment.metadata.seat, '33B');
    this.referenceRoute.textContent = `${segment.origin.iataCode ?? segment.origin.name}  →  ${segment.destination.iataCode ?? segment.destination.name}`;
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

    if (this.flightMode === 'live') {
      const liveSample = this.liveGps.sample(timeMs, this.segment);
      if (!liveSample) {
        this.syncPlayButton();
        this.geoNotice.textContent = 'Live GPS：等待 iPhone GPS 定位，不會播放模擬航線';
        return;
      }
      this.scene.update(
        liveSample.point,
        liveSample.bearingDegrees,
        this.cameraMode,
        liveSample.routePoints,
        liveAircraftAttitude(liveSample.point, liveSample.turnRateDegreesPerSecond)
      );
      this.scrubber.value = String(
        Math.round(Math.min(1, liveSample.distanceFlownMeters / Math.max(1, this.flightOverlay?.totalDistanceMeters ?? 1)) * 1000)
      );
      this.syncProgressDisplay();
      this.syncPlayButton();
      this.updateHud(
        liveSample,
        liveSample.elapsedSeconds,
        liveSample.status,
        liveSample.turnRateDegreesPerSecond
      );
      return;
    }

    this.clock.update(deltaSeconds);
    const sample = sampleReplayAt(this.segment, this.clock.currentSeconds);
    const actualRoute = getActualRouteThrough(this.segment, this.clock.currentSeconds);
    const simulatedAttitude = buildPilotAttitude(this.segment, sample, undefined, 'route');
    this.scene.update(sample.point, sample.bearingDegrees, this.cameraMode, actualRoute, {
      rollDegrees: simulatedAttitude.rollDegrees
    });

    this.scrubber.value = String(Math.round(this.clock.progressPercent * 1000));
    this.syncProgressDisplay();
    this.syncPlayButton();
    this.updateHud(sample, this.clock.currentSeconds);
  }

  private updateHud(
    sample: ReplaySample,
    elapsedSeconds: number,
    liveStatus?: LiveGpsStatus,
    liveTurnRateDegreesPerSecond?: number
  ): void {
    if (!this.journey || !this.segment || !this.flightOverlay) {
      return;
    }
    const metrics = buildFlightHudMetrics(this.journey, this.segment, sample, elapsedSeconds);
    const elapsedMinutes = Math.floor(elapsedSeconds / 60);
    const elapsedRemainder = Math.floor(elapsedSeconds % 60).toString().padStart(2, '0');
    const deviationMeters = calculateRouteDeviationMeters(sample, this.flightOverlay.plannedRoute);

    this.hudTitle.textContent = metrics.flightNumber;
    this.hudRoute.textContent = `${metrics.routeLabel} | ${localizePhase(metrics.phaseLabel)} | ETA ${metrics.etaLabel}`;
    this.referenceClock.textContent = `${metrics.etaLabel}  抵達目的地的時間`;
    this.referenceViewTitle.textContent = referenceViewLabel(this.cameraMode);
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
    this.renderPilotHud(metrics, sample, liveTurnRateDegreesPerSecond);
    this.renderReferenceFlightCards(metrics);

    this.renderBelowMe(sample);
    if (liveStatus === 'lost') {
      this.geoNotice.textContent = 'Live GPS：GPS signal lost，已停止外推並停在最後可信位置';
    } else if (liveStatus === 'estimated') {
      this.geoNotice.textContent = 'Live GPS：短暫斷訊，畫面以速度與航向暫時推算';
    } else if (liveStatus === 'live') {
      this.geoNotice.textContent = `Live GPS：真實 GPS 軌跡 ${formatDistance(sample.distanceFlownMeters)}`;
    }

    if (!this.isProductPanelOpen()) {
      this.renderProductPanel(sample.point);
    }
  }

  private isProductPanelOpen(): boolean {
    const shell = this.productPanel.closest('details');
    return shell instanceof HTMLDetailsElement && shell.open;
  }

  private syncPlayButton(): void {
    this.modeSelect.value = this.flightMode;
    this.speedSelect.disabled = this.flightMode === 'live';
    this.gpsButton.classList.toggle('is-active', this.flightMode === 'live');
    this.gpsButton.setAttribute('aria-pressed', String(this.flightMode === 'live'));
    this.gpsButton.textContent = this.flightMode === 'live' ? 'GPS ON' : 'GPS';
    if (this.flightMode === 'live') {
      this.playButton.disabled = true;
      this.playButton.textContent = '▶';
      this.scrubber.disabled = true;
      this.speedCard.hidden = true;
      this.syncProgressDisplay();
      return;
    }
    this.playButton.disabled = false;
    this.scrubber.disabled = false;
    this.playButton.textContent = this.clock?.isPlaying ? '❚❚' : '▶';
    this.syncProgressDisplay();
  }

  private syncProgressDisplay(): void {
    const progress = Math.min(100, Math.max(0, Number(this.scrubber.value) / 10));
    this.progressLabel.textContent = `${Math.round(progress)}%`;
    this.progressLabel.setAttribute('aria-label', `飛行進度 ${Math.round(progress)}%`);
  }

  private activateCameraMode(mode: CameraMode): void {
    this.cameraMode = mode;
    this.isPilotViewRailExpanded = false;
    this.scene?.prepareForTimelineJump();
    this.referenceViewTitle.textContent = referenceViewLabel(mode);
    this.setReferenceMenuOpen(false);
    this.syncViewRail();
  }

  private setReferenceMenuOpen(isOpen: boolean): void {
    this.isReferenceMenuOpen = isOpen;
    this.referenceMenu.hidden = !isOpen;
    this.referenceMenuButton.classList.toggle('is-open', isOpen);
    this.referenceMenuButton.setAttribute('aria-expanded', String(isOpen));
  }

  private renderReferenceMenu(renderSignal: AbortSignal): HTMLElement {
    const menuBody = document.createElement('div');
    menuBody.className = 'reference-menu-body';
    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'reference-menu-close';
    closeButton.textContent = '×';
    closeButton.setAttribute('aria-label', '關閉選單');
    closeButton.addEventListener('click', () => this.setReferenceMenuOpen(false), { signal: renderSignal });

    const menuTitle = document.createElement('h2');
    menuTitle.textContent = '飛行功能';
    const actionGrid = document.createElement('div');
    actionGrid.className = 'reference-menu-grid';
    const actions: Array<[string, string, () => void]> = [
      ['ⓘ', '航班資訊', () => this.setReferenceMenuOpen(false)],
      ['◎', '距離', () => this.setReferenceMenuOpen(false)],
      ['⌁', '航線圖', () => this.activateCameraMode('totalRoute')],
      ['▤', '街道圖', () => this.activateCameraMode('overhead')],
      ['⌖', '目的地指南', () => this.setReferenceMenuOpen(false)],
      ['▶', '自動播放', () => {
        if (this.flightMode !== 'live') {
          this.clock?.togglePlayback();
          this.syncPlayButton();
        }
        this.setReferenceMenuOpen(false);
      }],
      ['↻', '變加方向', () => this.activateCameraMode('global')]
    ];
    for (const [icon, label, action] of actions) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'reference-menu-item';
      button.append(referenceMenuIcon(icon), document.createElement('span'));
      button.lastElementChild!.textContent = label;
      button.addEventListener('click', action, { signal: renderSignal });
      actionGrid.append(button);
    }

    const viewTitle = document.createElement('h3');
    viewTitle.textContent = '視角';
    const viewGrid = document.createElement('div');
    viewGrid.className = 'reference-menu-view-grid';
    const views: Array<[CameraMode, string, string]> = [
      ['global', '◉', '瀏覽世界'],
      ['leftWindow', '◐', '左方視角'],
      ['flightPreview', '✈', '飛機360°'],
      ['rightWindow', '◑', '右方視角'],
      ['totalRoute', '⌁', '飛行路線'],
      ['pilotView', '▣', '駕駛艙視角'],
      ['cockpit', '▥', '飛機視角']
    ];
    for (const [mode, icon, label] of views) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'reference-view-item';
      button.dataset.mode = mode;
      button.append(referenceMenuIcon(icon), document.createElement('span'));
      button.lastElementChild!.textContent = label;
      button.addEventListener('click', () => this.activateCameraMode(mode), { signal: renderSignal });
      viewGrid.append(button);
    }

    const advancedButton = document.createElement('button');
    advancedButton.type = 'button';
    advancedButton.className = 'reference-menu-advanced';
    advancedButton.textContent = '更多設定與航班預載';
    advancedButton.addEventListener('click', () => {
      this.setReferenceMenuOpen(false);
      const drawer = this.root.querySelector<HTMLElement>('.system-drawer');
      drawer?.classList.add('is-open');
      drawer?.querySelector<HTMLElement>('.drawer-body')?.removeAttribute('hidden');
    }, { signal: renderSignal });
    menuBody.append(closeButton, menuTitle, actionGrid, viewTitle, viewGrid, advancedButton);
    return menuBody;
  }

  private renderReferenceFlightCards(metrics: ReturnType<typeof buildFlightHudMetrics>): void {
    this.geoNotice.textContent = `${metrics.remainingDistanceLabel} · ${metrics.speedKmh}`;
    // 航班資訊卡只在開啟時建立一次；每幀重建會替換按鈕節點，造成 X/觀看地圖無法穩定點擊。
    void this.activeModal;
  }

  private openModal(kind: 'flight-info' | 'api-key' | 'flight-data'): void {
    this.activeModal = kind;
    this.modalLayer.hidden = false;
    this.modalCard.dataset.kind = kind;
    if (kind === 'flight-info') {
      const sample = this.segment && this.clock
        ? sampleReplayAt(this.segment, this.clock.currentSeconds)
        : this.segment ? sampleReplayAt(this.segment, 0) : undefined;
      if (sample && this.journey && this.segment) {
        this.renderFlightInfoModal(buildFlightHudMetrics(this.journey, this.segment, sample, this.clock?.currentSeconds ?? 0), sample);
      }
      return;
    }
    this.modalTitle.textContent = kind === 'api-key' ? 'AviationStack API' : '輸入航班資料';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'inflight-modal-close';
    close.textContent = '×';
    close.setAttribute('aria-label', '關閉設定卡片');
    close.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.closeModal();
    });
    this.modalCard.replaceChildren(this.modalTitle, close);
    this.modalCard.append(this.preloadPanel);
    this.preloadPanel.dataset.mode = kind;
    this.modalCard.querySelector('.preload-form')?.classList.toggle('api-only', kind === 'api-key');
    const apiField = this.preloadPanel.querySelector('.preload-api-key-field');
    apiField?.classList.toggle('is-hidden-for-flight', kind === 'flight-data');
    const form = this.preloadPanel.querySelector('form');
    form?.querySelector('.preload-submit')?.classList.toggle('is-hidden-for-api', kind === 'api-key');
    (kind === 'api-key' ? this.aviationstackApiKeyInput : this.flightNumberInput).focus();
  }

  private closeModal(): void {
    this.activeModal = undefined;
    this.modalLayer.hidden = true;
    this.cancelActiveFlightCandidateSelection();
    this.modalCard.classList.remove('has-flight-choices');
    this.referenceSidePanel.hidden = true;
  }

  private renderFlightInfoModal(metrics: ReturnType<typeof buildFlightHudMetrics>, sample: ReplaySample): void {
    if (!this.segment) return;
    const value = (label: string, text: string): HTMLElement => {
      const item = document.createElement('div');
      item.className = 'inflight-info-value';
      item.append(Object.assign(document.createElement('span'), { textContent: label }), Object.assign(document.createElement('strong'), { textContent: text }));
      return item;
    };
    this.modalTitle.textContent = '航班資訊';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'inflight-modal-close';
    close.textContent = '×';
    close.setAttribute('aria-label', '關閉航班資訊');
    close.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.closeModal();
    });
    const route = document.createElement('div');
    route.className = 'inflight-airport-route';
    route.append(
      value(this.segment.origin.iataCode ?? this.segment.origin.name, this.segment.origin.name),
      Object.assign(document.createElement('span'), { textContent: '→' }),
      value(this.segment.destination.iataCode ?? this.segment.destination.name, this.segment.destination.name)
    );
    const grid = document.createElement('div');
    grid.className = 'inflight-info-grid';
    grid.append(
      value('高度', metrics.altitudeFeet),
      value('航行方向', metrics.headingDegrees),
      value('經緯度', `${sample.point.latitude.toFixed(4)}° N ${sample.point.longitude.toFixed(4)}° E`),
      value('飛行速度', metrics.speedKmh),
      value(`剩餘距離 ${this.segment.destination.iataCode ?? this.segment.destination.name}`, metrics.remainingDistanceLabel),
      value('外氣溫度', '—')
    );
    const mapButton = document.createElement('button');
    mapButton.type = 'button';
    mapButton.className = 'inflight-gold-button';
    mapButton.textContent = '觀看地圖';
    mapButton.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.closeModal();
      this.activateCameraMode('global');
    });
    this.modalCard.replaceChildren(this.modalTitle, close, route, grid, value('抵達目的地時間', metrics.etaLabel), mapButton);
  }

  private setFlightMode(mode: FlightMode, notifyNative: boolean): void {
    if (this.flightMode === mode && !notifyNative) {
      this.syncPlayButton();
      return;
    }
    this.flightMode = mode;
    this.pilotHudPreviousBearingDegrees = undefined;
    this.pilotHudSmoothedRollDegrees = 0;

    if (mode === 'live') {
      this.clock && (this.clock.isPlaying = false);
      this.scrubber.disabled = true;
      this.speedCard.hidden = true;
      this.capability.textContent = 'Live GPS：等待 iPhone GPS 定位';
    } else {
      if (this.clock) {
        this.clock.currentSeconds = 0;
        this.clock.setSpeed(50);
        this.clock.isPlaying = false;
      }
      this.speedSelect.value = '50';
      this.speedRange.value = '50';
      this.speedLabel.textContent = '50×';
      this.scrubber.disabled = false;
      this.capability.textContent = '模擬航線：使用目前航線資料';
    }

    this.syncPlayButton();
    if (notifyNative) {
      postNativeMessage('flight.mode.set', { mode });
    }
  }

  private syncViewRail(): void {
    const isPilotView = this.cameraMode === 'pilotView';
    const isWindowView = this.cameraMode === 'leftWindow' || this.cameraMode === 'rightWindow';
    this.root.classList.toggle('is-pilot-view', isPilotView);
    this.root.classList.toggle('is-window-view', isWindowView);
    this.root.classList.toggle('is-left-window', this.cameraMode === 'leftWindow');
    this.root.classList.toggle('is-right-window', this.cameraMode === 'rightWindow');
    this.root.classList.toggle('is-pilot-hud-off', isPilotView && !this.isPilotHudEnabled);
    this.viewRail.classList.toggle('is-expanded', isPilotView && this.isPilotViewRailExpanded);
    this.viewRail.setAttribute('aria-expanded', String(!isPilotView || this.isPilotViewRailExpanded));
    this.cockpitWindow.setAttribute('aria-hidden', String(!isPilotView && !isWindowView));
    this.pilotHud.setAttribute('aria-hidden', String(!isPilotView || !this.isPilotHudEnabled));
    this.pilotHudToggle.hidden = !isPilotView;
    this.pilotHud.hidden = !isPilotView || !this.isPilotHudEnabled;
    this.pilotHudToggle.textContent = this.isPilotHudEnabled ? 'HUD' : 'HUD off';
    this.pilotHudToggle.setAttribute('aria-pressed', String(this.isPilotHudEnabled));
    for (const button of this.viewRail.querySelectorAll<HTMLButtonElement>('.view-mode-button')) {
      const isActive = button.dataset.mode === this.cameraMode;
      button.classList.toggle('is-active', isActive);
      button.classList.toggle('is-hidden-in-pilot-menu', isPilotView && !this.isPilotViewRailExpanded && !isActive);
      button.setAttribute('aria-pressed', String(isActive));
    }
  }

  private renderPilotHud(
    metrics: ReturnType<typeof buildFlightHudMetrics>,
    sample: ReplaySample,
    liveTurnRateDegreesPerSecond?: number
  ): void {
    const attitude = buildPilotAttitude(
      this.segment,
      sample,
      this.flightMode === 'live' ? this.pilotHudPreviousBearingDegrees : undefined,
      this.flightMode === 'live' ? 'live' : 'route',
      liveTurnRateDegreesPerSecond
    );
    this.pilotHudSmoothedRollDegrees += (attitude.rollDegrees - this.pilotHudSmoothedRollDegrees) * 0.12;
    if (Math.abs(this.pilotHudSmoothedRollDegrees) < 0.8) {
      this.pilotHudSmoothedRollDegrees = 0;
    }
    attitude.rollDegrees = this.pilotHudSmoothedRollDegrees;
    this.pilotHudPreviousBearingDegrees = sample.bearingDegrees;
    this.pilotHud.replaceChildren(
      pilotScale('SPD', attitude.iasKnots, 'kt', 'left', attitude.iasTicks),
      pilotScale('ALT', metrics.altitudeFeet, 'ft', 'right', altitudeTicks(sample.point.altitudeMeters ?? 0)),
      pilotHorizon(attitude),
      pilotHeading(attitude.headingLabel),
      pilotVerticalSpeed(metrics.verticalSpeedLabel)
    );
  }

  private renderPreloadPanel(segment: JourneySegment, renderSignal: AbortSignal): void {
    if (this.flightCandidateLookupTimer !== undefined) {
      window.clearTimeout(this.flightCandidateLookupTimer);
      this.flightCandidateLookupTimer = undefined;
    }
    this.cancelActiveFlightCandidateSelection();
    this.selectedFlightCandidate = undefined;
    this.flightCandidateSelectionRequired = false;
    this.flightCandidateLookupGeneration += 1;
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
      this.cancelActiveFlightCandidateSelection();
      this.selectedFlightCandidate = undefined;
      this.flightCandidateLookupGeneration += 1;
      this.preloadStatus.textContent = '已修改設定，請按「套用航線」更新地球、時間與航跡。';
    };
    const applyKnownFlight = (): void => {
      const schedule = findScheduleByFlightNumber(this.flightNumberInput.value);
      const cachedFlights = this.flightPreloadProvider.getCachedFlights(this.flightNumberInput.value);
      if (cachedFlights.length > 1) {
        this.flightCandidateSelectionRequired = true;
        clearFlightCandidateForm(this.originInput, this.destinationInput, this.departureTimeInput, this.durationInput, this.aircraftTypeSelect);
        this.preloadStatus.textContent = `${this.flightNumberInput.value.trim().toUpperCase()} 已有 ${cachedFlights.length} 個航段快取，請選擇實際航段後再套用。`;
        return;
      }
      this.flightCandidateSelectionRequired = false;
      const cached = cachedFlights[0];
      if (!schedule && !cached) {
        this.originInput.value = '';
        this.destinationInput.value = '';
        this.departureTimeInput.value = '';
        this.durationInput.value = '';
        this.aircraftTypeSelect.value = '';
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
    const scheduleFlightCandidateLookup = (): void => {
      if (this.flightCandidateLookupTimer !== undefined) {
        window.clearTimeout(this.flightCandidateLookupTimer);
        this.flightCandidateLookupTimer = undefined;
      }
      if (normalizeFlightNumber(this.flightNumberInput.value).length < 3) {
        return;
      }
      this.flightCandidateLookupTimer = window.setTimeout(() => {
        void this.promptFlightCandidateSelection();
      }, 350);
    };
    this.aviationstackApiKeyInput.addEventListener('change', () => {
      writeAviationstackApiKey(this.aviationstackApiKeyInput.value);
      this.preloadStatus.textContent = this.aviationstackApiKeyInput.value.trim()
        ? 'aviationstack API key 已保存在本機。下次套用航線會先嘗試 API，成功後寫入航班快取。'
        : 'aviationstack API key 已清除；會使用本機快取或離線 seed。';
      if (this.aviationstackApiKeyInput.value.trim()) {
        scheduleFlightCandidateLookup();
      }
    }, { signal: renderSignal });
    this.flightNumberInput.addEventListener('input', () => {
      if (findScheduleByFlightNumber(this.flightNumberInput.value)) {
        applyKnownFlight();
      }
      scheduleFlightCandidateLookup();
    }, { signal: renderSignal });
    this.flightNumberInput.addEventListener('change', () => {
      applyKnownFlight();
      scheduleFlightCandidateLookup();
    }, { signal: renderSignal });

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
    const request = this.currentPreloadRequest();
    writeAviationstackApiKey(this.aviationstackApiKeyInput.value);

    try {
      this.preloadStatus.textContent = '正在查詢航班資料...';
      const selectedRecord = this.selectedFlightCandidate && candidateMatchesRequest(this.selectedFlightCandidate, request)
        ? this.selectedFlightCandidate
        : undefined;
      const candidates = selectedRecord ? [selectedRecord] : await this.flightPreloadProvider.lookupFlightCandidates(request);
      const chosenRecord = selectedRecord ?? (candidates.length > 1
        ? await this.chooseFlightCandidate(candidates)
        : candidates[0]);
      if (chosenRecord && !selectedRecord) {
        this.selectedFlightCandidate = chosenRecord;
        this.applyFlightCandidateToForm(chosenRecord);
      }
      if (candidates.length > 1 && !chosenRecord) {
        this.preloadStatus.textContent = '已取消航段選擇。';
        return;
      }
      if (this.flightCandidateSelectionRequired && !chosenRecord) {
        this.preloadStatus.textContent = '此航班有多個航段，請先選擇要套用的航段。';
        return;
      }

      this.preloadStatus.textContent = '正在建立預載航線...';
      const selectedRequest = chosenRecord
        ? preloadRequestForCandidate(request, chosenRecord)
        : request;
      const result = await this.flightPreloadProvider.preloadFlight(selectedRequest, chosenRecord);
      await this.loadJourney(result.journey);
      const sentToNative = postNativeMessage('flightPlan.apply', flightPlanPayloadFromJourney(result.journey));
      const message = `${result.journey.title} 已預載。${result.warnings[0] ?? ''}`;
      const nativeHint = sentToNative
        ? '已送至 iOS，這條航線可直接在 Flight 頁面切換模擬或 Live GPS。'
        : '瀏覽器模式會預載航線；Live GPS 請在 iOS Flight 頁面使用。';
      this.preloadStatus.textContent = `${message} ${nativeHint}`;
      this.capability.textContent = `${message} ${nativeHint}`;
    } catch (error) {
      this.preloadStatus.textContent = error instanceof Error ? error.message : '航班預載失敗';
    }
  }

  private currentPreloadRequest(): PreloadFlightRequest {
    return {
      flightNumber: this.flightNumberInput.value,
      originIata: this.originInput.value,
      destinationIata: this.destinationInput.value,
      departureDate: this.departureDateInput.value,
      departureTime: this.departureTimeInput.value,
      durationMinutes: Number(this.durationInput.value) || undefined,
      aircraftType: this.aircraftTypeSelect.value || undefined
    };
  }

  private async promptFlightCandidateSelection(): Promise<void> {
    const request = this.currentPreloadRequest();
    const generation = ++this.flightCandidateLookupGeneration;
    const cachedFlights = this.flightPreloadProvider.getCachedFlights(request.flightNumber);
    if (!readAviationstackApiKey() && cachedFlights.length <= 1) {
      this.preloadStatus.textContent = '尚未設定 aviationstack API key；請在有網路時輸入 API key，才能查詢並選擇多航段。';
      return;
    }
    let candidates: CachedFlightRecord[];
    try {
      candidates = await this.flightPreloadProvider.lookupFlightCandidates(request);
    } catch {
      this.preloadStatus.textContent = '航班查詢失敗；請確認網路與 aviationstack API key。';
      return;
    }
    if (generation !== this.flightCandidateLookupGeneration) {
      return;
    }
    if (candidates.length <= 1) {
      this.preloadStatus.textContent = candidates.length === 1
        ? '目前只查到一個航段；請確認航班日期或稍後重試。'
        : '目前查不到此航班資料；請確認航班號、網路與 API key。';
      return;
    }

    this.flightCandidateSelectionRequired = true;
    clearFlightCandidateForm(this.originInput, this.destinationInput, this.departureTimeInput, this.durationInput, this.aircraftTypeSelect);
    const selected = await this.chooseFlightCandidate(candidates);
    if (generation !== this.flightCandidateLookupGeneration || !selected) {
      return;
    }
    this.selectedFlightCandidate = selected;
    this.flightCandidateSelectionRequired = false;
    this.applyFlightCandidateToForm(selected);
    this.preloadStatus.textContent = `${selected.flightNumber} 已選擇 ${selected.originIata} → ${selected.destinationIata}；請按「套用航線」建立航跡。`;
  }

  private applyFlightCandidateToForm(record: CachedFlightRecord): void {
    this.originInput.value = record.originIata;
    this.destinationInput.value = record.destinationIata;
    if (record.flightDate) {
      this.departureDateInput.value = record.flightDate;
    }
    if (record.departureTime) {
      this.departureTimeInput.value = record.departureTime;
    }
    if (record.durationMinutes) {
      this.durationInput.value = String(record.durationMinutes);
    }
    this.aircraftTypeSelect.value = normalizeAircraftSelectValue(record.aircraftType ?? '');
  }

  private chooseFlightCandidate(candidates: CachedFlightRecord[]): Promise<CachedFlightRecord | undefined> {
    const key = candidates.map((record) => [
      record.flightNumber,
      record.originIata,
      record.destinationIata,
      record.flightDate,
      record.departureScheduled,
      record.arrivalScheduled
    ].join('|')).join('||');
    if (this.activeFlightCandidateSelection?.key === key) {
      return this.activeFlightCandidateSelection.promise;
    }
    this.cancelActiveFlightCandidateSelection();

    const panel = document.createElement('div');
    panel.className = 'preload-flight-choices';
    this.modalCard.classList.add('has-flight-choices');

    const title = document.createElement('strong');
    title.textContent = `查到 ${candidates.length} 個相同航班號的航段，請選擇`;
    panel.append(title);

    const list = document.createElement('div');
    list.className = 'preload-flight-choice-list';
    panel.append(list);
    this.preloadPanel.insertBefore(panel, this.preloadStatus);

    let resolveSelection: (record: CachedFlightRecord | undefined) => void = () => undefined;
    let resolved = false;
    const promise = new Promise<CachedFlightRecord | undefined>((resolve) => {
      resolveSelection = resolve;
    });
    const finish = (record: CachedFlightRecord | undefined): void => {
      if (resolved) return;
      resolved = true;
      panel.remove();
      this.modalCard.classList.remove('has-flight-choices');
      if (this.activeFlightCandidateSelection?.promise === promise) {
        this.activeFlightCandidateSelection = undefined;
      }
      resolveSelection(record);
    };
    this.activeFlightCandidateSelection = {
      key,
      promise,
      cancel: () => finish(undefined)
    };

    candidates.forEach((record, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'preload-flight-choice';
      button.addEventListener('click', () => finish(record));

      const route = document.createElement('strong');
      route.textContent = `${record.flightNumber}｜${airportLabel(record.originIata)} → ${airportLabel(record.destinationIata)}`;
      const timing = document.createElement('span');
      timing.textContent = `${record.flightDate ?? '日期未提供'}${formatScheduledTime(record.departureScheduled)}${formatScheduledTime(record.arrivalScheduled, ' → ')}`;
      const leg = document.createElement('small');
      leg.textContent = `第 ${index + 1} 段${record.aircraftType ? ` · ${record.aircraftType}` : ''}`;
      button.append(route, timing, leg);
      button.setAttribute('aria-label', `${route.textContent} ${timing.textContent} ${leg.textContent}`);
      list.append(button);
    });

    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'preload-flight-choice-cancel';
    cancel.textContent = '取消';
    cancel.addEventListener('click', () => finish(undefined));
    panel.append(cancel);
    return promise;
  }

  private cancelActiveFlightCandidateSelection(): void {
    this.activeFlightCandidateSelection?.cancel();
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
    const liveSample = this.flightMode === 'live' ? this.liveGps.sample(performance.now(), this.segment) : undefined;
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
    packDescription.textContent = 'Core Global Atlas 與 FlightGear Global Airway Graph 已隨目前 Flight build / iOS bundle 內建；離線時直接可用。';

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
      const hasQuery = this.airportBrowserQuery.trim().length > 0;
      resultList.hidden = !hasQuery;
      if (!hasQuery) {
        resultList.replaceChildren();
        return;
      }
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
    const mode = parseNativePayload<{ mode?: string }>(nativeMessage, 'flight.mode');
    if (mode?.mode === 'live' || mode?.mode === 'simulation') {
      this.setFlightMode(mode.mode, false);
      return;
    }
    const authorization = parseNativePayload<{ status?: string }>(nativeMessage, 'location.authorization');
    if (authorization) {
      const status = authorization.status ?? 'unknown';
      this.capability.textContent = status === 'authorizedAlways' || status === 'authorizedWhenInUse'
        ? 'Live GPS：已取得定位權限，等待第一個 iPhone GPS 座標'
        : status === 'denied' || status === 'restricted'
          ? 'Live GPS：定位權限被拒絕，請到設定允許 Travel Globe 定位'
          : `Live GPS：定位權限狀態 ${status}`;
      return;
    }
    const completed = parseNativePayload<NativeRecordingPayload>(nativeMessage, 'recording.completed');
    if (completed) {
      const completedJourney = completed.webJourneyId === this.journey.id
        ? completeJourneyFromRecording(this.journey, completed)
        : createJourneyFromNativeRecording(completed);
      if (!completedJourney) {
        this.capability.textContent = 'Live GPS：GPS 點不足，無法更新旅程';
        return;
      }
      void this.loadJourney(completedJourney);
      this.capability.textContent = 'Live GPS：已完成並寫入旅遊紀錄';
      return;
    }
    const started = parseNativePayload<NativeRecordingPayload>(nativeMessage, 'recording.started');
    if (started) {
      this.capability.textContent = `Live GPS：${started.flightNumber ?? 'GPS'} 已開始`;
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
    this.liveGps.ingest(point, performance.now());
    if (this.flightMode === 'live') {
      this.capability.textContent = 'Live GPS：已接收 iPhone CoreLocation 真實定位';
    }
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

function referenceNavButton(icon: string, label: string, action: () => void): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'reference-nav-button';
  button.append(referenceMenuIcon(icon), document.createElement('span'));
  button.lastElementChild!.textContent = label;
  button.addEventListener('click', action);
  return button;
}

function referenceMenuIcon(icon: string): HTMLElement {
  const element = document.createElement('span');
  element.className = 'reference-menu-icon';
  element.textContent = icon;
  element.setAttribute('aria-hidden', 'true');
  return element;
}

function referenceInfoCard(title: string, value: string, icon: string): HTMLElement {
  const card = document.createElement('article');
  card.className = 'reference-info-card';
  card.append(referenceMenuIcon(icon), document.createElement('div'));
  const body = card.lastElementChild!;
  const heading = document.createElement('span');
  heading.textContent = title;
  const detail = document.createElement('strong');
  detail.textContent = value;
  body.append(heading, detail);
  return card;
}

function referenceViewLabel(mode: CameraMode): string {
  const labels: Partial<Record<CameraMode, string>> = {
    global: '瀏覽世界',
    flightPreview: '飛機360°',
    totalRoute: '飛行路線',
    midFlight: '飛行路線',
    overhead: '街道圖',
    commandCenter: '塔台視角',
    pilotView: '駕駛艙視角',
    cockpit: '飛機視角',
    leftWindow: '左方視角',
    rightWindow: '右方視角',
    tail: '飛機視角',
    topDown: '街道圖',
    follow: '飛機360°',
    orbit: '飛機360°'
  };
  return labels[mode] ?? '飛行畫面';
}

interface PilotAttitude {
  pitchDegrees: number;
  rollDegrees: number;
  headingLabel: string;
  iasKnots: string;
  iasTicks: string[];
}

function pilotScale(label: string, value: string, unit: string, side: 'left' | 'right', ticks: string[]): HTMLElement {
  const item = document.createElement('div');
  item.className = `pilot-scale pilot-scale-${side}`;
  const title = document.createElement('span');
  title.textContent = `${label} ${unit}`;
  const readout = document.createElement('strong');
  readout.textContent = `${value.replace(` ${unit}`, '')} ${unit}`;
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
  horizon.style.setProperty('--pilot-pitch-offset', `${(-attitude.pitchDegrees * 7).toFixed(1)}px`);
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

function buildPilotAttitude(
  segment: JourneySegment | undefined,
  sample: ReplaySample,
  previousLiveBearingDegrees?: number,
  turnSource: 'route' | 'live' = 'route',
  liveTurnRateDegreesPerSecond?: number
): PilotAttitude {
  const headingDegrees = Math.round(sample.bearingDegrees);
  const point = sample.point;
  const speedMetersPerSecond = point.speedMetersPerSecond ?? 0;
  const altitudeMeters = point.altitudeMeters ?? 0;
  const adjacent = segment ? adjacentReplayPoints(segment, point.timestamp) : undefined;
  const verticalSpeedMetersPerSecond = adjacent
    ? ((adjacent.next.altitudeMeters ?? altitudeMeters) - (adjacent.previous.altitudeMeters ?? altitudeMeters)) /
      Math.max(1, (Date.parse(adjacent.next.timestamp) - Date.parse(adjacent.previous.timestamp)) / 1000)
    : 0;
  const pitchDegrees = pitchAngleForVerticalSpeed(verticalSpeedMetersPerSecond, speedMetersPerSecond);
  const liveTurnDegrees = previousLiveBearingDegrees === undefined
    ? 0
    : angleDeltaDegrees(previousLiveBearingDegrees, sample.bearingDegrees);
  const routeTurnRateDegreesPerMinute = adjacent
    ? routeTurnRateForReplayWindow(adjacent, sample.bearingDegrees)
    : 0;
  const rollDegrees = turnSource === 'live'
    ? liveTurnRateDegreesPerSecond === undefined
      ? liveBankAngleForTurn(liveTurnDegrees)
      : liveBankAngleForTurnRate(liveTurnRateDegreesPerSecond, speedMetersPerSecond)
    : routeBankAngleForTurnRate(routeTurnRateDegreesPerMinute);
  const ias = estimatedIasKnots(speedMetersPerSecond, altitudeMeters);

  return {
    pitchDegrees,
    rollDegrees,
    headingLabel: `HDG ${headingDegrees.toString().padStart(3, '0')}`,
    iasKnots: Math.round(ias).toString(),
    iasTicks: speedTicks(ias)
  };
}

function liveAircraftAttitude(
  point: LocationPoint,
  turnRateDegreesPerSecond: number
): { rollDegrees: number } {
  return {
    rollDegrees: liveBankAngleForTurnRate(turnRateDegreesPerSecond, point.speedMetersPerSecond ?? 0)
  };
}

function routeBankAngleForTurnRate(turnRateDegreesPerMinute: number): number {
  const deadbandDegreesPerMinute = 1.2;
  if (Math.abs(turnRateDegreesPerMinute) < deadbandDegreesPerMinute) {
    return 0;
  }
  return clamp(-turnRateDegreesPerMinute * 3.1, -8, 8);
}

function liveBankAngleForTurn(turnDegrees: number): number {
  const deadbandDegrees = 8;
  if (Math.abs(turnDegrees) < deadbandDegrees) {
    return 0;
  }
  return clamp(-turnDegrees * 0.32, -10, 10);
}

function liveBankAngleForTurnRate(turnRateDegreesPerSecond: number, speedMetersPerSecond: number): number {
  if (Math.abs(turnRateDegreesPerSecond) < 0.05 || speedMetersPerSecond < 8) {
    return 0;
  }
  const lateralAcceleration = speedMetersPerSecond * (turnRateDegreesPerSecond * Math.PI / 180);
  const bankDegrees = Math.atan2(lateralAcceleration, 9.80665) * 180 / Math.PI;
  return clamp(-bankDegrees, -18, 18);
}

function pitchAngleForVerticalSpeed(verticalSpeedMetersPerSecond: number, speedMetersPerSecond: number): number {
  if (Math.abs(verticalSpeedMetersPerSecond) < 0.28) {
    return 0;
  }
  const referenceSpeed = Math.max(30, speedMetersPerSecond * 0.56);
  return clamp(Math.atan2(verticalSpeedMetersPerSecond, referenceSpeed) * 180 / Math.PI, -10, 12);
}

function routeTurnRateForReplayWindow(
  adjacent: { previous: LocationPoint; next: LocationPoint },
  fallbackBearingDegrees: number
): number {
  const durationMinutes = Math.max(
    1 / 60,
    (Date.parse(adjacent.next.timestamp) - Date.parse(adjacent.previous.timestamp)) / 60000
  );
  const turnDegrees = angleDeltaDegrees(
    adjacent.previous.courseDegrees ?? fallbackBearingDegrees,
    adjacent.next.courseDegrees ?? fallbackBearingDegrees
  );
  return turnDegrees / durationMinutes;
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
  input.setAttribute('aria-label', label);
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
  select.setAttribute('aria-label', label);
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

function airportLabel(iata: string): string {
  const airport = findAirportByIata(iata);
  return airport ? `${iata} ${airport.municipality}` : iata;
}

function formatScheduledTime(value?: string, separator = ' '): string {
  if (!value) {
    return '';
  }
  const timestamp = new Date(value);
  if (!Number.isFinite(timestamp.getTime())) {
    return `${separator}${value}`;
  }
  return `${separator}${timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

function candidateMatchesRequest(record: CachedFlightRecord, request: PreloadFlightRequest): boolean {
  const requestedFlightNumber = normalizeFlightNumber(request.flightNumber);
  const requestedOrigin = normalizeOptionalIata(request.originIata);
  const requestedDestination = normalizeOptionalIata(request.destinationIata);
  return normalizeFlightNumber(record.flightNumber) === requestedFlightNumber
    && (!record.flightDate || !request.departureDate || record.flightDate === request.departureDate)
    && (!requestedOrigin || record.originIata === requestedOrigin)
    && (!requestedDestination || record.destinationIata === requestedDestination);
}

export function preloadRequestForCandidate(
  request: PreloadFlightRequest,
  candidate: CachedFlightRecord
): PreloadFlightRequest {
  return {
    ...request,
    originIata: candidate.originIata,
    destinationIata: candidate.destinationIata,
    departureDate: candidate.flightDate ?? request.departureDate,
    departureTime: candidate.departureTime ?? request.departureTime,
    durationMinutes: candidate.durationMinutes ?? request.durationMinutes,
    aircraftType: candidate.aircraftType ?? request.aircraftType,
    airlineName: candidate.airlineName,
    source: 'aviationstack'
  };
}

function clearFlightCandidateForm(
  originInput: HTMLInputElement,
  destinationInput: HTMLInputElement,
  departureTimeInput: HTMLInputElement,
  durationInput: HTMLInputElement,
  aircraftTypeSelect: HTMLSelectElement
): void {
  originInput.value = '';
  destinationInput.value = '';
  departureTimeInput.value = '';
  durationInput.value = '';
  aircraftTypeSelect.value = '';
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

function nearestSimulationSpeed(value: number): number {
  const speeds = [1, 5, 20, 50, 100];
  return speeds.reduce((nearest, speed) =>
    Math.abs(speed - value) < Math.abs(nearest - value) ? speed : nearest
  );
}
