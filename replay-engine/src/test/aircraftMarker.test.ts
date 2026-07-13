import { describe, expect, it } from 'vitest';
import {
  AIRCRAFT_MODEL_TARGET_SIZE,
  AIRCRAFT_VISUAL_ALTITUDE_FLOOR_METERS,
  createAircraftMarker
} from '../models/createAircraftMarker';

describe('aircraft visual sizing', () => {
  it('uses a restrained model scale for flight-system views', () => {
    expect(AIRCRAFT_MODEL_TARGET_SIZE).toBeLessThanOrEqual(0.18);
    expect(AIRCRAFT_VISUAL_ALTITUDE_FLOOR_METERS).toBeLessThanOrEqual(5_000);
  });

  it('starts every aircraft marker with the requested library type and an A320 loading silhouette', () => {
    for (const aircraftType of ['A321', 'B777', 'A380', 'B767']) {
      const marker = createAircraftMarker(aircraftType);
      const loadingModel = marker.children.find((child) => child.name === 'A320 loading aircraft silhouette');

      expect(marker.name).toBe(`Aircraft ${aircraftType}`);
      expect(loadingModel).toBeDefined();
      expect(loadingModel?.children.length).toBeGreaterThan(1);
    }
  });

  it('defaults unknown or missing aircraft types to A320 before the external model loads', () => {
    expect(createAircraftMarker().name).toBe('Aircraft A320');
    expect(createAircraftMarker('Unknown type').name).toBe('Aircraft A320');
  });
});
