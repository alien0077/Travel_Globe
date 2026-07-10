import CoreLocation
import Foundation

final class LocationRecorder: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private let repository: JourneyRepository
    private var activeJourneyId: UUID?
    private var profile: RecordingProfile = .balanced

    init(repository: JourneyRepository) {
        self.repository = repository
        super.init()
        manager.delegate = self
    }

    func start(journeyId: UUID, profile: RecordingProfile) async throws {
        activeJourneyId = journeyId
        self.profile = profile
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
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let journeyId = activeJourneyId else { return }
        for location in locations {
            let point = LocationPointRecord(
                id: UUID(),
                journeyId: journeyId,
                timestamp: location.timestamp,
                latitude: location.coordinate.latitude,
                longitude: location.coordinate.longitude,
                altitudeMeters: location.altitude,
                speedMetersPerSecond: max(0, location.speed),
                courseDegrees: location.course >= 0 ? location.course : nil,
                horizontalAccuracyMeters: location.horizontalAccuracy,
                verticalAccuracyMeters: location.verticalAccuracy >= 0 ? location.verticalAccuracy : nil,
                source: "gps"
            )
            Task {
                try? await repository.saveLocationPoint(point)
            }
        }
    }

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
