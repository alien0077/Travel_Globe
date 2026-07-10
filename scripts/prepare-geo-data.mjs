import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const landmarksPath = resolve(root, 'shared/fixtures/landmarks.json');
const outputPath = resolve(root, 'shared/offline-packs/core-global/manifest.json');
const landmarks = JSON.parse(readFileSync(landmarksPath, 'utf8'));
const regionCodes = [...new Set(landmarks.map((landmark) => landmark.countryCode).filter(Boolean))].sort();

const manifest = {
  id: 'core-global-fixture',
  version: '1.0.0',
  generatedAt: '2026-07-10T00:00:00.000Z',
  source: {
    kind: 'local-fixture',
    path: 'shared/fixtures/landmarks.json',
    licenseStatus: 'project-fixture-only',
    productionReplacementRequired: true
  },
  contents: {
    landmarks: landmarks.length,
    regionCodes,
    countryBorders: {
      status: 'placeholder',
      productionReplacementRequired: true
    },
    rtreeIndex: {
      status: 'not-required-for-fixture-pack',
      productionReplacementRequired: true
    }
  }
};

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`Prepared offline geo manifest at ${outputPath}`);
