import type { Journey } from '../data/types';
import { createStoredZip, readStoredZip, textZipEntry } from './zip';

export interface TravelGlobeManifest {
  format: 'travelglobe';
  packageVersion: '1.0.0';
  createdAt: string;
  journeyId: string;
  schemaVersion: string;
  appVersion: string;
  entries: string[];
}

export function createTravelGlobePackage(journey: Journey): Blob {
  const segment = journey.segments[0];
  const manifest: TravelGlobeManifest = {
    format: 'travelglobe',
    packageVersion: '1.0.0',
    createdAt: new Date().toISOString(),
    journeyId: journey.id,
    schemaVersion: journey.schemaVersion,
    appVersion: journey.appVersion,
    entries: [
      'manifest.json',
      'journey.json',
      'routes/raw.json',
      'routes/processed.json',
      'routes/derived-replay.json',
      'journal/journal.json'
    ]
  };

  return createStoredZip([
    textZipEntry('manifest.json', JSON.stringify(manifest, null, 2)),
    textZipEntry('journey.json', JSON.stringify(journey, null, 2)),
    textZipEntry('routes/raw.json', JSON.stringify(segment.rawRoute, null, 2)),
    textZipEntry('routes/processed.json', JSON.stringify(segment.processedRoute, null, 2)),
    textZipEntry('routes/derived-replay.json', JSON.stringify(segment.derivedReplayRoute, null, 2)),
    textZipEntry('journal/journal.json', JSON.stringify(journey.journal, null, 2))
  ]);
}

export async function readTravelGlobePackage(blob: Blob): Promise<unknown> {
  const entries = await readStoredZip(blob);
  const journeyJson = entries.get('journey.json');
  if (!journeyJson) {
    throw new Error('The .travelglobe package does not contain journey.json');
  }

  return JSON.parse(journeyJson) as unknown;
}

export function createJsonBlob(value: unknown): Blob {
  return new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' });
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  window.setTimeout(() => {
    anchor.remove();
    URL.revokeObjectURL(url);
  }, 1000);
}
