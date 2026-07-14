import { describe, expect, it } from 'vitest';
import { sampleJourney } from '../data/sampleJourney';
import { getPrimaryFlightSegment } from '../data/types';
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

  it('shows GPS and photo visit points as travel records', () => {
    const segment = getPrimaryFlightSegment(sampleJourney);
    const gpsEventId = `visit-${segment.id}-gps`;
    const photoEventId = `visit-${segment.id}-photo`;
    const journey = {
      ...sampleJourney,
      events: [
        ...sampleJourney.events,
        {
          id: gpsEventId,
          journeyId: sampleJourney.id,
          segmentId: segment.id,
          timestamp: segment.startTime,
          type: 'visitPoint',
          title: 'GPS打卡',
          subtitle: '使用目前 iPhone GPS 新增',
          location: { latitude: 35.6812, longitude: 139.7671 },
          mediaIds: [],
          importance: 0.74,
          source: 'quickGps',
          metadata: { editable: true }
        },
        {
          id: photoEventId,
          journeyId: sampleJourney.id,
          segmentId: segment.id,
          timestamp: segment.endTime,
          type: 'visitPoint',
          title: '照片打卡',
          subtitle: '從照片 GPS 匯入',
          location: { latitude: 35.6895, longitude: 139.6917 },
          mediaIds: [],
          importance: 0.78,
          source: 'photoGps',
          metadata: { editable: true }
        }
      ],
      segments: sampleJourney.segments.map((candidate) =>
        candidate.id === segment.id
          ? { ...candidate, events: [...candidate.events, gpsEventId, photoEventId] }
          : candidate
      )
    };
    const records = buildTravelRecords(journey);

    expect(records.some((record) => record.title === 'GPS打卡')).toBe(true);
    expect(records.some((record) => record.title === '照片打卡')).toBe(true);
  });
});
