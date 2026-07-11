import type { Journey, JourneySegment, LocationPoint } from '../data/types';
import { getPrimaryFlightSegment } from '../data/types';
import { buildFlightOverlay } from '../flight/flightAnalytics';

export function createGpx(journey: Journey): string {
  const segment = getPrimaryFlightSegment(journey);
  const route = segment.derivedReplayRoute.points;
  const waypoints = buildFlightOverlay(journey, segment).events;

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<gpx version="1.1" creator="Travel Globe" xmlns="http://www.topografix.com/GPX/1/1">',
    `  <metadata><name>${escapeXml(journey.title)}</name><time>${journey.startTime}</time></metadata>`,
    ...waypoints.map((event) => (
      `  <wpt lat="${event.point.latitude}" lon="${event.point.longitude}"><ele>${event.point.altitudeMeters ?? 0}</ele><time>${event.timestamp}</time><name>${escapeXml(event.title)}</name></wpt>`
    )),
    '  <trk>',
    `    <name>${escapeXml(trackName(segment))}</name>`,
    '    <trkseg>',
    ...route.map((point) => `      <trkpt lat="${point.latitude}" lon="${point.longitude}"><ele>${point.altitudeMeters ?? 0}</ele><time>${point.timestamp}</time></trkpt>`),
    '    </trkseg>',
    '  </trk>',
    '</gpx>'
  ].join('\n');
}

export function createKml(journey: Journey): string {
  const segment = getPrimaryFlightSegment(journey);
  const overlay = buildFlightOverlay(journey, segment);
  const plannedCoordinates = toKmlCoordinates(overlay.plannedRoute);
  const actualCoordinates = toKmlCoordinates(segment.derivedReplayRoute.points);

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<kml xmlns="http://www.opengis.net/kml/2.2">',
    '  <Document>',
    `    <name>${escapeXml(journey.title)}</name>`,
    '    <Style id="planned"><LineStyle><color>ffffffff</color><width>3</width></LineStyle></Style>',
    '    <Style id="actual"><LineStyle><color>ff2bdc70</color><width>4</width></LineStyle></Style>',
    linePlacemark('Flight Plan', '#planned', plannedCoordinates),
    linePlacemark('Actual Track', '#actual', actualCoordinates),
    ...overlay.events.map((event) => [
      '    <Placemark>',
      `      <name>${escapeXml(event.title)}</name>`,
      `      <description>${escapeXml(event.kind)}</description>`,
      `      <Point><coordinates>${event.point.longitude},${event.point.latitude},${event.point.altitudeMeters ?? 0}</coordinates></Point>`,
      '    </Placemark>'
    ].join('\n')),
    '  </Document>',
    '</kml>'
  ].join('\n');
}

function linePlacemark(name: string, style: string, coordinates: string): string {
  return [
    '    <Placemark>',
    `      <name>${escapeXml(name)}</name>`,
    `      <styleUrl>${style}</styleUrl>`,
    '      <LineString><tessellate>1</tessellate><altitudeMode>absolute</altitudeMode>',
    `        <coordinates>${coordinates}</coordinates>`,
    '      </LineString>',
    '    </Placemark>'
  ].join('\n');
}

function toKmlCoordinates(points: LocationPoint[]): string {
  return points
    .map((point) => `${point.longitude},${point.latitude},${point.altitudeMeters ?? 0}`)
    .join(' ');
}

function trackName(segment: JourneySegment): string {
  return `${segment.origin.iataCode ?? segment.origin.name} to ${segment.destination.iataCode ?? segment.destination.name}`;
}

function escapeXml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}
