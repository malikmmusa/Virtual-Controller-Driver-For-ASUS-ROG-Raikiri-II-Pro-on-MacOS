#if os(macOS) && canImport(CoreHID)
import BridgeCore
import CoreHID
import Foundation

/// Phase 4 proof of concept: a Core HID virtual device that presents itself as
/// an Xbox Series X|S controller (045E:0B13, Bluetooth LE) and receives the
/// bridge's reports.
///
/// Creating it requires the `com.apple.developer.hid.virtual.device`
/// entitlement. See docs/phase4-virtual-device.md for why, and for the ways
/// to get it. Without the entitlement the system refuses and `init` returns nil.
final class VirtualXboxSink: ReportSink {
    private let device: HIDVirtualDevice
    private let delegate: Delegate
    private let reports: AsyncStream<(Data, UInt64)>.Continuation
    private let timing = DispatchTiming()

    init?(onOutputReport: @escaping @Sendable ([UInt8]) -> Void) {
        let properties = HIDVirtualDevice.Properties(
            descriptor: Data(XboxIdentity.reportDescriptor),
            vendorID: XboxIdentity.vendorID,
            productID: XboxIdentity.productID,
            transport: .bluetoothLowEnergy,
            product: XboxIdentity.product,
            manufacturer: XboxIdentity.manufacturer,
            modelNumber: XboxIdentity.product,
            versionNumber: XboxIdentity.versionNumber,
            serialNumber: XboxIdentity.serialNumber,
            uniqueID: XboxIdentity.serialNumber,
            locationID: XboxIdentity.locationID,
            localizationCode: nil,
            extraProperties: nil)
        guard let device = HIDVirtualDevice(properties: properties) else { return nil }
        self.device = device
        delegate = Delegate(onOutputReport: onOutputReport)

        // dispatchInputReport is async. Separate Tasks per report could run out
        // of order, so reports go through one stream with a single consumer.
        let (stream, continuation) = AsyncStream.makeStream(of: (Data, UInt64).self,
                                                            bufferingPolicy: .bufferingNewest(32))
        reports = continuation
        let delegate = self.delegate
        let timing = self.timing
        Task.detached(priority: .high) {
            await device.activate(delegate: delegate)
            for await (report, enqueued) in stream {
                let start = MachClock.now()
                do {
                    try await device.dispatchInputReport(data: report, timestamp: SuspendingClock().now)
                } catch {
                    FileHandle.standardError.write("virtual device: dispatch failed: \(error)\n".data(using: .utf8)!)
                }
                timing.record(waited: MachClock.nanos(start &- enqueued), dispatch: MachClock.nanos(MachClock.now() &- start))
            }
        }
    }

    func deliver(_ report: UnsafeBufferPointer<UInt8>) {
        if case .dropped = reports.yield((Data(buffer: report), MachClock.now())) {
            timing.recordDrop()
        }
    }

    func statsLines() -> [String] { timing.lines() }

    /// Timing of the hand-off to Core HID, which Phase 3's numbers don't cover:
    /// how long a report waits in the queue, and how long dispatching takes.
    /// If dispatch were slower than the controller's report rate, reports would
    /// pile up and the wait would grow, which would show up as lag.
    final class DispatchTiming: @unchecked Sendable {
        private let lock = NSLock()
        private var waited = SampleWindow()
        private var dispatch = SampleWindow()
        private var drops = 0

        func record(waited w: UInt64, dispatch d: UInt64) {
            lock.lock(); defer { lock.unlock() }
            waited.add(w)
            dispatch.add(d)
        }

        func recordDrop() {
            lock.lock(); defer { lock.unlock() }
            drops += 1
        }

        func lines() -> [String] {
            lock.lock(); defer { lock.unlock() }
            return ["virtual: queue wait:      \(Format.summary(waited.summary()))",
                    "virtual: dispatch:        \(Format.summary(dispatch.summary()))  dropped \(drops)"]
        }
    }

    /// Receives requests the system (or a game) sends to the virtual device.
    final class Delegate: HIDVirtualDeviceDelegate, @unchecked Sendable {
        let onOutputReport: @Sendable ([UInt8]) -> Void

        init(onOutputReport: @escaping @Sendable ([UInt8]) -> Void) {
            self.onOutputReport = onOutputReport
        }

        func hidVirtualDevice(_ device: HIDVirtualDevice, receivedSetReportRequestOfType type: HIDReportType,
                              id: HIDReportID?, data: Data) async throws {
            guard type == .output else { return }
            var bytes = [UInt8](data)
            // Normalize to "report ID + payload", the form the Raikiri expects.
            if let id, bytes.count == Rumble.reportLength - 1 { bytes.insert(id.rawValue, at: 0) }
            onOutputReport(bytes)
        }

        func hidVirtualDevice(_ device: HIDVirtualDevice, receivedGetReportRequestOfType type: HIDReportType,
                              id: HIDReportID?, maxSize: Int) async throws -> Data {
            Data()   // the descriptor declares no feature reports
        }
    }
}
#endif
