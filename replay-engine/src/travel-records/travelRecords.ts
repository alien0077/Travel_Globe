import type { GeographicPoint, Journey, TimelineEvent } from '../data/types';
import { getSortedTimelineEvents } from '../timeline/timeline';

export interface TravelRecord {
  id: string;
  title: string;
  subtitle: string;
  timestamp: string;
  dateLabel: string;
  region: TravelRegion;
  regionLabel: string;
  markerLabel: string;
  location: GeographicPoint;
  coordinateLabel: string;
  accent: string;
  tags: string[];
}

export type TravelRegion = 'east-asia' | 'se-asia' | 'europe' | 'americas' | 'south-asia' | 'oceania' | 'world';

export interface TravelRecordEdit {
  title?: string;
  subtitle?: string;
  timestamp?: string;
  note?: string;
  hidden?: boolean;
}

export interface TravelRecordEdits {
  records: Record<string, TravelRecordEdit>;
}

export interface TravelRecordSummary {
  totalTrips: number;
  countries: string[];
  regions: Array<{ region: TravelRegion; label: string; count: number }>;
  years: Array<{ year: string; count: number }>;
}

const regionLabels: Record<TravelRegion, string> = {
  'east-asia': 'East Asia',
  'se-asia': 'SE Asia',
  europe: 'Europe',
  americas: 'Americas',
  'south-asia': 'South Asia',
  oceania: 'Oceania',
  world: 'World'
};

const regionAccents: Record<TravelRegion, string> = {
  'east-asia': '#18a999',
  'se-asia': '#e7a93c',
  europe: '#5c9ee6',
  americas: '#d95f59',
  'south-asia': '#8b77d7',
  oceania: '#36a2c8',
  world: '#74808a'
};

export function buildTravelRecords(journey: Journey): TravelRecord[] {
  const edits = readTravelRecordEdits(journey);
  const events = getSortedTimelineEvents(journey).filter((event) => event.location);
  const records = events.map((event) => applyRecordEdit(createRecordFromEvent(event), edits));

  if (records.length > 0) {
    return records.filter((record) => !edits.records[record.id]?.hidden);
  }

  return journey.segments
    .flatMap((segment) => [
      applyRecordEdit(createFallbackRecord(`${segment.id}-origin`, segment.origin.name, segment.startTime, segment.origin), edits),
      applyRecordEdit(createFallbackRecord(`${segment.id}-destination`, segment.destination.name, segment.endTime, segment.destination), edits)
    ])
    .filter((record) => !edits.records[record.id]?.hidden);
}

export function summarizeTravelRecords(journey: Journey, records: TravelRecord[]): TravelRecordSummary {
  const countries = new Set<string>();
  const regionCounts = new Map<TravelRegion, number>();
  const yearCounts = new Map<string, number>();

  for (const country of readCountries(journey)) {
    countries.add(country);
  }

  for (const record of records) {
    regionCounts.set(record.region, (regionCounts.get(record.region) ?? 0) + 1);
    yearCounts.set(record.dateLabel.slice(-4), (yearCounts.get(record.dateLabel.slice(-4)) ?? 0) + 1);
  }

  const regions = [...regionCounts.entries()]
    .map(([region, count]) => ({ region, label: regionLabels[region], count }))
    .sort((left, right) => right.count - left.count);

  const years = [...yearCounts.entries()]
    .map(([year, count]) => ({ year, count }))
    .sort((left, right) => left.year.localeCompare(right.year));

  return {
    totalTrips: Math.max(1, journey.segments.length),
    countries: [...countries],
    regions,
    years
  };
}

export function getRegionLabel(region: TravelRegion): string {
  return regionLabels[region];
}

export function readTravelRecordEdits(journey: Journey): TravelRecordEdits {
  const raw = journey.metadata.travelRecordEdits;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { records: {} };
  }
  const records = (raw as { records?: unknown }).records;
  if (!records || typeof records !== 'object' || Array.isArray(records)) {
    return { records: {} };
  }
  return { records: records as Record<string, TravelRecordEdit> };
}

export function writeTravelRecordEdit(
  journey: Journey,
  recordId: string,
  edit: TravelRecordEdit
): Journey {
  const edits = readTravelRecordEdits(journey);
  return {
    ...journey,
    metadata: {
      ...journey.metadata,
      travelRecordEdits: {
        records: {
          ...edits.records,
          [recordId]: {
            ...edits.records[recordId],
            ...edit
          }
        }
      }
    }
  };
}

