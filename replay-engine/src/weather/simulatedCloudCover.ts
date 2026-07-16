import type { GeographicPoint } from '../data/types';

export function simulatedCloudCoverFraction(point: GeographicPoint, timestamp: string): number {
  const time = Date.parse(timestamp);
  const day = Number.isFinite(time) ? Math.floor(time / 86_400_000) : 0;
  const latitudeWave = Math.sin(((point.latitude + day * 1.7) * Math.PI) / 18);
  const longitudeWave = Math.cos(((point.longitude - day * 2.1) * Math.PI) / 27);
  const synopticWave = Math.sin(((point.latitude * 0.53 + point.longitude * 0.31 + day * 0.77) * Math.PI) / 12);
  const tropicalBoost = Math.max(0, 1 - Math.abs(point.latitude) / 35) * 0.18;
  const polarDryness = Math.max(0, (Math.abs(point.latitude) - 58) / 32) * 0.16;
  const raw = 0.46 + latitudeWave * 0.16 + longitudeWave * 0.11 + synopticWave * 0.13 + tropicalBoost - polarDryness;
  return clamp(raw, 0.12, 0.88);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
