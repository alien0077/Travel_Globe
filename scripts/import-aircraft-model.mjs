import { copyFileSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { basename, dirname, extname, resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const libraryPath = resolve(root, 'replay-engine/public/models/aircraft/library.json');
const args = parseArgs(process.argv.slice(2));

if (!args.aircraft || !args.file) {
  throw new Error('Usage: node scripts/import-aircraft-model.mjs --aircraft a350-900 --file /path/to/model.glb');
}

const sourceFile = resolve(args.file);
if (!existsSync(sourceFile)) {
  throw new Error(`Model file not found: ${sourceFile}`);
}

const extension = extname(sourceFile).toLowerCase();
if (extension !== '.glb' && extension !== '.gltf') {
  throw new Error(`Unsupported model format "${extension}". Export or convert the model to .glb or .gltf first.`);
}

const library = JSON.parse(readFileSync(libraryPath, 'utf8'));
const entry = library.aircraft.find((item) => item.slug === args.aircraft || item.id.toLowerCase() === args.aircraft.toLowerCase());
if (!entry) {
  throw new Error(`Unknown aircraft "${args.aircraft}". Add it to ${libraryPath} first.`);
}

if (entry.license !== 'CC BY' && entry.license !== 'CC0') {
  throw new Error(`${entry.slug} is not marked as CC0/CC BY. Confirm the Sketchfab license before importing.`);
}

if (entry.editorialOnly || !entry.commercialUse || !entry.derivativesAllowed) {
  throw new Error(`${entry.slug} is not marked as commercial derivative-safe. Confirm license metadata before importing.`);
}

const licensePath = resolve(root, 'replay-engine/public', entry.licenseFile);
if (!existsSync(licensePath)) {
  throw new Error(`Missing license file: ${licensePath}`);
}

const actualFaces = Number(args.faces ?? entry.polygonBudget.actual ?? entry.polygonBudget.min);
if (actualFaces > entry.polygonBudget.max) {
  throw new Error(
    `${entry.slug} has ${actualFaces.toLocaleString('en-US')} faces, above the ${entry.polygonBudget.max.toLocaleString(
      'en-US'
    )} face LOD0 budget. Reduce the model first or pass --faces with the optimized face count.`
  );
}

const targetRelative = `assets/aircraft/${entry.slug}/${entry.slug}-lod0${extension}`;
const target = resolve(root, 'replay-engine/public', targetRelative);
mkdirSync(dirname(target), { recursive: true });
copyFileSync(sourceFile, target);

entry.modelUrl = targetRelative;
entry.format = extension.slice(1);
entry.status = 'ready';
entry.polygonBudget.actual = actualFaces;

writeFileSync(libraryPath, `${JSON.stringify(library, null, 2)}\n`);

console.log(`Imported ${basename(sourceFile)} as ${targetRelative}`);
console.log(`Updated ${libraryPath}`);
console.log(`License manifest: ${entry.licenseFile}`);
console.log(`File size: ${statSync(target).size.toLocaleString('en-US')} bytes`);

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith('--')) {
      continue;
    }
    parsed[key.slice(2)] = argv[index + 1];
    index += 1;
  }
  return parsed;
}
