// Timing statistics for the bridge. All values in nanoseconds.

/// Keeps the most recent `capacity` samples and summarizes them. Adding a
/// sample is O(1) and doesn't allocate once the buffer is full, so it's safe
/// on the input path; sorting happens only when a summary is requested.
public struct SampleWindow {
    public let capacity: Int
    private var samples: [UInt64] = []
    private var next = 0
    public private(set) var totalCount = 0

    public init(capacity: Int = 4096) {
        self.capacity = capacity
        samples.reserveCapacity(capacity)
    }

    public mutating func add(_ value: UInt64) {
        totalCount += 1
        if samples.count < capacity {
            samples.append(value)
        } else {
            samples[next] = value
            next = (next + 1) % capacity
        }
    }

    public var isEmpty: Bool { samples.isEmpty }

    public struct Summary: Equatable {
        public let count: Int
        public let min: UInt64
        public let median: UInt64
        public let p95: UInt64
        public let p99: UInt64
        public let max: UInt64
    }

    public func summary() -> Summary? {
        guard !samples.isEmpty else { return nil }
        let s = samples.sorted()
        // Nearest-rank percentile, in integer arithmetic.
        func pct(_ percent: Int) -> UInt64 { s[((s.count - 1) * percent + 50) / 100] }
        return Summary(count: s.count, min: s[0], median: pct(50), p95: pct(95), p99: pct(99), max: s[s.count - 1])
    }
}

public enum Format {
    /// 850 -> "850 ns", 12_345 -> "12.3 µs", 30_280_000 -> "30.28 ms"
    public static func duration(_ ns: UInt64) -> String {
        if ns < 1_000 { return "\(ns) ns" }
        if ns < 1_000_000 {
            let tenths = (ns + 50) / 100
            return "\(tenths / 10).\(tenths % 10) µs"
        }
        let hundredths = (ns + 5_000) / 10_000
        let frac = hundredths % 100
        return "\(hundredths / 100).\(frac < 10 ? "0" : "")\(frac) ms"
    }

    public static func summary(_ s: SampleWindow.Summary?) -> String {
        guard let s else { return "no samples" }
        return "median \(duration(s.median))  p95 \(duration(s.p95))  p99 \(duration(s.p99))  " +
               "max \(duration(s.max))  (n=\(s.count))"
    }
}
