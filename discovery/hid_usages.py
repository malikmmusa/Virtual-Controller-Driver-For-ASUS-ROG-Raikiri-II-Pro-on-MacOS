"""Human-readable names for HID usage pages and usages.

Only the pages a game controller is likely to use are covered. The source of
truth is the USB-IF "HID Usage Tables" document (HUT 1.4+); anything not in
these tables is printed as a hex number instead.
"""

from __future__ import annotations

USAGE_PAGES = {
    0x01: "Generic Desktop",
    0x02: "Simulation Controls",
    0x05: "Game Controls",
    0x06: "Generic Device Controls",
    0x07: "Keyboard/Keypad",
    0x08: "LED",
    0x09: "Button",
    0x0C: "Consumer",
    0x0F: "Physical Input Device (Haptics/FFB)",
    0x20: "Sensors",
}

_GENERIC_DESKTOP = {
    0x01: "Pointer",
    0x02: "Mouse",
    0x04: "Joystick",
    0x05: "Game Pad",
    0x06: "Keyboard",
    0x07: "Keypad",
    0x08: "Multi-axis Controller",
    0x30: "X",
    0x31: "Y",
    0x32: "Z",
    0x33: "Rx",
    0x34: "Ry",
    0x35: "Rz",
    0x36: "Slider",
    0x37: "Dial",
    0x38: "Wheel",
    0x39: "Hat Switch",
    0x3D: "Start",
    0x3E: "Select",
    0x40: "Vx",
    0x41: "Vy",
    0x42: "Vz",
    0x80: "System Control",
    0x85: "System Main Menu",
    0x90: "D-pad Up",
    0x91: "D-pad Down",
    0x92: "D-pad Right",
    0x93: "D-pad Left",
}

_SIMULATION = {
    0xBB: "Throttle",
    0xC4: "Accelerator",
    0xC5: "Brake",
}

_CONSUMER = {
    0x01: "Consumer Control",
    0x30: "Power",
    0x40: "Menu",
    0xB0: "Play",
    0xB1: "Pause",
    0xB2: "Record",
    0xCD: "Play/Pause",
    0xE2: "Mute",
    0xE9: "Volume Increment",
    0xEA: "Volume Decrement",
    0x223: "AC Home",
    0x224: "AC Back",
}

_PAGES = {
    0x01: _GENERIC_DESKTOP,
    0x02: _SIMULATION,
    0x0C: _CONSUMER,
}

COLLECTION_TYPES = {
    0x00: "Physical",
    0x01: "Application",
    0x02: "Logical",
    0x03: "Report",
    0x04: "Named Array",
    0x05: "Usage Switch",
    0x06: "Usage Modifier",
}


def page_name(page: int) -> str:
    if page in USAGE_PAGES:
        return USAGE_PAGES[page]
    if 0xFF00 <= page <= 0xFFFF:
        return f"Vendor Defined 0x{page:04X}"
    return f"Page 0x{page:04X}"


def usage_name(page: int, usage: int) -> str:
    if page == 0x09:
        return "No Button" if usage == 0 else f"Button {usage}"
    if page == 0x07:
        return f"Key 0x{usage:02X}"
    table = _PAGES.get(page, {})
    if usage in table:
        return table[usage]
    return f"{page_name(page)}:0x{usage:02X}"
