import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const libraryPath = resolve(root, 'replay-engine/public/models/aircraft/library.json');
const allowedLicenses = new Set(['cc0', 'cc-by']);
const blockedLicensePatterns = [/non.?commercial/i, /\bnc\b/i, /no.?derivatives/i, /\bnd\b/i, /editorial/i];
const args = new Set(process.argv.slice(2));
const dryRun = args.has('--dry-run');

if (!dryRun) {
  throw new Error(
    'Automatic Sketchfab API downloads are disabled. Log in to Sketchfab, download the GLB manually, then run npm --prefix replay-engine run import:aircraft-model -- --aircraft a350-900 --file /path/to/model.glb'
  );
}

const library = JSON.parse(readFileSync(libraryPath, 'utf8'));
const candidates = library.aircraft.filter((entry) => entry.source?.platform === 'Sketchfab' && entry.source.modelUid);

if (candidates.length === 0) {
  console.log('No Sketchfab aircraft candidates configured.');
  process.exit(0);
}

const attribution = [];

for (const entry of candidates) {
  const metadata = await fetchJson(`https://api.sketchfab.com/v3/models/${entry.source.modelUid}`);
  const license = normalizeLicense(metadata.license);
  const label = metadata.license?.label ?? metadata.license?.name ?? metadata.license?.slug ?? 'unknown';

  assertUsableLicense(entry.id, label, license);
  assertAttribution(entry, metadata);

  const modelTitle = metadata.name ?? entry.label;
  console.log(`${entry.id}: ${modelTitle} (${label}) by ${metadata.user?.displayName ?? entry.author}`);

  attribution.push({
    id: entry.id,
    title: modelTitle,
    author: metadata.user?.displayName ?? entry.author,
    license: label,
    source: entry.source.modelUrl ?? entry.sourceUrl,
    provider: 'Sketchfab'
  });

  if (dryRun) {
    continue;
  }
}

console.log(`Audited ${attribution.length} Sketchfab candidate models.`);
console.log('Download GLB files manually from Sketchfab, then import them with npm --prefix replay-engine run import:aircraft-model -- --aircraft <slug> --file <path>');

async function fetchJson(url) {
  const response = await fetch(url, {
    headers: {
      Accept: 'application/json'
    }
  });
  if (!response.ok) {
    throw new Error(`${url} failed: ${response.status} ${response.statusText}.`);
  }
  return response.json();
}

function normalizeLicense(license) {
  const raw = `${license?.slug ?? ''} ${license?.label ?? ''} ${license?.name ?? ''}`.toLowerCase();
  if (raw.includes('cc0')) return 'cc0';
  if (raw.includes('attribution') && !raw.includes('noncommercial') && !raw.includes('noderivatives')) return 'cc-by';
  if (raw.includes('cc-by') && !raw.includes('nc') && !raw.includes('nd')) return 'cc-by';
  return raw.trim();
}

function assertUsableLicense(id, label, normalized) {
  if (blockedLicensePatterns.some((pattern) => pattern.test(label)) || !allowedLicenses.has(normalized)) {
    throw new Error(`${id}: rejected license "${label}". Only CC0 and CC BY are allowed.`);
  }
}

function assertAttribution(entry, metadata) {
  const author = metadata.user?.displayName ?? entry.author;
  const source = entry.source.modelUrl ?? entry.sourceUrl;
  if (!author || !source || !entry.attribution.includes('Sketchfab')) {
    throw new Error(`${entry.id}: attribution must include author, source URL, and Sketchfab.`);
  }
}
