import { describe, expect, it } from 'vitest';
import { listAirportSuggestions } from '../flight-preload/airportIndex';
import { matchAirportSuggestions } from '../ui/TravelGlobeApp';

describe('airport picker suggestions', () => {
  const airports = listAirportSuggestions();

  it('searches the full scheduled-service OurAirports index', () => {
    const matches = matchAirportSuggestions(airports, 'PAAP');

    expect(airports.length).toBeGreaterThan(4_000);
    expect(matches[0].iataCode).toBe('PTD');
    expect(matches[0].icaoCode).toBe('PAAP');
    expect(matches[0].name).toContain('Port Alexander');
  });

  it('prioritizes exact IATA matches for manual route edits', () => {
    const matches = matchAirportSuggestions(airports, 'PTD');

    expect(matches[0].iataCode).toBe('PTD');
    expect(matches[0].name).toContain('Port Alexander');
  });
});
