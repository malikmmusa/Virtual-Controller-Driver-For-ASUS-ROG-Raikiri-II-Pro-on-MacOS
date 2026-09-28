"""Tests for the parsing parts of inspect_system.py. No Mac needed.

Run from the repo root:  python3 -m unittest discover -s recognition/tests -v
"""

import os
import plistlib
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import inspect_system as ins  # noqa: E402

RAIKIRI = {
    "IOObjectClass": "IOHIDDevice",
    "IORegistryEntryName": "RAIKIRI II PRO PC",
    "Product": "RAIKIRI II PRO PC",
    "VendorID": 0x0B05,
    "ProductID": 0x1C66,
    "Transport": "Bluetooth",
    "SerialNumber": "a4-c1-38-12-34-56",
    "PrimaryUsagePage": 1,
    "PrimaryUsage": 5,
    "DeviceUsagePairs": [{"DeviceUsagePage": 1, "DeviceUsage": 5}, {"DeviceUsagePage": 1, "DeviceUsage": 1}],
    "ReportDescriptor": bytes(range(40)),
    "IORegistryEntryChildren": [
        {"IOObjectClass": "IOHIDInterface", "IORegistryEntryName": "IOHIDInterface",
         "IORegistryEntryChildren": [{"IOObjectClass": "IOHIDEventDriver", "IORegistryEntryName": "IOHIDEventDriver",
                                      "CFBundleIdentifier": "com.apple.iokit.IOHIDFamily"}]},
    ],
}
KEYBOARD = {"IOObjectClass": "AppleHIDKeyboard", "Product": "Apple Internal Keyboard", "VendorID": 0x05AC,
            "PrimaryUsagePage": 1, "PrimaryUsage": 6}


class IoregTests(unittest.TestCase):
    def test_only_controllers_are_listed_with_driver_stack(self):
        text = ins.describe_hid_devices(plistlib.dumps([KEYBOARD, RAIKIRI]))
        self.assertIn("--- RAIKIRI II PRO PC  [IOHIDDevice]", text)
        self.assertNotIn("Apple Internal Keyboard", text)
        self.assertIn('Transport = "Bluetooth"', text)
        self.assertIn("VendorID = 2821 (0xB05)", text)
        self.assertIn("ReportDescriptor = <40 bytes> 00 01 02", text)
        self.assertIn("IOHIDEventDriver [IOHIDEventDriver] CFBundleIdentifier=com.apple.iokit.IOHIDFamily", text)

    def test_serial_is_masked(self):
        text = ins.describe_hid_devices(plistlib.dumps([RAIKIRI]))
        self.assertNotIn("12-34", text)
        self.assertIn('SerialNumber = "xx-xx-xx-xx-xx-56" (masked)', text)

    def test_nothing_connected_and_garbage(self):
        self.assertIn("no controller-like", ins.describe_hid_devices(plistlib.dumps([KEYBOARD])))
        self.assertIn("could not parse", ins.describe_hid_devices(b"not a plist"))


class BluetoothTests(unittest.TestCase):
    PROFILE = """Bluetooth:

      Bluetooth Controller:
          Address: 11:22:33:44:55:66
      Connected:
          RAIKIRI II PRO PC:
              Address: A4:C1:38:12:34:56
              Vendor ID: 0x0B05
              Product ID: 0x1C66
              Minor Type: Gamepad
          Magic Mouse:
              Address: 00:00:00:00:00:01
"""

    def test_extracts_and_masks_block(self):
        block = ins.bluetooth_block(self.PROFILE)
        self.assertIn("Minor Type: Gamepad", block)
        self.assertNotIn("Magic Mouse", block)
        self.assertNotIn("12:34", block)
        self.assertIn("xx:xx:xx:xx:xx:56 (masked)", block)

    def test_missing(self):
        self.assertIn("no Bluetooth device", ins.bluetooth_block("Bluetooth:\n  Connected:\n"))


class PlistScanTests(unittest.TestCase):
    def test_finds_nested_microsoft_entries(self):
        doc = {"Controllers": [{"VendorID": 1118, "ProductID": 2835, "Name": "Xbox Series X"},
                               {"VendorID": 1356, "ProductID": 3302}],
               "Other": {"idVendor": "0x045E", "idProduct": 736}}
        hits = list(ins.find_vendor_entries(doc, 0x045E))
        self.assertEqual([p for p, _ in hits], ["/Controllers[0]", "/Other"])
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.plist"), "wb") as fh:
                plistlib.dump(doc, fh, fmt=plistlib.FMT_BINARY)
            with open(os.path.join(d, "broken.plist"), "wb") as fh:
                fh.write(b"\x00junk")
            out = ins.scan_plists([d], 0x045E)
        self.assertIn("/Controllers[0]", out)
        self.assertIn("ProductID=2835", out)

    def test_booleans_are_not_vendor_ids(self):
        self.assertEqual(list(ins.find_vendor_entries({"VendorSpecific": True}, 1)), [])


class StringAndLogTests(unittest.TestCase):
    def test_string_hits(self):
        blob = (b"\x00\x01GCControllerDidConnectNotification\x00IOHIDManagerCreate\x00"
                b"SDL_GameControllerOpen\x00xinput\x00short\x00gcode_parser\x00_GCDeviceInit\x00"
                b"/System/Library/Frameworks/GameController.framework/GameController\x00")
        out = ins.string_hits(blob)
        self.assertIn("Apple GameController framework: 3 strings", out)
        self.assertIn("_GCDeviceInit", out)
        self.assertNotIn("gcode_parser", out)
        self.assertIn("IOKit HID (raw HID access): 1 strings", out)
        self.assertIn("SDL_GameControllerOpen", out)
        self.assertIn("Xbox / Microsoft IDs: 1 strings", out)
        self.assertIn("ASUS / Raikiri: 0 strings", out)

    def test_grep_tail(self):
        log = "\n".join(["boot", "Controller added vid=0x0b05 pid=0x1c66", "network ok",
                         "GCDevice init", "provider started", "gamepad removed"])
        lines = ins.grep_tail(log, ins.LOG_PATTERN, 2)
        self.assertEqual(lines, ["GCDevice init", "gamepad removed"])
        self.assertNotIn("provider started", ins.grep_tail(log, ins.LOG_PATTERN, 10))

    def test_account_ids_are_scrubbed(self):
        line = ('INFO events request {"clientId":"78589","deviceId":"a34d41","userId":"9nQJ",'
                '"gamepad":"x"} email=someone@example.com')
        out = ins.grep_tail(line, ins.LOG_PATTERN, 5)[0]
        for secret in ("78589", "a34d41", "9nQJ", "someone@"):
            self.assertNotIn(secret, out)
        self.assertIn('"gamepad":"x"', out)

    def test_mask(self):
        self.assertEqual(ins.mask("abc"), "abc")
        self.assertTrue(re.fullmatch(r"x+:x+:x+:x+:x+:66", ins.mask("11:22:33:44:55:66")))


if __name__ == "__main__":
    unittest.main()
