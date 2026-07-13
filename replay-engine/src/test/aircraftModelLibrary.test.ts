import { describe, expect, it } from 'vitest';
import aircraftLibraryJson from '../../public/models/aircraft/library.json';
import {
  findAircraftModel,
  isAircraftModelReady,
  normalizeAircraftType,
  REQUIRED_AIRCRAFT_TYPES,
  selectAircraftModel,
  type AircraftModelLibrary
} from '../models/aircraftModelLibrary';

const aircraftLibrary = aircraftLibraryJson as AircraftModelLibrary;

describe('aircraft model library', () => {
  it('keeps a model slot for every required aircraft family', () => {
    expect(aircraftLibrary.aircraft.map((entry) => entry.id).sort()).toEqual([...REQUIRED_AIRCRAFT_TYPES].sort());
  });

  it('normalizes common aircraft type labels to model library IDs', () => {
    expect(normalizeAircraftType('Airbus A380-800')).toBe('A380');
    expect(normalizeAircraftType('Boeing 787-9 Dreamliner')).toBe('B787');
    expect(normalizeAircraftType('B77W')).toBe('B777');
    expect(normalizeAircraftType('A359')).toBe('A350');
    expect(findAircraftModel(aircraftLibrary, 'Boeing 737-800')?.id).toBe('B737');
    expect(findAircraftModel(aircraftLibrary, 'a350-900')?.id).toBe('A350');
  });

  it('selects the requested ready model or falls back to the default A320 model', () => {
    const b737 = aircraftLibrary.aircraft.find((entry) => entry.id === 'B737');
    const a320 = aircraftLibrary.aircraft.find((entry) => entry.id === 'A320');
    const a380 = aircraftLibrary.aircraft.find((entry) => entry.id === 'A380');
    expect(b737).toBeDefined();
    expect(a320).toBeDefined();
    expect(a380).toBeDefined();

    const library: AircraftModelLibrary = {
      ...aircraftLibrary,
      aircraft: [
        {
          ...b737!,
          status: 'ready',
          modelUrl: 'assets/aircraft/b737-800/b737-800-lod0.glb',
          license: 'CC BY',
          author: 'Test Author',
          sourceName: 'Sketchfab',
          sourceUrl: 'https://sketchfab.com/3d-models/test',
          attribution: 'Test model by Test Author via Sketchfab.',
          commercialUse: true,
          derivativesAllowed: true,
          editorialOnly: false,
          polygonBudget: { min: 500, max: 40000, actual: 8000 }
        },
        {
          ...a380!,
          status: 'ready',
          modelUrl: 'assets/aircraft/a380-800/a380-800-lod0.glb',
          license: 'CC BY',
          author: 'Test Author',
          sourceName: 'Sketchfab',
          sourceUrl: 'https://sketchfab.com/3d-models/test',
          attribution: 'Test model by Test Author via Sketchfab.',
          commercialUse: true,
          derivativesAllowed: true,
          editorialOnly: false,
          polygonBudget: { min: 500, max: 40000, actual: 8000 }
        },
        {
          ...a320!,
          status: 'ready',
          modelUrl: 'assets/aircraft/a320-200/a320-200-lod0.glb',
          license: 'CC BY',
          author: 'Test Author',
          sourceName: 'Sketchfab',
          sourceUrl: 'https://sketchfab.com/3d-models/test',
          attribution: 'Test model by Test Author via Sketchfab.',
          commercialUse: true,
          derivativesAllowed: true,
          editorialOnly: false,
          polygonBudget: { min: 500, max: 40000, actual: 8000 }
        }
      ]
    };

    expect(isAircraftModelReady(library.aircraft[0])).toBe(true);
    expect(isAircraftModelReady(library.aircraft[1])).toBe(true);
    expect(selectAircraftModel(library, 'Airbus A380-800')?.id).toBe('A380');
    expect(selectAircraftModel(library, undefined)?.id).toBe('A320');
    expect(selectAircraftModel(library, 'Unknown aircraft')?.id).toBe('A320');
  });

  it('rejects non-commercial, no-derivatives, editorial, and non-offline ready assets', () => {
    for (const entry of aircraftLibrary.aircraft) {
      expect(entry.format === 'glb' || entry.format === 'gltf').toBe(true);
      expect(entry.slug.length).toBeGreaterThan(0);
      expect(entry.variants.length).toBeGreaterThan(0);
      expect(entry.licenseFile).toMatch(/^assets\/aircraft\/.+\/license\.json$/);
      expect(entry.polygonBudget.min).toBeGreaterThanOrEqual(500);
      expect(entry.polygonBudget.max).toBeLessThanOrEqual(3_000_000);

      if (entry.status !== 'ready') {
        expect(isAircraftModelReady(entry)).toBe(false);
        continue;
      }

      expect(entry.license === 'CC0' || entry.license === 'CC BY').toBe(true);
      expect(entry.commercialUse).toBe(true);
      expect(entry.derivativesAllowed).toBe(true);
      expect(entry.editorialOnly).toBe(false);
      expect(entry.modelUrl).toMatch(/\.(glb|gltf)$/);
      expect(entry.author.length).toBeGreaterThan(0);
      expect(entry.sourceUrl).toMatch(/^https?:\/\//);
      expect(entry.attribution).toContain(entry.author);
      expect(entry.attribution).toContain(entry.sourceName);
    }
  });
});
