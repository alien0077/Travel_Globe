import XCTest

final class TravelGlobeUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["-TravelGlobeUITestFlightCandidates"]
        app.launch()
    }

    override func tearDownWithError() throws {
        app = nil
    }

    func testFlightInputShowsMultipleFlightLegs() throws {
        let flightInputButton = app.buttons["輸入航班"]
        XCTAssertTrue(flightInputButton.waitForExistence(timeout: 12))
        flightInputButton.tap()

        let flightNumber = app.textFields["航班號"]
        XCTAssertTrue(flightNumber.waitForExistence(timeout: 5))
        flightNumber.doubleTap()
        flightNumber.typeText("FD234")

        let candidates = app.buttons.matching(NSPredicate(format: "label CONTAINS 'FD234'"))
        XCTAssertTrue(candidates.firstMatch.waitForExistence(timeout: 8))
        XCTAssertGreaterThanOrEqual(candidates.count, 2)
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS 'DMK'" )).firstMatch.exists)
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS 'NRT'" )).firstMatch.exists)

        let bangkokToKaohsiung = app.buttons.matching(
            NSPredicate(format: "label CONTAINS 'DMK' AND label CONTAINS 'KHH'")
        ).firstMatch
        XCTAssertTrue(bangkokToKaohsiung.waitForExistence(timeout: 3))
        bangkokToKaohsiung.tap()

        XCTAssertEqual((app.textFields["起飛"].value as? String), "DMK")
        XCTAssertEqual((app.textFields["抵達"].value as? String), "KHH")
    }
}
