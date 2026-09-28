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

Captured with `map` over Bluetooth on 2026-09-28
([captures/raikiri-bt-mapping.json](captures/raikiri-bt-mapping.json)).
Field keys are `I<report id>@<bit offset>+<bit size>`, with the offset counted
from the byte after the report ID. Every standard control matches the Xbox
Series Bluetooth layout above.

| Control | Field | Report/bit | Rest | Pressed | Notes |
|---|---|---|---|---|---|
| A | Button 1 | I1@104+1 | 0 | 1 | |
| B | Button 2 | I1@105+1 | 0 | 1 | |
| X | Button 4 | I1@107+1 | 0 | 1 | |
| Y | Button 5 | I1@108+1 | 0 | 1 | |
| LB | Button 7 | I1@110+1 | 0 | 1 | |
| RB | Button 8 | I1@111+1 | 0 | 1 | |
| LT | Brake | I1@64+10 | 0 | 1023 | Analog only, no digital bit |
| RT | Accelerator | I1@80+10 | 0 | 1023 | Analog only, no digital bit |
| View | Button 11 | I1@114+1 | 0 | 1 | |
| Menu | Button 12 | I1@115+1 | 0 | 1 | |
| Guide | *nothing in report 0x01* | | | | **Open question**; see below |
| L3 | Button 14 | I1@117+1 | 0 | 1 | |
| R3 | Button 15 | I1@118+1 | 0 | 1 | |
| D-pad up / right / down / left | Hat Switch | I1@96+4 | 0 | 1 / 3 / 5 / 7 | Diagonals are the even values |
| Left stick left / right | X | I1@0+16 | 32897 | 13 / 65515 | |
| Left stick up / down | Y | I1@16+16 | 34136 | 6 / 65515 | Up is 0 |
| Right stick left / right | Z | I1@32+16 | 33664 | 3 / 65455 | |
| Right stick up / down | Rz | I1@48+16 | 33574 | 33 / 65503 | Up is 0 |
| M1 | Button 4 | I1@107+1 | 0 | 1 | Same as X |
| M2 | Button 5 | I1@108+1 | 0 | 1 | Same as Y |
| M3 | Button 14 | I1@117+1 | 0 | 1 | Same as L3 |
| M4 | Button 1 | I1@104+1 | 0 | 1 | Same as A |
| M5 | Button 2 | I1@105+1 | 0 | 1 | Same as B |
| M6 | Hat Switch | I1@96+4 | 0 | 1 (N) | Same as D-pad up |

Never moved: buttons 3, 6, 9 and 10 (unused on Xbox too), button 13 (Xbox's
Guide slot) and Share/Record (this controller may not have a Share button).

### M buttons: copied in firmware

Each M button sent exactly the bits of its assigned control, even when that
control was a D-pad direction. None has a bit of its own. So:

- Reassigning M buttons on the controller or in Armoury Crate carries over to
  the Mac automatically. Nothing on our side needs to change.
- The Mac can't tell an M button from the control it copies, so the Phase 3
  daemon can't give M buttons separate functions.
- The assignments seen here (M1 = X, M2 = Y, M3 = L3, M4 = A, M5 = B,
  M6 = D-pad up) are whatever the active profile held during the capture.

### Guide button: open question

Pressing Guide changed nothing in report 0x01. Xbox puts Guide at button 13,
which never moved. Possible explanations:

1. It arrives in a separate report ID that the descriptor doesn't declare.
   Older Xbox One S firmware did this. The tool used to hide such reports;
   `monitor` and `map` now print them.
2. The controller keeps the button for itself (power, pairing, profiles or
   menus) and never sends it over Bluetooth.

Check by running `monitor` and pressing only Guide.

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
