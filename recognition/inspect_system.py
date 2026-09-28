#!/usr/bin/env python3
"""Phase 2: read-only inspection of how macOS and GeForce NOW see controllers.

Collects, into one report file:
  1. every game-controller-like HID device in the IORegistry, with all of its
     properties (Transport, VendorID, ProductID, SerialNumber, ...) and the
     driver objects attached below it
  2. the Bluetooth details of the Raikiri (Classic vs Low Energy, minor type)
  3. system plists that mention Microsoft's vendor ID (1118 = 0x045E), which is
     where an allowlist of known controllers would live if it's data, not code
  4. GeForce NOW: which controller APIs its binaries reference, and the
     controller-related lines of its log file
  5. recent log messages from gamecontrollerd, Apple's controller daemon

Nothing here changes system state. It only runs ioreg, system_profiler, log
show and otool, and reads files.

Usage:
  python3 inspect_system.py                   # writes phase2_report.txt
  python3 inspect_system.py --out other.txt
"""

from __future__ import annotations

import argparse
import glob
import os
import plistlib
import re
import subprocess
import sys
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

MICROSOFT_VID = 0x045E     # 1118
ASUS_VID = 0x0B05          # 2821
RAIKIRI_PID = 0x1C66       # 7270

# IORegistry keys whose values are large or uninteresting blobs.
SKIP_KEYS = {"ReportDescriptor", "IORegistryEntryChildren", "HIDDescriptor", "ReportInterval_DEPRECATED",
             "IOCFPlugInTypes", "Elements", "InputReportElements"}
SERIAL_KEYS = {"SerialNumber", "kUSBSerialNumberString", "USB Serial Number", "DeviceAddress", "BD_ADDR"}


# ------------------------------------------------------------------ helpers

