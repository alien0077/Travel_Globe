import { describe, expect, it } from 'vitest';
import { sampleJourney } from '../data/sampleJourney';
import { generateOfflineJournal } from '../journal/generateJournal';
import { createPhotoTimelineEvents } from '../media/photoMatcher';
import { evaluateNotifications } from '../notifications/notificationRules';
import {
  coreOfflinePacks,
  describeInstalledPacks,
  formatBytes,
  getInstalledSizeBytes,
  installPack
} from '../offline/offlinePacks';
import { reduceAutoRecordingState, type AutoRecordingContext } from '../recording/autoRecorder';
import { buildTimeMachineState } from '../time-machine/timeMachine';
import { buildPlanSummary, matchEventsToPlan } from '../travel-plan/planEngine';

describe('complete product mode services', () => {
  it('summarizes travel plan completion', () => {
    const plan = buildPlanSummary(sampleJourney);
    const matched = matchEventsToPlan(sampleJourney.events, plan.plannedPlaces);

    expect(plan.completedCount).toBe(2);
    expect(matched.every((place) => place.status === 'completed')).toBe(true);
  });

  it('generates an offline deterministic journal', () => {
    const journal = generateOfflineJournal(sampleJourney);

    expect(journal.title).toContain('Journal');
    expect(journal.markdown).toContain('Taipei to Tokyo Flight');
    expect(journal.markdown).toContain('Timeline');
  });

  it('builds time machine state from stored journeys', () => {
    const state = buildTimeMachineState([sampleJourney]);

    expect(state.years).toEqual([2026]);
    expect(state.countries).toEqual(['TW', 'JP']);
    expect(state.lifetimeDistanceMeters).toBeGreaterThan(2_000_000);
  });

  it('reduces automatic recording state from movement signals', () => {
    const context: AutoRecordingContext = {
      home: sampleJourney.segments[0].origin,
      state: 'Idle'
    };
    const possible = reduceAutoRecordingState(context, {
      timestamp: '2026-07-10T02:00:00Z',
      location: { latitude: 25.25, longitude: 121.5 },
      speedMetersPerSecond: 12
    });
    const recording = reduceAutoRecordingState(possible, {
      timestamp: '2026-07-10T02:05:00Z',
      location: { latitude: 25.5, longitude: 122.0 },
      speedMetersPerSecond: 80
    });

    expect(possible.state).toBe('PossibleJourney');
    expect(recording.state).toBe('JourneyRecording');
  });

  it('manages offline packs and notification rules', () => {
    const packState = installPack({ packs: [] }, coreOfflinePacks[0], '2026-07-10T00:00:00Z');
    const notifications = evaluateNotifications(sampleJourney.segments[0].derivedReplayRoute.points[1], 100);

    expect(packState.packs).toHaveLength(1);
    expect(getInstalledSizeBytes(packState)).toBe(coreOfflinePacks[0].sizeBytes);
    expect(formatBytes(getInstalledSizeBytes(packState))).toMatch(/MB$/);
    expect(describeInstalledPacks(packState)).toContain('Core Global Atlas');
    expect(notifications.map((item) => item.id)).toContain('gps-estimated');
    expect(notifications.map((item) => item.id)).toContain('storage-low');
  });

  it('creates photo timeline events from imported media candidates', () => {
    const events = createPhotoTimelineEvents(sampleJourney, [
      {
        id: 'media-1',
        name: 'haneda.jpg',
        createdAt: '2026-07-10T06:05:00Z',
        latitude: 35.55,
        longitude: 139.78
      }
    ]);

    expect(events[0].title).toBe('Photo: haneda.jpg');
    expect(events[0].source).toBe('photo');
  });
});
