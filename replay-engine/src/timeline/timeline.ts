import type { Journey, TimelineEvent } from '../data/types';

export function getSortedTimelineEvents(journey: Journey): TimelineEvent[] {
  return [...journey.events].sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
}

export function formatEventTime(event: TimelineEvent): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
    hourCycle: 'h23'
  }).format(new Date(event.timestamp));
}
