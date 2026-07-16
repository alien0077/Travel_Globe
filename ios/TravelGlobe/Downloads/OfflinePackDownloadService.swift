import CryptoKit
import Foundation

struct OfflinePackDownloadService {
    private let remoteBaseURL = URL(string: "https://alien0077.github.io/Travel_Globe/")!
    private let session: URLSession
    private let fileManager: FileManager

    init(session: URLSession = .shared, fileManager: FileManager = .default) {
        self.session = session
        self.fileManager = fileManager
    }

    func availablePacks() -> [OfflinePackDescriptor] {
        [
            OfflinePackDescriptor(id: "core-global", name: "Core Global Atlas", sizeBytes: 44_700_000),
            OfflinePackDescriptor(id: "east-asia-flight", name: "East Asia Flight Context", sizeBytes: 4_000_000)
        ]
    }

    func updateIfNeeded(force: Bool = false) async throws -> OfflinePackUpdateResult {
        try ensureRootDirectory()
        let remote = try await remoteRevision()
        let state = loadUpdateState()
        if !force, state?.revision == remote.revision {
            return OfflinePackUpdateResult(status: .alreadyCurrent, revision: remote.revision, downloadedBytes: 0)
        }

        let stagingURL = Self.stagingReplayRootURL
        if fileManager.fileExists(atPath: stagingURL.path) {
            try fileManager.removeItem(at: stagingURL)
        }
        try fileManager.createDirectory(at: stagingURL, withIntermediateDirectories: true)

        var downloadedBytes = 0
        for asset in Self.webRuntimeAssets {
            let data = try await download(relativePath: asset)
            try write(data, to: stagingURL.appendingPathComponent(asset))
            downloadedBytes += data.count
        }

        let manifests = [remote.geoManifest, remote.aviationManifest]
        for manifest in manifests {
            try write(manifest.data, to: stagingURL.appendingPathComponent(manifest.relativePath))
            downloadedBytes += manifest.data.count
            for payload in manifest.payloadFiles {
                let relativePath = "offline-packs/core-global/\(payload.filename)"
                let data = try await download(relativePath: relativePath)
                if sha256(data) != payload.sha256 {
                    throw OfflinePackUpdateError.checksumMismatch(payload.filename)
                }
                try write(data, to: stagingURL.appendingPathComponent(relativePath))
                downloadedBytes += data.count
            }
        }

        let activeURL = Self.downloadedReplayRootURL
        let previousURL = Self.previousReplayRootURL
        if fileManager.fileExists(atPath: previousURL.path) {
            try fileManager.removeItem(at: previousURL)
        }
        if fileManager.fileExists(atPath: activeURL.path) {
            try fileManager.moveItem(at: activeURL, to: previousURL)
        }
        try fileManager.moveItem(at: stagingURL, to: activeURL)
        if fileManager.fileExists(atPath: previousURL.path) {
            try fileManager.removeItem(at: previousURL)
        }

        saveUpdateState(OfflinePackUpdateState(
            revision: remote.revision,
            updatedAt: Date(),
            geoGeneratedAt: remote.geoManifest.generatedAt,
            aviationGeneratedFrom: remote.aviationManifest.generatedFrom
        ))
        return OfflinePackUpdateResult(status: .updated, revision: remote.revision, downloadedBytes: downloadedBytes)
    }

    func loadUpdateState() -> OfflinePackUpdateState? {
        guard let data = try? Data(contentsOf: Self.updateStateURL) else {
            return nil
        }
        return try? JSONDecoder().decode(OfflinePackUpdateState.self, from: data)
    }

    static func effectiveReplayRootURL() -> URL? {
        if
            FileManager.default.fileExists(atPath: downloadedReplayRootURL.appendingPathComponent("index.html").path),
            FileManager.default.fileExists(atPath: downloadedReplayRootURL.appendingPathComponent("index.js").path)
        {
            return downloadedReplayRootURL
        }
        return bundledReplayRootURL
    }

    static func replayEngineIndexURL() -> URL? {
        effectiveReplayRootURL()?.appendingPathComponent("index.html")
    }

    static func replayAssetURL(relativePath: String) -> URL? {
        let cleanPath = relativePath.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if let active = effectiveReplayRootURL() {
            let candidate = active.appendingPathComponent(cleanPath).standardizedFileURL
            let root = active.standardizedFileURL.path
            if candidate.path == root || candidate.path.hasPrefix(root + "/"), FileManager.default.fileExists(atPath: candidate.path) {
                return candidate
            }
        }
        guard let bundledReplayRootURL else {
            return nil
        }
        let bundled = bundledReplayRootURL.appendingPathComponent(cleanPath).standardizedFileURL
        let bundledRoot = bundledReplayRootURL.standardizedFileURL.path
        guard bundled.path == bundledRoot || bundled.path.hasPrefix(bundledRoot + "/") else {
            return nil
        }
        return FileManager.default.fileExists(atPath: bundled.path) ? bundled : nil
    }

