import { describe, expect, it } from 'vitest';
import { sampleJourney } from '../data/sampleJourney';
import { buildTravelRecords, writeTravelRecordEdit } from '../travel-records/travelRecords';

describe('travel record edits', () => {
  it('applies title edits without changing source journey events', () => {
    const originalRecords = buildTravelRecords(sampleJourney);
    const originalEventCount = sampleJourney.events.length;
    const edited = writeTravelRecordEdit(sampleJourney, originalRecords[0].id, {
      title: '手動修改標題',
      subtitle: '人工備註'
    });
    const records = buildTravelRecords(edited);

    expect(records[0].title).toBe('手動修改標題');
    expect(records[0].subtitle).toBe('人工備註');
    expect(sampleJourney.events).toHaveLength(originalEventCount);
  });

  it('hides records through the overlay instead of deleting source events', () => {
    const originalRecords = buildTravelRecords(sampleJourney);
    const edited = writeTravelRecordEdit(sampleJourney, originalRecords[0].id, { hidden: true });
    const records = buildTravelRecords(edited);

    expect(records.some((record) => record.id === originalRecords[0].id)).toBe(false);
    expect(edited.events.some((event) => event.id === originalRecords[0].id)).toBe(true);
  });
});
