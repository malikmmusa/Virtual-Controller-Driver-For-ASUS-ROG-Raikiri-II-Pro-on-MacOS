# Phase 1: Discovery

Goal: learn exactly what the Raikiri II Pro sends over HID in wireless mode,
and build a table that maps each physical control to a field in its reports.
Everything in later phases (the translation daemon and the virtual Xbox
device) is built on that table.

Nothing in this phase changes system security settings. The only permission
involved is the normal, revocable macOS privacy prompt for Input Monitoring.

## Background: how HID works

HID (Human Interface Device) is a USB class that Bluetooth and most 2.4 GHz
dongles reuse. It has two pieces that matter here.

**Reports** are the actual data. An *input report* is a small packet the
device sends to the host, typically every few milliseconds or whenever
something changes. For a gamepad it's something like
`01 80 7F 80 80 08 00 00 00 00`: stick positions, a hat, and a bitfield of
buttons. *Output reports* go the other way (for example, rumble or LEDs), and
*feature reports* are request/response configuration.

**The report descriptor** is how the device explains its reports. It's a
compact bytecode program the host runs once when the device connects. It
contains no data; it declares the layout. For example:

```
05 01        Usage Page (Generic Desktop)
09 30        Usage (X)
15 00        Logical Minimum (0)
26 FF 00     Logical Maximum (255)
75 08        Report Size (8)       <- bits per field
95 01        Report Count (1)      <- number of fields
81 02        Input (Data, Var, Abs) <- "emit": allocate those bits in the input report
```

That reads as "the next 8 bits of the input report are the X axis, 0 to 255."
The parser in `discovery/hid_descriptor.py` runs the whole program and
produces a field table: byte and bit offset, size, range, and meaning. Read
its module docstring for the item encoding. It's about 1 byte of prefix and
0 to 4 bytes of data per item.

A few concepts that show up in the output:

| Term | Meaning |
|---|---|
| Usage Page / Usage | A (page, id) pair saying what a field *means*. `(0x01, 0x30)` is Generic Desktop X. Page `0x09` is Buttons, where usage *n* is "Button n". Pages `0xFF00`–`0xFFFF` are vendor-defined (opaque). |
| Report ID | When a device has several report types, byte 0 of each report is an ID saying which layout applies. If the descriptor declares no IDs, there's no ID byte. |
| Logical Min/Max | The raw value range. If the minimum is negative, the field is signed. |
| Hat Switch | Usage `0x39`. A D-pad encoded as a direction number: usually 0 = N, 1 = NE, … 7 = NW, plus an out-of-range "null" value (often 8 or 15) for centered. |
| Var vs Array | `Var`: one field per usage (normal for gamepads). `Array`: each slot holds the *index* of a pressed usage (normal for keyboards). |
| Const | Padding bits that keep fields byte-aligned. |

**The macOS stack.** The kernel's IOHIDFamily parses the descriptor and
publishes an `IOHIDDevice` in the IORegistry. Userspace reaches it through
IOKit's `IOHIDManager`/`IOHIDDevice` APIs. `hidapi` is a thin cross-platform
wrapper over exactly those calls, so what we see in Python is what a native
daemon sees in Phase 3. You can inspect the same data with
`ioreg -r -c IOHIDDevice -l | less` (look for `ReportDescriptor`, `VendorID`,
`ProductID` and `Transport`).

## Setup (Apple Silicon)

```bash
cd discovery
python3 -m venv .venv            # python3 from Xcode CLT (3.9+) or Homebrew
source .venv/bin/activate
pip install -r requirements.txt  # installs hidapi (Cython binding, prebuilt arm64 wheel)
```

If `pip` tries to compile hidapi from source, install the Command Line Tools
first (`xcode-select --install`).

> **Two packages called `hid`.** PyPI has `hidapi` (the Cython binding we use)
> and an unrelated ctypes package named `hid`. Both install a module called
> `hid`. The script detects the wrong one and tells you how to fix it.

### Permissions and gotchas

- **Input Monitoring.** If opening the device fails, go to
  System Settings → Privacy & Security → Input Monitoring, enable your
  terminal app (Terminal, iTerm, or VS Code), then quit and relaunch the
  terminal. macOS requires this whenever a device exposes keyboard or mouse
  usages. The Raikiri may expose those even in wireless mode.
- **Exclusive access.** On macOS, hidapi opens devices in *seize* mode, so
  while the script runs other apps (a browser tab using the Gamepad API,
  Steam) can't see the controller, and vice versa. Close them if the open
  fails.
- **Multiple interfaces.** One physical controller can expose several HID
  interfaces (the gamepad, a consumer-control interface for volume/media, and
  a vendor interface for Armoury Crate configuration). The script picks the
  one declaring Game Pad or Joystick. Use `list` to see all of them and
  `--path` to choose another.

## Steps

Run these with the controller in **wireless mode**, powered on and connected.

### 1. List interfaces

```bash
python3 raikiri_probe.py list          # ASUS (VID 0x0B05) devices only
python3 raikiri_probe.py list --all    # everything, if nothing shows up
```

Note the **bus** column. It says whether the "wireless mode" you're using is
the 2.4 GHz dongle (shows as USB) or Bluetooth. That matters in Phase 2,
because the Xbox Wireless Controller that macOS recognizes is a *Bluetooth*
HID device.

### 2. Dump the report descriptor

