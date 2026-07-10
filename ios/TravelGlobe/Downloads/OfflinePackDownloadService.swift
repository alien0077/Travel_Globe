import Foundation

struct OfflinePackDownloadService {
    func availablePacks() -> [OfflinePackDescriptor] {
        [
            OfflinePackDescriptor(id: "core-global", name: "Core Global Labels", sizeBytes: 42_000_000),
            OfflinePackDescriptor(id: "east-asia-flight", name: "East Asia Flight Context", sizeBytes: 68_000_000)
        ]
    }
}

struct OfflinePackDescriptor: Identifiable, Codable {
    var id: String
    var name: String
    var sizeBytes: Int
}
