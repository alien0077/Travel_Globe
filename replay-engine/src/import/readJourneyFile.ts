import { assertJourney } from '../data/validateJourney';
import type { Journey } from '../data/types';
import { readTravelGlobePackage } from '../export/travelglobePackage';

export async function readJourneyFile(file: File): Promise<Journey> {
  const value = file.name.endsWith('.travelglobe')
    ? await readTravelGlobePackage(file)
    : JSON.parse(await file.text()) as unknown;

  assertJourney(value);
  return value;
}
