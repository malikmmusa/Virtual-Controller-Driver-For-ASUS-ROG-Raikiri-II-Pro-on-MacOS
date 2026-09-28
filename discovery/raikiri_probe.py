#!/usr/bin/env python3
"""Phase 1 discovery tool for the ASUS ROG Raikiri II Pro (or any HID gamepad).

Subcommands:
  list        Enumerate HID interfaces (default: ASUS devices only).
  descriptor  Dump and decode the HID report descriptor.
  monitor     Print live input reports, highlighting what changed.
  map         Guided mode: prompts for each control and records which field
              it moves. Writes a JSON mapping file.

Examples:
  python3 raikiri_probe.py list
  python3 raikiri_probe.py descriptor --save raikiri_descriptor.bin
  python3 raikiri_probe.py monitor
  python3 raikiri_probe.py map --out raikiri_mapping.json

Requires the `hidapi` package (the Cython binding, version 0.14 or newer):
  pip3 install 'hidapi>=0.14'
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hid_descriptor import Descriptor, DescriptorError, format_fields, format_items, parse_descriptor  # noqa: E402
from hid_usages import page_name, usage_name  # noqa: E402
from mapping import DEFAULT_CONTROLS, Baseline, PressRecorder, decode, summary_notes  # noqa: E402

DEFAULT_VID = 0x0B05   # ASUSTek
DEFAULT_PID = 0x1C66   # "RAIKIRI II PRO PC" (wireless)
READ_SIZE = 512        # bigger than any gamepad report; hidapi returns the actual length
READ_TIMEOUT_MS = 50   # short timeout keeps Ctrl-C responsive and lets timers advance
BUS_TYPES = {0: "unknown", 1: "USB", 2: "Bluetooth", 3: "I2C", 4: "SPI"}


# --------------------------------------------------------------------------- utils

class Style:
    enabled = False

    @classmethod
    def wrap(cls, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if cls.enabled else text

    @classmethod
    def hi(cls, text: str) -> str:      # changed bytes
        return cls.wrap("1;33", text)

    @classmethod
    def dim(cls, text: str) -> str:
        return cls.wrap("2", text)

    @classmethod
    def bold(cls, text: str) -> str:
        return cls.wrap("1", text)


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def import_hid():
    interpreter = f"{sys.executable} (Python {platform.python_version()}, {platform.machine()})"
    try:
        import hid  # type: ignore
    except ImportError as e:
        # Show the real reason: "No module named 'hid'" means this interpreter
        # doesn't have the package; anything else means it failed to load.
        die(f"could not import the 'hid' module: {e}\n"
            f"  Python running this script: {interpreter}\n"
            "  - If that path isn't inside your .venv, run: .venv/bin/python raikiri_probe.py ...\n"
            "  - Otherwise install into exactly this interpreter: python3 -m pip install 'hidapi>=0.14'")
    if not hasattr(hid, "device"):
        # The unrelated ctypes package `hid` also installs a module named `hid`.
        die(f"the 'hid' module at {getattr(hid, '__file__', '?')} is not the hidapi Cython binding.\n"
            f"  Python running this script: {interpreter}\n"
            "  Fix: python3 -m pip uninstall hid && python3 -m pip install 'hidapi>=0.14'")
    return hid


def hexbytes(data: bytes, prev: Optional[bytes] = None) -> str:
    out = []
    for i, b in enumerate(data):
        s = f"{b:02X}"
        if prev is not None and (i >= len(prev) or prev[i] != b):
            s = Style.hi(s)
        out.append(s)
    return " ".join(out)


def hexdump(data: bytes, width: int = 16) -> str:
    return "\n".join(f"{i:04X}  {' '.join(f'{b:02X}' for b in data[i:i + width])}"
                     for i in range(0, len(data), width))


def parse_int(text: str) -> int:
    return int(text, 0)


def load_descriptor_file(path: str) -> bytes:
    """Accept raw binary, or hex text ("05 01 09 05", "0x05, 0x01", ...) with optional # comments."""
    with open(path, "rb") as fh:
        blob = fh.read()
    try:
        text = blob.decode("ascii")
    except UnicodeDecodeError:
        return blob
    text = re.sub(r"#[^\n]*", "", text)      # allow "# comment" lines
    tokens = re.findall(r"(?:0x)?([0-9A-Fa-f]{2})\b", text)
    stripped = re.sub(r"0x|[\s,]", "", text)
    if tokens and re.fullmatch(r"[0-9A-Fa-f]*", stripped):
        return bytes(int(t, 16) for t in tokens)
    return blob


