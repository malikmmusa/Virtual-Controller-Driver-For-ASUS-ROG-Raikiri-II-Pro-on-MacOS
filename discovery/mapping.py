"""Pure logic for the guided "press each control" mapping mode.

Nothing here touches hardware. The CLI feeds decoded report values in, with
timestamps, and these classes decide whether a control is currently pressed
and which fields it moved. Keeping it pure makes it unit-testable on any OS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from hid_descriptor import Descriptor, Field

# Analog fields must leave their resting range by this fraction of their full
# logical range before we call them "moved". Big enough to ignore stick drift,
# small enough that a full stick deflection or trigger pull clears it easily.
ANALOG_THRESHOLD = 0.15


def decode(desc: Descriptor, report: bytes) -> Dict[str, int]:
    """Decode one raw report into {field.key: value} for its non-padding inputs."""
    rid, payload = desc.split_report(report)
    out: Dict[str, int] = {}
    for f in desc.input_fields(rid):
        v = f.extract(payload)
        if v is not None:
            out[f.key] = v
    return out


def is_analog(f: Field) -> bool:
    return f.bit_size > 1 and not f.is_hat and (f.logical_max - f.logical_min) >= 16


class Baseline:
    """Resting state of every input field, learned while nothing is pressed."""

    def __init__(self, fields: Iterable[Field]):
        self.fields: Dict[str, Field] = {f.key: f for f in fields}
        self.lo: Dict[str, int] = {}
        self.hi: Dict[str, int] = {}

    def add(self, values: Dict[str, int]) -> None:
        for k, v in values.items():
            if k in self.fields:
                self.lo[k] = min(self.lo.get(k, v), v)
                self.hi[k] = max(self.hi.get(k, v), v)

    @property
    def empty(self) -> bool:
        return not self.lo

    def rest_value(self, key: str) -> Optional[int]:
        if key not in self.lo:
            return None
        return (self.lo[key] + self.hi[key]) // 2

    def noise(self, key: str) -> int:
        return self.hi.get(key, 0) - self.lo.get(key, 0)

    def deviation(self, key: str, value: int) -> float:
        """How far `value` is outside the resting band, as a fraction of range.

        0.0 means "at rest". Digital fields (buttons, hat) have no tolerance:
        any change from their resting value counts as fully deviated.
        """
        f = self.fields.get(key)
        if f is None or key not in self.lo:
            return 0.0
        lo, hi = self.lo[key], self.hi[key]
        if not is_analog(f):
            return 0.0 if lo <= value <= hi else 1.0
        span = max(1, f.logical_max - f.logical_min)
        tol = math.ceil(ANALOG_THRESHOLD * span)
        if value < lo - tol:
            return (lo - value) / span
        if value > hi + tol:
            return (value - hi) / span
        return 0.0

    def active(self, values: Dict[str, int]) -> Dict[str, float]:
        return {k: d for k, v in values.items() if (d := self.deviation(k, v)) > 0}


@dataclass
class FieldHit:
    key: str
    rest: int
    peak: int
    deviation: float


@dataclass
class PressRecorder:
    """State machine for one prompted control: wait -> pressed -> released.

    feed() takes the current full input state (merged across report IDs) plus a
    timestamp and returns "waiting", "pressed" or "released". A press ends once
    every field has been back at rest for `release_hold` seconds, which stops a
    bouncy release from ending the capture too early.
    """

    baseline: Baseline
    release_hold: float = 0.3
    state: str = "waiting"
    hits: Dict[str, FieldHit] = field(default_factory=dict)
    pressed_at: Optional[float] = None
    quiet_since: Optional[float] = None

    def feed(self, values: Dict[str, int], t: float) -> str:
        if self.state == "released":
            return self.state
        active = self.baseline.active(values)
        if active:
            if self.state == "waiting":
                self.state = "pressed"
                self.pressed_at = t
            self.quiet_since = None
            for k, d in active.items():
                prev = self.hits.get(k)
                if prev is None or d > prev.deviation:
                    rest = self.baseline.rest_value(k)
                    self.hits[k] = FieldHit(k, rest if rest is not None else 0, values[k], d)
        elif self.state == "pressed":
            if self.quiet_since is None:
                self.quiet_since = t
            elif t - self.quiet_since >= self.release_hold:
                self.state = "released"
        return self.state

    def ranked_hits(self) -> List[FieldHit]:
        """Fields the control moved; hits[0] is the primary.

        Analog fields rank first: some triggers also set a digital button at
        full pull, and the analog axis is the one we want to translate.
        """
        fields = self.baseline.fields
        return sorted(self.hits.values(), key=lambda h: (is_analog(fields[h.key]), h.deviation), reverse=True)


# Controls to prompt for, as (id, prompt). Named after the Xbox layout because
# that is what we'll translate *to* in phase 3; the Raikiri uses the same
# physical layout (A = bottom face button).
DEFAULT_CONTROLS: List[Tuple[str, str]] = [
    ("A", "A (bottom face button)"),
    ("B", "B (right face button)"),
    ("X", "X (left face button)"),
    ("Y", "Y (top face button)"),
    ("LB", "LB (left bumper)"),
    ("RB", "RB (right bumper)"),
    ("LT", "LT (left trigger) - pull it ALL the way"),
    ("RT", "RT (right trigger) - pull it ALL the way"),
    ("View", "View / Back / Select (left of the center)"),
    ("Menu", "Menu / Start (right of the center)"),
    ("Guide", "Guide: the round logo button in the CENTER of the controller (short press only)"),
    ("L3", "L3 (click the left stick)"),
    ("R3", "R3 (click the right stick)"),
    ("DpadUp", "D-pad UP"),
    ("DpadRight", "D-pad RIGHT"),
    ("DpadDown", "D-pad DOWN"),
    ("DpadLeft", "D-pad LEFT"),
    ("LSLeft", "Left stick fully LEFT"),
    ("LSRight", "Left stick fully RIGHT"),
    ("LSUp", "Left stick fully UP"),
    ("LSDown", "Left stick fully DOWN"),
    ("RSLeft", "Right stick fully LEFT"),
    ("RSRight", "Right stick fully RIGHT"),
    ("RSUp", "Right stick fully UP"),
    ("RSDown", "Right stick fully DOWN"),
    # Programmable back buttons. The firmware may send them as their own
    # buttons, as a copy of whatever button they're assigned to, or not at all.
    ("M1", "M1 back button (wait to skip if absent)"),
    ("M2", "M2 back button (wait to skip if absent)"),
    ("M3", "M3 back button (wait to skip if absent)"),
    ("M4", "M4 back button (wait to skip if absent)"),
    ("M5", "M5 back button (wait to skip if absent)"),
    ("M6", "M6 back button (wait to skip if absent)"),
    ("Extra1", "Any other button (e.g. mode/menu/mute), or wait to skip"),
    ("Extra2", "Any other button, or wait to skip"),
]


def is_programmable(control_id: str) -> bool:
    return control_id.startswith("M") and control_id[1:].isdigit()


def summary_notes(results: Dict[str, dict], field_names: Dict[str, str]) -> List[str]:
    """Explain what the mapping says about duplicate, silent and unused inputs.

    `results` is the per-control dict written to the JSON file; `field_names`
    maps every non-padding input field key to its name.
    """
    notes: List[str] = []
    owners: Dict[Tuple[str, int], List[str]] = {}
    for cid, r in results.items():
        if not r.get("skipped"):
            p = r["fields"][0]
            owners.setdefault((p["key"], p["peak"]), []).append(cid)
    for ids in owners.values():
        if len(ids) < 2:
            continue
        m = [c for c in ids if is_programmable(c)]
        others = [c for c in ids if not is_programmable(c)]
        if m and others:
            notes.append(f"{', '.join(m)} sent exactly what {', '.join(others)} sends. The controller remaps "
                         "it in firmware, so the Mac can't tell them apart. Reassigning it on the controller "
                         "works without changing our table, but we can't give it its own function on the Mac.")
        else:
            notes.append(f"{', '.join(ids)} produced the same field and value; they are indistinguishable "
                         "(or one was pressed by mistake).")
    silent = [c for c, r in results.items() if r.get("skipped") and is_programmable(c)]
    if silent:
        it, was, has = ("they", "weren't", "have them") if len(silent) > 1 else ("it", "wasn't", "have it")
        notes.append(f"{', '.join(silent)} sent nothing. Either {it} {was} pressed, the controller doesn't "
                     f"{has}, or the current profile leaves {'them' if len(silent) > 1 else 'it'} unassigned "
                     "(the firmware sends no data).")
    touched = {f["key"] for r in results.values() if not r.get("skipped") for f in r["fields"]}
    unused = [name for key, name in field_names.items() if key not in touched]
    if unused:
        notes.append(f"Declared in the descriptor but never moved: {', '.join(unused)}. These may be "
                     "unprompted controls, spare slots, or back buttons in a different profile.")
    return notes
