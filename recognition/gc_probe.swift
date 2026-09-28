// Phase 2: ask Apple's GameController framework which controllers it accepts.
//
// This is the ground truth for "does macOS recognize this controller?": the
// same API GeForce NOW's native app uses. It lists every GCController, says
// which profile macOS picked (Xbox, DualSense, ...), and prints input as you
// press things, so you can confirm input actually flows.
//
// Run (needs Xcode or the Command Line Tools):
//   swift gc_probe.swift            # listens for 30 seconds
//   swift gc_probe.swift 60         # listens for 60 seconds
// If `swift` complains about the SDK, compile instead:
//   swiftc gc_probe.swift -o gc_probe && ./gc_probe
//
// It also asks the framework, for each HID gamepad, whether it claims it
// (GCController.supportsHIDDevice). It changes nothing on the system.

import AppKit
import Foundation
import GameController
import IOKit.hid

let seconds = Double(CommandLine.arguments.dropFirst().first ?? "") ?? 30

func stamp() -> String {
    let f = DateFormatter()
    f.dateFormat = "HH:mm:ss.SSS"
    return f.string(from: Date())
}

func profileName(_ c: GCController) -> String {
    guard let pad = c.extendedGamepad else {
        return c.microGamepad != nil ? "micro gamepad" : "no gamepad profile"
    }
    if #available(macOS 11.3, *), pad is GCDualSenseGamepad { return "DualSense" }
    if #available(macOS 11.0, *) {
        if pad is GCXboxGamepad { return "Xbox" }
        if pad is GCDualShockGamepad { return "DualShock" }
    }
    return "extended gamepad (\(type(of: pad)))"
}

func describe(_ c: GCController) -> String {
    var lines = [
        "  vendorName:      \(c.vendorName ?? "(nil)")",
        "  productCategory: \(c.productCategory)",
        "  profile:         \(profileName(c))",
        "  attached:        \(c.isAttachedToDevice)",
    ]
    if #available(macOS 11.0, *) {
        let p = c.physicalInputProfile
        lines.append("  buttons (\(p.buttons.count)): \(p.buttons.keys.sorted().joined(separator: ", "))")
        lines.append("  axes (\(p.axes.count)): \(p.axes.keys.sorted().joined(separator: ", "))")
        lines.append("  dpads (\(p.dpads.count)): \(p.dpads.keys.sorted().joined(separator: ", "))")
        lines.append("  haptics:         \(c.haptics != nil ? "yes" : "no")")
    }
    return lines.joined(separator: "\n")
}

// Last printed state per element, so analog jitter doesn't flood the output:
// buttons print on press/release, sticks and axes when they cross +/-0.5.
var lastState: [ObjectIdentifier: String] = [:]

func coarse(_ v: Float) -> String { v > 0.5 ? "+" : (v < -0.5 ? "-" : "0") }

func watchInput(_ c: GCController) {
    guard #available(macOS 11.0, *) else { return }
    c.physicalInputProfile.valueDidChangeHandler = { _, element in
        let name = element.localizedName ?? "\(type(of: element))"
        var state = ""
        var detail = ""
        if let b = element as? GCControllerButtonInput {
            state = b.isPressed ? "pressed" : "released"
            detail = String(format: " (value %.2f)", b.value)
        } else if let d = element as? GCControllerDirectionPad {
            state = "x\(coarse(d.xAxis.value)) y\(coarse(d.yAxis.value))"
            detail = String(format: " (x=%+.2f y=%+.2f)", d.xAxis.value, d.yAxis.value)
        } else if let a = element as? GCControllerAxisInput {
            state = coarse(a.value)
            detail = String(format: " (%+.2f)", a.value)
        } else {
            return
        }
        let key = ObjectIdentifier(element)
        if lastState[key] == state { return }
        lastState[key] = state
        print("\(stamp())   input: \(name): \(state)\(detail)")
    }
}

func hex4(_ v: Int) -> String {
    let h = String(v, radix: 16, uppercase: true)
    return String(repeating: "0", count: max(0, 4 - h.count)) + h
}

// For every HID gamepad/joystick IOKit knows about, ask the framework whether it
// claims the device. SDL (inside GeForce NOW) and GeForce NOW's own HID code
// skip devices the framework claims, expecting a GCController to appear. A
// device that is claimed but never delivered falls through both.
func checkHIDDevices() {
    let manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
    let matching: [[String: Int]] = [
        [kIOHIDDeviceUsagePageKey: kHIDPage_GenericDesktop, kIOHIDDeviceUsageKey: kHIDUsage_GD_GamePad],
        [kIOHIDDeviceUsagePageKey: kHIDPage_GenericDesktop, kIOHIDDeviceUsageKey: kHIDUsage_GD_Joystick],
        [kIOHIDDeviceUsagePageKey: kHIDPage_GenericDesktop, kIOHIDDeviceUsageKey: kHIDUsage_GD_MultiAxisController],
    ]
    IOHIDManagerSetDeviceMatchingMultiple(manager, matching as CFArray)
    _ = IOHIDManagerOpen(manager, IOOptionBits(kIOHIDOptionsTypeNone))
    defer { IOHIDManagerClose(manager, IOOptionBits(kIOHIDOptionsTypeNone)) }
    guard let devices = IOHIDManagerCopyDevices(manager) as? Set<IOHIDDevice>, !devices.isEmpty else {
        print("HID gamepads seen by IOKit: none\n")
        return
    }
    print("HID gamepads seen by IOKit, and whether GameController claims them:")
    for device in devices {
        let name = IOHIDDeviceGetProperty(device, kIOHIDProductKey as CFString) as? String ?? "?"
        let vid = IOHIDDeviceGetProperty(device, kIOHIDVendorIDKey as CFString) as? Int ?? 0
        let pid = IOHIDDeviceGetProperty(device, kIOHIDProductIDKey as CFString) as? Int ?? 0
        var claimed = "n/a (needs macOS 11)"
        if #available(macOS 11.0, *) {
            claimed = GCController.supportsHIDDevice(device) ? "YES" : "no"
        }
        print("  \(name)  \(hex4(vid)):\(hex4(pid))  supportsHIDDevice: \(claimed)")
    }
    print("")
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
if #available(macOS 11.3, *) {
    // Deliver input even though this terminal process isn't the frontmost app.
    GCController.shouldMonitorBackgroundEvents = true
}

let center = NotificationCenter.default
center.addObserver(forName: .GCControllerDidConnect, object: nil, queue: .main) { note in
    guard let c = note.object as? GCController else { return }
    print("\(stamp()) CONNECTED: \(c.vendorName ?? "(unnamed)")\n\(describe(c))")
    watchInput(c)
}
center.addObserver(forName: .GCControllerDidDisconnect, object: nil, queue: .main) { note in
    let c = note.object as? GCController
    print("\(stamp()) DISCONNECTED: \(c?.vendorName ?? "(unnamed)")")
}

print("GameController probe on macOS \(ProcessInfo.processInfo.operatingSystemVersionString)")
print("Listening for \(Int(seconds)) s. Controllers macOS accepts appear below; press buttons to see input.")
print("Tip: turn the controller off and on while this runs to see the connect event.\n")
checkHIDDevices()

// Controllers that were already connected show up shortly after launch,
// either via the notification above or in this list.
DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
    let list = GCController.controllers()
    print("\(stamp()) GCController.controllers(): \(list.count) controller(s)")
    if list.isEmpty {
        print("  none. macOS's GameController framework does not accept any connected controller.")
    }
}

DispatchQueue.main.asyncAfter(deadline: .now() + seconds) {
    print("\n\(stamp()) done.")
    exit(0)
}
app.run()