```bash
python3 raikiri_probe.py descriptor --save raikiri_descriptor.bin | tee raikiri_descriptor.txt
```

You get a hex dump, the item-by-item decode, and the field table. Check the
field table against what the browser reported: 15 buttons, and which usages
account for the 7 "axes." The browser's axis numbering is Chrome's own
ordering, so the descriptor is the source of truth.

### 3. Watch live reports

```bash
python3 raikiri_probe.py monitor
python3 raikiri_probe.py monitor --min-delta 3   # hide small stick jitter
```

Each line is a report that differs from the previous one. Changed bytes are
highlighted, and below each line is the decoded list of changed fields. Try:

1. **Leave the controller untouched for 5 seconds, then press Ctrl-C.** The
   statistics show whether it streams reports continuously (steady rate even
   when idle) or only reports on change, plus the interval distribution. That
   rate and jitter set our latency floor for Phase 3.
2. Press a few buttons and watch which bit flips.
3. Move each stick to all four extremes and note which value means "up." HID
   convention is Y increasing *downward*, but devices vary.
4. Pull each trigger slowly. Is it analog? What's the resolution? Does it
   also flip a digital button at full pull?

### 4. Guided mapping

```bash
python3 raikiri_probe.py map --out raikiri_mapping.json
```

The script first learns the resting state of every field (hands off!), then
prompts for each control in Xbox terms (A, B, …, LT, RT, D-pad, stick
directions), then the M1–M6 back buttons. For each prompt: press and hold the control, then
release. It records every field that moved, which is the **primary** field
(analog fields first, then by how far they moved), and the value at rest and
at the extreme. If you don't press anything for 8 seconds, it skips that
control, which is useful for buttons the controller doesn't have.

To redo a few controls: `map --controls LT,RT,Guide --out redo.json`.

It prints a Markdown table at the end. Paste it into
[`raikiri-mapping.md`](raikiri-mapping.md).

## Programmable back buttons (M1–M6)

The M buttons are the most important unknown, because the design decides who
controls them. You set up a remap in Armoury Crate or on the controller, and
it's saved in the controller's firmware. The firmware then reports M buttons
over HID in one of three ways:

| What the firmware sends | What `map` shows | What it means for us |
|---|---|---|
| **A copy of the assigned button.** M1 set to A sends A's bit. | M1 has the same field and value as A, plus a note saying so. | Your remaps keep working on the Mac automatically, and changing them needs no change on our side. But the Mac only ever sees "A," so the daemon can't give M1 a separate job. |
| **Its own bit** (for example, button 14), whatever it's assigned to. | M1 has a field no other control uses. | The daemon sees M1 directly and can map it to anything through its own config file. That gives you remapping on the Mac, independent of Armoury Crate. |
| **Nothing** (unassigned in the current profile). | M1 is *(skipped)*. | Assign it to something and map again to see which of the rows above applies. |

The descriptor alone can't tell these apart: it declares button slots but
not which physical button drives each one. Counting still helps. The browser
saw 15 buttons, and the standard controls (A, B, X, Y, LB, RB, View, Menu,
L3, R3, Guide) use about 11 of them. That leaves too few slots for six M
buttons to each have their own bit in this report. So expect either firmware
copying for at least some of them, or a separate report (possibly on the
vendor-defined interface; check `list`). The end-of-map notes also list
fields no control moved. Those are the candidate slots for M buttons in
another profile.

To pin down the behavior, run `map` twice:

1. With each M button assigned to a *different* standard button (M1 = A,
   M2 = B, M3 = X, M4 = Y, M5 = LB, M6 = RB). If the M buttons then match those face buttons, the
   controller is copying the assigned button (row 1).
2. With the M buttons unassigned or disabled, if the controller allows it.
   If they still produce their own bits, they're raw inputs (row 2). If they
   go silent, it's row 3.

Profiles are stored on the controller, and so is any profile-switch button.
Note which profile was active when you captured, because the mapping is a
snapshot of that profile.

## What we need to learn (Phase 1 exit checklist)

- [ ] Transport of wireless mode: USB (dongle) or Bluetooth
- [ ] Full report descriptor saved (`raikiri_descriptor.bin`)
- [ ] Top-level collections and all interfaces (gamepad, consumer, vendor?)
- [ ] Report ID(s) and input report length
- [ ] Stick axes: usages, bit depth, range, center value, direction polarity
- [ ] Triggers: usages, analog resolution, whether they also report as buttons
- [ ] D-pad: hat switch or four buttons; value per direction; null value
- [ ] All 15 buttons identified, including whether the ROG/Guide button is reported at all
- [ ] M1–M6: own bits, copies of the assigned button, or silent (see [Programmable back buttons](#programmable-back-buttons-m1m6))
- [ ] Idle behavior: continuous streaming or on-change; report interval (median, p95)
- [ ] Output reports in the descriptor (rumble? LEDs?), for later

## Files produced

| File | What it is |
|---|---|
| `raikiri_descriptor.bin` | Raw descriptor bytes. Decode it offline any time with `descriptor --descriptor-file raikiri_descriptor.bin`. |
| `raikiri_descriptor.txt` | Human-readable decode |
| `raikiri_mapping.json` | Per-control mapping, plus descriptor hex and sample reports |

Commit these under `docs/captures/` so later phases can build test fixtures
from real data.
