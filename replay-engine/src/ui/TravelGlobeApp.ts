import type { CameraMode } from '../camera/CameraController';
import { BrowserRuntimeAdapter } from '../bridge/RuntimeAdapter';
import type { Journey, JourneySegment } from '../data/types';
import { getPrimaryFlightSegment } from '../data/types';
import { createGpx, createKml } from '../export/geoExport';
import { downloadBlob } from '../export/travelglobePackage';
import {
  buildFlightHudMetrics,
  buildFlightOverlay,
  calculateRouteDeviationMeters,
  getActualRouteThrough,
  landmarksForSegment,
  summarizeBelowMe,
  type FlightOverlay
} from '../flight/flightAnalytics';
import { OfflineAirportFlightPreloadProvider } from '../flight/flightPlanProvider';
import type { PreloadFlightRequest } from '../flight-preload/buildPreloadedFlightJourney';
import {
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
import { DEFAULT_AIRCRAFT_TYPE } from '../models/aircraftModelLibrary';
import { evaluateNotifications } from '../notifications/notificationRules';
import {
  coreOfflinePacks,
  describeInstalledPacks,
  formatBytes,
  getInstalledSizeBytes,
  installPack,
  type OfflinePackState
} from '../offline/offlinePacks';
import { reduceAutoRecordingState, type AutoRecordingContext } from '../recording/autoRecorder';
import { ReplayClock } from '../replay/ReplayClock';
import { getRouteTimeBounds, sampleReplayAt } from '../replay/buildReplayFrames';
import { summarizeJourney } from '../statistics/journeyStatistics';
import { buildTimeMachineState } from '../time-machine/timeMachine';
import {
  buildTravelRecords,
  getRegionLabel,
  summarizeTravelRecords,
  type TravelRecord,
  type TravelRegion
} from '../travel-records/travelRecords';
import { buildPlanSummary } from '../travel-plan/planEngine';

export class TravelGlobeApp {
  private readonly root: HTMLElement;
  private readonly adapter: BrowserRuntimeAdapter;
  private readonly flightPreloadProvider = new OfflineAirportFlightPreloadProvider();
  private journey?: Journey;
  private scene?: TravelGlobeScene;
  private clock?: ReplayClock;
  private segment?: JourneySegment;
  private flightOverlay?: FlightOverlay;
  private routeLandmarks: GeographicFeature[] = [];
  private cameraMode: CameraMode = 'flightPreview';
  private lastFrameMs?: number;
  private packState: OfflinePackState = { packs: [] };
  private autoRecordingContext?: AutoRecordingContext;
  private travelRecords: TravelRecord[] = [];
  private activeRecordId?: string;
  private activeRegion: TravelRegion | 'all' = 'all';

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
  private readonly flightNumberInput = document.createElement('input');
  private readonly originInput = document.createElement('input');
  private readonly destinationInput = document.createElement('input');
  private readonly departureDateInput = document.createElement('input');
  private readonly departureTimeInput = document.createElement('input');
  private readonly durationInput = document.createElement('input');
  private readonly aircraftTypeSelect = document.createElement('select');
  private readonly preloadStatus = document.createElement('div');
  private readonly fileInput = document.createElement('input');

  constructor(root: HTMLElement, journey: Journey) {
    this.root = root;
    this.adapter = new BrowserRuntimeAdapter(journey);
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
    const bounds = getRouteTimeBounds(this.segment);
    this.clock = new ReplayClock(bounds.durationSeconds);
    this.lastFrameMs = undefined;

    this.renderShell(journey, this.segment);
    this.scene?.dispose();
    this.scene = new TravelGlobeScene(
      this.viewport,
      this.segment,
      this.flightOverlay,
      this.routeLandmarks
    );
    this.scene.start((timeMs) => this.frame(timeMs));
    await this.adapter.saveJourney(journey);
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
        button.addEventListener('click', () => {
          this.cameraMode = mode;
          this.syncViewRail();
        });
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
    this.recordFilterBar.className = 'record-filters';
    this.timelineList.className = 'timeline-list';
    timeline.append(timelineTitle, this.recordFilterBar, this.timelineList);

    this.productPanel.className = 'product-panel';
    const productShell = document.createElement('details');
    productShell.className = 'dock-panel product-panel-shell';
    productShell.open = false;
    const productSummary = document.createElement('summary');
    productSummary.className = 'panel-summary panel-title';
    productSummary.textContent = 'Travel Atlas';
    productShell.append(productSummary, this.productPanel);

    this.preloadPanel.className = 'preload-panel';
    const preloadShell = document.createElement('details');
    preloadShell.className = 'dock-panel preload-panel-shell';
    preloadShell.open = false;
    const preloadSummary = document.createElement('summary');
    preloadSummary.className = 'panel-summary panel-title';
    preloadSummary.textContent = '航班預載';
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
      this.clock?.seekPercent(Number(this.scrubber.value) / 1000);
    });

    const importButton = document.createElement('button');
    importButton.type = 'button';
    importButton.className = 'control-button secondary-action';
    importButton.textContent = 'Import';
    importButton.addEventListener('click', () => this.fileInput.click());

    const exportButton = document.createElement('button');
    exportButton.type = 'button';
    exportButton.className = 'control-button secondary-action';
    exportButton.textContent = 'Export';
    exportButton.addEventListener('click', () => this.exportTravelGlobe());

    const shareButton = document.createElement('button');
    shareButton.type = 'button';
    shareButton.className = 'control-button secondary-action';
    shareButton.textContent = 'Share';
    shareButton.addEventListener('click', () => this.exportShareSafeJson());

    const manualLink = document.createElement('a');
    manualLink.className = 'control-button control-link secondary-action';
    manualLink.href = './readme.html';
    manualLink.textContent = '使用手冊';

    const gpxButton = document.createElement('button');
    gpxButton.type = 'button';
    gpxButton.className = 'control-button secondary-action';
    gpxButton.textContent = 'GPX';
    gpxButton.addEventListener('click', () => this.exportGpx());

    const kmlButton = document.createElement('button');
    kmlButton.type = 'button';
    kmlButton.className = 'control-button secondary-action';
    kmlButton.textContent = 'KML';
    kmlButton.addEventListener('click', () => this.exportKml());

    const journalButton = document.createElement('button');
    journalButton.type = 'button';
    journalButton.className = 'control-button secondary-action';
    journalButton.textContent = 'Journal';
    journalButton.addEventListener('click', () => this.exportJournalMarkdown());

    const packButton = document.createElement('button');
    packButton.type = 'button';
    packButton.className = 'control-button secondary-action';
    packButton.textContent = 'Pack';
    packButton.addEventListener('click', () => {
      this.packState = installPack(this.packState, coreOfflinePacks[1]);
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

    const actionGrid = document.createElement('div');
    actionGrid.className = 'action-grid';
    actionGrid.append(importButton, exportButton, shareButton, manualLink, gpxButton, kmlButton, journalButton, packButton);

    const systemDrawer = document.createElement('details');
    systemDrawer.className = 'dock-panel system-drawer';
    systemDrawer.open = false;
    const systemSummary = document.createElement('summary');
    systemSummary.className = 'panel-summary panel-title';
    systemSummary.textContent = '更多';
    const drawerBody = document.createElement('div');
    drawerBody.className = 'drawer-body';
    drawerBody.append(actionGrid, this.capability, this.belowMe, preloadShell, productShell, timeline);
    systemDrawer.append(systemSummary, drawerBody);

    controls.append(this.playButton, this.speedSelect, this.scrubber, this.hudStats);
    dock.append(systemDrawer);
    this.recordPreview.className = 'record-preview';
    overlay.append(hud, this.viewRail, dock, this.pilotHud, controls);
    this.root.replaceChildren(this.viewport, overlay, this.fileInput);

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

    this.clock.update(deltaSeconds);
    const sample = sampleReplayAt(this.segment, this.clock.currentSeconds);
    const actualRoute = getActualRouteThrough(this.segment, this.clock.currentSeconds);
    this.scene.update(sample.point, sample.bearingDegrees, this.cameraMode, actualRoute);

    this.scrubber.value = String(Math.round(this.clock.progressPercent * 1000));
    this.syncPlayButton();
    this.updateHud(sample, this.clock.currentSeconds);
  }

  private updateHud(
    sample: ReturnType<typeof sampleReplayAt>,
    elapsedSeconds: number
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
      localizePhase(metrics.phaseLabel),
      metrics.verticalSpeedLabel,
      `航向 ${metrics.headingDegrees}`,
      `T+${elapsedMinutes}:${elapsedRemainder}`,
      `偏離 ${formatDistance(deviationMeters)}`
    ].join(' | ');
    this.renderPilotHud(metrics);

    this.renderBelowMe(sample);

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
    this.preloadStatus.textContent = '輸入航班或選擇起飛/抵達，修改日期時間後按「套用航線」才會更新地球與航跡。';

    const markPending = (): void => {
      this.preloadStatus.textContent = '已修改設定，請按「套用航線」更新地球、時間與航跡。';
    };
    const applyKnownFlight = (): void => {
      const schedule = findScheduleByFlightNumber(this.flightNumberInput.value);
      if (!schedule) {
        markPending();
        return;
      }
      this.originInput.value = schedule.originIata;
      this.destinationInput.value = schedule.destinationIata;
      this.departureTimeInput.value = schedule.defaultDepartureTime;
      this.durationInput.value = String(schedule.defaultDurationMinutes);
      this.aircraftTypeSelect.value = schedule.defaultAircraftType;
      this.preloadStatus.textContent = `${schedule.flightNumber} 已帶入 ${schedule.originIata} -> ${schedule.destinationIata}、${schedule.defaultDepartureTime}、${schedule.defaultAircraftType}。請按「套用航線」更新地球與航跡。`;
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
      input.addEventListener('input', markPending);
      input.addEventListener('change', markPending);
    }
    this.flightNumberInput.addEventListener('input', () => {
      if (findScheduleByFlightNumber(this.flightNumberInput.value)) {
        applyKnownFlight();
      }
    });
    this.flightNumberInput.addEventListener('change', applyKnownFlight);

    form.append(
      field('航班號', this.flightNumberInput, { placeholder: 'CI100' }),
      airportField('起飛', this.originInput, airportSuggestions, markPending, {
        placeholder: 'TPE / Taipei'
      }),
      airportField('抵達', this.destinationInput, airportSuggestions, markPending, {
        placeholder: 'NRT / Tokyo'
      }),
      field('日期', this.departureDateInput, { type: 'date' }),
      field('時間', this.departureTimeInput, { type: 'time' }),
      field('分鐘', this.durationInput, { type: 'number', min: '30', step: '5', required: false }),
      selectField('機型', this.aircraftTypeSelect),
      submitButton
    );
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

    try {
      this.preloadStatus.textContent = '正在建立預載航線...';
      const result = await this.flightPreloadProvider.preloadFlight(request);
      await this.loadJourney(result.journey);
      const message = `${result.journey.title} 已預載。${result.warnings[0] ?? ''}`;
      this.preloadStatus.textContent = message;
      this.capability.textContent = message;
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
    content.append(meta, title, subtitle, tags);

    this.recordPreview.replaceChildren(image, content);
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

  private exportTravelGlobe(): void {
    if (!this.journey) {
      return;
    }
    void this.adapter.exportJourney(this.journey);
  }

  private exportShareSafeJson(): void {
    if (!this.journey) {
      return;
    }
    void this.adapter.exportShareSafeJourney(this.journey);
  }

  private exportJournalMarkdown(): void {
    if (!this.journey) {
      return;
    }
    const journal = generateOfflineJournal(this.journey);
    downloadBlob(new Blob([journal.markdown], { type: 'text/markdown' }), `${this.journey.id}.journal.md`);
  }

  private exportGpx(): void {
    if (!this.journey) {
      return;
    }
    downloadBlob(new Blob([createGpx(this.journey)], { type: 'application/gpx+xml' }), `${this.journey.id}.gpx`);
  }

  private exportKml(): void {
    if (!this.journey) {
      return;
    }
    downloadBlob(new Blob([createKml(this.journey)], { type: 'application/vnd.google-earth.kml+xml' }), `${this.journey.id}.kml`);
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

    this.productPanel.replaceChildren(list, regionBars, packDescription);
  }
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
  const wrapper = field(label, input, { placeholder: options.placeholder, list: options.list, required: false });
  wrapper.classList.add('airport-picker');

  const menu = document.createElement('div');
  menu.className = 'airport-picker-menu';
  menu.hidden = true;
  wrapper.append(menu);

  const showMatches = (): void => {
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
        menu.hidden = true;
        input.blur();
        onSelect();
      };
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
      menu.hidden = true;
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

function toInputDate(timestamp: string): string {
  return new Date(timestamp).toISOString().slice(0, 10);
}

function toInputTime(timestamp: string): string {
  return new Date(timestamp).toISOString().slice(11, 16);
}
