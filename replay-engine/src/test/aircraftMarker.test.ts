import { describe, expect, it } from 'vitest';
import {
  AIRCRAFT_MODEL_TARGET_SIZE,
  AIRCRAFT_VISUAL_ALTITUDE_FLOOR_METERS
} from '../models/createAircraftMarker';

describe('aircraft visual sizing', () => {
  it('uses a restrained model scale for flight-system views', () => {
    expect(AIRCRAFT_MODEL_TARGET_SIZE).toBeLessThanOrEqual(0.18);
    expect(AIRCRAFT_VISUAL_ALTITUDE_FLOOR_METERS).toBeLessThanOrEqual(5_000);
  });
});
