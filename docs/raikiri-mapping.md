# Raikiri II Pro (Bluetooth) → field mapping

The device facts and descriptor findings below come from the captured
descriptor ([captures/raikiri-bt-descriptor.hex](captures/raikiri-bt-descriptor.hex)).
Fill in the Controls table from `raikiri_probe.py map` output; see
[phase1-discovery.md](phase1-discovery.md).

## Device

| Property | Value |
|---|---|
| VID:PID | 0x0B05:0x1C66 |
| Product string | RAIKIRI II PRO PC |
| Transport (wireless mode) | Bluetooth |
| Report ID(s) | 0x01 input (state), 0x03 output (rumble) |
| Input report length (bytes, incl. ID) | 17 |
| Idle behavior | On change only: no reports while untouched |
| Report interval | About 30 ms steps (33 Hz) while a stick moves: min 19, median 30 ms. Gaps between separate presses are multiples of about 30 ms. |
| Other interfaces | None over Bluetooth. The single interface is the gamepad; "Pointer" is only the Physical collection around the sticks. |

## Descriptor findings

The descriptor has the **same report layout as the Xbox Series X|S
controller over Bluetooth (firmware 5.x)**, as documented by SDL
(`src/joystick/hidapi/SDL_hidapi_xboxone.c`, `HIDAPI_DriverXboxOneBluetooth_HandleButtons`).
The Raikiri already sends Xbox-format reports, just under ASUS's VID/PID.

Input report 0x01 (byte index includes the ID byte, as SDL counts it):

| Bytes | Field | Range |
|---|---|---|
| 1–2, 3–4 | Left stick X, Y | 0..65535, 16-bit unsigned |
| 5–6, 7–8 | Right stick X (Z), Y (Rz) | 0..65535 |
| 9–10 | LT (Brake), low 10 bits | 0..1023 |
| 11–12 | RT (Accelerator), low 10 bits | 0..1023 |
| 13 | D-pad hat, low nibble | 1 = N … 8 = NW, 0 = centered |
| 14–15 | Buttons 1–15, 1 bit each | |
| 16 | Share (Consumer: Record), bit 0 | |

Button assignment we *expect* if it matches Xbox (from SDL); confirm with `map`:

| HID button | Bit | Xbox control |
|---|---|---|
| 1 | byte 14, 0x01 | A |
| 2 | byte 14, 0x02 | B |
| 3 | byte 14, 0x04 | *(unused on Xbox)* |
| 4 | byte 14, 0x08 | X |
| 5 | byte 14, 0x10 | Y |
| 6 | byte 14, 0x20 | *(unused on Xbox)* |
| 7 | byte 14, 0x40 | LB |
| 8 | byte 14, 0x80 | RB |
| 9, 10 | byte 15, 0x01/0x02 | *(unused on Xbox)* |
| 11 | byte 15, 0x04 | View |
| 12 | byte 15, 0x08 | Menu |
| 13 | byte 15, 0x10 | Guide |
| 14 | byte 15, 0x20 | L3 |
| 15 | byte 15, 0x40 | R3 |

Four slots are unused (3, 6, 9, 10), so six M buttons can't each have their
own bit. Expect them to copy their assigned button, unless the four spare
slots turn out to carry some of them.

Output report 0x03 is Xbox-style rumble: a 4-bit motor enable mask, four
magnitudes of 0–100 (the Xbox order is left trigger, right trigger, strong,
weak; to verify), duration and start delay in 10 ms units, and a loop count.

## Controls

Field keys are `I<report id>@<bit offset>+<bit size>`, as printed by the tool.

| Control | Field | Report/bit | Rest | Pressed | Also changes |
|---|---|---|---|---|---|
| A | | | | | |
| B | | | | | |
| X | | | | | |
| Y | | | | | |
| LB | | | | | |
| RB | | | | | |
| LT | | | | | |
| RT | | | | | |
| View | | | | | |
| Menu | | | | | |
| Guide | | | | | |
| L3 | | | | | |
| R3 | | | | | |
| DpadUp | | | | | |
| DpadRight | | | | | |
| DpadDown | | | | | |
| DpadLeft | | | | | |
| LSLeft | | | | | |
| LSRight | | | | | |
| LSUp | | | | | |
| LSDown | | | | | |
| RSLeft | | | | | |
| RSRight | | | | | |
| RSUp | | | | | |
| RSDown | | | | | |
| M1 | | | | | |
| M2 | | | | | |
| M3 | | | | | |
| M4 | | | | | |
| M5 | | | | | |
| M6 | | | | | |

## Observations

From the first `monitor` capture (Bluetooth, macOS):

- **Report timing.** The controller sends only when something changes, and
  never faster than about every 30 ms. Almost every interval is close to a
  multiple of 30 ms (29.8, 59.9, 89, 120, 181, 240, 300…). All 65 received
  reports were distinct, so nothing was hidden by the tool's de-duplication.
  At 33 Hz, input can wait up to about 30 ms before it's even sent. That's a
  property of the controller and its Bluetooth link, not of our code, and it
  sets the latency floor for this connection. It's worth comparing with other
  connection modes later.
- **Buttons seen** in the capture all landed in the slots the Xbox layout
  predicts: 1, 4, 5, 7, 8 and 14. None landed in the unused slots 3, 6, 9 or
  10. The D-pad reported hat value 5 (S). `map` will confirm which physical
  button is which.
- **Resting stick values** in this capture: left X ≈ 33040–33346,
  left Y ≈ 34106 (about 4% off the 32768 center), right X 32890,
  right Y 32995.
- **Stick return artifact.** After the left stick is released, reports
  alternate between one fixed value (for example X 33295, Y 34127 repeated
  exactly) and a series that converges toward center over about 300 ms,
  then drifts slowly for another second. It looks like firmware filtering.
  It's within a normal dead zone (about 5% of range), but Phase 3 should
  keep it in mind.

*Record which controller profile was active and what each M button was
assigned to during the capture.*

*Notes on quirks: axis polarity, trigger/button overlap, dead zones, fields
that never change, and so on.*
