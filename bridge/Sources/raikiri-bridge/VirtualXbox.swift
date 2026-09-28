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
    private let reports: AsyncStream<Data>.Continuation

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
        let (stream, continuation) = AsyncStream.makeStream(of: Data.self, bufferingPolicy: .bufferingNewest(32))
        reports = continuation
        let delegate = self.delegate
        Task.detached(priority: .high) {
            await device.activate(delegate: delegate)
            for await report in stream {
                do {
                    try await device.dispatchInputReport(data: report, timestamp: SuspendingClock().now)
                } catch {
                    FileHandle.standardError.write("virtual device: dispatch failed: \(error)\n".data(using: .utf8)!)
                }
            }
        }
    }

    func deliver(_ report: UnsafeBufferPointer<UInt8>) {
        reports.yield(Data(buffer: report))
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
