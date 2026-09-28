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
| H1 | Apple's GameController framework ignores the Raikiri | **Confirmed** by Experiment 2 | Experiments 1–2 |
| H2 | Its allowlist is keyed on identity (vendor/product ID, maybe name), not the report format | **Confirmed:** the allowlist is IOKit personalities that match on VendorID + ProductID (Experiment 3) | Experiment 3 |
| H3 | A virtual device with Xbox Series identity (`045E:0B13`) and the Xbox descriptor is accepted as an Xbox controller | **Strongly supported:** Apple's personality for `045E:0B13` is marked `GCIOMatchVirtual = true` | Phase 4, first test |
| H4 | GeForce NOW's native app accepts whatever GameController accepts as Xbox, or opens it via its HID backend | Partly answered: GFN uses the framework *and* SDL2 with SDL's controller database; it listed 0 gamepads | Experiment 6; Phase 4 end-to-end |

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

## Results

Recorded on macOS "Version 27.0 (Build 26A428)", with the Raikiri connected
over Bluetooth. Sections 1–3 of the inspector report are in
[captures/phase2-report-excerpt.txt](captures/phase2-report-excerpt.txt).

| Experiment | Result |
|---|---|
| 0: GeForce NOW in Chrome | **Doesn't work**, although a Gamepad API tester in the same browser does. Chrome reports the Raikiri with mapping "n/a"; GFN's web client apparently needs `mapping == "standard"`, which Chrome grants from its own list of known IDs. |
| 1: System Settings | The Raikiri is listed both in Bluetooth and on the **Game Controllers** page. |
| 2: `gc_probe.swift` | `GCController.controllers(): 0 controller(s)`. Apps get nothing. |
| 3–5: `inspect_system.py` | See the findings below. |

### Finding A: the allowlist, on disk

`/System/Library/Extensions/AppleGameControllerPersonality.kext` holds the
allowlist as **IOKit personalities**. Each one matches an `IOHIDInterface` by
`VendorID` + `ProductID`, and binds Apple's game controller driver
(`AppleGCHIDUserEventDriver`, `IOProbeScore` 1000) with a
`GameControllerCategory` such as `"xbox"`. Microsoft entries include:

| Personality | VID:PID | `GCIOMatchVirtual` |
|---|---|---|
| Xbox Series X Wireless Controller | `045E:0B13` | **true** |
| Xbox Series X Wireless Controller 2 | `045E:0B23` | true |
| Xbox Wireless Controller BLE (One S) | `045E:0B20` | true |
| Xbox Wireless Controller (One S, Classic BT) | `045E:02FD`, `045E:02E0` | true |
| Xbox Elite V2 (BT/BLE) | `045E:0B05`, `0B22`, `0B3C`, `0B02` | true |
| Xbox Series X Wired, Xbox Wired, Xbox 360, Elite V2 USB | `0B12`, `02EA`, `028E`, `0B00` | *absent* |
| Xbox Adaptive Controller | `0B0C`, `0B21` | absent |

Wired Xbox controllers use a separate DriverKit driver,
`/System/Library/DriverExtensions/XboxGamepad.dext`, which speaks the USB
protocol and then presents a HID device.

This confirms H2: recognition is by vendor/product ID. The report format
isn't checked at matching time.

The `GCIOMatchVirtual` key is almost certainly the "checks to ignore virtual
HID devices" Apple mentioned. Every device carries a `HIDVirtualDevice`
property, and the Raikiri's is `false`. Apple's driver apparently refuses
devices with `HIDVirtualDevice = true` unless the matching personality sets
`GCIOMatchVirtual`. The Bluetooth wireless Xbox entries, including our
target `045E:0B13`, do set it. That's a strong sign a virtual Xbox Series
controller is allowed by design. It's inferred from the key name; Phase 4's
first test confirms it.

### Finding B: what a real Bluetooth controller looks like to macOS

The Raikiri's IORegistry entry (masked in the capture) shows what our
virtual device should imitate:

- Class `IOHIDUserDevice`: Bluetooth LE HID devices are user-space HID
  devices created by the Bluetooth stack, with `HIDVirtualDevice = false`.
