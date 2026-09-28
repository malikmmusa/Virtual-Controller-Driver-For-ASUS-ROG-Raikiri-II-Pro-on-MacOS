# Phase 2: What makes macOS and GeForce NOW accept a controller

Goal: before building anything that needs special signing, find out what
Apple's GameController framework and the GeForce NOW Mac app check when they
decide whether to accept a controller, and whether a virtual device can pass
those checks.

This phase has two parts: research (below) and read-only experiments on your
Mac ([Experiments](#experiments)). Nothing here changes system settings.

## What Phase 1 already told us

Over Bluetooth, the Raikiri's report descriptor and input reports have the
**same layout as an Xbox Series X|S controller over Bluetooth**. See
[raikiri-mapping.md](raikiri-mapping.md). The difference is its identity:

| | Raikiri II Pro | Xbox Series X\|S controller (Bluetooth) |
|---|---|---|
| Vendor ID | `0x0B05` (ASUS) | `0x045E` (Microsoft) |
| Product ID | `0x1C66` | `0x0B13` ([SDL's controller list][sdl-list]) |
| Product name | RAIKIRI II PRO PC | Xbox Wireless Controller |
| Report format | Xbox Series BT, firmware 5.x | same |

So if macOS ignores the Raikiri, it isn't because of the data format.

## Research findings

### 1. Apple's framework accepts only known controllers

Apple's Developer Technical Support has said the framework "currently
filters to known controllers only", which includes "the major console vendor
controllers and a number of other popular controllers". There's no public
list and no public API for adding a controller. Apple's advice to vendors is
to file a bug asking for support ([Apple forums, 2024–25][apple-list]).

That confirms the allowlist part of the original hypothesis. What the list
is keyed on (vendor/product ID, name, descriptor) isn't documented. Because
the Raikiri's data format already matches Xbox exactly, the identity fields
are the prime suspects. Experiment 3 below looks for the list on disk.

### 2. Apple filters out *some* virtual devices

An Apple engineer wrote in January 2026 ([Apple forums][apple-virtual]):

> There are some existing checks in the OS game controller support to ignore
> virtual HID devices, specifically to prevent issues arising from looping
> game controller input back into the OS. […] we can't guarantee this won't
> break in the future.

That's the biggest risk for Phase 4. But third-party projects show the
checks can be passed:

| Project | Virtual device | Recognized by GameController? | Notes |
|---|---|---|---|
| [PadLink][padlink] | DualShock 4, DriverKit, notarized | Yes, per its site | Shipping product; no SIP changes needed |
| [JoyCon2Mac][joycon2mac] | DualSense (`054C:0CE6`), DriverKit | Yes, per its README; lists GeForce NOW as working | Reports `Transport = "USB"`, a fixed serial and a nonzero location ID ("SDL/cloud apps depend on the Sony VID/PID, report shape, stable serial, and stable location ID"). Needs SIP and AMFI off. |
| [Flight-stick driver blog][leopiney] | "Virtual Xbox controller", DriverKit | Listed in Game Controllers settings as "GamePad-1" | **GeForce NOW's native app rejected it**; the browser version worked |

We don't know what Apple's virtual-device check looks at. Plausible
candidates are the `Transport` property (for example "Virtual"), how the
device was created (a CoreHID/`IOHIDUserDevice` user-space device versus a
DriverKit driver), or a missing physical parent in the IORegistry. That's
speculation until Phase 4 can test it. The working projects above copy a
real controller's identity closely and don't call themselves virtual.

### 3. GeForce NOW has its own controller logic

[gfn-steam-controller-fix][gfn-fix] documents how the native app handles
controllers:

- It has **two backends**: Apple's GameController framework, and its own
  raw-HID backend in `libGeronimo.dylib`.
- "Unmodified GFN detects that device through Apple's `GameController.framework`,
  suppresses its own HID path, …". With the GameController backend disabled,
  GFN opened a Steam virtual controller (`045e:028e`, the Xbox 360 ID)
  through its HID backend.
- GFN writes a log file at
  `~/Library/Application Support/NVIDIA/GeForceNOW/geronimo.log`.

So for the native app, "recognized by macOS" might be neither required nor
enough. The flight-stick blog's virtual controller was listed by macOS but
still rejected. Its name, "GamePad-1", suggests macOS saw a generic gamepad
rather than an Xbox controller, so the missing piece may have been an exact
Xbox identity. Experiment 4 reads GFN's log to see what it decides about the
Raikiri.

SDL, which many other games use, also doesn't know the Raikiri's ID. Its
list has ASUS's ROG Ally X but not `0B05:1C66`.

### 4. Signing: the fork in the road for Phase 4

Every way to create a real virtual HID device (DriverKit, or Apple's newer
Core HID `HIDVirtualDevice`) needs **restricted entitlements**. From Apple
DTS, March 2026 ([Apple forums][apple-entitlements]):

- DriverKit entitlements have *development-only* variants that work in
  development-signed builds **without Apple's approval**, but they need a
  **paid Apple Developer Program membership** ($99/year).
- Core HID's virtual-device entitlement has no development variant yet, so
  it needs Apple's approval.
- The entitlement-free route is disabling SIP and AMFI, which Apple
  describes as a boot-level change with serious security implications.

Phase 4 explains all of this properly before anything is changed. The
choice between a paid account and disabling protections is yours to make
then.

## Revised hypotheses

| # | Hypothesis | Status | How we test it |
|---|---|---|---|
| H1 | Apple's GameController framework ignores the Raikiri | Very likely | Experiments 1–2 |
| H2 | Its allowlist is keyed on identity (vendor/product ID, maybe name), not the report format | Likely: the format already matches Xbox | Experiment 3; Phase 4 |
| H3 | A virtual device with Xbox Series identity (`045E:0B13`), the Xbox descriptor and a non-virtual transport is accepted as an Xbox controller | Plausible: the DualSense/DualShock 4 projects above | Phase 4, first test |
| H4 | GeForce NOW's native app accepts whatever GameController accepts as Xbox, or opens it via its HID backend | Unknown: one negative report, one positive (DualSense) | Experiment 4 now; Phase 4 end-to-end |

## Experiments

All of these are read-only. Keep the Raikiri connected over Bluetooth. The
tools are in `recognition/`.

### Experiment 0: GeForce NOW in the browser (2 minutes)

Open [play.geforcenow.com](https://play.geforcenow.com) in Chrome, start any
game and try the controller. The browser version reads controllers through
the browser's Gamepad API, not Apple's framework, so it may already work.
Chrome reported the Raikiri with mapping "n/a", though, so buttons might be
scrambled. Either way it's a useful data point, and possibly a stopgap.

### Experiment 1: System Settings

Open **System Settings** and look for **Game Controllers** in the sidebar.
It appears only when macOS recognizes a controller. If it's there, check
whether the Raikiri is listed.

### Experiment 2: ask the GameController framework directly

```bash
cd ~/raikiri/recognition
swift gc_probe.swift 30
```

While it runs, turn the controller off and on, then press some buttons. If
macOS accepts the controller you'll see `CONNECTED` with a profile (Xbox,
DualSense, …) and your inputs. If it prints `0 controller(s)` and nothing
else, macOS's framework ignores the Raikiri (H1 confirmed).

If `swift` fails with an SDK error, compile it instead:
`swiftc gc_probe.swift -o gc_probe && ./gc_probe 30`.

### Experiments 3–5: the system inspector

Do these first:
1. Turn the controller off and on, so the system log has a fresh connection.
2. Open the GeForce NOW app, wait until it's fully loaded with the controller
   connected, press a few buttons, then quit it. This puts the controller
   in GFN's log.

Then, within 15 minutes:

```bash
cd ~/raikiri/recognition
../discovery/.venv/bin/python inspect_system.py
```

It writes `phase2_report.txt`, which covers:

- **(1) IORegistry:** every property macOS attached to the Raikiri, and
  which drivers sit on top of it. This is exactly what a virtual device will
  have to imitate.
- **(2) Bluetooth:** Classic vs Low Energy. Real Xbox Series controllers use
  Bluetooth LE.
- **(3) Allowlist on disk:** any system plist that mentions Microsoft's
  vendor ID. If the allowlist is data, this finds it. If nothing turns up,
  it's compiled into the framework.
- **(4) GeForce NOW:** which controller APIs its binaries use, and the
  controller lines from its log.
- **(5) gamecontrollerd:** what Apple's controller daemon logged about the
  connection.

Serial numbers and Bluetooth addresses are masked. Log lines are copied as
they are, so skim the report before sharing it.

### Optional: watch Apple's daemon live

```bash
log stream --style compact --predicate 'process == "gamecontrollerd"'
```

Turn the controller off and on while it runs, then press Ctrl-C.

## What the results will mean

- **The Raikiri isn't recognized (expected), and GFN's log shows it sees the
  device but skips it:** the plan stands. Phase 3 reads the Raikiri; Phase 4
  presents it as `045E:0B13`. Phase 4's first milestone is an end-to-end test
  in GeForce NOW before any polishing.
- **Experiment 0 works well:** you have a working stopgap today, and the
  native-app project can continue without pressure.
- **Experiment 3 finds an allowlist plist:** we learn exactly which fields
  are matched, which tells Phase 4 what to copy.
- **The Raikiri *is* recognized:** the problem is only in GeForce NOW, and the
  plan changes to focus on GFN's own backend.

[sdl-list]: https://github.com/libsdl-org/SDL/blob/main/src/joystick/controller_list.h
[apple-list]: https://developer.apple.com/forums/thread/763679
[apple-virtual]: https://developer.apple.com/forums/thread/812774
[apple-entitlements]: https://developer.apple.com/forums/thread/820708
[padlink]: https://padlink.nimets.com/
[joycon2mac]: https://github.com/OZORDI/JoyCon2Mac
[leopiney]: https://www.leopiney.com/blog/flight-stick-driver
[gfn-fix]: https://github.com/mikeqwe/gfn-steam-controller-fix
