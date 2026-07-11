import type { CameraMode } from '../camera/CameraController';
import { BrowserRuntimeAdapter } from '../bridge/RuntimeAdapter';
import type { Journey, JourneySegment, TimelineEvent } from '../data/types';
import { getPrimaryFlightSegment } from '../data/types';
import { createGpx, createKml } from '../export/geoExport';
import { createJsonBlob, createTravelGlobePackage, downloadBlob } from '../export/travelglobePackage';
import {
  buildFlightHudMetrics,
  buildFlightOverlay,
  calculateRouteDeviationMeters,
  getActualRouteThrough,
  summarizeBelowMe,
  type FlightOverlay
} from '../flight/flightAnalytics';
import { findNearestLandmark } from '../geo/landmarks';
import { formatDistance } from '../geo/geodesy';
import { TravelGlobeScene } from '../globe/TravelGlobeScene';
import { readJourneyFile } from '../import/readJourneyFile';
import { generateOfflineJournal } from '../journal/generateJournal';
import { evaluateNotifications } from '../notifications/notificationRules';
import { coreOfflinePacks, formatBytes, getInstalledSizeBytes, installPack, type OfflinePackState } from '../offline/offlinePacks';
import { createShareSafeJourney } from '../privacy/redactJourney';
import { reduceAutoRecordingState, type AutoRecordingContext } from '../recording/autoRecorder';
import { ReplayClock } from '../replay/ReplayClock';
import { getRouteTimeBounds, sampleReplayAt } from '../replay/buildReplayFrames';
import { summarizeJourney } from '../statistics/journeyStatistics';
import { formatEventTime, getSortedTimelineEvents } from '../timeline/timeline';
import { buildTimeMachineState } from '../time-machine/timeMachine';
import { buildPlanSummary } from '../travel-plan/planEngine';

export class TravelGlobeApp {
  private readonly root: HTMLElement;
  private readonly adapter: BrowserRuntimeAdapter;
  private journey?: Journey;
  private scene?: TravelGlobeScene;
  private clock?: ReplayClock;
  private segment?: JourneySegment;
  private flightOverlay?: FlightOverlay;
  private cameraMode: CameraMode = 'global';
  private lastFrameMs?: number;
  private packState: OfflinePackState = { packs: [] };
  private autoRecordingContext?: AutoRecordingContext;

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
  private readonly productPanel = document.createElement('section');
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
    const bounds = getRouteTimeBounds(this.segment);
    this.clock = new ReplayClock(bounds.durationSeconds);
    this.lastFrameMs = undefined;

