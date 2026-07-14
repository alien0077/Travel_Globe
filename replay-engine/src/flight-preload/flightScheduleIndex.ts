import { normalizeIata } from './airportIndex';

export interface FlightScheduleRecord {
  flightNumber: string;
  airlineName: string;
  originIata: string;
  destinationIata: string;
  defaultDepartureTime?: string;
  defaultDurationMinutes?: number;
  defaultAircraftType?: string;
  source: 'offline-schedule-index';
}

const schedules: FlightScheduleRecord[] = [
  {
    flightNumber: 'CI100',
    airlineName: 'China Airlines',
    originIata: 'TPE',
    destinationIata: 'NRT',
    defaultDepartureTime: '09:30',
    defaultDurationMinutes: 185,
    defaultAircraftType: 'A350',
    source: 'offline-schedule-index'
  },
  {
    flightNumber: 'BR190',
    airlineName: 'EVA Air',
    originIata: 'TPE',
    destinationIata: 'HND',
    defaultDepartureTime: '09:30',
    defaultDurationMinutes: 190,
    defaultAircraftType: 'B787',
    source: 'offline-schedule-index'
  },
  {
    flightNumber: 'FD234',
    airlineName: 'Thai AirAsia',
    originIata: 'KHH',
    destinationIata: 'NRT',
    defaultDurationMinutes: 235,
    defaultAircraftType: 'A320',
    source: 'offline-schedule-index'
  },
  {
    flightNumber: 'FD235',
    airlineName: 'Thai AirAsia',
    originIata: 'NRT',
    destinationIata: 'KHH',
    defaultDurationMinutes: 235,
    defaultAircraftType: 'A320',
    source: 'offline-schedule-index'
  }
];

export function findScheduleByFlightNumber(flightNumber: string): FlightScheduleRecord | undefined {
  const normalized = normalizeFlightNumber(flightNumber);
  return schedules.find((schedule) => schedule.flightNumber === normalized);
}

export function normalizeFlightNumber(value: string): string {
  return value.trim().toUpperCase().replace(/\s+/g, '');
}

export function normalizeOptionalIata(value?: string): string | undefined {
  const normalized = normalizeIata(value ?? '');
  return normalized.length > 0 ? normalized : undefined;
}
