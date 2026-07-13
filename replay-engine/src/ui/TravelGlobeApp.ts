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
  summarizeBelowMe,
  type FlightOverlay
} from '../flight/flightAnalytics';
import { OfflineAirportFlightPreloadProvider } from '../flight/flightPlanProvider';
import type { PreloadFlightRequest } from '../flight-preload/buildPreloadedFlightJourney';
import { findAirportContextByIata, getAirportIndexSummary, listAirportSuggestions } from '../flight-preload/airportIndex';
import { findNearestLandmark } from '../geo/landmarks';
import { formatDistance } from '../geo/geodesy';
import { TravelGlobeScene } from '../globe/TravelGlobeScene';
import { readJourneyFile } from '../import/readJourneyFile';
import { generateOfflineJournal } from '../journal/generateJournal';
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
  private cameraMode: CameraMode = 'global';
  private lastFrameMs?: number;
  private packState: OfflinePackState = { packs: [] };
  private autoRecordingContext?: AutoRecordingContext;
  private travelRecords: TravelRecord[] = [];
  private activeRecordId?: string;
  private activeRegion: TravelRegion | 'all' = 'all';

  private readonly viewport = document.createElement('section');
  private readonly playButton = document.createElement('button');
  private readonly speedSelect = document.createElement('select');
  private readonly cameraSelect = document.createElement('select');
  private readonly scrubber = document.createElement('input');
  private readonly hudTitle = document.createElement('div');
  private readonly hudRoute = document.createElement('div');
  private readonly hudStats = document.createElement('div');
  private readonly hudPoint = document.createElement('div');
  private readonly belowMe = document.createElement('div');
  private readonly capability = document.createElement('div');
  private readonly timelineList = document.createElement('div');
  private readonly recordFilterBar = document.createElement('div');
  private readonly recordPreview = document.createElement('article');
  private readonly productPanel = document.createElement('section');
  private readonly preloadPanel = document.createElement('section');
  private readonly flightNumberInput = document.createElement('input');
  private readonly originInput = document.createElement('input');
  private readonly destinationInput = document.createElement('input');
  private readonly departureDateInput = document.createElement('input');
  private readonly departureTimeInput = document.createElement('input');
  private readonly durationInput = document.createElement('input');
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
      this.travelRecords.map((record) => record.location)
    );
    this.scene.start((timeMs) => this.frame(timeMs));
    await this.adapter.saveJourney(journey);
  }

  private renderShell(journey: Journey, segment: JourneySegment): void {
    const isCompactViewport = window.matchMedia('(max-width: 720px)').matches;
    this.root.className = isCompactViewport ? 'app-shell is-compact' : 'app-shell';
    this.viewport.className = 'globe-viewport';

    const overlay = document.createElement('section');
    overlay.className = 'overlay';

    const hud = document.createElement('section');
    hud.className = 'hud';
    this.hudTitle.className = 'hud-title';
    this.hudRoute.className = 'hud-route';
    this.hudStats.className = 'hud-stats';
    this.hudPoint.className = 'hud-point';
    this.belowMe.className = 'below-me';
    this.capability.className = 'capability';
    hud.append(this.hudTitle, this.hudRoute, this.hudStats, this.hudPoint, this.belowMe, this.capability);

    const dock = document.createElement('section');
    dock.className = 'info-dock';

    const timeline = document.createElement('details');
    timeline.className = 'dock-panel timeline-panel';
    timeline.open = !isCompactViewport;
    const timelineTitle = document.createElement('summary');
    timelineTitle.className = 'panel-summary panel-title';
    timelineTitle.textContent = '旅遊紀錄';
    this.recordFilterBar.className = 'record-filters';
    this.timelineList.className = 'timeline-list';
    timeline.append(timelineTitle, this.recordFilterBar, this.timelineList);

    this.productPanel.className = 'product-panel';
    const productShell = document.createElement('details');
    productShell.className = 'dock-panel product-panel-shell';
    productShell.open = !isCompactViewport;
    const productSummary = document.createElement('summary');
    productSummary.className = 'panel-summary panel-title';
    productSummary.textContent = 'Travel Atlas';
    productShell.append(productSummary, this.productPanel);

    this.preloadPanel.className = 'preload-panel';
    const preloadShell = document.createElement('details');
    preloadShell.className = 'dock-panel preload-panel-shell';
    preloadShell.open = !isCompactViewport;
    const preloadSummary = document.createElement('summary');
    preloadSummary.className = 'panel-summary panel-title';
    preloadSummary.textContent = '航班預載';
    preloadShell.append(preloadSummary, this.preloadPanel);

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

    this.cameraSelect.className = 'control-select camera-select';
    const cameraOptions: Array<{ mode: CameraMode; label: string }> = [
      { mode: 'global', label: 'Global View' },
      { mode: 'follow', label: 'Follow camera' },
      { mode: 'orbit', label: 'Orbit cinema' },
      { mode: 'cockpit', label: 'Cockpit view' },
      { mode: 'leftWindow', label: 'Left window' },
      { mode: 'rightWindow', label: 'Right window' },
      { mode: 'tail', label: 'Tail chase' },
      { mode: 'topDown', label: 'Top down' }
    ];
    for (const { mode, label } of cameraOptions) {
      const option = document.createElement('option');
      option.value = mode;
      option.textContent = label;
      this.cameraSelect.appendChild(option);
    }
    this.cameraSelect.value = this.cameraMode;
    this.cameraSelect.addEventListener('change', () => {
      this.cameraMode = this.cameraSelect.value as CameraMode;
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

    controls.append(
      this.playButton,
      this.speedSelect,
      this.cameraSelect,
      importButton,
      exportButton,
      shareButton,
      manualLink,
      gpxButton,
      kmlButton,
      journalButton,
      packButton,
      this.scrubber
    );
    dock.append(preloadShell, productShell, timeline);
    this.recordPreview.className = 'record-preview';
    overlay.append(hud, dock, this.recordPreview, controls);
    this.root.replaceChildren(this.viewport, overlay, this.fileInput);
    if (isCompactViewport) {
      this.applyCompactRuntimeLayout({ overlay, hud, dock, controls });
    }

    this.hudTitle.textContent = 'TRAVEL ATLAS';
    this.hudRoute.textContent = `${journey.title} | ${segment.origin.iataCode ?? segment.origin.name} to ${segment.destination.iataCode ?? segment.destination.name}`;
    this.capability.textContent = this.adapter.getLocationCapability().reason ?? 'Standalone browser replay';
    this.renderRegionFilters();
    this.renderTimeline();
    this.renderRecordPreview();
    this.renderPreloadPanel(segment);
    this.renderProductPanel();
    this.syncPlayButton();
  }

  private applyCompactRuntimeLayout(elements: {
    overlay: HTMLElement;
    hud: HTMLElement;
    dock: HTMLElement;
    controls: HTMLElement;
  }): void {
    Object.assign(document.documentElement.style, {
      height: '100%',
      minHeight: '100%',
      overflow: 'hidden'
    });
    Object.assign(document.body.style, {
      height: '100%',
      minHeight: '100%',
      margin: '0',
      overflow: 'hidden',
      background: '#07141a'
    });
    Object.assign(this.root.style, {
      position: 'relative',
      width: '100%',
      height: '100%',
      minHeight: '100vh',
      overflow: 'hidden',
      background: '#07141a'
    });
    Object.assign(this.viewport.style, {
      position: 'absolute',
      inset: '0',
      zIndex: '0',
      width: '100%',
      height: '100%',
      minHeight: '0',
      background:
        'radial-gradient(circle at 50% 36%, rgba(255,255,255,.78) 0 24%, rgba(255,255,255,0) 48%), linear-gradient(180deg, #e8f3f0 0%, #cfdfdc 48%, #08151b 100%)'
    });
    Object.assign(elements.overlay.style, {
      position: 'absolute',
      inset: '0',
      zIndex: '2',
      display: 'block',
      overflow: 'hidden',
      padding: '0',
      pointerEvents: 'none',
      background: 'linear-gradient(180deg, rgba(8,17,23,.56) 0%, rgba(8,17,23,.2) 44%, rgba(8,17,23,.68) 100%)',
      WebkitOverflowScrolling: 'touch'
    });

    for (const panel of [elements.hud, elements.dock, this.recordPreview, elements.controls]) {
      Object.assign(panel.style, {
        position: 'static',
        width: '100%',
        transform: 'none'
      });
    }

    Object.assign(elements.hud.style, {
      position: 'absolute',
      top: '10px',
      left: '10px',
      right: '10px',
      width: 'auto',
      padding: '12px',
      maxHeight: '25vh',
      overflow: 'hidden',
      pointerEvents: 'auto'
    });
    for (const extra of [this.belowMe, this.capability]) {
      extra.style.display = 'none';
    }
    Object.assign(this.hudPoint.style, {
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis'
    });
    Object.assign(this.recordPreview.style, {
      display: 'none'
    });
    Object.assign(elements.dock.style, {
      position: 'absolute',
      top: 'calc(20px + 25vh)',
      right: '10px',
      left: 'auto',
      width: 'min(184px, calc(100vw - 20px))',
      display: 'grid',
      gap: '8px',
      marginTop: '0',
      pointerEvents: 'auto'
    });
    Object.assign(elements.controls.style, {
      position: 'absolute',
      left: '10px',
      right: '10px',
      bottom: '10px',
      width: 'auto',
      display: 'grid',
      gridTemplateColumns: '82px 82px minmax(0, 1fr)',
      gap: '8px',
      margin: '0',
      padding: '8px',
      pointerEvents: 'auto'
    });
    for (const secondaryAction of elements.controls.querySelectorAll<HTMLElement>('.secondary-action')) {
      secondaryAction.style.display = 'none';
    }
    Object.assign(this.cameraSelect.style, {
      gridColumn: 'auto',
      minWidth: '0'
    });
    Object.assign(this.scrubber.style, {
      gridColumn: '1 / -1',
      width: '100%',
      minWidth: '0'
    });

    for (const panel of this.root.querySelectorAll<HTMLElement>('.hud, .dock-panel, .record-preview, .controls')) {
      Object.assign(panel.style, {
        border: '1px solid rgba(40,78,77,.13)',
        borderRadius: '8px',
        background: 'rgba(255,255,255,.82)',
        boxShadow: '0 18px 52px rgba(36,61,58,.18)',
        color: '#1f3332'
      });
    }
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

    this.hudTitle.textContent = 'TRAVEL ATLAS';
    this.hudRoute.textContent = `${metrics.flightNumber} | ${metrics.routeLabel}`;
    this.hudStats.replaceChildren(
      metricItem('Altitude', metrics.altitudeFeet),
      metricItem('Speed', metrics.speedKmh),
      metricItem('Ground Speed', metrics.groundSpeedKmh),
      metricItem('Heading', metrics.headingDegrees),
      metricItem('Distance', metrics.distanceLabel),
      metricItem('ETA', metrics.etaLabel)
    );

    this.hudPoint.textContent = [
      metrics.phaseLabel,
      `${point.latitude.toFixed(3)}, ${point.longitude.toFixed(3)}`,
      point.source,
      `T+${elapsedMinutes}:${elapsedRemainder}`,
      `Deviation ${formatDistance(deviationMeters)}`
    ].join(' | ');

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
    this.playButton.textContent = this.clock?.isPlaying ? 'Pause' : 'Play';
  }

  private renderPreloadPanel(segment: JourneySegment): void {
    const form = document.createElement('form');
    form.className = 'preload-form';

    const airports = document.createElement('datalist');
    airports.id = 'airport-iata-options';
    airports.replaceChildren(
      ...listAirportSuggestions().map((airport) => {
        const option = document.createElement('option');
        option.value = airport.iataCode ?? '';
        option.label = `${airport.iataCode} ${airport.name}`;
        return option;
      })
    );

    this.flightNumberInput.value = stringValue(segment.metadata.flightNumber, 'CI100');
    this.originInput.value = '';
    this.destinationInput.value = '';
    this.departureDateInput.value = toInputDate(segment.startTime);
    this.departureTimeInput.value = toInputTime(segment.startTime);
    this.durationInput.value = '';

    const submitButton = document.createElement('button');
    submitButton.type = 'submit';
    submitButton.className = 'preload-submit';
    submitButton.textContent = '預載進入';

    this.preloadStatus.className = 'preload-status';
    this.preloadStatus.textContent = '輸入 CI100 可由離線班表解析 TPE -> NRT；手動機場欄位可留空或覆寫。';

    form.append(
      field('航班號', this.flightNumberInput, { placeholder: 'CI100' }),
      field('起飛', this.originInput, { placeholder: '自動', list: airports.id, required: false }),
      field('抵達', this.destinationInput, { placeholder: '自動', list: airports.id, required: false }),
      field('日期', this.departureDateInput, { type: 'date' }),
      field('時間', this.departureTimeInput, { type: 'time' }),
      field('分鐘', this.durationInput, { type: 'number', min: '30', step: '5', required: false }),
      submitButton
    );
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      void this.preloadFlightFromForm();
    });

    this.preloadPanel.replaceChildren(airports, form, this.preloadStatus);
  }

  private async preloadFlightFromForm(): Promise<void> {
    const request: PreloadFlightRequest = {
      flightNumber: this.flightNumberInput.value,
      originIata: this.originInput.value,
      destinationIata: this.destinationInput.value,
      departureDate: this.departureDateInput.value,
      departureTime: this.departureTimeInput.value,
      durationMinutes: Number(this.durationInput.value) || undefined
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
    const nearest = findNearestLandmark(sample.point, sample.bearingDegrees);
    const summary = summarizeBelowMe(sample.point, sample.bearingDegrees);
    const nearby = summary.nearby
      .slice(0, 3)
      .map((item) => `${item.feature.name} ${formatDistance(item.distanceMeters)}`)
      .join(' | ');
    const nextCity = summary.nextMajorCity
      ? `Next major city: ${summary.nextMajorCity.feature.name} ${formatDistance(summary.nextMajorCity.distanceMeters)}`
      : '';

    this.belowMe.replaceChildren(
      textLine(`Below: ${summary.belowLabel}`),
      textLine(`Crossing: ${summary.crossingLabel}`),
      textLine(`Nearby: ${nearby}`),
      textLine(nextCity || (nearest ? `Window: ${nearest.feature.name}, ${nearest.relativeWindow}` : 'Window: no nearby landmark fixture'))
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

function stringValue(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : fallback;
}

function toInputDate(timestamp: string): string {
  return new Date(timestamp).toISOString().slice(0, 10);
}

function toInputTime(timestamp: string): string {
  return new Date(timestamp).toISOString().slice(11, 16);
}