- `Transport = "Bluetooth Low Energy"` (Real Xbox Series controllers are BLE too.)
- `VersionNumber = 0x0509` (firmware 5.9, the Xbox Series BT firmware line),
  `ReportInterval = 8000` µs, `MaxInputReportSize = 17`, `MaxOutputReportSize = 9`.
- `GameControllerSupportedHIDDevice = false`, and the generic
  `AppleUserHIDEventDriver` attached instead of Apple's game controller driver.

### Finding C: macOS 27 "sees" generic gamepads, but doesn't give them to apps

gamecontrollerd logs `[Generic Device Manager] Matched Kernel Service vendorID
= 2821, productID = 7270 ... 'RAIKIRI II PRO PC'`. That's why the Game
Controllers settings page lists it. But no `GCController` reaches apps
(Experiment 2, and GFN's own session). Generic support appears limited to
the system's own use.

### Finding D: how GeForce NOW reads controllers

`libGeronimo.dylib` (GFN 2.0.88.129) links **both**
`GameController.framework` and the bundled **SDL2.framework**, and contains:

- `Enabled GameController.framework backend`, and `Not handling device %p via
  HID because GameController will take it.`: devices Apple accepts go through
  the framework; everything else goes through GFN's HID/SDL path.
- An embedded copy of the **SDL_GameControllerDB** (`# Source:
  https://github.com/mdqinc/SDL_GameControllerDB`) with hundreds of mappings.
  SDL only calls a device a "game controller" if it has a mapping there.
- Its log reported `connectedGamepadInfoList: []`: neither path accepted the
  Raikiri.

That suggests a **driverless fix for GeForce NOW specifically**. SDL reads
extra mappings from the `SDL_GAMECONTROLLERCONFIG` environment variable, so
we can give GFN's SDL a mapping for the Raikiri. See Experiment 6.

### Experiment 6: an SDL mapping for GeForce NOW (no driver)

[`recognition/raikiri_sdl_mapping.txt`](../recognition/raikiri_sdl_mapping.txt)
is derived from SDL2's macOS IOKit backend (`SDL_iokitjoystick.c`):

- **GUID** `03000000050b0000661c000009050000`: bus USB (that backend always
  uses USB), vendor `0B05`, product `1C66`, version `0509`, name CRC left 0.
  SDL retries without the CRC, and a second line with version 0 covers
  SDL's retry that ignores the version.
- **Numbering**: SDL sorts elements by HID usage number. So HID buttons
  1–15 become b0–b14 and Share (Consumer Record) becomes b15. Axes become
  X a0, Y a1, Z a2, Rz a3, Accelerator (RT) a4, Brake (LT) a5, and the hat
  is h0. That's the same shape as SDL's own mappings for Xbox Bluetooth
  controllers on macOS.

It's verified against real SDL 2.32. The GUID decodes to `0B05:1C66`
version `0509`, and a virtual joystick numbered this way yields the right
Xbox controls (`recognition/tests/test_sdl_mapping.py`).

To try it on the Mac:

```bash
cd ~/raikiri/recognition
../discovery/.venv/bin/pip install pysdl2 pysdl2-dll
../discovery/.venv/bin/python sdl_probe.py        # does SDL call it a game controller now?
./launch_gfn_with_mapping.sh                      # GFN with the mapping; quit GFN to undo
```

`sdl_probe.py` should show "game controller: YES" after the mapping is added,
and name each control as you press it. If `launch_gfn_with_mapping.sh` makes
the controller work in a game, GeForce NOW is solved without any driver.
The general fix (other apps, and Apple's framework) is still Phases 3–4.

### Experiment 6, first run: SDL sees no joystick at all

`sdl_probe.py` with SDL 2.32.10 reported `SDL sees 0 joystick(s)`, both with
and without our mapping. So the problem is earlier than the mapping.

The likely cause is a gap between SDL and Apple's framework. Before SDL's
macOS IOKit backend opens a HID device, it asks
`[GCController supportsHIDDevice:]` (SDL2 `SDL_mfijoystick.m`,
`IOS_SupportedHIDDevice`). If the answer is yes, it leaves the device to its
GameController backend. On macOS 27, gamecontrollerd's new Generic Device
Manager matches the Raikiri (Finding C), so the framework may answer yes and
then never deliver a `GCController`. GFN's library has the same pattern:
`Not handling device %p via HID because GameController will take it.`

Two tests settle it:

- `gc_probe.swift` now prints `supportsHIDDevice` for every HID gamepad.
  **YES** for the Raikiri confirms the gap.
  **Result: confirmed.** `RAIKIRI II PRO PC  0B05:1C66  supportsHIDDevice: YES`,
  followed by `GCController.controllers(): 0 controller(s)`. The framework
  claims the Raikiri but never delivers it to apps, so code that defers
  claimed devices (SDL, GFN's HID path) drops it too.
- `sdl_probe.py --no-mfi` sets SDL's documented `SDL_JOYSTICK_MFI=0` hint,
  which turns that check off. If SDL then sees the Raikiri, the mapping can
  be tested, and `launch_gfn_with_mapping.sh --no-mfi` tries the same in
  GeForce NOW. GFN's own HID code may still defer the device to Apple's
  framework; if so, only Phases 3–4 fix GFN.

**Result of `sdl_probe.py --no-mfi`: works.** SDL 2.32.10 then lists
`ASUSTeK RAIKIRI II PRO PC`, GUID `0300b3cc050b0000661c000009050000`, with 16
buttons, 6 axes and 1 hat, which is exactly the shape the mapping assumes.
Without the mapping it's "game controller: no"; with it, "YES". Live input
came through with the right names: a, x, y, both sticks, and both triggers
going 0 → 32767. The exact GUID (name CRC `0xCCB3`) is now the first line of
the mapping file, so GFN's SDL build matches it even without SDL's CRC
fallback.

**Result of `launch_gfn_with_mapping.sh --no-mfi`: doesn't work.** GFN
logged `"connectedGamepadInfoList":[]` at startup and again after the
controller was power-cycled, and the game ignored the controller. GFN's own
HID layer also defers devices the framework claims (`Not handling device %p
via HID because GameController will take it.`), and no SDL hint reaches
that check. The mapping is still correct and useful for other SDL apps run
with `SDL_JOYSTICK_MFI=0`.

## Conclusions

1. **The hypothesis is confirmed, with the exact mechanism.** Apple's
   framework binds its game controller driver through IOKit personalities
   in `AppleGameControllerPersonality.kext`, keyed on vendor/product ID.
   `0B05:1C66` isn't listed, so the Raikiri gets the generic HID driver.
2. **macOS 27 makes it worse: the Raikiri is claimed but never delivered.**
   gamecontrollerd's Generic Device Manager matches it, so
   `GCController.supportsHIDDevice` returns YES, but apps get no
   `GCController`. Any app that defers claimed devices to the framework
   drops it, including SDL by default and GeForce NOW always. That's
   probably worth a Feedback report to Apple (Game Controllers area).
3. **No configuration-only fix exists for GeForce NOW.** The browser client
   needs Chrome's "standard" mapping, and the native app defers to the
   framework. The one remaining shortcut would be patching GFN's binary to
   disable its GameController backend, as [gfn-fix] does for the Steam
   Controller. It's fragile across GFN updates, needs re-signing a modified
   copy, and modifying the client may conflict with NVIDIA's terms. This
   project doesn't take that route unless you decide to.
4. **The plan stands, with a precise target.** Phase 4 presents a virtual
   **Xbox Series X Wireless Controller, `045E:0B13`**. Apple's personality
   for it allows virtual devices (`GCIOMatchVirtual`), and the Raikiri
   already produces its exact report format, so the virtual device can reuse
   the Raikiri's descriptor. Phase 3 reads the Raikiri and forwards reports
   almost unchanged. A real Xbox controller appears as a normal
   `GCController`, which is the path GFN uses.

[sdl-list]: https://github.com/libsdl-org/SDL/blob/main/src/joystick/controller_list.h
[apple-list]: https://developer.apple.com/forums/thread/763679
[apple-virtual]: https://developer.apple.com/forums/thread/812774
[apple-entitlements]: https://developer.apple.com/forums/thread/820708
[padlink]: https://padlink.nimets.com/
[joycon2mac]: https://github.com/OZORDI/JoyCon2Mac
[leopiney]: https://www.leopiney.com/blog/flight-stick-driver
[gfn-fix]: https://github.com/mikeqwe/gfn-steam-controller-fix
