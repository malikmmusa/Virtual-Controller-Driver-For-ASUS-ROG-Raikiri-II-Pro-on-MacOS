import XCTest
@testable import BridgeCore

final class XboxReportTests: XCTestCase {
    // Reports captured from the real controller in Phase 1 (monitor/map).
    let rest = bytes("01d9804e85ca8144820000000000000000")
    let guidePressed = bytes("01d9804e85ca8144820000000000001000")
    let dpadDownAndStick = bytes("012a7a7e7e7a80e3800000000005000000")

    func testCapturedReportsDecode() throws {
        let r = try GamepadState(report: rest)
        XCTAssertEqual(r.leftX, 0x80D9)
        XCTAssertEqual(r.leftY, 0x854E)
        XCTAssertEqual(r.buttons, [])
        XCTAssertEqual(r.hat, 0)
        XCTAssertEqual(try GamepadState(report: guidePressed).buttons, .guide)
        let d = try GamepadState(report: dpadDownAndStick)
        XCTAssertEqual(d.hatName, "S")
        XCTAssertEqual(d.leftX, 0x7A2A)
    }

    func testCanonicalizeIsIdentityForRealReports() throws {
        for r in [rest, guidePressed, dpadDownAndStick] {
            XCTAssertEqual(try XboxReport.canonicalized(r), r)
        }
    }

    func testCanonicalizeClearsPaddingAndBadHat() throws {
        var r = rest
        r[9] = 0xFF    // LT low byte
        r[10] = 0xFF   // LT high byte: only 2 bits are data
        r[12] = 0xFC   // RT high byte: padding only
        r[13] = 0xFC   // hat nibble 0xC (invalid) + padding nibble
        r[15] = 0xFF   // buttons high byte incl. padding bit 15
        r[16] = 0xFF   // share + padding
        let c = try XboxReport.canonicalized(r)
        XCTAssertEqual(c[10], 0x03)
        XCTAssertEqual(c[12], 0x00)
        XCTAssertEqual(c[13], 0x00)
        XCTAssertEqual(c[15], 0x7F)
        XCTAssertEqual(c[16], 0x01)
        let s = try GamepadState(report: c)
        XCTAssertEqual(s.leftTrigger, 0x3FF)
        XCTAssertTrue(s.buttons.contains([.guide, .rightStick, .menu]))
    }

    func testRejections() {
        XCTAssertThrowsError(try XboxReport.canonicalized(Array(rest.dropLast()))) {
            XCTAssertEqual($0 as? XboxReport.Rejection, .wrongLength(16))
        }
        var wrongID = rest
        wrongID[0] = 0x03
        XCTAssertThrowsError(try XboxReport.canonicalized(wrongID)) {
            XCTAssertEqual($0 as? XboxReport.Rejection, .wrongReportID(3))
        }
    }

    func testStateRoundTrip() throws {
        var s = GamepadState()
        s.leftX = 13
        s.rightY = 65503
        s.leftTrigger = 1023
        s.hat = 7
        s.buttons = [.a, .leftBumper, .view, .guide]
        XCTAssertEqual(try GamepadState(report: s.report()), s)
        XCTAssertEqual(s.buttons.names, ["A", "LB", "View", "Guide"])
    }
}

final class RumbleTests: XCTestCase {
    func testPacketMatchesSDL() {
        // SDL: { 0x03, 0x0F, lt, rt, low, high, 0xFF, 0x00, 0xEB }
        XCTAssertEqual(Rumble(leftTrigger: 1, rightTrigger: 2, strong: 60, weak: 30).report(),
                       [0x03, 0x0F, 1, 2, 60, 30, 0xFF, 0x00, 0xEB])
        XCTAssertEqual(Rumble(strong: 250).strong, 100)
        XCTAssertTrue(Rumble.off.isOff)
    }

    func testParse() throws {
        let r = try Rumble(report: [0x03, 0xFF, 5, 6, 200, 8, 9, 10, 11])
        XCTAssertEqual(r.enableMask, 0x0F)
        XCTAssertEqual(r.strong, 100)
        XCTAssertEqual(r.report(), [0x03, 0x0F, 5, 6, 100, 8, 9, 10, 11])
        XCTAssertThrowsError(try Rumble(report: [0x01, 0, 0, 0, 0, 0, 0, 0, 0]))
        XCTAssertThrowsError(try Rumble(report: [0x03]))
    }

    func testCoalescer() {
        let ms: UInt64 = 1_000_000
        var c = RumbleCoalescer(minimumIntervalNanos: 50 * ms)
        let a = Rumble(strong: 10), b = Rumble(strong: 20), d = Rumble(strong: 30)
        XCTAssertEqual(c.submit(a, at: 1000 * ms), .sendNow(a))
        XCTAssertEqual(c.submit(b, at: 1010 * ms), .sendAt(1050 * ms))
        XCTAssertEqual(c.submit(d, at: 1020 * ms), .alreadyScheduled)   // replaces b
        XCTAssertNil(c.due(at: 1049 * ms))
        XCTAssertEqual(c.due(at: 1050 * ms), d)
        XCTAssertNil(c.due(at: 1200 * ms))
        XCTAssertEqual(c.submit(a, at: 1200 * ms), .sendNow(a))
    }
}

final class StatsTests: XCTestCase {
    func testWindow() throws {
        var w = SampleWindow(capacity: 100)
        XCTAssertNil(w.summary())
        for v in 1...200 { w.add(UInt64(v)) }        // keeps the last 100: 101...200
        let s = try XCTUnwrap(w.summary())
        XCTAssertEqual(w.totalCount, 200)
        XCTAssertEqual(s.count, 100)
        XCTAssertEqual(s.min, 101)
        XCTAssertEqual(s.max, 200)
        XCTAssertEqual(s.median, 151)
        XCTAssertEqual(s.p95, 195)
    }

    func testFormat() {
        XCTAssertEqual(Format.duration(850), "850 ns")
        XCTAssertEqual(Format.duration(12_345), "12.3 µs")
        XCTAssertEqual(Format.duration(30_280_000), "30.28 ms")
        XCTAssertEqual(Format.duration(8_040_000), "8.04 ms")
    }
}

private func bytes(_ hex: String) -> [UInt8] {
    var out: [UInt8] = []
    var i = hex.startIndex
    while i < hex.endIndex {
        let j = hex.index(i, offsetBy: 2)
        out.append(UInt8(hex[i..<j], radix: 16)!)
        i = j
    }
    return out
}

final class ChangesTests: XCTestCase {
    func testDirections() {
        XCTAssertEqual(Changes.direction(x: 32897, y: 34136), "center")   // captured rest
        XCTAssertEqual(Changes.direction(x: 13, y: 34136), "left")        // captured LSLeft
        XCTAssertEqual(Changes.direction(x: 32897, y: 6), "up")           // captured LSUp
        XCTAssertEqual(Changes.direction(x: 65515, y: 65515), "down-right")
    }

    func testDescribe() {
        var a = GamepadState()
        var b = a
        b.buttons = [.a, .guide]
        b.hat = 3
        b.leftX = 13
        b.rightTrigger = 1023
        XCTAssertEqual(Changes.describe(from: a, to: b),
                       ["A pressed", "Guide pressed", "D-pad E", "left stick left", "RT full"])
        a = b
        b.buttons = [.guide]
        b.hat = 0
        b.rightTrigger = 500
        XCTAssertEqual(Changes.describe(from: a, to: b), ["A released", "D-pad released", "RT half"])
        XCTAssertEqual(Changes.describe(from: b, to: b), [])
    }
}