def run(cmd: List[str], timeout: int = 120) -> Tuple[int, str]:
    """Run a command and return (exit code, stdout+stderr). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return 127, f"(command not found: {cmd[0]})"
    except subprocess.TimeoutExpired:
        return 124, f"(timed out after {timeout}s: {' '.join(cmd)})"
    out = p.stdout.decode("utf-8", "replace")
    if p.returncode and p.stderr:
        out += p.stderr.decode("utf-8", "replace")
    return p.returncode, out


def mask(value: str) -> str:
    """Hide most of an identifier (serials are often Bluetooth addresses),
    keeping its shape and the last group so two devices can be told apart."""
    s = str(value)
    if len(s) <= 4:
        return s
    return re.sub(r"[0-9A-Za-z]", "x", s[:-2]) + s[-2:]


def fmt_value(key: str, v) -> str:
    if key in SERIAL_KEYS and isinstance(v, str):
        return f'"{mask(v)}" (masked)'
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return f"{v} (0x{v:X})" if v > 9 else str(v)
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}={fmt_value(k, x)}" for k, x in sorted(v.items())) + "}"
    if isinstance(v, list):
        if len(v) > 12:
            return f"[{len(v)} items]"
        return "[" + ", ".join(fmt_value(key, x) for x in v) + "]"
    return f'"{v}"' if isinstance(v, str) else repr(v)


def section(title: str) -> str:
    return f"\n{'=' * 78}\n{title}\n{'=' * 78}\n"


# --------------------------------------------------------- 1. IORegistry

def walk(entries: Iterable[dict], depth: int = 0) -> Iterator[Tuple[dict, int]]:
    for e in entries:
        yield e, depth
        yield from walk(e.get("IORegistryEntryChildren", []), depth + 1)


def is_controller_like(props: dict) -> bool:
    vid = props.get("VendorID")
    if vid in (ASUS_VID, MICROSOFT_VID):
        return True
    pairs = props.get("DeviceUsagePairs") or []
    usages = {(p.get("DeviceUsagePage"), p.get("DeviceUsage")) for p in pairs if isinstance(p, dict)}
    usages.add((props.get("PrimaryUsagePage"), props.get("PrimaryUsage")))
    return bool(usages & {(1, 4), (1, 5), (1, 8)})


def describe_hid_devices(ioreg_plist: bytes) -> str:
    """Pretty-print controller-like IOHIDDevice entries from `ioreg -a` output."""
    try:
        roots = plistlib.loads(ioreg_plist)
    except Exception as e:  # malformed or empty output
        return f"(could not parse ioreg output: {e})\n"
    if isinstance(roots, dict):
        roots = [roots]
    out = []
    seen = 0
    for root in roots:
        if not isinstance(root, dict) or not is_controller_like(root):
            continue
        seen += 1
        name = root.get("Product") or root.get("IORegistryEntryName", "?")
        out.append(f"--- {name}  [{root.get('IOObjectClass', '?')}]")
        for k in sorted(root):
            if k in SKIP_KEYS:
                continue
            out.append(f"    {k} = {fmt_value(k, root[k])}")
        rd = root.get("ReportDescriptor")
        if isinstance(rd, bytes):
            out.append(f"    ReportDescriptor = <{len(rd)} bytes> {rd[:16].hex(' ')} ...")
        kids = list(walk(root.get("IORegistryEntryChildren", []), 1))
        if kids:
            out.append("    Objects attached below it (driver stack):")
            for child, depth in kids:
                extra = ""
                for key in ("IOUserClass", "CFBundleIdentifier", "IOClass"):
                    if key in child:
                        extra += f" {key}={child[key]}"
                out.append(f"    {'  ' * depth}{child.get('IORegistryEntryName', '?')} "
                           f"[{child.get('IOObjectClass', '?')}]{extra}")
        out.append("")
    if not seen:
        out.append("(no controller-like HID devices found; is the controller connected?)")
    return "\n".join(out) + "\n"


# ------------------------------------------------------ 2. Bluetooth

def bluetooth_block(profile_text: str, needle: str = "RAIKIRI") -> str:
    """Extract the indented block for one device from system_profiler output."""
    lines = profile_text.splitlines()
    for i, line in enumerate(lines):
        if needle.lower() in line.lower() and line.rstrip().endswith(":"):
            indent = len(line) - len(line.lstrip())
            block = [line]
            for nxt in lines[i + 1:]:
                if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                    break
                block.append(nxt)
            text = "\n".join(block)
            return re.sub(r"(Address:\s*)(\S+)", lambda m: m.group(1) + mask(m.group(2)) + " (masked)", text)
    return f"(no Bluetooth device named like '{needle}' found)"


# ------------------------------------------ 3. plists naming Microsoft VID

def find_vendor_entries(obj, vid: int, path: str = "") -> Iterator[Tuple[str, dict]]:
    """Yield (path, dict) for every dict whose vendor-ish key equals `vid`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if re.search(r"vendor", str(k), re.I) and _as_int(v) == vid:
                yield path or "/", obj
                break
        for k, v in obj.items():
            yield from find_vendor_entries(v, vid, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from find_vendor_entries(v, vid, f"{path}[{i}]")


def _as_int(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v, 0)
        except ValueError:
            return None
    return None


def scan_plists(roots: List[str], vid: int, max_files: int = 20000) -> str:
    out = []
    count = 0
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if not fn.endswith(".plist"):
                    continue
                count += 1
                if count > max_files:
                    out.append(f"(stopped after {max_files} plists)")
                    return "\n".join(out) + "\n"
                path = os.path.join(dirpath, fn)
                try:
                    with open(path, "rb") as fh:
                        data = plistlib.load(fh)
                except Exception:
                    continue
                for where, d in find_vendor_entries(data, vid):
                    summary = {k: v for k, v in d.items() if not isinstance(v, (dict, list, bytes))}
                    out.append(f"{path}  {where}\n    {fmt_value('', summary)}")
    return ("\n".join(out) if out else f"(no plist entries with vendor {vid} under {', '.join(roots)})") + "\n"


# --------------------------------------------------------- 4. GeForce NOW

STRING_PATTERNS = [
    # Case-sensitive, and not SDL's own SDL_GameController* API.
    # C symbols carry a leading underscore (_GCDeviceInit), so only letters
    # may not precede "GC".
    ("Apple GameController framework", r"(?-i:(?<![_A-Za-z])GameController|(?<![A-Za-z])GC[A-Z][a-z][A-Za-z]+)"),
    ("IOKit HID (raw HID access)", r"IOHIDManager|IOHIDDevice"),
    ("SDL", r"\bSDL_[A-Za-z]+"),
    ("Xbox / Microsoft IDs", r"xbox|xinput|045e"),
    ("ASUS / Raikiri", r"raikiri|\b0b05\b|\b1c66\b"),
    ("Controller allow/deny words", r"(?:un)?supported controller|allowlist|whitelist|blacklist|blocklist"),
]


def printable_strings(data: bytes, min_len: int = 6) -> Iterator[str]:
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % min_len, data):
        yield m.group().decode("ascii")