    private func remoteRevision() async throws -> RemoteReplayRevision {
        async let geoManifest = fetchManifest("offline-packs/core-global/manifest.json")
        async let aviationManifest = fetchManifest("offline-packs/core-global/ourairports-manifest.json")
        async let runtimeSignature = headSignature(relativePath: "index.js")
        let remoteGeo = try await geoManifest
        let remoteAviation = try await aviationManifest
        let signature = [
            remoteGeo.contentSignature,
            remoteAviation.contentSignature,
            try await runtimeSignature
        ].joined(separator: "|")
        return RemoteReplayRevision(
            revision: sha256(Data(signature.utf8)),
            geoManifest: remoteGeo,
            aviationManifest: remoteAviation
        )
    }

    private func fetchManifest(_ relativePath: String) async throws -> RemotePackManifest {
        let data = try await download(relativePath: relativePath)
        let decoded = try JSONDecoder().decode(RemotePackManifestBody.self, from: data)
        return RemotePackManifest(
            relativePath: relativePath,
            data: data,
            generatedAt: decoded.generatedAt,
            generatedFrom: decoded.generatedFrom,
            payloadFiles: decoded.payloadFiles,
            contentSignature: decoded.contentSignature
        )
    }

    private func headSignature(relativePath: String) async throws -> String {
        var request = URLRequest(url: remoteURL(relativePath))
        request.httpMethod = "HEAD"
        let (_, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw OfflinePackUpdateError.unavailable(relativePath)
        }
        let etag = http.value(forHTTPHeaderField: "ETag") ?? ""
        let modified = http.value(forHTTPHeaderField: "Last-Modified") ?? ""
        let length = http.value(forHTTPHeaderField: "Content-Length") ?? ""
        return "\(relativePath)|\(etag)|\(modified)|\(length)"
    }

    private func download(relativePath: String) async throws -> Data {
        var request = URLRequest(url: remoteURL(relativePath))
        request.setValue("TravelGlobe iOS offline-pack updater", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw OfflinePackUpdateError.unavailable(relativePath)
        }
        return data
    }

    private func write(_ data: Data, to url: URL) throws {
        try fileManager.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url, options: .atomic)
    }

    private func remoteURL(_ relativePath: String) -> URL {
        URL(string: relativePath, relativeTo: remoteBaseURL)!.absoluteURL
    }

    private func ensureRootDirectory() throws {
        try fileManager.createDirectory(at: Self.updateContainerURL, withIntermediateDirectories: true)
    }

    private func saveUpdateState(_ state: OfflinePackUpdateState) {
        guard let data = try? JSONEncoder().encode(state) else {
            return
        }
        try? fileManager.createDirectory(at: Self.updateContainerURL, withIntermediateDirectories: true)
        try? data.write(to: Self.updateStateURL, options: .atomic)
    }

    private func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static let webRuntimeAssets = [
        "index.html",
        "index.js",
        "index.css",
        "readme.html"
    ]

    private static let bundledReplayRootURL = Bundle.main.resourceURL?.appendingPathComponent("ReplayEngine", isDirectory: true)

    private static let updateContainerURL: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return base.appendingPathComponent("TravelGlobe/ReplayEngineRemote", isDirectory: true)
    }()

    private static let downloadedReplayRootURL = updateContainerURL.appendingPathComponent("active", isDirectory: true)
    private static let stagingReplayRootURL = updateContainerURL.appendingPathComponent("staging", isDirectory: true)
    private static let previousReplayRootURL = updateContainerURL.appendingPathComponent("previous", isDirectory: true)
    private static let updateStateURL = updateContainerURL.appendingPathComponent("update-state.json")
}

struct OfflinePackDescriptor: Identifiable, Codable {
    var id: String
    var name: String
    var sizeBytes: Int
}

struct OfflinePackUpdateState: Codable {
    var revision: String
    var updatedAt: Date
    var geoGeneratedAt: String?
    var aviationGeneratedFrom: String?
}

struct OfflinePackUpdateResult {
    enum Status {
        case updated
        case alreadyCurrent
    }

    var status: Status
    var revision: String
    var downloadedBytes: Int
}

private struct RemoteReplayRevision {
    var revision: String
    var geoManifest: RemotePackManifest
    var aviationManifest: RemotePackManifest
}

private struct RemotePackManifest {
    var relativePath: String
    var data: Data
    var generatedAt: String?
    var generatedFrom: String?
    var payloadFiles: [RemotePackPayloadFile]
    var contentSignature: String
}

private struct RemotePackManifestBody: Decodable {
    var generatedAt: String?
    var generatedFrom: String?
    var payloads: [String: [RemotePackPayloadFile]]?

    var payloadFiles: [RemotePackPayloadFile] {
        (payloads ?? [:]).values.flatMap { $0 }
    }

    var contentSignature: String {
        let payloadSignature = payloadFiles
            .sorted { $0.path < $1.path }
            .map { "\($0.path):\($0.sha256):\($0.bytes)" }
            .joined(separator: "|")
        return "\(generatedFrom ?? "")|\(payloadSignature)"
    }
}

private struct RemotePackPayloadFile: Decodable {
    var path: String
    var bytes: Int
    var sha256: String

    var filename: String {
        URL(fileURLWithPath: path).lastPathComponent
    }
}

enum OfflinePackUpdateError: LocalizedError {
    case unavailable(String)
    case checksumMismatch(String)

    var errorDescription: String? {
        switch self {
        case .unavailable(let path):
            return "Remote offline data unavailable: \(path)"
        case .checksumMismatch(let filename):
            return "Offline data checksum mismatch: \(filename)"
        }
    }
}
