// raikiri-bridge: Phase 3 of the Raikiri II Pro -> Xbox controller project.
//
// Reads the Raikiri's input reports through IOKit, turns each one into an
// Xbox Series X|S Bluetooth report (the formats are identical; translation
// validates and canonicalizes), and hands it to a sink. Phase 4 adds the
// sink that feeds the virtual Xbox controller. Until then the sinks print
// what the bridge would send, and the bridge measures its own latency.

#if os(macOS)
import BridgeCore
import Foundation

let usage = """
    Usage: raikiri-bridge [command] [options]

    Commands:
      run      (default) Read the controller and print each change as the bridge
               sees it, plus latency statistics.
      rumble   Test the reverse path: vibrate the controller.

    run options:
      --quiet            Don't print input changes; statistics only.
      --stats SECONDS    How often to print statistics (default 10, 0 = only at exit).
      --seize            Open the controller exclusively (other apps stop seeing it).

    rumble options:
      --strong N  --weak N  --lt N  --rt N     Motor strengths, 0-100 (defaults 60, 30, 0, 0)
      --ms N                                   Duration in milliseconds (default 600)

    Common:
      --vid 0x0B05  --pid 0x1C66               Which controller to open.

    Ctrl-C stops `run` and prints final statistics.
    """

struct Options {
    var command = "run"
    var quiet = false
    var statsEvery = 10.0
    var seize = false
    var strong: UInt8 = 60, weak: UInt8 = 30, lt: UInt8 = 0, rt: UInt8 = 0
    var ms = 600
    var vid = 0x0B05
    var pid = 0x1C66
}

func parseOptions(_ args: [String]) -> Options {
    var o = Options()
    var i = 0
    func value() -> String {
        i += 1
        guard i < args.count else { fail("missing value for \(args[i - 1])") }
        return args[i]
    }
    func int(_ s: String) -> Int {
        let parsed = s.hasPrefix("0x") ? Int(s.dropFirst(2), radix: 16) : Int(s)
        guard let v = parsed else { fail("not a number: \(s)") }
        return v
    }
    func percent(_ s: String) -> UInt8 { UInt8(max(0, min(100, int(s)))) }
    while i < args.count {
        switch args[i] {
        case "run", "rumble": o.command = args[i]
        case "--quiet": o.quiet = true
        case "--stats": o.statsEvery = Double(value()) ?? 10
        case "--seize": o.seize = true
        case "--strong": o.strong = percent(value())
        case "--weak": o.weak = percent(value())
        case "--lt": o.lt = percent(value())
        case "--rt": o.rt = percent(value())
        case "--ms": o.ms = max(10, int(value()))
        case "--vid": o.vid = int(value())
        case "--pid": o.pid = int(value())
        case "-h", "--help": print(usage); exit(0)
        default: fail("unknown argument: \(args[i])\n\n\(usage)")
        }
        i += 1
    }
    return o
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(("error: " + message + "\n").data(using: .utf8)!)
    exit(1)
}

func say(_ message: String) {
    print(message)
    fflush(stdout)
}

// MARK: - Sinks

/// Where translated Xbox reports go. Called on the input queue for every
/// report, so implementations must return quickly.
protocol ReportSink: AnyObject {
    func deliver(_ report: UnsafeBufferPointer<UInt8>)
}

/// Prints what changed. Decoding and printing happen on a separate
/// low-priority queue, so console I/O never delays the input path.
final class ConsoleSink: ReportSink {
    private let queue = DispatchQueue(label: "raikiri.console", qos: .utility)
    private var last = GamepadState()

    func deliver(_ report: UnsafeBufferPointer<UInt8>) {
        let bytes = Array(report)
        queue.async {
            guard let state = try? GamepadState(report: bytes) else { return }
            for line in Changes.describe(from: self.last, to: state) { say("  \(line)") }
            self.last = state
        }
    }
}

/// Discards reports. With --quiet, only the statistics are printed.
final class NullSink: ReportSink {
    func deliver(_ report: UnsafeBufferPointer<UInt8>) {}
}

// MARK: - Bridge

/// The input path: timestamp, translate, deliver. Runs on the device's input
/// queue; statistics are only touched there too.
final class Bridge {
    let device: RaikiriDevice
    let sink: ReportSink
    private var interval = SampleWindow()     // time between reports, kernel clock
    private var delivery = SampleWindow()     // kernel receive -> our callback
    private var processing = SampleWindow()   // our callback -> sink returned
    private var lastKernelTime: UInt64?
    private var rejected = 0
    private var sinceLastPrint = 0

