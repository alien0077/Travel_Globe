import type { CameraMode } from '../camera/CameraController';
import { BrowserRuntimeAdapter } from '../bridge/RuntimeAdapter';
import type { Journey, JourneySegment } from '../data/types';
import { getPrimaryFlightSegment } from '../data/types';
import { formatDistance } from '../geo/geodesy';
import { TravelGlobeScene } from '../globe/TravelGlobeScene';
import { ReplayClock } from '../replay/ReplayClock';
import { getRouteTimeBounds, sampleReplayAt } from '../replay/buildReplayFrames';

export class TravelGlobeApp {
  private readonly root: HTMLElement;
  private readonly adapter: BrowserRuntimeAdapter;
  private scene?: TravelGlobeScene;
  private clock?: ReplayClock;
  private segment?: JourneySegment;
  private cameraMode: CameraMode = 'global';
  private lastFrameMs?: number;

  private readonly viewport = document.createElement('section');
  private readonly playButton = document.createElement('button');
  private readonly speedSelect = document.createElement('select');
  private readonly cameraSelect = document.createElement('select');
  private readonly scrubber = document.createElement('input');
  private readonly hudTitle = document.createElement('div');
  private readonly hudRoute = document.createElement('div');
  private readonly hudStats = document.createElement('div');
  private readonly hudPoint = document.createElement('div');
  private readonly capability = document.createElement('div');

  constructor(root: HTMLElement, journey: Journey) {
    this.root = root;
    this.adapter = new BrowserRuntimeAdapter(journey);
  }

  async start(): Promise<void> {
    const journey = await this.adapter.loadJourney();
    this.segment = getPrimaryFlightSegment(journey);
    const bounds = getRouteTimeBounds(this.segment);
    this.clock = new ReplayClock(bounds.durationSeconds);

    this.renderShell(journey, this.segment);
    this.scene = new TravelGlobeScene(this.viewport, this.segment);
    this.scene.start((timeMs) => this.frame(timeMs));
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
    this.capability.className = 'capability';
    hud.append(this.hudTitle, this.hudRoute, this.hudStats, this.hudPoint, this.capability);

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

    this.cameraSelect.className = 'control-select';
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

    controls.append(this.playButton, this.speedSelect, this.cameraSelect, this.scrubber);
    overlay.append(hud, controls);
    this.root.replaceChildren(this.viewport, overlay);

    this.hudTitle.textContent = journey.title;
    this.hudRoute.textContent = `${segment.origin.iataCode ?? segment.origin.name} to ${segment.destination.iataCode ?? segment.destination.name}`;
    this.capability.textContent = this.adapter.getLocationCapability().reason ?? 'Standalone browser replay';
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
  }

  private syncPlayButton(): void {
    this.playButton.textContent = this.clock?.isPlaying ? 'Pause' : 'Play';
  }
}
