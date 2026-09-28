"""Checks for raikiri_sdl_mapping.txt.

The format checks always run. The semantic checks run against real SDL2 when
PySDL2 is installed (pip install pysdl2 pysdl2-dll): they decode the GUID and
drive a virtual joystick numbered like the Raikiri is under SDL's macOS IOKit
backend, then check which Xbox-style controls SDL reports.
"""

import ctypes
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sdl_probe import env_value, load_mappings  # noqa: E402

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import sdl2  # type: ignore
except ImportError:
    sdl2 = None


class FormatTests(unittest.TestCase):
    def test_lines(self):
        maps = load_mappings()
        self.assertEqual(len(maps), 3)
        # Exact GUID captured on the Mac, then CRC-less fallbacks.
        self.assertEqual([m.split(",")[0] for m in maps],
                         ["0300b3cc050b0000661c000009050000", "03000000050b0000661c000009050000",
                          "03000000050b0000661c000000000000"])
        self.assertEqual(len({m.split(",", 1)[1] for m in maps}), 1)   # same mapping body
        for m in maps:
            self.assertTrue(m.endswith("platform:Mac OS X,"))
        self.assertEqual(env_value(maps).count("\n"), 2)


@unittest.skipUnless(sdl2, "PySDL2 not installed")
class SdlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert sdl2.SDL_Init(sdl2.SDL_INIT_GAMECONTROLLER) == 0

    @classmethod
    def tearDownClass(cls):
        sdl2.SDL_Quit()

    def test_guid_decodes_to_raikiri(self):
        for m in load_mappings():
            g = sdl2.SDL_JoystickGetGUIDFromString(m.split(",")[0].encode())
            v, p, ver, crc = (ctypes.c_uint16() for _ in range(4))
            sdl2.SDL_GetJoystickGUIDInfo(g, *(ctypes.byref(x) for x in (v, p, ver, crc)))
            self.assertEqual((v.value, p.value), (0x0B05, 0x1C66))
            self.assertIn(crc.value, (0, 0xCCB3))
            self.assertIn(ver.value, (0x0509, 0))
            self.assertGreaterEqual(sdl2.SDL_GameControllerAddMapping(m.encode()), 0)

    def test_controls(self):
        idx = sdl2.SDL_JoystickAttachVirtual(sdl2.SDL_JOYSTICK_TYPE_UNKNOWN, 6, 16, 1)
        js = sdl2.SDL_JoystickOpen(idx)
        buf = ctypes.create_string_buffer(33)
        sdl2.SDL_JoystickGetGUIDString(sdl2.SDL_JoystickGetGUID(js), buf, 33)
        body = load_mappings()[0].split(",", 1)[1].replace("platform:Mac OS X,", "")
        self.assertGreaterEqual(sdl2.SDL_GameControllerAddMapping(f"{buf.value.decode()},{body}".encode()), 0)
        gc = sdl2.SDL_GameControllerOpen(idx)
        self.assertTrue(gc)

        def update():
            sdl2.SDL_JoystickUpdate()
            sdl2.SDL_GameControllerUpdate()

        def btn(name):
            return sdl2.SDL_GameControllerGetButton(gc, getattr(sdl2, "SDL_CONTROLLER_BUTTON_" + name))

        # HID button number (from the Phase 1 capture) -> Xbox control.
        expect = {1: "A", 2: "B", 4: "X", 5: "Y", 7: "LEFTSHOULDER", 8: "RIGHTSHOULDER", 11: "BACK",
                  12: "START", 13: "GUIDE", 14: "LEFTSTICK", 15: "RIGHTSTICK"}
        for hid, name in expect.items():
            sdl2.SDL_JoystickSetVirtualButton(js, hid - 1, 1)
            update()
            self.assertEqual(btn(name), 1, f"HID button {hid}")
            sdl2.SDL_JoystickSetVirtualButton(js, hid - 1, 0)
            update()
        sdl2.SDL_JoystickSetVirtualHat(js, 0, sdl2.SDL_HAT_DOWN)
        update()
        self.assertEqual(btn("DPAD_DOWN"), 1)
        # Accelerator (usage 0xC4) sorts before Brake (0xC5): a4 = RT, a5 = LT.
        # A released trigger is logical 0, which SDL reports as axis -32768.
        sdl2.SDL_JoystickSetVirtualAxis(js, 4, -32768)
        sdl2.SDL_JoystickSetVirtualAxis(js, 5, 32767)
        update()
        self.assertEqual(sdl2.SDL_GameControllerGetAxis(gc, sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT), 32767)
        self.assertEqual(sdl2.SDL_GameControllerGetAxis(gc, sdl2.SDL_CONTROLLER_AXIS_TRIGGERRIGHT), 0)


if __name__ == "__main__":
    unittest.main()