    this.renderShell(journey, this.segment);
    this.scene?.dispose();
    this.scene = new TravelGlobeScene(this.viewport, this.segment, this.flightOverlay);
    this.scene.start((timeMs) => this.frame(timeMs));
    await this.adapter.saveJourney(journey);
  }

  private renderShell(journey: Journey, segment: JourneySegment): void {
    this.root.className = 'app-shell';
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

    const isCompactViewport = window.matchMedia('(max-width: 720px)').matches;
    const dock = document.createElement('section');
    dock.className = 'info-dock';

    const timeline = document.createElement('details');
    timeline.className = 'dock-panel timeline-panel';
    timeline.open = !isCompactViewport;
    const timelineTitle = document.createElement('summary');
    timelineTitle.className = 'panel-summary panel-title';
    timelineTitle.textContent = 'Timeline';
    this.timelineList.className = 'timeline-list';
    timeline.append(timelineTitle, this.timelineList);

    this.productPanel.className = 'product-panel';
    const productShell = document.createElement('details');
    productShell.className = 'dock-panel product-panel-shell';
    productShell.open = false;
    const productSummary = document.createElement('summary');
    productSummary.className = 'panel-summary panel-title';
    productSummary.textContent = 'Product Modes';
    productShell.append(productSummary, this.productPanel);

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
    importButton.className = 'control-button';
    importButton.textContent = 'Import';
    importButton.addEventListener('click', () => this.fileInput.click());

    const exportButton = document.createElement('button');
    exportButton.type = 'button';
    exportButton.className = 'control-button';
    exportButton.textContent = 'Export';
    exportButton.addEventListener('click', () => this.exportTravelGlobe());

    const shareButton = document.createElement('button');
    shareButton.type = 'button';
    shareButton.className = 'control-button';
    shareButton.textContent = 'Share JSON';
    shareButton.addEventListener('click', () => this.exportShareSafeJson());

    const manualLink = document.createElement('a');
    manualLink.className = 'control-button control-link';
    manualLink.href = './readme.html';
    manualLink.textContent = '使用手冊';

    const gpxButton = document.createElement('button');
    gpxButton.type = 'button';
    gpxButton.className = 'control-button';
    gpxButton.textContent = 'GPX';
    gpxButton.addEventListener('click', () => this.exportGpx());

    const kmlButton = document.createElement('button');
    kmlButton.type = 'button';
    kmlButton.className = 'control-button';
    kmlButton.textContent = 'KML';
    kmlButton.addEventListener('click', () => this.exportKml());

    const journalButton = document.createElement('button');
    journalButton.type = 'button';
    journalButton.className = 'control-button';
    journalButton.textContent = 'Journal';
    journalButton.addEventListener('click', () => this.exportJournalMarkdown());

    const packButton = document.createElement('button');
    packButton.type = 'button';
    packButton.className = 'control-button';
    packButton.textContent = 'Install Pack';
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
    dock.append(timeline, productShell);
    overlay.append(hud, dock, controls);
    this.root.replaceChildren(this.viewport, overlay, this.fileInput);

    this.hudTitle.textContent = journey.title;
    this.hudRoute.textContent = `${segment.origin.iataCode ?? segment.origin.name} to ${segment.destination.iataCode ?? segment.destination.name}`;
    this.capability.textContent = this.adapter.getLocationCapability().reason ?? 'Standalone browser replay';
    this.renderTimeline(journey.events);
    this.renderProductPanel();
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
    this.hudRoute.textContent = metrics.routeLabel;
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

  private renderTimeline(events: TimelineEvent[]): void {
    const sourceEvents = this.flightOverlay
      ? this.flightOverlay.events.map((event) => ({
          timestamp: event.timestamp,
          title: event.title
        }))
      : getSortedTimelineEvents({ events } as Journey);
    const items = sourceEvents.map((event) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'timeline-item';
      button.textContent = `${formatTimestampUtc(event.timestamp)} ${event.title}`;
      button.addEventListener('click', () => this.seekToTimestamp(event.timestamp));
      return button;
    });

    this.timelineList.replaceChildren(...items);
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
    const blob = createTravelGlobePackage(this.journey);
    downloadBlob(blob, `${this.journey.id}.travelglobe`);
  }

  private exportShareSafeJson(): void {
    if (!this.journey) {
      return;
    }
    const shareSafe = createShareSafeJourney(this.journey);
    downloadBlob(createJsonBlob(shareSafe), `${this.journey.id}.share-safe.json`);
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
    const rows = [
      ['Plan', `${plan.completedCount}/${plan.plannedPlaces.length} places completed`],
      ['Journal', `${journal.markdown.split('\n').length} markdown lines ready`],
      ['Time Machine', `${timeMachine.years.join(', ')} | ${formatDistance(timeMachine.lifetimeDistanceMeters)}`],
      ['Stats', `${formatDistance(summary.totalDistanceMeters)} | ${summary.countriesVisited.join(' -> ')}`],
      ['Offline Packs', `${this.packState.packs.length} installed | ${formatBytes(getInstalledSizeBytes(this.packState))}`],
      ['Auto Recording', this.autoRecordingContext?.state ?? 'Idle'],
      ['Notifications', notifications.length > 0 ? notifications.map((item) => item.title).join(', ') : 'clear']
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

    this.productPanel.replaceChildren(list);
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

function formatTimestampUtc(timestamp: string): string {
  return formatEventTime({ timestamp } as TimelineEvent);
}
