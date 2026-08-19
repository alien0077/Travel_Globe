import XCTest

final class TravelGlobeUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        // Replay Engine is intentionally landscape-only, matching the iPhone
        // cabin reference layout. Set this before launch so WebView controls
        // are exposed in the same orientation as the production app.
        XCUIDevice.shared.orientation = .landscapeLeft
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

    func testCabinWindowViewsShowColoredEarthSurface() throws {
        let rightView = app.buttons["右方視角"]
        XCTAssertTrue(rightView.waitForExistence(timeout: 12))
        rightView.tap()
        XCTAssertTrue(app.staticTexts["右方視角"].waitForExistence(timeout: 5))
        assertHighResolutionEarthTextureLoaded()
        Thread.sleep(forTimeInterval: 2.0)
        assertScreenshotContainsEarthTexture(app.screenshot(), named: "right-window-earth")

        let leftView = app.buttons["左方視角"]
        XCTAssertTrue(leftView.waitForExistence(timeout: 5))
        leftView.tap()
        XCTAssertTrue(app.staticTexts["左方視角"].waitForExistence(timeout: 5))
        assertHighResolutionEarthTextureLoaded()
        Thread.sleep(forTimeInterval: 2.0)
        assertScreenshotContainsEarthTexture(app.screenshot(), named: "left-window-earth")
    }

    private func assertHighResolutionEarthTextureLoaded(
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let highResolutionTexture = app.descendants(matching: .any).matching(
            NSPredicate(format: "label CONTAINS '高解析衛星地表' OR value CONTAINS '高解析衛星地表'")
        ).firstMatch
        XCTAssertTrue(
            highResolutionTexture.waitForExistence(timeout: 8),
            "客艙視角仍在使用 fallback 地表材質",
            file: file,
            line: line
        )
    }

    private func assertScreenshotContainsEarthTexture(
        _ screenshot: XCUIScreenshot,
        named name: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)

        guard let image = screenshot.image.cgImage,
              let providerData = image.dataProvider?.data,
              let bytes = CFDataGetBytePtr(providerData) else {
            XCTFail("無法讀取客艙視角截圖像素", file: file, line: line)
            return
        }

        let bytesPerPixel = max(1, image.bitsPerPixel / 8)
        let sampleStepX = max(1, image.width / 96)
        let sampleStepY = max(1, image.height / 64)
        var sampleCount = 0
        var earthLikePixels = 0
        for y in stride(from: image.height / 7, to: image.height * 6 / 7, by: sampleStepY) {
            for x in stride(from: image.width / 12, to: image.width * 11 / 12, by: sampleStepX) {
                let offset = y * image.bytesPerRow + x * bytesPerPixel
                let red = Int(bytes[offset])
                let green = Int(bytes[offset + min(1, bytesPerPixel - 1)])
                let blue = Int(bytes[offset + min(2, bytesPerPixel - 1)])
                let brightest = max(red, max(green, blue))
                let darkest = min(red, min(green, blue))
                sampleCount += 1
                if brightest >= 72 && brightest - darkest >= 18 {
                    earthLikePixels += 1
                }
            }
        }

        XCTAssertGreaterThan(
            earthLikePixels,
            max(8, sampleCount / 80),
            "客艙視角截圖疑似只剩黑色背景或邊界線",
            file: file,
            line: line
        )
    }
}
