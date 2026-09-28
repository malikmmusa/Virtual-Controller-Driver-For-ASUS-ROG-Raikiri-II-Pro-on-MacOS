// The Raikiri II Pro's Bluetooth input report, which has the same layout as
// the Xbox Series X|S controller's Bluetooth report (firmware 5.x). See
// docs/raikiri-mapping.md for how this was established.
//
// Byte offsets below include the report ID at byte 0, i.e. they index the
// buffer exactly as IOKit delivers it.
//
//   0      report ID (0x01)
//   1-2    left stick X   (UInt16 LE, 0...65535, ~32768 at rest)
//   3-4    left stick Y   (up = 0)
//   5-6    right stick X
//   7-8    right stick Y  (up = 0)
//   9-10   left trigger   (low 10 bits, 0...1023; top 6 bits padding)
//   11-12  right trigger  (low 10 bits)
//   13     hat switch     (low nibble: 0 = centered, 1 = N ... 8 = NW)
//   14-15  buttons        (15 bits, see XboxButtons; bit 15 padding)
//   16     share          (bit 0; this controller has no Share button)

public enum XboxReport {
    public static let inputReportID: UInt8 = 0x01
    public static let inputReportLength = 17

    /// Why a report was rejected by `canonicalize`.
    public enum Rejection: Error, Equatable {
        case wrongReportID(UInt8)
        case wrongLength(Int)
    }

    /// The translation step, done in place on the report buffer.
    ///
    /// The Raikiri already speaks the Xbox Series layout, so translating means
    /// validating the report and clearing bits that must be zero: the padding
    /// next to the 10-bit triggers, 4-bit hat and 15 buttons, and any hat
    /// value outside 0...8. No allocation, no copying.
    @inlinable
    public static func canonicalize(_ report: UnsafeMutableBufferPointer<UInt8>) throws {
        guard report.count == inputReportLength else { throw Rejection.wrongLength(report.count) }
        guard report[0] == inputReportID else { throw Rejection.wrongReportID(report[0]) }
        report[10] &= 0x03
        report[12] &= 0x03
        report[13] &= 0x0F
        if report[13] > 8 { report[13] = 0 }
        report[15] &= 0x7F
        report[16] &= 0x01
    }

    /// Convenience wrapper for arrays (tests, tools). The hot path uses the
    /// buffer version.
    public static func canonicalized(_ report: [UInt8]) throws -> [UInt8] {
        var copy = report
        try copy.withUnsafeMutableBufferPointer { try canonicalize($0) }
        return copy
    }
}

/// Xbox button bits in bytes 14-15 of the input report, read as a
/// little-endian UInt16. Bits 2, 5, 8 and 9 are unused on Xbox controllers.
public struct XboxButtons: OptionSet, Hashable {
    public let rawValue: UInt16
    public init(rawValue: UInt16) { self.rawValue = rawValue }

    public static let a = XboxButtons(rawValue: 1 << 0)
    public static let b = XboxButtons(rawValue: 1 << 1)
    public static let x = XboxButtons(rawValue: 1 << 3)
    public static let y = XboxButtons(rawValue: 1 << 4)
    public static let leftBumper = XboxButtons(rawValue: 1 << 6)
    public static let rightBumper = XboxButtons(rawValue: 1 << 7)
    public static let view = XboxButtons(rawValue: 1 << 10)
    public static let menu = XboxButtons(rawValue: 1 << 11)
    public static let guide = XboxButtons(rawValue: 1 << 12)
    public static let leftStick = XboxButtons(rawValue: 1 << 13)
    public static let rightStick = XboxButtons(rawValue: 1 << 14)

    public static let named: [(XboxButtons, String)] = [
        (.a, "A"), (.b, "B"), (.x, "X"), (.y, "Y"), (.leftBumper, "LB"), (.rightBumper, "RB"),
        (.view, "View"), (.menu, "Menu"), (.guide, "Guide"), (.leftStick, "L3"), (.rightStick, "R3"),
    ]

    public var names: [String] { Self.named.filter { contains($0.0) }.map { $0.1 } }
}

/// A decoded input report, for display and tests. The bridge itself never
/// needs to decode: it forwards the canonicalized bytes.
public struct GamepadState: Equatable {
    public var leftX: UInt16 = 0x8000
    public var leftY: UInt16 = 0x8000
    public var rightX: UInt16 = 0x8000
    public var rightY: UInt16 = 0x8000
    public var leftTrigger: UInt16 = 0
    public var rightTrigger: UInt16 = 0
    public var hat: UInt8 = 0
    public var buttons: XboxButtons = []
    public var share = false

    public init() {}

    public init(report: [UInt8]) throws {
        let r = try XboxReport.canonicalized(report)
        func u16(_ i: Int) -> UInt16 { UInt16(r[i]) | UInt16(r[i + 1]) << 8 }
        leftX = u16(1)
        leftY = u16(3)
        rightX = u16(5)
        rightY = u16(7)
        leftTrigger = u16(9)
        rightTrigger = u16(11)
        hat = r[13]
        buttons = XboxButtons(rawValue: u16(14))
        share = r[16] & 1 == 1
    }

    public func report() -> [UInt8] {
        var r = [UInt8](repeating: 0, count: XboxReport.inputReportLength)
        r[0] = XboxReport.inputReportID
        func put(_ v: UInt16, _ i: Int) { r[i] = UInt8(v & 0xFF); r[i + 1] = UInt8(v >> 8) }
        put(leftX, 1)
        put(leftY, 3)
        put(rightX, 5)
        put(rightY, 7)
        put(leftTrigger & 0x3FF, 9)
        put(rightTrigger & 0x3FF, 11)
        r[13] = hat <= 8 ? hat : 0
        put(buttons.rawValue & 0x7FFF, 14)
        r[16] = share ? 1 : 0
        return r
    }

    public static let hatNames = ["-", "N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    public var hatName: String { Self.hatNames[Int(min(hat, 8))] }
}