function createRecordFromEvent(event: TimelineEvent): TravelRecord {
  const location = event.location as GeographicPoint;
  const region = classifyRegion(location);
  return {
    id: event.id,
    title: event.title,
    subtitle: event.subtitle ?? event.type,
    timestamp: event.timestamp,
    dateLabel: formatRecordDate(event.timestamp),
    region,
    regionLabel: regionLabels[region],
    markerLabel: markerLabelFor(event.title, region),
    location,
    coordinateLabel: formatCoordinate(location),
    accent: regionAccents[region],
    tags: [regionLabels[region], event.type.replace(/([A-Z])/g, ' $1').trim()]
  };
}

function applyRecordEdit(record: TravelRecord, edits: TravelRecordEdits): TravelRecord {
  const edit = edits.records[record.id];
  if (!edit) {
    return record;
  }
  return {
    ...record,
    title: edit.title?.trim() || record.title,
    subtitle: edit.subtitle?.trim() || record.subtitle,
    timestamp: edit.timestamp && Number.isFinite(Date.parse(edit.timestamp)) ? edit.timestamp : record.timestamp,
    dateLabel: edit.timestamp && Number.isFinite(Date.parse(edit.timestamp)) ? formatRecordDate(edit.timestamp) : record.dateLabel,
    tags: edit.note?.trim() ? [...record.tags, 'Edited'] : record.tags
  };
}

function createFallbackRecord(id: string, title: string, timestamp: string, location: GeographicPoint): TravelRecord {
  const region = classifyRegion(location);
  return {
    id,
    title,
    subtitle: 'Journey waypoint',
    timestamp,
    dateLabel: formatRecordDate(timestamp),
    region,
    regionLabel: regionLabels[region],
    markerLabel: markerLabelFor(title, region),
    location,
    coordinateLabel: formatCoordinate(location),
    accent: regionAccents[region],
    tags: [regionLabels[region], 'Waypoint']
  };
}

function classifyRegion(point: GeographicPoint): TravelRegion {
  const { latitude, longitude } = point;
  if (latitude >= 18 && latitude <= 48 && longitude >= 115 && longitude <= 147) {
    return 'east-asia';
  }
  if (latitude >= -12 && latitude <= 24 && longitude >= 95 && longitude <= 142) {
    return 'se-asia';
  }
  if (latitude >= 35 && latitude <= 72 && longitude >= -12 && longitude <= 42) {
    return 'europe';
  }
  if (latitude >= -56 && latitude <= 72 && longitude >= -170 && longitude <= -30) {
    return 'americas';
  }
  if (latitude >= 5 && latitude <= 34 && longitude >= 60 && longitude <= 95) {
    return 'south-asia';
  }
  if (latitude >= -48 && latitude <= 0 && longitude >= 110 && longitude <= 180) {
    return 'oceania';
  }
  return 'world';
}

function formatRecordDate(timestamp: string): string {
  return new Intl.DateTimeFormat('en', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC'
  }).format(new Date(timestamp));
}

function formatCoordinate(point: GeographicPoint): string {
  const latitude = `${Math.abs(point.latitude).toFixed(2)}${point.latitude >= 0 ? 'N' : 'S'}`;
  const longitude = `${Math.abs(point.longitude).toFixed(2)}${point.longitude >= 0 ? 'E' : 'W'}`;
  return `${latitude}, ${longitude}`;
}

function markerLabelFor(title: string, region: TravelRegion): string {
  if (/tokyo|haneda|japan/i.test(title)) {
    return 'JP';
  }
  if (/taipei|taoyuan|taiwan/i.test(title)) {
    return 'TW';
  }
  return regionLabels[region].slice(0, 2).toUpperCase();
}

function readCountries(journey: Journey): string[] {
  const countries = new Set<string>();
  for (const segment of journey.segments) {
    if (segment.origin.countryCode) {
      countries.add(segment.origin.countryCode);
    }
    if (segment.destination.countryCode) {
      countries.add(segment.destination.countryCode);
    }
  }
  const statsCountries = journey.statistics?.countriesVisited;
  if (Array.isArray(statsCountries)) {
    for (const country of statsCountries) {
      if (typeof country === 'string') {
        countries.add(country);
      }
    }
  }
  return [...countries];
}
