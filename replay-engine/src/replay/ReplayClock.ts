export class ReplayClock {
  readonly durationSeconds: number;
  currentSeconds = 0;
  speed = 5;
  isPlaying = true;

  constructor(durationSeconds: number) {
    this.durationSeconds = Math.max(1, durationSeconds);
  }

  update(deltaSeconds: number): void {
    if (!this.isPlaying) {
      return;
    }

    this.currentSeconds = Math.min(
      this.durationSeconds,
      this.currentSeconds + deltaSeconds * this.speed
    );

    if (this.currentSeconds >= this.durationSeconds) {
      this.isPlaying = false;
    }
  }

  seekPercent(percent: number): void {
    const clamped = Math.min(1, Math.max(0, percent));
    this.currentSeconds = this.durationSeconds * clamped;
  }

  setSpeed(speed: number): void {
    this.speed = Math.max(1, speed);
  }

  togglePlayback(): void {
    if (this.currentSeconds >= this.durationSeconds) {
      this.currentSeconds = 0;
    }
    this.isPlaying = !this.isPlaying;
  }

  get progressPercent(): number {
    return this.currentSeconds / this.durationSeconds;
  }
}
