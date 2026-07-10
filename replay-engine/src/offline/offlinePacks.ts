export interface OfflinePack {
  id: string;
  name: string;
  version: string;
  regionCodes: string[];
  sizeBytes: number;
  checksum: string;
  installedAt?: string;
}

export interface OfflinePackState {
  packs: OfflinePack[];
}

export const coreOfflinePacks: OfflinePack[] = [
  {
    id: 'core-global',
    name: 'Core Global Labels',
    version: '1.0.0',
    regionCodes: ['GLOBAL'],
    sizeBytes: 42_000_000,
    checksum: 'core-global-fixture'
  },
  {
    id: 'east-asia-flight',
    name: 'East Asia Flight Context',
    version: '1.0.0',
    regionCodes: ['TW', 'JP'],
    sizeBytes: 68_000_000,
    checksum: 'east-asia-fixture'
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
