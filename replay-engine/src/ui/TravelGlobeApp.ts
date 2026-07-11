import type { CameraMode } from '../camera/CameraController';
import { BrowserRuntimeAdapter } from '../bridge/RuntimeAdapter';
import type { Journey, JourneySegment, TimelineEvent } from '../data/types';
import { getPrimaryFlightSegment } from '../data/types';
import { createJsonBlob, createTravelGlobePackage, downloadBlob } from '../export/travelglobePackage';
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
    const bounds = getRouteTimeBounds(this.segment);
    this.clock = new ReplayClock(bounds.durationSeconds);
    this.lastFrameMs = undefined;

    this.renderShell(journey, this.segment);
    this.scene?.dispose();
    this.scene = new TravelGlobeScene(this.viewport, this.segment);
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
    for (const mode of ['global', 'follow'] satisfies CameraMode[]) {
      const option = document.createElement('option');
      option.value = mode;
      option.textContent = mode === 'global' ? 'Global camera' : 'Follow camera';
      this.cameraSelect.appendChild(option);
    }
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
    this.scene.update(sample.point, sample.bearingDegrees, this.cameraMode);

    this.scrubber.value = String(Math.round(this.clock.progressPercent * 1000));
    this.syncPlayButton();
    this.updateHud(sample, this.clock.currentSeconds);
  }

  private updateHud(
    sample: ReturnType<typeof sampleReplayAt>,
    elapsedSeconds: number
  ): void {
    const point = sample.point;
    const altitudeFeet = ((point.altitudeMeters ?? 0) * 3.28084).toFixed(0);
    const speedKnots = ((point.speedMetersPerSecond ?? 0) * 1.94384).toFixed(0);
    const elapsedMinutes = Math.floor(elapsedSeconds / 60);
    const elapsedRemainder = Math.floor(elapsedSeconds % 60).toString().padStart(2, '0');

    this.hudStats.textContent = [
      `ALT ${altitudeFeet} ft`,
      `GS ${speedKnots} kt`,
      `HDG ${sample.bearingDegrees.toFixed(0)}`,
      `FLOWN ${formatDistance(sample.distanceFlownMeters)}`,
      `REM ${formatDistance(sample.remainingDistanceMeters)}`,
      `T+${elapsedMinutes}:${elapsedRemainder}`
    ].join('  ');

    this.hudPoint.textContent = `${point.latitude.toFixed(3)}, ${point.longitude.toFixed(3)} | ${point.source}`;

    const nearest = findNearestLandmark(point, sample.bearingDegrees);
    this.belowMe.textContent = nearest
      ? `Below me: nearest ${nearest.feature.name}, ${formatDistance(nearest.distanceMeters)}, ${nearest.relativeWindow} window`
      : 'Below me: no nearby landmark fixture';

    if (this.journey) {
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
  }

  private syncPlayButton(): void {
    this.playButton.textContent = this.clock?.isPlaying ? 'Pause' : 'Play';
  }

  private renderTimeline(events: TimelineEvent[]): void {
    const items = getSortedTimelineEvents({ events } as Journey).map((event) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'timeline-item';
      button.textContent = `${formatEventTime(event)} ${event.title}`;
      button.addEventListener('click', () => this.seekToEvent(event));
      return button;
    });

    this.timelineList.replaceChildren(...items);
  }

  private seekToEvent(event: TimelineEvent): void {
    if (!this.segment || !this.clock) {
      return;
    }
    const bounds = getRouteTimeBounds(this.segment);
    const elapsedSeconds = (Date.parse(event.timestamp) - bounds.startMs) / 1000;
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
