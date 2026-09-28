# Phase 3: The bridge (reading and translating the Raikiri)

Goal: a user-space program that reads the Raikiri through IOKit, turns each
input report into an Xbox Series X|S Bluetooth report, and hands it to
whatever will present the virtual controller (Phase 4). It should add as
little delay as possible, and measure what it does add.

The code is a Swift package in [`bridge/`](../bridge):

| Part | What it is | Runs on |
|---|---|---|
| `BridgeCore` | Report layout, translation, rumble packets, statistics, change descriptions | Anywhere (the unit tests run on Linux too) |
| `raikiri-bridge` | The macOS program: IOKit input, sinks, command line | macOS 13+ |

## How a report flows

```
Raikiri --(BLE, ~30 ms cadence)--> bluetoothd --> kernel IOHIDDevice
    --> IOHIDManager report callback on "raikiri.input" queue   [timestamp: kernel receive]
        --> copy 17 bytes into our buffer
        --> XboxReport.canonicalize (in place)
        --> sink.deliver(...)                                    [Phase 4: virtual Xbox controller]
```

### Why it's built this way

- **Raw report callback, not value callbacks.** IOKit can call you once per
  changed *element* (button, axis) or once per *report*. Per report is one
  call with all 17 bytes, exactly what we forward. Per element would mean
  up to 20 callbacks, then reassembling a report.
- **A dedicated serial queue at user-interactive QoS.** The callbacks run on
  `raikiri.input` (`IOHIDManagerSetDispatchQueue`), the highest QoS for
  ordinary work, so the scheduler favors it and the main thread can't delay it.
- **Translation is almost free.** Phase 1 showed the Raikiri already uses
  the Xbox Series Bluetooth report layout byte for byte. `canonicalize`
  checks the report ID and length, clears the padding bits, and turns an
  out-of-range hat value into "centered", in place, with no allocation.
  Anything that fails the check (another report ID) is counted and dropped,
  never forwarded.
- **Nothing slow on the hot path.** The console sink copies the 17 bytes and
  hands them to a low-priority queue for decoding and printing, so terminal
  I/O never delays the next report.
- **Rumble goes the other way on its own queue.** `IOHIDDeviceSetReport`
  blocks until the Bluetooth write finishes, so it runs on `raikiri.output`.
  `RumbleCoalescer` (in BridgeCore, not wired up until Phase 4) limits
  forwarding to one packet per 50 ms, as SDL does for Xbox over Bluetooth,
  and always sends the newest request.

### What the statistics mean

Every 10 seconds, and when you press Ctrl-C, the bridge prints three timings:

| Line | Measured from → to | What it tells you |
|---|---|---|
| report interval | one kernel receive → the next | How often the controller sends. Phase 1 saw steps of about 30 ms. It's set by the controller and the Bluetooth link; the bridge can't change it. |
| kernel → bridge | kernel receive timestamp → our callback starts | Delivery cost from the kernel to user space: scheduling, queue wake-up. Measured: about 0.13 ms. |
| bridge processing | our callback starts → sink returns | Our own cost, including the hand-off to the sink. Measured: about 0.025 ms. |

The radio part, from the controller to `bluetoothd`, can't be measured from
software. Phase 1's report interval sets its scale: a press waits up to
about 30 ms for the controller's next report.

## Results (first run on the Mac)

macOS 27.0, Raikiri over Bluetooth LE. The bridge built with the Command
Line Tools on the first try. The `ld: warning: search path ... not found`
lines come from the CLT lacking Xcode's test frameworks and are harmless.

- **Correctness:** every control printed the expected Xbox name: face
  buttons, bumpers, L3/R3, all eight D-pad directions, stick directions and
  LT levels. 99 reports, 0 rejected.
- **Timing** (99 reports, console sink):

  | | median | p95 | p99 | max |
  |---|---|---|---|---|
  | report interval | 30.14 ms | 149.97 ms | 327.83 ms | 1108 ms |
  | kernel → bridge | 129.6 µs | 260.5 µs | 498.2 µs | 548.3 µs |
  | bridge processing | 25.2 µs | 39.5 µs | 42.4 µs | 103.5 µs |

  The bridge adds about 0.15 ms, under 1% of the controller's 30 ms report
  cadence, which remains the dominant delay. Kernel → bridge is higher than
  a busy-loop estimate would suggest. Reports arrive after ~30 ms of idle,
  so the core and our thread have to wake up; that's typical on Apple
  Silicon and still small.
- **Rumble:** `raikiri-bridge rumble` sent `03 0F 00 00 3C 1E 3C 00 00`
  (grips) and `03 0F 50 50 00 00 3C 00 00` (triggers), and IOKit accepted
  both, plus the stop packets. So the output path to the controller works.
  Not verified by feel, because vibration is disabled on this controller.
  Game rumble forwarding is optional for Phase 4.

## Build and run (on the Mac)

```bash
cd ~/raikiri && git pull && cd bridge
swift build -c release
.build/release/raikiri-bridge --help
```

**1. Watch the translated stream:**

```bash
.build/release/raikiri-bridge
```

It prints `Connected: RAIKIRI II PRO PC over Bluetooth Low Energy`, then one
line per change (`A pressed`, `left stick up-right`, `LT full`, `D-pad E`,
…) and statistics every 10 seconds. Press every control once to check the
mapping, move the sticks around for about 20 seconds, then press Ctrl-C and
keep the final statistics.

**2. Latency only:**

```bash
.build/release/raikiri-bridge --quiet --stats 5
```

Wiggle both sticks continuously so reports keep flowing.

**3. Rumble, the reverse path Phase 4 needs for game vibration:**

```bash
.build/release/raikiri-bridge rumble                        # grips, 600 ms
.build/release/raikiri-bridge rumble --strong 0 --weak 0 --lt 80 --rt 80   # trigger motors
```

It prints the exact packet (`03 0F …`) and whether IOKit accepted it. If the
controller vibrates, games' rumble can be forwarded in Phase 4.

`--seize` opens the controller exclusively, so other apps (browsers, SDL
games) stop seeing the real Raikiri while the bridge runs. Phase 4 uses
this so apps don't see two controllers. It isn't needed for testing.

## Tests

```bash
cd bridge && swift test     # needs Xcode on macOS (XCTest); works with any Swift toolchain on Linux
```

The tests use reports captured from your controller in Phase 1: they decode
them, check that canonicalization leaves real reports untouched, and check
that the rumble packet matches SDL's.