# --------------------------------------------------------------------- device I/O

def enumerate_interfaces(hid, vid: int, pid: int) -> List[dict]:
    """hidapi lists one entry per (interface, top-level usage). Group them by path."""
    by_path: Dict[bytes, dict] = {}
    for d in hid.enumerate(vid, pid):
        entry = by_path.setdefault(d["path"], dict(d, usages=[]))
        pair = (d["usage_page"], d["usage"])
        if pair not in entry["usages"]:
            entry["usages"].append(pair)
    return list(by_path.values())


def is_gamepad(entry: dict) -> bool:
    return any(p == 0x01 and u in (0x04, 0x05, 0x08) for p, u in entry["usages"])


def describe_interface(d: dict) -> str:
    usages = ", ".join(f"{page_name(p)}/{usage_name(p, u)}" for p, u in d["usages"])
    bus = BUS_TYPES.get(d.get("bus_type", 0), str(d.get("bus_type")))
    return (f"{d['vendor_id']:04X}:{d['product_id']:04X}  bus={bus:<9} iface={d['interface_number']:<3} "
            f"{d['manufacturer_string'] or '?'} / {d['product_string'] or '?'}\n"
            f"    usages: {usages}\n"
            f"    path:   {d['path'].decode(errors='replace')}")


def select_interface(hid, args) -> dict:
    entries = enumerate_interfaces(hid, args.vid, args.pid)
    if args.path:
        for e in entries or enumerate_interfaces(hid, 0, 0):
            if e["path"].decode(errors="replace") == args.path:
                return e
        die(f"no HID interface with path {args.path!r} (run `list --all`)")
    if not entries:
        die(f"no HID interface with VID:PID {args.vid:04X}:{args.pid:04X} found.\n"
            "  - Is the controller on and connected in wireless mode?\n"
            "  - Run `python3 raikiri_probe.py list --all` to see everything macOS exposes.")
    pads = [e for e in entries if is_gamepad(e)]
    chosen = (pads or entries)[0]
    if len(entries) > 1:
        print(Style.dim(f"{len(entries)} interfaces match; using the "
                        f"{'gamepad' if pads else 'first'} one. Override with --path."), file=sys.stderr)
    return chosen


def open_device(hid, entry: dict):
    dev = hid.device()
    try:
        dev.open_path(entry["path"])
    except (IOError, OSError) as e:
        hint = ""
        if platform.system() == "Darwin":
            hint = ("\n  macOS hints:\n"
                    "  - System Settings > Privacy & Security > Input Monitoring: allow your terminal app\n"
                    "    (required when the device also exposes keyboard/mouse usages), then restart it.\n"
                    "  - hidapi opens devices in exclusive (seize) mode on macOS. Quit other apps that may\n"
                    "    hold the controller (Steam, a browser tab using the Gamepad API, etc.).")
        die(f"could not open {entry['path'].decode(errors='replace')}: {e}{hint}")
    return dev


def read_descriptor(dev, args) -> Optional[bytes]:
    if args.descriptor_file:
        return load_descriptor_file(args.descriptor_file)
    if dev is None:
        return None
    try:
        return bytes(dev.get_report_descriptor())
    except AttributeError:
        print("warning: this hidapi binding has no get_report_descriptor(); upgrade with "
              "pip3 install -U 'hidapi>=0.14'", file=sys.stderr)
    except (IOError, OSError) as e:
        print(f"warning: could not read the report descriptor: {e}", file=sys.stderr)
    return None


def try_parse(raw: Optional[bytes]) -> Optional[Descriptor]:
    if not raw:
        return None
    try:
        return parse_descriptor(raw)
    except DescriptorError as e:
        print(f"warning: descriptor parse failed ({e}); falling back to raw bytes", file=sys.stderr)
        return None


def read_report(dev) -> Optional[bytes]:
    data = dev.read(READ_SIZE, READ_TIMEOUT_MS)
    return bytes(data) if data else None


# ----------------------------------------------------------------------- commands

def cmd_list(args) -> None:
    hid = import_hid()
    vid = 0 if args.all else args.vid
    entries = enumerate_interfaces(hid, vid, 0)
    if not entries:
        print("No HID interfaces found." if args.all else
              f"No HID interfaces with VID {vid:04X}. Try `list --all`.")
        return
    for e in sorted(entries, key=lambda e: (e["vendor_id"], e["product_id"], e["interface_number"])):
        tag = Style.bold("  <-- gamepad") if is_gamepad(e) else ""
        print(describe_interface(e) + tag)
        print()


