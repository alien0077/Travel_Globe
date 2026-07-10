import { describe, expect, it } from 'vitest';
import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import journeySchema from '../../../contracts/journey.schema.json';
import locationPointSchema from '../../../contracts/location-point.schema.json';
import flightSegmentSchema from '../../../contracts/flight-segment.schema.json';
import timelineEventSchema from '../../../contracts/timeline-event.schema.json';
import travelPlanSchema from '../../../contracts/travel-plan.schema.json';
import mediaItemSchema from '../../../contracts/media-item.schema.json';
import sampleJourney from '../../../shared/sample-journeys/taipei-tokyo-flight.json';

describe('journey schema', () => {
  it('validates the Taipei to Tokyo sample journey', () => {
    const ajv = new Ajv2020({ allErrors: true });
    addFormats(ajv);
    ajv.addSchema(locationPointSchema);
    ajv.addSchema(flightSegmentSchema);
    ajv.addSchema(timelineEventSchema);
    ajv.addSchema(travelPlanSchema);
    ajv.addSchema(mediaItemSchema);

    const validate = ajv.compile(journeySchema);
    const valid = validate(sampleJourney);

    expect(validate.errors ?? []).toEqual([]);
    expect(valid).toBe(true);
  });
});
