import CoreLocation
import Foundation

final class LocationRecorder: NSObject, CLLocationManagerDelegate {
    private struct OneShotLocationRequest {
        var journeyId: UUID
        var segmentId: String?
        var continuation: CheckedContinuation<LocationPointRecord, Error>
    }

    private let manager = CLLocationManager()
    private let repository: JourneyRepository
    private var activeJourneyId: UUID?
    private var activeSegmentId: String?
    private var profile: RecordingProfile = .balanced
    private var lastAcceptedPoint: LocationPointRecord?
    private var lastSavedPoint: LocationPointRecord?
    private var oneShotLocationRequest: OneShotLocationRequest?

    var onLocationUpdate: ((LocationPointRecord) -> Void)?

    init(repository: JourneyRepository) {
        self.repository = repository
        super.init()
        manager.delegate = self
    }

    func start(journeyId: UUID, segmentId: String?, profile: RecordingProfile) async throws {
        activeJourneyId = journeyId
        activeSegmentId = segmentId
        self.profile = profile
        lastAcceptedPoint = nil
        lastSavedPoint = nil
        configure(profile: profile)
        manager.requestWhenInUseAuthorization()
        manager.requestAlwaysAuthorization()
        manager.startUpdatingLocation()
    }

    func stop() async {
        manager.stopUpdatingLocation()
        if let activeJourneyId {
            try? await repository.completeJourney(id: activeJourneyId, endedAt: Date())
        }
        activeJourneyId = nil
        activeSegmentId = nil
        lastAcceptedPoint = nil
        lastSavedPoint = nil
    }

    func requestCurrentPoint(journeyId: UUID, segmentId: String?) async throws -> LocationPointRecord {
        try await withCheckedThrowingContinuation { continuation in
            oneShotLocationRequest = OneShotLocationRequest(
                journeyId: journeyId,
                segmentId: segmentId,
                continuation: continuation
            )
            manager.requestWhenInUseAuthorization()
            manager.desiredAccuracy = kCLLocationAccuracyBest
            manager.distanceFilter = kCLDistanceFilterNone
            manager.requestLocation()
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        if let request = oneShotLocationRequest {
            if let point = locations.compactMap({ location in
                makePoint(
                    from: location,
                    journeyId: request.journeyId,
                    segmentId: request.segmentId,
                    source: "quickGps",
                    checkTimestampOrder: false
                )
            }).last {
                oneShotLocationRequest = nil
                request.continuation.resume(returning: point)
            } else {
                oneShotLocationRequest = nil
                request.continuation.resume(throwing: LocationRecorderError.noUsableLocation)
            }
        }

        guard let journeyId = activeJourneyId else { return }
        for location in locations {
            guard let point = makePoint(from: location, journeyId: journeyId) else {
                continue
            }
            lastAcceptedPoint = point
            onLocationUpdate?(point)

            guard shouldPersist(point) else {
                continue
            }
            lastSavedPoint = point
            Task {
                try? await repository.saveLocationPoint(point)
            }
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        if let request = oneShotLocationRequest {
            oneShotLocationRequest = nil
            request.continuation.resume(throwing: error)
        }
    }

    private func makePoint(
        from location: CLLocation,
        journeyId: UUID,
        segmentId: String? = nil,
        source: String = "gps",
        checkTimestampOrder: Bool = true
    ) -> LocationPointRecord? {
        let coordinate = location.coordinate
        guard
            coordinate.latitude.isFinite,
            coordinate.longitude.isFinite,
            (-90...90).contains(coordinate.latitude),
            (-180...180).contains(coordinate.longitude),
            location.horizontalAccuracy.isFinite,
            location.horizontalAccuracy >= 0,
            location.horizontalAccuracy <= maxHorizontalAccuracyMeters,
            checkTimestampOrder ? (lastAcceptedPoint.map({ location.timestamp > $0.timestamp }) ?? true) : true
        else {
            return nil
        }

        return LocationPointRecord(
                id: UUID(),
                journeyId: journeyId,
                segmentId: segmentId ?? activeSegmentId,
                timestamp: location.timestamp,
                latitude: coordinate.latitude,
                longitude: coordinate.longitude,
                altitudeMeters: location.verticalAccuracy >= 0 ? location.altitude : nil,
                speedMetersPerSecond: location.speed >= 0 ? location.speed : nil,
                courseDegrees: location.course >= 0 ? location.course : nil,
                horizontalAccuracyMeters: location.horizontalAccuracy,
                verticalAccuracyMeters: location.verticalAccuracy >= 0 ? location.verticalAccuracy : nil,
                source: source
            )
    }

    private func shouldPersist(_ point: LocationPointRecord) -> Bool {
        guard point.source == "gps" else { return false }
        guard let previous = lastSavedPoint else { return true }

        let elapsedSeconds = point.timestamp.timeIntervalSince(previous.timestamp)
        if elapsedSeconds >= minimumSaveIntervalSeconds {
            return true
        }
        if distanceMeters(from: previous, to: point) >= minimumSaveDistanceMeters {
            return true
        }
        if courseDeltaDegrees(previous.courseDegrees, point.courseDegrees) >= significantCourseChangeDegrees {
            return true
        }

        let previousAltitude = previous.altitudeMeters ?? 0
        let currentAltitude = point.altitudeMeters ?? previousAltitude
        return abs(currentAltitude - previousAltitude) >= significantAltitudeChangeMeters
    }

    private var maxHorizontalAccuracyMeters: Double {
        switch profile {
        case .flight:
            return 2_500
        default:
            return 500
        }
    }

    private let minimumSaveIntervalSeconds: TimeInterval = 5
    private let minimumSaveDistanceMeters: Double = 250
    private let significantCourseChangeDegrees: Double = 12
    private let significantAltitudeChangeMeters: Double = 120

    private func configure(profile: RecordingProfile) {
        manager.allowsBackgroundLocationUpdates = true
        manager.pausesLocationUpdatesAutomatically = profile != .flight

        switch profile {
        case .flight:
            manager.desiredAccuracy = kCLLocationAccuracyBestForNavigation
            manager.distanceFilter = 100
            manager.activityType = .otherNavigation
        case .walking:
            manager.desiredAccuracy = kCLLocationAccuracyBest
            manager.distanceFilter = 10
            manager.activityType = .fitness
        case .driving:
            manager.desiredAccuracy = kCLLocationAccuracyBestForNavigation
            manager.distanceFilter = 20
            manager.activityType = .automotiveNavigation
        default:
            manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
            manager.distanceFilter = 50
            manager.activityType = .other
        }
    }
}

enum LocationRecorderError: Error {
    case noUsableLocation
}

private func distanceMeters(from lhs: LocationPointRecord, to rhs: LocationPointRecord) -> Double {
    let earthRadiusMeters = 6_371_008.8
    let lat1 = lhs.latitude * .pi / 180
    let lat2 = rhs.latitude * .pi / 180
    let deltaLat = (rhs.latitude - lhs.latitude) * .pi / 180
    let deltaLon = (rhs.longitude - lhs.longitude) * .pi / 180
    let sinLat = sin(deltaLat / 2)
    let sinLon = sin(deltaLon / 2)
    let h = sinLat * sinLat + cos(lat1) * cos(lat2) * sinLon * sinLon
    return 2 * earthRadiusMeters * atan2(sqrt(h), sqrt(1 - h))
}

private func courseDeltaDegrees(_ lhs: Double?, _ rhs: Double?) -> Double {
    guard let lhs, let rhs else { return 0 }
    let delta = abs(lhs - rhs).truncatingRemainder(dividingBy: 360)
    return min(delta, 360 - delta)
}