def print_descriptor_report(raw: bytes, desc: Optional[Descriptor]) -> None:
    print(Style.bold(f"Report descriptor: {len(raw)} bytes"))
    print(hexdump(raw))
    print()
    if desc is None:
        return
    print(Style.bold("Top-level collections: ") + ("; ".join(desc.application_collections()) or "none"))
    print(Style.bold("Report IDs: ") + (", ".join(f"0x{r:02X}" for r in desc.report_ids)
                                        if desc.uses_report_ids else "none (unnumbered reports)"))
    for w in desc.warnings:
        print(f"warning: {w}")
    print()
    print(Style.bold("Items (offset, bytes, meaning):"))
    print(format_items(desc.items))
    print()
    print(Style.bold("Field layout (what each bit of each report means):"))
    print(format_fields(desc))


def cmd_descriptor(args) -> None:
    dev = None
    if not args.descriptor_file:
        hid = import_hid()
        entry = select_interface(hid, args)
        print(describe_interface(entry))
        print()
        dev = open_device(hid, entry)
    try:
        raw = read_descriptor(dev, args)
    finally:
        if dev is not None:
            dev.close()
    if not raw:
        die("no descriptor available")
    if args.save:
        with open(args.save, "wb") as fh:
            fh.write(raw)
        print(f"saved {len(raw)} bytes to {args.save}\n")
    print_descriptor_report(raw, try_parse(raw))


def format_changes(desc: Descriptor, rid: int, cur: Dict[str, int], prev: Dict[str, int],
                   min_delta: int) -> str:
    parts = []
    for f in desc.input_fields(rid):
        a, b = prev.get(f.key), cur.get(f.key)
        if a == b or b is None:
            continue
        if a is not None and f.bit_size > 1 and not f.is_hat and abs(b - a) <= min_delta:
            continue
        before = "?" if a is None else f.describe_value(a)
        parts.append(f"{f.name} {before}->{f.describe_value(b)}")
    return ", ".join(parts)


def print_stats(counts: Dict[int, int], intervals: List[float], elapsed: float) -> None:
    total = sum(counts.values())
    print()
    print(Style.bold("Report statistics"))
    print(f"  {total} reports in {elapsed:.1f} s = {total / elapsed if elapsed else 0:.1f} reports/s")
    for rid, n in sorted(counts.items()):
        print(f"  report ID 0x{rid:02X}: {n}")
    if len(intervals) >= 2:
        ms = sorted(i * 1000 for i in intervals)
        p95 = ms[int(0.95 * (len(ms) - 1))]
        print(f"  interval ms: min {ms[0]:.2f}  median {statistics.median(ms):.2f}  "
              f"p95 {p95:.2f}  max {ms[-1]:.2f}")
    print("  (Tip: leave the controller untouched for a few seconds while monitoring. If reports keep\n"
          "   arriving at a steady rate, it streams continuously; if they stop, it reports on change.)")


