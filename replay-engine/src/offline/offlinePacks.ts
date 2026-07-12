import geoManifest from '../../../shared/offline-packs/core-global/manifest.json';
import ourAirportsManifest from '../../../shared/offline-packs/core-global/ourairports-manifest.json';

export interface OfflinePack {
  id: string;
  name: string;
  version: string;
  regionCodes: string[];
  sizeBytes: number;
  checksum: string;
  dataLayers: string[];
  attribution: string[];
  installedAt?: string;
}

export interface OfflinePackState {
  packs: OfflinePack[];
}

export const coreOfflinePacks: OfflinePack[] = [
  {
    id: 'core-global',
    name: 'Core Global Atlas',
    version: geoManifest.version,
    regionCodes: ['GLOBAL', ...geoManifest.contents.regionCodes],
    sizeBytes: manifestSizeBytes(geoManifest) + manifestSizeBytes(ourAirportsManifest),
    checksum: checksumFromGeneratedSources([geoManifest.indexes.boundaries, ourAirportsManifest.generatedFrom]),
    dataLayers: [
      'Natural Earth coastlines',
      'Natural Earth country borders',
      'OurAirports airport index',
      'OurAirports frequencies',
      'OurAirports navaids'
    ],
    attribution: ['Made with Natural Earth.', 'Airport and runway data provided by OurAirports.']
  },
  {
    id: 'east-asia-flight',
    name: 'East Asia Flight Context',
    version: ourAirportsManifest.version,
    regionCodes: ['TW', 'JP'],
    sizeBytes: Math.round(manifestSizeBytes(ourAirportsManifest) * 0.18),
    checksum: checksumFromGeneratedSources([ourAirportsManifest.generatedFrom, 'TW-JP']),
    dataLayers: ['TPE/NRT/HND airport context', 'nearby radio frequencies', 'associated navaids'],
    attribution: ['Airport and runway data provided by OurAirports.']
  }
];

export function installPack(state: OfflinePackState, pack: OfflinePack, installedAt = new Date().toISOString()): OfflinePackState {
  const installed = { ...pack, installedAt };
  return {
    packs: [...state.packs.filter((candidate) => candidate.id !== pack.id), installed]
  };
}

export function deletePack(state: OfflinePackState, packId: string): OfflinePackState {
  return {
    packs: state.packs.filter((pack) => pack.id !== packId)
  };
}

export function getInstalledSizeBytes(state: OfflinePackState): number {
  return state.packs.reduce((total, pack) => total + pack.sizeBytes, 0);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1_000) {
    return `${bytes} B`;
  }
  if (bytes < 1_000_000) {
    return `${(bytes / 1_000).toFixed(1)} KB`;
  }
  if (bytes < 1_000_000_000) {
    return `${(bytes / 1_000_000).toFixed(1)} MB`;
  }
  return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
}

export function describeInstalledPacks(state: OfflinePackState): string {
  if (state.packs.length === 0) {
    return 'No offline data installed';
  }
  return state.packs.map((pack) => `${pack.name}: ${pack.dataLayers.length} layers`).join(' | ');
}

function manifestSizeBytes(manifest: { files?: Array<{ bytes: number }>; sources?: Array<{ files: Array<{ bytes: number }> }> }): number {
  const directFiles = manifest.files ?? [];
  const sourceFiles = manifest.sources?.flatMap((source) => source.files) ?? [];
  return [...directFiles, ...sourceFiles].reduce((total, file) => total + file.bytes, 0);
}

function checksumFromGeneratedSources(parts: string[]): string {
  return parts.join('|').replace(/^sha256:/, '').slice(0, 24);
}
