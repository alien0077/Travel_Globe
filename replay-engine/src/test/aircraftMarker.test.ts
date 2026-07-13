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

  it('creates visible, deterministic models for widebody and narrowbody aircraft', () => {
    for (const aircraftType of ['A321', 'B777', 'A380', 'B767']) {
      const marker = createAircraftMarker(aircraftType);
      const proceduralModel = marker.children.find((child) => child.name === `${aircraftType} procedural aircraft model`);

      expect(marker.name).toBe(`Aircraft ${aircraftType}`);
      expect(proceduralModel).toBeDefined();
      expect(proceduralModel?.children.length).toBeGreaterThan(5);
    }
  });
});
