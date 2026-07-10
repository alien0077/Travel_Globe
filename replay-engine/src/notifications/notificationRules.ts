import type { LocationPoint } from '../data/types';

export interface TravelNotification {
  id: string;
  title: string;
  body: string;
  severity: 'info' | 'warning';
}

export function evaluateNotifications(point: LocationPoint, storageRemainingBytes: number): TravelNotification[] {
  const notifications: TravelNotification[] = [];

  if (point.source === 'estimated' || point.source === 'interpolated') {
    notifications.push({
      id: 'gps-estimated',
      title: 'GPS gap estimated',
      body: 'Replay is using display-only estimated movement until the next measured fix.',
      severity: 'warning'
    });
  }

  if (storageRemainingBytes < 500_000_000) {
    notifications.push({
      id: 'storage-low',
      title: 'Storage warning',
      body: 'Available storage is low for long journey recording.',
      severity: 'warning'
    });
  }

  return notifications;
}