def string_hits(data: bytes, per_pattern: int = 15) -> str:
    compiled = [(label, re.compile(rx, re.I)) for label, rx in STRING_PATTERNS]
    hits: Dict[str, List[str]] = {label: [] for label, _ in compiled}
    counts = {label: 0 for label, _ in compiled}
    for s in printable_strings(data):
        for label, rx in compiled:
            if rx.search(s):
                counts[label] += 1
                if len(hits[label]) < per_pattern and s not in hits[label]:
                    hits[label].append(s[:160])
    out = []
    for label, _ in compiled:
        out.append(f"  {label}: {counts[label]} strings")
        out.extend(f"      {s}" for s in hits[label])
    return "\n".join(out)


def find_gfn_app() -> Optional[str]:
    candidates = []
    for base in ("/Applications", os.path.expanduser("~/Applications")):
        candidates += glob.glob(os.path.join(base, "*GeForce*NOW*.app"))
    return sorted(candidates)[0] if candidates else None


def gfn_binaries(app: str) -> List[str]:
    """The main executable plus bundled libraries that plausibly handle input."""
    out = sorted(glob.glob(os.path.join(app, "Contents", "MacOS", "*")))
    for path in glob.glob(os.path.join(app, "Contents", "Frameworks", "**", "*"), recursive=True):
        base = os.path.basename(path).lower()
        if os.path.isfile(path) and not os.path.islink(path) and (
                base.endswith(".dylib") or re.search(r"geronimo|sdl|hid|input|controller|gamepad", base)):
            out.append(path)
    return [p for p in out if os.path.isfile(p)]


LOG_PATTERN = re.compile(
    r"controller|gamepad|joystick|\bhid\b|gcdevice|gamecontroller|xinput|raikiri|0x?0b05|0x?1c66|"
    r"\bvid\b|\bpid\b|vendor ?id|product ?id", re.I)


def grep_tail(text: str, pattern: re.Pattern, limit: int) -> List[str]:
    return [line[:300] for line in text.splitlines() if pattern.search(line)][-limit:]


def inspect_gfn() -> str:
    app = find_gfn_app()
    if not app:
        return "(GeForce NOW app not found in /Applications or ~/Applications)\n"
    out = [f"App: {app}"]
    _, ver = run(["defaults", "read", os.path.join(app, "Contents", "Info"), "CFBundleShortVersionString"])
    out.append(f"Version: {ver.strip()}")
    frameworks = sorted(os.path.basename(p) for p in glob.glob(os.path.join(app, "Contents", "Frameworks", "*")))
    out.append(f"Bundled frameworks/libraries ({len(frameworks)}): {', '.join(frameworks)}")
    for binary in gfn_binaries(app):
        size = os.path.getsize(binary)
        out.append(f"\n-- {os.path.relpath(binary, app)} ({size / 1e6:.1f} MB)")
        code, linked = run(["otool", "-L", binary])
        if code == 0:
            libs = [ln.strip().split(" (")[0] for ln in linked.splitlines()[1:]]
            interesting = [lib for lib in libs if re.search(r"GameController|IOKit|SDL|CoreHID|Geronimo", lib, re.I)]
            out.append("  links: " + (", ".join(interesting) or "(none of GameController/IOKit/SDL/CoreHID)"))
        if size > 400e6:
            out.append("  (too large to scan for strings)")
            continue
        with open(binary, "rb") as fh:
            out.append(string_hits(fh.read()))
    return "\n".join(out) + "\n"


