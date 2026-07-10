import type { Journey, TimelineEvent } from '../data/types';

export interface MediaCandidate {
  id: string;
  name: string;
  createdAt: string;
  latitude?: number;
  longitude?: number;
}

export function createPhotoTimelineEvents(journey: Journey, media: MediaCandidate[]): TimelineEvent[] {
  return media.map((item) => ({
    id: `photo-${item.id}`,
    journeyId: journey.id,
    timestamp: item.createdAt,
    type: 'userNote',
    title: `Photo: ${item.name}`,
    location:
      typeof item.latitude === 'number' && typeof item.longitude === 'number'
        ? { latitude: item.latitude, longitude: item.longitude }
        : undefined,
    mediaIds: [item.id],
    importance: 0.35,
    source: 'photo',
    metadata: {
      fileName: item.name
    }
  }));
}
