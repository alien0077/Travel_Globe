import Foundation
import Photos

struct PhotoImportService {
    func requestAuthorization() async -> PHAuthorizationStatus {
        await PHPhotoLibrary.requestAuthorization(for: .readWrite)
    }

    func fetchAssets(from startDate: Date, to endDate: Date) -> PHFetchResult<PHAsset> {
        let options = PHFetchOptions()
        options.predicate = NSPredicate(
            format: "creationDate >= %@ AND creationDate <= %@",
            startDate as NSDate,
            endDate as NSDate
        )
        options.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: true)]
        return PHAsset.fetchAssets(with: options)
    }

    func visitPoints(
        for journey: JourneyRecord,
        existingSourceIds: Set<String>,
        limit: Int = 80
    ) -> [VisitPointRecord] {
        let endDate = journey.endTime ?? Date()
        let assets = fetchAssets(from: journey.startTime, to: endDate)
        var points: [VisitPointRecord] = []
        assets.enumerateObjects { asset, _, stop in
            guard points.count < limit else {
                stop.pointee = true
                return
            }
            guard
                !existingSourceIds.contains(asset.localIdentifier),
                let location = asset.location,
                let timestamp = asset.creationDate,
                location.coordinate.latitude.isFinite,
                location.coordinate.longitude.isFinite,
                (-90...90).contains(location.coordinate.latitude),
                (-180...180).contains(location.coordinate.longitude)
            else {
                return
            }

            points.append(
                VisitPointRecord(
                    id: UUID(),
                    journeyId: journey.id,
                    segmentId: journey.webSegmentId,
                    timestamp: timestamp,
                    latitude: location.coordinate.latitude,
                    longitude: location.coordinate.longitude,
                    altitudeMeters: location.verticalAccuracy >= 0 ? location.altitude : nil,
                    horizontalAccuracyMeters: location.horizontalAccuracy >= 0 ? location.horizontalAccuracy : nil,
                    title: "照片打卡",
                    note: "從照片 GPS 匯入",
                    source: "photoGps",
                    sourceId: asset.localIdentifier
                )
            )
        }
        return points
    }
}
