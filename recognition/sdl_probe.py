#!/usr/bin/env python3
"""Phase 2: see the Raikiri the way SDL (bundled inside GeForce NOW) sees it.

GeForce NOW's native app ships SDL2 and, for controllers Apple's framework
doesn't take, only accepts devices that SDL calls a *game controller*: a
joystick with a mapping in SDL's controller database. The Raikiri's ID isn't
in that database. This tool:

  1. lists every SDL joystick with its GUID, IDs and button/axis/hat counts,
     and whether SDL considers it a game controller
  2. adds our mapping (raikiri_sdl_mapping.txt) and checks again
  3. prints named game-controller events (a, leftshoulder, lefttrigger, ...)
     as you press things, so you can confirm the mapping is right

Setup (inside the discovery venv, or any Python 3):
  pip install pysdl2 pysdl2-dll

Usage:
  python3 sdl_probe.py              # 30 s, with our mapping
  python3 sdl_probe.py --raw        # also print raw joystick indices
  python3 sdl_probe.py --no-mapping # SDL's view without our mapping
  python3 sdl_probe.py --no-mfi     # stop SDL deferring devices to Apple's framework
  python3 sdl_probe.py --print-env  # print the SDL_GAMECONTROLLERCONFIG value

About --no-mfi: before SDL's macOS IOKit backend opens a HID device, it asks
Apple's framework `[GCController supportsHIDDevice:]`. If the answer is yes,
SDL leaves the device to its GameController ("MFi") backend. If Apple claims
a device but never delivers a GCController for it, SDL ends up with nothing.
Setting the SDL_JOYSTICK_MFI hint to 0 turns that check (and that backend)
off.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from typing import List

HERE = os.path.dirname(os.path.abspath(__file__))
MAPPING_FILE = os.path.join(HERE, "raikiri_sdl_mapping.txt")


def load_mappings(path: str = MAPPING_FILE) -> List[str]:
    """Mapping lines from the file, without comments or blank lines."""
    with open(path) as fh:
        return [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]


def env_value(mappings: List[str]) -> str:
    """SDL_GAMECONTROLLERCONFIG accepts several mappings separated by newlines."""
    return "\n".join(mappings)


def guid_string(sdl2, guid) -> str:
    buf = ctypes.create_string_buffer(33)
    sdl2.SDL_JoystickGetGUIDString(guid, buf, 33)
    return buf.value.decode()


def describe_joysticks(sdl2) -> None:
    n = sdl2.SDL_NumJoysticks()
    print(f"SDL sees {n} joystick(s):")
    for i in range(n):
        name = (sdl2.SDL_JoystickNameForIndex(i) or b"?").decode(errors="replace")
        guid = guid_string(sdl2, sdl2.SDL_JoystickGetDeviceGUID(i))
        vid = sdl2.SDL_JoystickGetDeviceVendor(i)
        pid = sdl2.SDL_JoystickGetDeviceProduct(i)
        ver = sdl2.SDL_JoystickGetDeviceProductVersion(i)
        js = sdl2.SDL_JoystickOpen(i)
        counts = ""
        if js:
            counts = (f"buttons={sdl2.SDL_JoystickNumButtons(js)} axes={sdl2.SDL_JoystickNumAxes(js)} "
                      f"hats={sdl2.SDL_JoystickNumHats(js)}")
        is_gc = bool(sdl2.SDL_IsGameController(i))
        print(f"  [{i}] {name}\n      GUID {guid}  VID {vid:04X} PID {pid:04X} version {ver:04X}  {counts}\n"
              f"      game controller: {'YES' if is_gc else 'no'}")
        if is_gc:
            gc = sdl2.SDL_GameControllerOpen(i)
            mapping = sdl2.SDL_GameControllerMapping(gc) if gc else None
            if mapping:
                print(f"      mapping: {mapping.decode(errors='replace')[:160]}...")


def watch(sdl2, seconds: float, raw: bool) -> None:
    print(f"\nListening for {seconds:.0f} s. Press buttons, move sticks, pull triggers.")
    event = sdl2.SDL_Event()
    last_axis = {}
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            t = event.type
            if t == sdl2.SDL_CONTROLLERDEVICEADDED:
                sdl2.SDL_GameControllerOpen(event.cdevice.which)
                print("  controller added")
            elif t in (sdl2.SDL_CONTROLLERBUTTONDOWN, sdl2.SDL_CONTROLLERBUTTONUP):
                name = sdl2.SDL_GameControllerGetStringForButton(event.cbutton.button).decode()
                state = "pressed" if t == sdl2.SDL_CONTROLLERBUTTONDOWN else "released"
                print(f"  controller button {name}: {state}")
            elif t == sdl2.SDL_CONTROLLERAXISMOTION:
                name = sdl2.SDL_GameControllerGetStringForAxis(event.caxis.axis).decode()
                v = event.caxis.value
                # Print only when the axis crosses a coarse step, to avoid jitter spam.
                step = round(v / 16384)
                if last_axis.get(name) != step:
                    last_axis[name] = step
                    print(f"  controller axis {name}: {v}")
            elif raw and t in (sdl2.SDL_JOYBUTTONDOWN, sdl2.SDL_JOYBUTTONUP):
                state = "down" if t == sdl2.SDL_JOYBUTTONDOWN else "up"
                print(f"    raw b{event.jbutton.button} {state}")
            elif raw and t == sdl2.SDL_JOYHATMOTION:
                print(f"    raw h{event.jhat.hat} = {event.jhat.value}")
            elif raw and t == sdl2.SDL_JOYAXISMOTION:
                key = f"a{event.jaxis.axis}"
                step = round(event.jaxis.value / 16384)
                if last_axis.get(key) != step:
                    last_axis[key] = step
                    print(f"    raw {key} = {event.jaxis.value}")
        time.sleep(0.005)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seconds", nargs="?", type=float, default=30)
    ap.add_argument("--raw", action="store_true", help="also print raw joystick button/axis/hat indices")
    ap.add_argument("--no-mapping", action="store_true", help="don't add our mapping")
    ap.add_argument("--no-mfi", action="store_true",
                    help="set SDL_JOYSTICK_MFI=0 so SDL doesn't defer devices to Apple's framework")
    ap.add_argument("--print-env", action="store_true", help="print the SDL_GAMECONTROLLERCONFIG value and exit")
    args = ap.parse_args(argv)

    mappings = load_mappings()
    if args.print_env:
        print(env_value(mappings))
        return
    try:
        import sdl2  # type: ignore
    except ImportError:
        sys.exit("PySDL2 not found. Install it with:  pip install pysdl2 pysdl2-dll")

    sdl2.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
    if args.no_mfi:
        sdl2.SDL_SetHint(b"SDL_JOYSTICK_MFI", b"0")
    if sdl2.SDL_Init(sdl2.SDL_INIT_GAMECONTROLLER) != 0:
        sys.exit(f"SDL_Init failed: {sdl2.SDL_GetError().decode()}")
    v = sdl2.SDL_version()
    sdl2.SDL_GetVersion(ctypes.byref(v))
    print(f"SDL {v.major}.{v.minor}.{v.patch}\n")
    time.sleep(0.5)   # let device discovery settle
    sdl2.SDL_PumpEvents()

    mfi = (sdl2.SDL_GetHint(b"SDL_JOYSTICK_MFI") or b"(default: on)").decode()
    print(f"SDL_JOYSTICK_MFI = {mfi}\n")
    print("Without our mapping:")
    describe_joysticks(sdl2)
    if sdl2.SDL_NumJoysticks() == 0 and not args.no_mfi:
        print("  (none: try again with --no-mfi; see the docstring for why)")
    if not args.no_mapping:
        for m in mappings:
            if sdl2.SDL_GameControllerAddMapping(m.encode()) < 0:
                print(f"error: SDL rejected a mapping line: {sdl2.SDL_GetError().decode()}")
        print("\nWith our mapping:")
        describe_joysticks(sdl2)
    try:
        watch(sdl2, args.seconds, args.raw)
    except KeyboardInterrupt:
        pass
    sdl2.SDL_Quit()


if __name__ == "__main__":
    main()