def gfn_log_lines(limit: int = 200) -> str:
    base = os.path.expanduser("~/Library/Application Support/NVIDIA/GeForceNOW")
    logs = sorted(glob.glob(os.path.join(base, "*.log")), key=os.path.getmtime)
    if not logs:
        return f"(no *.log files in {base})\n"
    out = []
    for path in logs[-3:]:
        try:
            with open(path, "r", errors="replace") as fh:
                text = fh.read()
        except OSError as e:
            out.append(f"{path}: {e}")
            continue
        lines = grep_tail(text, LOG_PATTERN, limit)
        out.append(f"-- {path}: {len(lines)} matching lines (last {limit} shown)")
        out.extend(lines)
    return "\n".join(out) + "\n"


# ------------------------------------------------------ 5. gamecontrollerd

GCD_PATTERN = re.compile(r"raikiri|0x?0b05|0x?1c66|\b2821\b|\b7270\b|asus|ignor|unsupport|virtual|reject|"
                         r"filter|match|not supported|allow|added|removed|connect", re.I)


def gamecontrollerd_log(minutes: int) -> str:
    code, text = run(["log", "show", "--last", f"{minutes}m", "--style", "compact", "--info", "--predicate",
                      'process == "gamecontrollerd" OR subsystem CONTAINS[c] "gamecontroller"'], timeout=300)
    if code != 0 and not text.strip():
        return "(log show failed)\n"
    lines = text.splitlines()
    hits = grep_tail(text, GCD_PATTERN, 150)
    return (f"{len(lines)} lines from gamecontrollerd in the last {minutes} min; "
            f"{len(hits)} matching lines shown:\n" + "\n".join(hits) + "\n")


# ------------------------------------------------------------------ main

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="phase2_report.txt")
    ap.add_argument("--log-minutes", type=int, default=15,
                    help="how far back to read gamecontrollerd's log (default 15)")
    ap.add_argument("--skip-plist-scan", action="store_true", help="skip the (slow) system plist scan")
    args = ap.parse_args(argv)
    if sys.platform != "darwin":
        sys.exit("This script inspects macOS; run it on the Mac.")

    parts = [section("System")]
    for cmd in (["sw_vers"], ["uname", "-m"]):
        parts.append(run(cmd)[1].rstrip("\n") + "\n")

    print("1/5 reading the IORegistry...", file=sys.stderr)
    parts.append(section("1. Controller-like HID devices (ioreg)"))
    raw = subprocess.run(["ioreg", "-a", "-r", "-c", "IOHIDDevice", "-l"], capture_output=True).stdout
    parts.append(describe_hid_devices(raw))

    print("2/5 reading Bluetooth details...", file=sys.stderr)
    parts.append(section("2. Bluetooth details (system_profiler)"))
    parts.append(bluetooth_block(run(["system_profiler", "SPBluetoothDataType"])[1]) + "\n")

    parts.append(section("3. System plists that mention Microsoft's vendor ID (0x045E)"))
    if args.skip_plist_scan:
        parts.append("(skipped)\n")
    else:
        print("3/5 scanning system plists (a minute or two)...", file=sys.stderr)
        roots = [r for r in ("/System/Library/Frameworks/GameController.framework",
                             "/System/Library/PrivateFrameworks", "/System/Library/Extensions",
                             "/System/Library/DriverExtensions", "/System/Library/GameControllerSupport",
                             "/Library/Apple/System/Library")
                 if os.path.isdir(r)]
        parts.append(scan_plists(roots, MICROSOFT_VID))

    print("4/5 inspecting GeForce NOW...", file=sys.stderr)
    parts.append(section("4a. GeForce NOW: binaries"))
    parts.append(inspect_gfn())
    parts.append(section("4b. GeForce NOW: controller-related log lines"))
    parts.append(gfn_log_lines())

    print("5/5 reading gamecontrollerd's log...", file=sys.stderr)
    parts.append(section(f"5. gamecontrollerd log (last {args.log_minutes} min)"))
    parts.append(gamecontrollerd_log(args.log_minutes))

    report = "".join(parts)
    with open(args.out, "w") as fh:
        fh.write(report)
    print(f"\nWrote {args.out} ({len(report.splitlines())} lines). Skim it before sharing: serials and "
          "Bluetooth addresses are masked, but log lines are copied as-is.", file=sys.stderr)


if __name__ == "__main__":
    main()