def cmd_monitor(args) -> None:
    hid = import_hid()
    entry = select_interface(hid, args)
    print(describe_interface(entry))
    dev = open_device(hid, entry)
    desc = None if args.raw else try_parse(read_descriptor(dev, args))
    if desc is None and not args.raw:
        print("(no descriptor: showing raw bytes only)")
    print(Style.dim("Printing reports that differ from the previous report with the same ID. "
                    "Changed bytes are highlighted. Ctrl-C to stop.\n"))
    last_raw: Dict[int, bytes] = {}
    last_vals: Dict[int, Dict[str, int]] = {}
    counts: Dict[int, int] = {}
    intervals: List[float] = []
    start = prev_t = prev_print = time.monotonic()
    first = True
    try:
        while True:
            report = read_report(dev)
            if report is None:
                continue
            now = time.monotonic()
            if not first:
                intervals.append(now - prev_t)
            first = False
            prev_t = now
            rid = desc.split_report(report)[0] if desc else (report[0] if report else 0)
            counts[rid] = counts.get(rid, 0) + 1
            prev = last_raw.get(rid)
            if prev == report and not args.all:
                continue
            decoded = ""
            if desc:
                vals = decode(desc, report)
                decoded = ("(first report with this ID)" if rid not in last_vals else
                           format_changes(desc, rid, vals, last_vals[rid], args.min_delta))
                last_vals[rid] = vals
                if not decoded and prev is not None and not args.all:
                    last_raw[rid] = report
                    continue      # only sub-threshold analog noise changed
            last_raw[rid] = report
            line = (f"{now - start:9.3f}s {Style.dim(f'+{(now - prev_print) * 1000:7.1f}ms')}  "
                    f"len={len(report):<3} {hexbytes(report, prev)}")
            prev_print = now
            print(line + (f"\n{'':22}{decoded}" if decoded else ""), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()
    print_stats(counts, intervals, time.monotonic() - start)


# --------------------------------------------------------------------------- map

class InputState:
    """Latest decoded value of every field, merged across report IDs."""

    def __init__(self, dev, desc: Descriptor):
        self.dev, self.desc = dev, desc
        self.values: Dict[str, int] = {}
        self.last_raw: Dict[int, bytes] = {}

    def poll(self) -> bool:
        report = read_report(self.dev)
        if report is None:
            return False
        rid = self.desc.split_report(report)[0]
        self.last_raw[rid] = report
        self.values.update(decode(self.desc, report))
        return True


def learn_baseline(state: InputState, fields, seconds: float) -> Baseline:
    base = Baseline(fields)
    print(f"Hands off the controller. Learning the resting state for {seconds:.0f} s...", flush=True)
    end = time.monotonic() + seconds
    got_any = False
    while time.monotonic() < end:
        if state.poll():
            got_any = True
            base.add(state.values)
    if got_any:
        return base
    # Some pads only send a report when something changes. Get one by having
    # the user tap a button, then use the state after the release.
    print("No reports while idle (the controller reports on change only).\n"
          "Tap any face button once and let go...", flush=True)
    while not state.poll():
        pass
    quiet_until = time.monotonic() + 1.0
    while time.monotonic() < quiet_until:
        if state.poll():
            quiet_until = time.monotonic() + 1.0
    base.add(state.values)
    return base


def capture_control(state: InputState, base: Baseline, prompt: str, wait_s: float, hold_max_s: float):
    rec = PressRecorder(base)
    print(f"\n{Style.bold('>>')} Press and hold: {Style.bold(prompt)}  "
          f"{Style.dim(f'(release to confirm; {wait_s:.0f}s to skip)')}", flush=True)
    t0 = time.monotonic()
    while True:
        state.poll()
        now = time.monotonic()
        s = rec.feed(state.values, now)
        if s == "waiting" and now - t0 > wait_s:
            print("   skipped")
            return None
        if s == "pressed" and rec.pressed_at is not None and now - rec.pressed_at > hold_max_s:
            print("   (held too long; recording what we saw)")
            break
        if s == "released":
            break
    return rec.ranked_hits()


def cmd_map(args) -> None:
    hid = import_hid()
    entry = select_interface(hid, args)
    print(describe_interface(entry))
    dev = open_device(hid, entry)
    raw = read_descriptor(dev, args)
    desc = try_parse(raw)
    if desc is None:
        dev.close()
        die("map mode needs the report descriptor. Upgrade hidapi (>=0.14) or pass --descriptor-file.")
    fields = {f.key: f for f in desc.input_fields()}
    controls = DEFAULT_CONTROLS
    if args.controls:
        wanted = [c.strip() for c in args.controls.split(",") if c.strip()]
        known = dict(DEFAULT_CONTROLS)
        controls = [(c, known.get(c, c)) for c in wanted]

    state = InputState(dev, desc)
    results: Dict[str, dict] = {}
    try:
        base = learn_baseline(state, fields.values(), args.baseline)
        print(f"Resting state learned for {len(base.lo)} fields.")
        for cid, prompt in controls:
            hits = capture_control(state, base, prompt, args.timeout, args.hold_max)
            if hits is None:
                results[cid] = {"skipped": True}
                continue
            if not hits:
                print("   nothing moved?")
                results[cid] = {"skipped": True}
                continue
            out = []
            for i, h in enumerate(hits):
                f = fields[h.key]
                label = "primary " if i == 0 else "also    "
                print(f"   {label}{f.name:<16} key={h.key:<12} rest={f.describe_value(h.rest):<14} "
                      f"-> {f.describe_value(h.peak)}")
                out.append({"key": h.key, "name": f.name, "usage_page": f.usage_page, "usage": f.usage,
                            "report_id": f.report_id, "bit_offset": f.bit_offset, "bit_size": f.bit_size,
                            "logical_min": f.logical_min, "logical_max": f.logical_max,
                            "rest": h.rest, "peak": h.peak, "deviation": round(h.deviation, 3)})
            results[cid] = {"fields": out}
    except KeyboardInterrupt:
        print("\ninterrupted; saving what we have")
    finally:
        dev.close()

    doc = {
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "device": {
            "vendor_id": f"0x{entry['vendor_id']:04X}", "product_id": f"0x{entry['product_id']:04X}",
            "product": entry["product_string"], "manufacturer": entry["manufacturer_string"],
            "bus": BUS_TYPES.get(entry.get("bus_type", 0), "unknown"),
            "usages": [[f"0x{p:04X}", f"0x{u:04X}"] for p, u in entry["usages"]],
        },
        "descriptor_hex": raw.hex() if raw else None,
        "uses_report_ids": desc.uses_report_ids,
        "sample_reports": {f"0x{rid:02X}": r.hex() for rid, r in state.last_raw.items()},
        "controls": results,
    }
    with open(args.out, "w") as fh:
        json.dump(doc, fh, indent=2)
    print_summary(results, fields)
    print(f"\nSaved mapping to {args.out}")


def print_summary(results: Dict[str, dict], fields) -> None:
    print("\n" + Style.bold("Mapping summary (paste into docs/raikiri-mapping.md)") + "\n")
    print("| Control | Field | Report/bit | Rest | Pressed | Also changes |")
    print("|---|---|---|---|---|---|")
    for cid, r in results.items():
        if r.get("skipped"):
            print(f"| {cid} | *(skipped)* | | | | |")
            continue
        p = r["fields"][0]
        f = fields[p["key"]]
        also = "; ".join(f"{x['name']}={x['peak']}" for x in r["fields"][1:])
        print(f"| {cid} | {p['name']} | {p['key']} | {f.describe_value(p['rest'])} | "
              f"{f.describe_value(p['peak'])} | {also} |")
    for note in summary_notes(results, {k: f.name for k, f in fields.items()}):
        print(f"\nnote: {note}")


# ------------------------------------------------------------------------ main

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    sub = p.add_subparsers(dest="cmd", required=True)

    def device_opts(sp):
        sp.add_argument("--vid", type=parse_int, default=DEFAULT_VID, help="vendor ID (default 0x0B05)")
        sp.add_argument("--pid", type=parse_int, default=DEFAULT_PID, help="product ID (default 0x1C66)")
        sp.add_argument("--path", help="exact hidapi path of the interface to open (see `list`)")
        sp.add_argument("--descriptor-file", help="use this descriptor (binary or hex text) instead of "
                                                  "reading it from the device")

    sp = sub.add_parser("list", help="enumerate HID interfaces")
    sp.add_argument("--vid", type=parse_int, default=DEFAULT_VID)
    sp.add_argument("--all", action="store_true", help="show every HID interface, not just this vendor")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("descriptor", help="dump and decode the report descriptor")
    device_opts(sp)
    sp.add_argument("--save", help="write the raw descriptor bytes to this file")
    sp.set_defaults(func=cmd_descriptor)

    sp = sub.add_parser("monitor", help="print live input reports")
    device_opts(sp)
    sp.add_argument("--all", action="store_true", help="print every report, even unchanged repeats")
    sp.add_argument("--raw", action="store_true", help="don't decode fields, raw bytes only")
    sp.add_argument("--min-delta", type=int, default=0,
                    help="hide analog changes of this size or smaller (e.g. 3 to hide stick jitter)")
    sp.set_defaults(func=cmd_monitor)

    sp = sub.add_parser("map", help="guided per-control mapping, saved as JSON")
    device_opts(sp)
    sp.add_argument("--out", default="raikiri_mapping.json")
    sp.add_argument("--controls", help="comma-separated subset of controls, e.g. A,B,LT")
    sp.add_argument("--timeout", type=float, default=8.0, help="seconds to wait before skipping a control")
    sp.add_argument("--hold-max", type=float, default=10.0, help="max seconds to record one press")
    sp.add_argument("--baseline", type=float, default=2.0, help="seconds to learn the resting state")
    sp.set_defaults(func=cmd_map)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    Style.enabled = sys.stdout.isatty() and not args.no_color and "NO_COLOR" not in os.environ
    args.func(args)


if __name__ == "__main__":
    main()
