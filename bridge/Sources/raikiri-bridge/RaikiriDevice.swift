#if os(macOS)
import Foundation
import IOKit
import IOKit.hid

/// Reads the Raikiri over IOKit HID and sends it output reports.
///
/// Latency notes:
/// - Uses the raw input *report* callback, not per-element value callbacks.
///   One callback per report, with the bytes exactly as the device sent them.
/// - The callback runs on a dedicated serial queue with user-interactive QoS,
///   not on the main thread, so nothing else delays it.
/// - The timestamp variant of the callback gives the time the kernel received
///   the report, so we can measure how long delivery to us took.
/// - Output reports (rumble) are sent from a separate queue, because
///   IOHIDDeviceSetReport blocks until the Bluetooth write completes.
final class RaikiriDevice {
    typealias ReportHandler = (_ report: UnsafeMutableBufferPointer<UInt8>, _ kernelTime: UInt64) -> Void

    let inputQueue = DispatchQueue(label: "raikiri.input", qos: .userInteractive)
    private let outputQueue = DispatchQueue(label: "raikiri.output", qos: .userInitiated)
    private let manager: IOHIDManager
    private var device: IOHIDDevice?          // touched only on inputQueue
    private let scratch = UnsafeMutablePointer<UInt8>.allocate(capacity: 64)

    var onReport: ReportHandler?
    var onConnect: ((String) -> Void)?
    var onDisconnect: (() -> Void)?

    init(vendorID: Int, productID: Int) {
        manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
        let matching: [String: Int] = [
            kIOHIDVendorIDKey: vendorID,
            kIOHIDProductIDKey: productID,
            kIOHIDDeviceUsagePageKey: kHIDPage_GenericDesktop,
            kIOHIDDeviceUsageKey: kHIDUsage_GD_GamePad,
        ]
        IOHIDManagerSetDeviceMatching(manager, matching as CFDictionary)
    }

    /// Start matching and receiving reports. With `seize`, the device is opened
    /// exclusively, so other apps stop seeing the real Raikiri while we run.
    func start(seize: Bool) -> IOReturn {
        let context = Unmanaged.passUnretained(self).toOpaque()
        IOHIDManagerRegisterDeviceMatchingCallback(manager, { context, _, _, device in
            RaikiriDevice.from(context).matched(device)
        }, context)
        IOHIDManagerRegisterDeviceRemovalCallback(manager, { context, _, _, device in
            RaikiriDevice.from(context).removed(device)
        }, context)
        IOHIDManagerRegisterInputReportWithTimeStampCallback(manager, {
            context, result, _, type, _, report, length, timeStamp in
            guard result == kIOReturnSuccess, type == kIOHIDReportTypeInput else { return }
            RaikiriDevice.from(context).received(report, length, timeStamp)
        }, context)
        IOHIDManagerSetDispatchQueue(manager, inputQueue)
        IOHIDManagerSetCancelHandler(manager) {}
        let options = seize ? kIOHIDOptionsTypeSeizeDevice : kIOHIDOptionsTypeNone
        let result = IOHIDManagerOpen(manager, IOOptionBits(options))
        IOHIDManagerActivate(manager)
        return result
    }

    private static func from(_ context: UnsafeMutableRawPointer?) -> RaikiriDevice {
        Unmanaged<RaikiriDevice>.fromOpaque(context!).takeUnretainedValue()
    }

    private func matched(_ device: IOHIDDevice) {
        self.device = device
        let name = IOHIDDeviceGetProperty(device, kIOHIDProductKey as CFString) as? String ?? "?"
        let transport = IOHIDDeviceGetProperty(device, kIOHIDTransportKey as CFString) as? String ?? "?"
        onConnect?("\(name) over \(transport)")
    }

    private func removed(_ device: IOHIDDevice) {
        if self.device == device { self.device = nil }
        onDisconnect?()
    }

    private func received(_ report: UnsafeMutablePointer<UInt8>, _ length: CFIndex, _ timeStamp: UInt64) {
        // Copy into our own buffer: the one IOKit hands us belongs to it.
        let n = min(Int(length), 64)
        scratch.update(from: report, count: n)
        onReport?(UnsafeMutableBufferPointer(start: scratch, count: n), timeStamp)
    }

    /// Send an output report (first byte = report ID). Calls back on the
    /// output queue with the IOKit result, or nil if no device is connected.
    func sendOutputReport(_ bytes: [UInt8], completion: ((IOReturn?) -> Void)? = nil) {
        inputQueue.async {
            let device = self.device
            self.outputQueue.async {
                guard let device, let id = bytes.first else { completion?(nil); return }
                let result = bytes.withUnsafeBufferPointer {
                    IOHIDDeviceSetReport(device, kIOHIDReportTypeOutput, CFIndex(id), $0.baseAddress!, $0.count)
                }
                completion?(result)
            }
        }
    }
}

/// mach_absolute_time() ticks to nanoseconds. On Apple Silicon one tick is
/// 125/3 ns; on Intel it's 1 ns.
enum MachClock {
    static let timebase: mach_timebase_info_data_t = {
        var info = mach_timebase_info_data_t()
        mach_timebase_info(&info)
        return info
    }()

    static func now() -> UInt64 { mach_absolute_time() }

    static func nanos(_ ticks: UInt64) -> UInt64 {
        ticks &* UInt64(timebase.numer) / UInt64(timebase.denom)
    }
}
#endif
