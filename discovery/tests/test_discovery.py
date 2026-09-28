"""Unit tests for the descriptor parser and mapping logic. No hardware needed.

Run from the repo root:  python3 -m unittest discover -s discovery/tests -v
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from hid_descriptor import DescriptorError, format_fields, format_items, parse_descriptor, parse_items  # noqa: E402
from mapping import Baseline, PressRecorder, decode, summary_notes  # noqa: E402
import raikiri_probe  # noqa: E402

# A plausible generic gamepad: report ID 1, 4 stick axes, hat, 15 buttons,
# 2 analog triggers. Shaped like what the browser reported for the Raikiri
# (15 buttons, 7 "axes" counting the hat), but invented for the tests.
GAMEPAD = bytes.fromhex(
    "05 01 09 05 a1 01 85 01"
    "09 30 09 31 09 32 09 35 15 00 26 ff 00 75 08 95 04 81 02"   # X Y Z Rz, 8 bits
    "09 39 15 00 25 07 35 00 46 3b 01 65 14 75 04 95 01 81 42"   # hat, 4 bits, null state
    "65 00 75 04 95 01 81 03"                                    # 4 bits padding
    "05 09 19 01 29 0f 15 00 25 01 75 01 95 0f 81 02"            # buttons 1..15
    "75 01 95 01 81 03"                                          # 1 bit padding
    "05 02 09 c5 09 c4 15 00 25 ff 75 08 95 02 81 02"            # brake, accel; max 0xFF 1-byte
    "c0"
)


def report(x=0x80, y=0x80, z=0x80, rz=0x80, hat=8, buttons=0, brake=0, accel=0):
    return bytes([1, x, y, z, rz, hat & 0x0F]) + buttons.to_bytes(2, "little") + bytes([brake, accel])


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.d = parse_descriptor(GAMEPAD)
        self.by_name = {f.name: f for f in self.d.input_fields()}

    def test_layout(self):
        self.assertEqual(self.d.report_ids, [1])
        self.assertEqual(self.d.report_bits[("Input", 1)], 72)
        self.assertEqual(self.d.max_input_report_len(), 10)
        self.assertEqual(self.d.warnings, [])
        self.assertEqual(self.d.application_collections(), ["Generic Desktop / Game Pad"])
        self.assertEqual(self.by_name["X"].bit_offset, 0)
        self.assertEqual(self.by_name["Rz"].bit_offset, 24)
        self.assertEqual(self.by_name["Hat Switch"].bit_offset, 32)
        self.assertTrue(self.by_name["Hat Switch"].has_null_state)
        self.assertEqual(self.by_name["Button 1"].bit_offset, 40)
        self.assertEqual(self.by_name["Button 15"].bit_offset, 54)
        self.assertEqual(self.by_name["Accelerator"].bit_offset, 64)
        self.assertEqual(len([f for f in self.d.input_fields() if f.usage_page == 9]), 15)

    def test_one_byte_ff_logical_max_is_255(self):
        self.assertEqual(self.by_name["Brake"].logical_max, 255)
        self.assertFalse(self.by_name["Brake"].is_signed)

    def test_decode(self):
        v = decode(self.d, report(x=0, hat=2, buttons=(1 << 0) | (1 << 14), accel=200))
        names = {f.key: f.name for f in self.d.input_fields()}
        named = {names[k]: val for k, val in v.items()}
        self.assertEqual(named["X"], 0)
        self.assertEqual(named["Y"], 0x80)
        self.assertEqual(named["Hat Switch"], 2)
        self.assertEqual(named["Button 1"], 1)
        self.assertEqual(named["Button 2"], 0)
        self.assertEqual(named["Button 15"], 1)
        self.assertEqual(named["Accelerator"], 200)
        self.assertEqual(self.by_name["Hat Switch"].describe_value(2), "2 (E)")
        self.assertIn("null", self.by_name["Hat Switch"].describe_value(8))

    def test_short_report_gives_none(self):
        payload = report()[1:5]
        self.assertIsNone(self.by_name["Accelerator"].extract(payload))
        self.assertEqual(self.by_name["X"].extract(payload), 0x80)

    def test_pretty_printers_run(self):
        text = format_items(self.d.items)
        self.assertIn("Usage (Game Pad)", text)
        self.assertIn("Usage Minimum (Button 1)", text)
        self.assertIn("Hat Switch", format_fields(self.d))

    def test_signed_unaligned_and_unnumbered(self):
        # No report ID; 12-bit signed axis starting at bit 4.
        desc = bytes.fromhex("05 01 09 04 a1 01 75 04 95 01 81 03"
                             "09 30 16 00 f8 26 ff 07 75 0c 95 01 81 02 c0")
        d = parse_descriptor(desc)
        self.assertFalse(d.uses_report_ids)
        x = d.input_fields()[0]
        self.assertTrue(x.is_signed)
        self.assertEqual((x.logical_min, x.logical_max), (-2048, 2047))
        raw = ((-5 & 0xFFF) << 4).to_bytes(2, "little")
        self.assertEqual(d.split_report(raw), (0, raw))
        self.assertEqual(x.extract(raw), -5)

    def test_push_pop_extended_usage_and_array(self):
        desc = bytes.fromhex(
            "05 01 09 05 a1 01 85 02"
            "15 00 25 01 75 01 a4"               # push (size=1, max=1)
            "25 07 75 03 95 01"                  # changed globals
            "0b 39 00 01 00 81 02"               # extended usage: page 1 usage 0x39 (hat)
            "b4"                                 # pop: back to size=1, max=1
            "95 05 05 09 19 01 29 05 81 02"      # 5 buttons, 1 bit each
            "05 0c 15 00 26 24 02 75 10 95 01"   # consumer array, 16 bit
            "19 00 2a 24 02 81 00 c0")
        d = parse_descriptor(desc)
        self.assertEqual(d.warnings, [])
        hat, *rest = d.input_fields()
        self.assertTrue(hat.is_hat)
        self.assertEqual(hat.bit_size, 3)
        buttons = [f for f in rest if f.usage_page == 9]
        self.assertEqual([b.bit_size for b in buttons], [1] * 5)
        self.assertEqual(buttons[0].bit_offset, 3)
        arr = rest[-1]
        self.assertTrue(arr.is_array)
        self.assertEqual(arr.describe_value(0x224), "548 (AC Back)")

    def test_tokenizer_errors_and_long_items(self):
        with self.assertRaises(DescriptorError):
            parse_items(bytes([0x26, 0xFF]))       # 2-byte item with 1 byte of data
        items = parse_items(bytes([0xFE, 0x02, 0x10, 0xAA, 0xBB, 0x05, 0x01]))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1].udata, 1)


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.d = parse_descriptor(GAMEPAD)
        self.base = Baseline(self.d.input_fields())
        for jitter in (0x7E, 0x80, 0x82):          # sticks jitter a little at rest
            self.base.add(decode(self.d, report(x=jitter, y=jitter)))
        self.key = {f.name: f.key for f in self.d.input_fields()}

    def test_jitter_is_not_activity(self):
        self.assertEqual(self.base.active(decode(self.d, report(x=0x70, y=0x90))), {})

    def test_detects_button_hat_stick_trigger(self):
        active = self.base.active(decode(self.d, report(buttons=1 << 3)))
        self.assertEqual(list(active), [self.key["Button 4"]])
        active = self.base.active(decode(self.d, report(hat=0)))
        self.assertEqual(list(active), [self.key["Hat Switch"]])
        active = self.base.active(decode(self.d, report(x=0)))
        self.assertEqual(list(active), [self.key["X"]])
        active = self.base.active(decode(self.d, report(brake=255)))
        self.assertEqual(list(active), [self.key["Brake"]])

    def test_press_recorder(self):
        rec = PressRecorder(self.base, release_hold=0.3)
        rest = decode(self.d, report())
        self.assertEqual(rec.feed(rest, 0.0), "waiting")
        self.assertEqual(rec.feed(decode(self.d, report(accel=120)), 0.1), "pressed")
        # Trigger that also sets a digital button at full pull.
        self.assertEqual(rec.feed(decode(self.d, report(accel=255, buttons=1 << 7)), 0.2), "pressed")
        self.assertEqual(rec.feed(rest, 0.3), "pressed")
        self.assertEqual(rec.feed(rest, 0.5), "pressed")     # not quiet long enough yet
        self.assertEqual(rec.feed(rest, 0.61), "released")
        hits = rec.ranked_hits()
        self.assertEqual([h.key for h in hits], [self.key["Accelerator"], self.key["Button 8"]])
        accel = next(h for h in hits if h.key == self.key["Accelerator"])
        self.assertEqual((accel.rest, accel.peak), (0, 255))

    def test_bounce_restarts_release_timer(self):
        rec = PressRecorder(self.base, release_hold=0.3)
        pressed, rest = decode(self.d, report(buttons=1)), decode(self.d, report())
        rec.feed(pressed, 0.0)
        rec.feed(rest, 0.1)
        rec.feed(pressed, 0.2)
        self.assertEqual(rec.feed(rest, 0.45), "pressed")
        self.assertEqual(rec.feed(rest, 0.8), "released")


class SummaryNoteTests(unittest.TestCase):
    @staticmethod
    def hit(key, peak=1):
        return {"fields": [{"key": key, "peak": peak}]}

    def test_firmware_remapped_back_button(self):
        results = {"A": self.hit("I1@40+1"), "M1": self.hit("I1@40+1"), "M2": self.hit("I1@53+1")}
        notes = summary_notes(results, {"I1@40+1": "Button 1", "I1@53+1": "Button 14"})
        self.assertEqual(len(notes), 1)
        self.assertIn("M1 sent exactly what A sends", notes[0])

    def test_silent_back_buttons_and_unused_fields(self):
        results = {"A": self.hit("I1@40+1"), "M3": {"skipped": True}, "M4": {"skipped": True}}
        notes = summary_notes(results, {"I1@40+1": "Button 1", "I1@54+1": "Button 15"})
        self.assertIn("M3, M4 sent nothing", notes[0])
        self.assertIn("never moved: Button 15", notes[1])

    def test_ordinary_duplicates(self):
        notes = summary_notes({"A": self.hit("k"), "B": self.hit("k")}, {"k": "Button 1"})
        self.assertIn("A, B produced the same field", notes[0])


class CliTests(unittest.TestCase):
    def test_descriptor_from_hex_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(", ".join(f"0x{b:02x}" for b in GAMEPAD))
        try:
            self.assertEqual(raikiri_probe.load_descriptor_file(fh.name), GAMEPAD)
            out = io.StringIO()
            with redirect_stdout(out):
                raikiri_probe.main(["--no-color", "descriptor", "--descriptor-file", fh.name])
            self.assertIn("Field layout", out.getvalue())
            self.assertIn("Accelerator", out.getvalue())
        finally:
            os.unlink(fh.name)

    def test_binary_descriptor_file(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".bin", delete=False) as fh:
            fh.write(GAMEPAD)
        try:
            self.assertEqual(raikiri_probe.load_descriptor_file(fh.name), GAMEPAD)
        finally:
            os.unlink(fh.name)


if __name__ == "__main__":
    unittest.main()
