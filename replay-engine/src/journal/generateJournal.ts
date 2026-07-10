import type { Journey } from '../data/types';
import { formatDistance } from '../geo/geodesy';
import { summarizeJourney } from '../statistics/journeyStatistics';
import { getSortedTimelineEvents } from '../timeline/timeline';

export interface JournalOutput {
  title: string;
  markdown: string;
}

export function generateOfflineJournal(journey: Journey): JournalOutput {
  const summary = summarizeJourney(journey);
  const events = getSortedTimelineEvents(journey);
  const firstEvent = events[0];
  const lastEvent = events[events.length - 1];
  const route = journey.segments[0];

  const lines = [
    `# ${journey.title}`,
    '',
    `Travel Globe replayed this journey from ${route.origin.name} to ${route.destination.name}.`,
    `Total replay distance was about ${formatDistance(summary.totalDistanceMeters)} across ${summary.segmentCount} segment.`,
    `The route touched ${summary.countriesVisited.join(' and ')} and included ${summary.eventCount} timeline events.`,
    ''
  ];

  if (firstEvent && lastEvent) {
    lines.push(
      `The journey began with "${firstEvent.title}" and ended with "${lastEvent.title}".`,
      ''
    );
  }

  lines.push('## Timeline');
  for (const event of events) {
    lines.push(`- ${new Date(event.timestamp).toISOString()}: ${event.title}`);
  }

  return {
    title: `${journey.title} Journal`,
    markdown: lines.join('\n')
  };
}
