# Virtual Xbox controller driver for the ASUS ROG Raikiri II Pro on macOS

In wireless mode, the Raikiri II Pro (VID `0x0B05`, PID `0x1C66`) shows up on
macOS as a generic HID gamepad. Apps built on Apple's GameController
framework, such as the native GeForce NOW app, ignore it. This project
translates its input into a virtual controller that macOS treats as an Xbox
Wireless Controller.

Target: Apple Silicon, recent macOS. Wired mode (XInput/GIP) is out of scope
for now.

## Plan

| Phase | What | Status |
|---|---|---|
| 1 | **Discovery:** dump the HID report descriptor and live reports; build a control → field mapping table | Done. Over Bluetooth the Raikiri already sends Xbox Series-format reports under ASUS's VID/PID: [docs/raikiri-mapping.md](docs/raikiri-mapping.md) |
| 2 | **Verify the hypothesis:** what makes GameController recognize a device as an Xbox controller (VID/PID, descriptor, transport) | Research done; experiments ready: [docs/phase2-recognition.md](docs/phase2-recognition.md) |
| 3 | **Userspace daemon:** read the Raikiri via IOHIDManager and translate reports to Xbox format with minimal latency | Not started |
| 4 | **Virtual device:** a DriverKit virtual HID device presenting the translated reports as an Xbox controller (signing, entitlements, and the dev-mode path explained before touching any security settings) | Not started |

## Layout

```
discovery/
  raikiri_probe.py     CLI: list | descriptor | monitor | map
  hid_descriptor.py    dependency-free HID report descriptor parser
  hid_usages.py        usage page/usage name tables
  mapping.py           guided-mapping logic (pure, unit-tested)
  tests/               python3 -m unittest discover -s discovery/tests
recognition/
  gc_probe.swift       lists what Apple's GameController framework accepts
  inspect_system.py    read-only report: IORegistry, Bluetooth, allowlist, GeForce NOW
  tests/               python3 -m unittest discover -s recognition/tests
docs/
  phase1-discovery.md  HID background, setup, and step-by-step instructions
  raikiri-mapping.md   the mapping table and Phase 1 findings
  phase2-recognition.md  research and experiments on controller recognition
  captures/            real descriptor and mapping captures (test fixtures)
```

## Quick start (Phase 1)

```bash
cd discovery
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 raikiri_probe.py list
python3 raikiri_probe.py descriptor --save raikiri_descriptor.bin
python3 raikiri_probe.py monitor
python3 raikiri_probe.py map
```
