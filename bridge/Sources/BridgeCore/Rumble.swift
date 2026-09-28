// Rumble: output report 0x03, identical on the Raikiri and the Xbox Series
// controller over Bluetooth. Layout (from the Raikiri's descriptor, and the
// packet SDL sends in SDL_hidapi_xboxone.c):
//
//   0  report ID 0x03
//   1  motor enable mask (low 4 bits; SDL always sends 0x0F)
//   2  left trigger motor   0...100
//   3  right trigger motor  0...100
//   4  left grip (strong, low frequency)   0...100
//   5  right grip (weak, high frequency)   0...100
//   6  duration in 10 ms units (SDL: 0xFF)
//   7  start delay in 10 ms units
//   8  loop count (SDL: 0xEB)

public struct Rumble: Equatable {
    public static let reportID: UInt8 = 0x03
    public static let reportLength = 9

    public var enableMask: UInt8 = 0x0F
    public var leftTrigger: UInt8 = 0
    public var rightTrigger: UInt8 = 0
    public var strong: UInt8 = 0
    public var weak: UInt8 = 0
    public var duration: UInt8 = 0xFF
    public var startDelay: UInt8 = 0
    public var loopCount: UInt8 = 0xEB

    public init(leftTrigger: UInt8 = 0, rightTrigger: UInt8 = 0, strong: UInt8 = 0, weak: UInt8 = 0,
                duration: UInt8 = 0xFF, startDelay: UInt8 = 0, loopCount: UInt8 = 0xEB) {
        self.leftTrigger = min(leftTrigger, 100)
        self.rightTrigger = min(rightTrigger, 100)
        self.strong = min(strong, 100)
        self.weak = min(weak, 100)
        self.duration = duration
        self.startDelay = startDelay
        self.loopCount = loopCount
    }

    public static let off = Rumble(duration: 0, loopCount: 0)

    public enum Rejection: Error, Equatable {
        case wrongReportID(UInt8)
        case wrongLength(Int)
    }

    /// Parse an output report as a game or the OS would send it to the
    /// virtual Xbox controller (Phase 4 forwards these to the Raikiri).
    public init(report: [UInt8]) throws {
        guard report.count == Self.reportLength else { throw Rejection.wrongLength(report.count) }
        guard report[0] == Self.reportID else { throw Rejection.wrongReportID(report[0]) }
        enableMask = report[1] & 0x0F
        leftTrigger = min(report[2], 100)
        rightTrigger = min(report[3], 100)
        strong = min(report[4], 100)
        weak = min(report[5], 100)
        duration = report[6]
        startDelay = report[7]
        loopCount = report[8]
    }

    public func report() -> [UInt8] {
        [Self.reportID, enableMask & 0x0F, leftTrigger, rightTrigger, strong, weak, duration, startDelay, loopCount]
    }

    public var isOff: Bool { leftTrigger == 0 && rightTrigger == 0 && strong == 0 && weak == 0 }
}

/// Rate limiter for rumble over Bluetooth. Games can update rumble every
/// frame; the controller's link can't keep up (SDL waits 50 ms between
/// Bluetooth rumble packets). Only the latest request matters, so requests
/// that arrive too soon replace each other and the newest is sent when the
/// interval has passed. Times are in nanoseconds on any monotonic clock.
public struct RumbleCoalescer {
    public let minimumInterval: UInt64
    public private(set) var lastSent: UInt64?
    public private(set) var pending: Rumble?

    public init(minimumIntervalNanos: UInt64 = 50_000_000) {
        minimumInterval = minimumIntervalNanos
    }

    public enum Decision: Equatable {
        case sendNow(Rumble)
        case sendAt(UInt64)   // caller should call `due(at:)` at this time
        case alreadyScheduled
    }

    public mutating func submit(_ rumble: Rumble, at now: UInt64) -> Decision {
        if let last = lastSent, now &- last < minimumInterval {
            let hadPending = pending != nil
            pending = rumble
            return hadPending ? .alreadyScheduled : .sendAt(last + minimumInterval)
        }
        pending = nil
        lastSent = now
        return .sendNow(rumble)
    }

    /// The pending rumble, if its time has come.
    public mutating func due(at now: UInt64) -> Rumble? {
        guard let p = pending, let last = lastSent, now &- last >= minimumInterval else { return nil }
        pending = nil
        lastSent = now
        return p
    }
}
