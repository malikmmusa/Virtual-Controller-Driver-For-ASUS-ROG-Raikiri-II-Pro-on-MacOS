// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "RaikiriBridge",
    platforms: [.macOS(.v15)],   // Core HID (Phase 4) needs macOS 15
    targets: [
        // Pure logic: report layout, translation, rumble, statistics. No IOKit,
        // so it builds and tests on any platform.
        .target(name: "BridgeCore"),
        // The macOS program: IOKit HID input, output to a sink.
        .executableTarget(name: "raikiri-bridge", dependencies: ["BridgeCore"]),
        .testTarget(name: "BridgeCoreTests", dependencies: ["BridgeCore"]),
    ],
    swiftLanguageModes: [.v5]
)