    init(device: RaikiriDevice, sink: ReportSink) {
        self.device = device
        self.sink = sink
    }

    func handle(_ report: UnsafeMutableBufferPointer<UInt8>, kernelTime: UInt64) {
        let start = Clock.now()
        let received = kernelTime != 0 ? kernelTime : start
        if start >= received { delivery.add(Clock.nanos(start - received)) }
        if let last = lastKernelTime, received > last { interval.add(Clock.nanos(received - last)) }
        lastKernelTime = received
        sinceLastPrint += 1

        do {
            try XboxReport.canonicalize(report)
        } catch {
            rejected += 1   // e.g. an unexpected report ID; never forwarded
            return
        }
        sink.deliver(UnsafeBufferPointer(report))
        processing.add(Clock.nanos(Clock.now() - start))
    }

    /// Call on the input queue.
    func printStats(final: Bool = false) {
        if !final && sinceLastPrint == 0 { return }
        sinceLastPrint = 0
        say("""
            [stats] \(delivery.totalCount) reports, \(rejected) rejected
                    report interval:          \(Format.summary(interval.summary()))
                    kernel -> bridge:         \(Format.summary(delivery.summary()))
                    bridge processing:        \(Format.summary(processing.summary()))
            """)
    }
}

// MARK: - Commands

func runBridge(_ o: Options) -> Never {
    let device = RaikiriDevice(vendorID: o.vid, productID: o.pid)
    let bridge = Bridge(device: device, sink: o.quiet ? NullSink() : ConsoleSink())
    device.onConnect = { say("Connected: \($0)") }
    device.onDisconnect = { say("Disconnected. Waiting for the controller to come back...") }
    device.onReport = { bridge.handle($0, kernelTime: $1) }

    say(String(format: "Waiting for controller %04X:%04X. Ctrl-C to stop.", o.vid, o.pid))
    let result = device.start(seize: o.seize)
    if result != kIOReturnSuccess {
        say(String(format: "warning: IOHIDManagerOpen returned 0x%08X%@", result,
                   o.seize ? " (seize may need the device to be free: quit apps using it)" : ""))
    }

    var timer: DispatchSourceTimer?
    if o.statsEvery > 0 {
        let t = DispatchSource.makeTimerSource(queue: device.inputQueue)
        t.schedule(deadline: .now() + o.statsEvery, repeating: o.statsEvery)
        t.setEventHandler { bridge.printStats() }
        t.resume()
        timer = t
    }

    signal(SIGINT, SIG_IGN)
    let sigint = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
    sigint.setEventHandler {
        timer?.cancel()
        device.inputQueue.sync { bridge.printStats(final: true) }
        exit(0)
    }
    sigint.resume()
    withExtendedLifetime((bridge, sigint)) { dispatchMain() }
}

func runRumble(_ o: Options) -> Never {
    let device = RaikiriDevice(vendorID: o.vid, productID: o.pid)
    let tenths = UInt8(min(255, o.ms / 10))
    let on = Rumble(leftTrigger: o.lt, rightTrigger: o.rt, strong: o.strong, weak: o.weak,
                    duration: tenths, startDelay: 0, loopCount: 0)
    var sent = false

    device.onConnect = { name in
        guard !sent else { return }
        sent = true
        say("Connected: \(name)")
        say("Sending rumble \(on.report().map { String(format: "%02X", $0) }.joined(separator: " "))")
        device.sendOutputReport(on.report()) { result in
            say(result == kIOReturnSuccess ? "Sent. You should feel it for \(o.ms) ms."
                                           : String(format: "Send failed: 0x%08X", result ?? -1))
            DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(o.ms + 100)) {
                device.sendOutputReport(Rumble.off.report()) { _ in
                    say("Stopped.")
                    exit(result == kIOReturnSuccess ? 0 : 1)
                }
            }
        }
    }
    say("Waiting for the controller...")
    _ = device.start(seize: false)
    DispatchQueue.main.asyncAfter(deadline: .now() + 10) {
        if !sent { fail("controller not found within 10 s") }
    }
    withExtendedLifetime(device) { dispatchMain() }
}

let options = parseOptions(Array(CommandLine.arguments.dropFirst()))
switch options.command {
case "rumble": runRumble(options)
default: runBridge(options)
}

#else
print("raikiri-bridge runs on macOS only. BridgeCore builds and tests anywhere: swift test")
#endif
