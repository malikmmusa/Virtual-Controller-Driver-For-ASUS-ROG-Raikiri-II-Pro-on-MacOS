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
| Idle behavior | *TBD: streams at N Hz / on change only* |
| Report interval (median / p95 ms) | *TBD* |
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

*Record which controller profile was active and what each M button was
assigned to during the capture.*

*Notes on quirks: axis polarity, trigger/button overlap, dead zones, fields
that never change, and so on.*
