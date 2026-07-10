import XCTest
@testable import TravelGlobe

final class TravelGlobeSmokeTests: XCTestCase {
    func testJourneyRecordCodable() throws {
        let journey = JourneyRecord(
            id: UUID(),
            title: "Smoke",
            startTime: Date(timeIntervalSince1970: 0),
            status: .planned,
            segmentType: .flight
        )
        let data = try JSONEncoder().encode(journey)
        let decoded = try JSONDecoder().decode(JourneyRecord.self, from: data)
        XCTAssertEqual(decoded.title, "Smoke")
    }
}
