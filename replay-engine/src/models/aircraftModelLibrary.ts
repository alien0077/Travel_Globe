export const REQUIRED_AIRCRAFT_TYPES = ['A320', 'A321', 'B737', 'B767', 'B777', 'B787', 'A350', 'A380'] as const;

export type RequiredAircraftType = (typeof REQUIRED_AIRCRAFT_TYPES)[number];
export const DEFAULT_AIRCRAFT_TYPE = 'A320' satisfies RequiredAircraftType;
export type AircraftModelFormat = 'glb' | 'gltf';
export type AircraftModelLicense = 'CC0' | 'CC BY';

export interface AircraftModelPolygonBudget {
  min: number;
  max: number;
  actual?: number;
}

export interface AircraftModelSource {
  platform: 'Sketchfab' | 'Local' | 'Other';
  modelUid?: string;
  modelUrl?: string;
}

export interface AircraftModelEntry {
  id: RequiredAircraftType;
  slug: string;
  icaoType: string;
  label: string;
  aliases: string[];
  variants: string[];
  status: 'missing' | 'candidate' | 'ready';
  modelUrl: string;
  licenseUrl?: string;
  licenseFile?: string;
  format: AircraftModelFormat;
  polygonBudget: AircraftModelPolygonBudget;
  license: AircraftModelLicense | null;
  author: string;
  sourceName: string;
  sourceUrl: string;
  source: AircraftModelSource;
  attribution: string;
  commercialUse: boolean;
  derivativesAllowed: boolean;
  editorialOnly: boolean;
  neutralizeLivery: boolean;
}

export interface AircraftModelLibrary {
  schemaVersion: string;
  policy: {
    allowedLicenses: AircraftModelLicense[];
    disallowedLicenseKeywords: string[];
    requireCommercialUse: boolean;
    requireDerivativesAllowed: boolean;
    requireSourceAttribution: boolean;
    requireOfflineBundle: boolean;
    polygonBudget: AircraftModelPolygonBudget;
  };
  aircraft: AircraftModelEntry[];
}

export function findAircraftModel(
  library: AircraftModelLibrary,
  aircraftType: string | undefined
): AircraftModelEntry | undefined {
  if (!aircraftType) {
    return undefined;
  }

  const normalized = normalizeAircraftType(aircraftType);
  return library.aircraft.find((entry) => {
    const candidates = [entry.id, entry.slug, entry.icaoType, entry.label, ...entry.aliases, ...entry.variants];
    return candidates.some((candidate) => normalizeAircraftType(candidate) === normalized);
  });
}

export function selectAircraftModel(
  library: AircraftModelLibrary,
  aircraftType: string | undefined
): AircraftModelEntry | undefined {
  const requested = findAircraftModel(library, aircraftType);
  if (requested && isAircraftModelReady(requested)) {
    return requested;
  }

  const defaultAircraft = findAircraftModel(library, DEFAULT_AIRCRAFT_TYPE);
  if (defaultAircraft && isAircraftModelReady(defaultAircraft)) {
    return defaultAircraft;
  }

  return library.aircraft.find(isAircraftModelReady);
}

export function isAircraftModelReady(entry: AircraftModelEntry): boolean {
  return (
    entry.status === 'ready' &&
    entry.modelUrl.trim().length > 0 &&
    isAllowedAircraftLicense(entry.license) &&
    entry.commercialUse &&
    entry.derivativesAllowed &&
    !entry.editorialOnly &&
    isAllowedAircraftModelFormat(entry.format) &&
    isWithinPolygonBudget(entry.polygonBudget)
  );
}

export function isAllowedAircraftLicense(license: AircraftModelLicense | null): license is AircraftModelLicense {
  return license === 'CC0' || license === 'CC BY';
}

export function isAllowedAircraftModelFormat(format: string): format is AircraftModelFormat {
  return format === 'glb' || format === 'gltf';
}

export function isWithinPolygonBudget(budget: AircraftModelPolygonBudget): boolean {
  const actual = budget.actual ?? budget.min;
  return budget.min >= 500 && budget.max <= 3000000 && actual >= budget.min && actual <= budget.max;
}

export function normalizeAircraftType(value: string): string {
  const compact = value.toUpperCase().replace(/[^A-Z0-9]/g, '');
  if (/B738|B739|B737800|BOEING737800/.test(compact)) return 'B737';
  if (/B763|B767300|BOEING767300/.test(compact)) return 'B767';
  if (/B772|B77W|B777300ER|BOEING777300ER/.test(compact)) return 'B777';
  if (/B788|B789|B7879|BOEING7879|DREAMLINER/.test(compact)) return 'B787';
  if (/A319|A20N|A320200|AIRBUSA320200/.test(compact)) return 'A320';
  if (/A21N|A321NEO|AIRBUSA321NEO/.test(compact)) return 'A321';
  if (/A359|A35K|A350900|AIRBUSA350900/.test(compact)) return 'A350';
  if (/A388|A380800|AIRBUSA380800/.test(compact)) return 'A380';
  if (/A320|AIRBUSA320/.test(compact)) return 'A320';
  if (/A321|AIRBUSA321/.test(compact)) return 'A321';
  if (/B737|BOEING737|737/.test(compact)) return 'B737';
  if (/B767|BOEING767|767/.test(compact)) return 'B767';
  if (/B777|BOEING777|777/.test(compact)) return 'B777';
  if (/B787|BOEING787|787|DREAMLINER/.test(compact)) return 'B787';
  if (/A350|AIRBUSA350/.test(compact)) return 'A350';
  if (/A380|AIRBUSA380/.test(compact)) return 'A380';
  return compact;
}
