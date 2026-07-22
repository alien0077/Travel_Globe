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

const offlinePackStateKey = 'travel-globe:offline-pack-state:v1';

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
      'Natural Earth geography regions',
      'GeoNames cities',
      'Travel Globe spatial grid',
      'OurAirports airport index',
      'OurAirports frequencies',
      'OurAirports navaids'
    ],
    attribution: [
      'Made with Natural Earth.',
      'Contains GeoNames data available under CC BY 4.0.',
      'Airport and runway data provided by OurAirports.'
    ]
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

export function loadOfflinePackState(): OfflinePackState {
  if (typeof localStorage === 'undefined') {
    return { packs: [] };
  }
  try {
    const raw = localStorage.getItem(offlinePackStateKey);
    if (!raw) {
      return { packs: [] };
    }
    const parsed = JSON.parse(raw) as OfflinePackState;
    if (!Array.isArray(parsed.packs)) {
      return { packs: [] };
    }
    return {
      packs: parsed.packs
        .filter((pack) => typeof pack.id === 'string')
        .map((pack) => reconcilePack(pack))
    };
  } catch {
    return { packs: [] };
  }
}

export function saveOfflinePackState(state: OfflinePackState): void {
  if (typeof localStorage === 'undefined') {
    return;
  }
  localStorage.setItem(offlinePackStateKey, JSON.stringify(state));
}

export function isPackInstalled(state: OfflinePackState, packId: string): boolean {
  return state.packs.some((pack) => pack.id === packId);
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
    return '資料檔已隨目前 Replay build 提供；尚未標記任何離線資料包';
  }
  return state.packs.map((pack) => `${pack.name}: ${pack.dataLayers.length} layers`).join(' | ');
}

function manifestSizeBytes(manifest: {
  files?: Array<{ bytes: number }>;
  sources?: Array<{ files: Array<{ bytes: number }> }>;
  payloads?: Record<string, Array<{ bytes: number }>>;
}): number {
  const directFiles = manifest.files ?? [];
  const sourceFiles = manifest.sources?.flatMap((source) => source.files) ?? [];
  const payloadFiles = Object.values(manifest.payloads ?? {}).flat();
  return [...directFiles, ...sourceFiles, ...payloadFiles].reduce((total, file) => total + file.bytes, 0);
}

function checksumFromGeneratedSources(parts: string[]): string {
  return parts.join('|').replace(/^sha256:/, '').slice(0, 24);
}

function reconcilePack(pack: OfflinePack): OfflinePack {
  const current = coreOfflinePacks.find((candidate) => candidate.id === pack.id);
  if (!current) {
    return pack;
  }
  return {
    ...current,
    installedAt: pack.installedAt
  };
}
