"""A small, dependency-free HID report descriptor parser.

A HID report descriptor is a bytecode program that describes the layout of
the reports a device sends (Input), receives (Output) and exchanges on request
(Feature). The host runs this program once at enumeration time and builds a
table of fields: "bits 8..15 of report 1 are the X axis, range 0..255", and so
on. This module does exactly that, so we can decode raw reports ourselves and
see what the device *claims* each byte means.

Item encoding (HID 1.11, section 6.2.2.2), one prefix byte followed by data:

    bit  7 6 5 4 | 3 2 | 1 0
         bTag    | bType | bSize

    bSize: 0, 1, 2 or 4 data bytes (encoded as 0, 1, 2, 3)
    bType: 0 = Main, 1 = Global, 2 = Local
    bTag:  which item within that type

Main items (Input/Output/Feature/Collection/End Collection) "emit" things.
Global items (Usage Page, Logical Min/Max, Report Size/Count, Report ID, ...)
persist until changed. Local items (Usage, Usage Min/Max, ...) apply only to
the next Main item and are then cleared.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

from hid_usages import COLLECTION_TYPES, nibble_signed, page_name, unit_name, usage_name

TYPE_MAIN, TYPE_GLOBAL, TYPE_LOCAL = 0, 1, 2

MAIN_TAGS = {
    0x8: "Input",
    0x9: "Output",
    0xB: "Feature",
    0xA: "Collection",
    0xC: "End Collection",
}
GLOBAL_TAGS = {
    0x0: "Usage Page",
    0x1: "Logical Minimum",
    0x2: "Logical Maximum",
    0x3: "Physical Minimum",
    0x4: "Physical Maximum",
    0x5: "Unit Exponent",
    0x6: "Unit",
    0x7: "Report Size",
    0x8: "Report ID",
    0x9: "Report Count",
    0xA: "Push",
    0xB: "Pop",
}
LOCAL_TAGS = {
    0x0: "Usage",
    0x1: "Usage Minimum",
    0x2: "Usage Maximum",
    0x3: "Designator Index",
    0x4: "Designator Minimum",
    0x5: "Designator Maximum",
    0x7: "String Index",
    0x8: "String Minimum",
    0x9: "String Maximum",
    0xA: "Delimiter",
}

# Flag bits of Input/Output/Feature items (HID 1.11, section 6.2.2.5).
_MAIN_FLAG_NAMES = [
    ("Data", "Const"),
    ("Array", "Var"),
    ("Abs", "Rel"),
    ("NoWrap", "Wrap"),
    ("Linear", "NonLinear"),
    ("PrefState", "NoPrefState"),
    ("NoNull", "Null"),
    ("NonVol", "Vol"),
]


class DescriptorError(ValueError):
    pass


@dataclass
class Item:
    offset: int          # byte offset of the prefix byte within the descriptor
    raw: bytes           # prefix + data bytes, exactly as they appear
    type: int            # TYPE_MAIN / TYPE_GLOBAL / TYPE_LOCAL (3 = reserved/long)
    tag: int
    size: int            # number of data bytes (0, 1, 2 or 4)
    udata: int           # data interpreted as unsigned little-endian
    sdata: int           # data interpreted as signed (two's complement)

    @property
    def name(self) -> str:
        table = {TYPE_MAIN: MAIN_TAGS, TYPE_GLOBAL: GLOBAL_TAGS, TYPE_LOCAL: LOCAL_TAGS}.get(self.type, {})
        return table.get(self.tag, f"Unknown(type={self.type}, tag=0x{self.tag:X})")


def parse_items(desc: bytes) -> List[Item]:
    """Split a descriptor into items. Pure tokenizing, no semantics."""
    items: List[Item] = []
    i = 0
    while i < len(desc):
        prefix = desc[i]
        if prefix == 0xFE:
            # Long item: 0xFE, bDataSize, bLongItemTag, data... Reserved by the
            # spec and practically never used, but skip it correctly if present.
            if i + 2 >= len(desc):
                raise DescriptorError(f"truncated long item at offset {i}")
            n = desc[i + 1]
            end = i + 3 + n
            if end > len(desc):
                raise DescriptorError(f"truncated long item at offset {i}")
            items.append(Item(i, bytes(desc[i:end]), 3, desc[i + 2], n, 0, 0))
            i = end
            continue
        size = (0, 1, 2, 4)[prefix & 0x3]
        end = i + 1 + size
        if end > len(desc):
            raise DescriptorError(f"truncated item 0x{prefix:02X} at offset {i}")
        data = bytes(desc[i + 1:end])
        udata = int.from_bytes(data, "little") if size else 0
        sdata = int.from_bytes(data, "little", signed=True) if size else 0
        items.append(Item(i, bytes(desc[i:end]), (prefix >> 2) & 0x3, prefix >> 4, size, udata, sdata))
        i = end
    return items


def main_flags_str(flags: int) -> str:
    return ", ".join(names[(flags >> bit) & 1] for bit, names in enumerate(_MAIN_FLAG_NAMES))


def short_flags_str(flags: int) -> str:
    """Only the flags that matter when reading a field table."""
    out = ["Const" if flags & 0x01 else ("Var" if flags & 0x02 else "Array")]
    out += [name for bit, name in ((2, "Rel"), (3, "Wrap"), (4, "NonLinear"), (6, "Null")) if flags >> bit & 1]
    return " ".join(out)


@dataclass
class Field:
    """One value inside one report, e.g. 'X axis, report 1, bits 8..15'."""

    kind: str                    # "Input", "Output" or "Feature"
    report_id: int               # 0 when the device doesn't use report IDs
    bit_offset: int              # from the start of the report *payload* (after the ID byte)
    bit_size: int
    usage_page: int
    usage: int                   # for array fields: the first usage in `array_usages`
    logical_min: int
    logical_max: int
    flags: int
    collection_path: Tuple[str, ...] = ()
    array_usages: List[Tuple[int, int]] = field(default_factory=list)  # (page, usage)

    @property
    def is_constant(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def is_array(self) -> bool:
        return not (self.flags & 0x02)

    @property
    def is_relative(self) -> bool:
        return bool(self.flags & 0x04)

    @property
    def has_null_state(self) -> bool:
        return bool(self.flags & 0x40)

    @property
    def is_signed(self) -> bool:
        return self.logical_min < 0

    @property
    def is_hat(self) -> bool:
        return self.usage_page == 0x01 and self.usage == 0x39

    @property
    def name(self) -> str:
        if self.is_constant:
            return "(padding)"
        if self.is_array:
            return f"Array[{usage_name(*self.array_usages[0])}..]" if self.array_usages else "Array"
        return usage_name(self.usage_page, self.usage)

    @property
    def key(self) -> str:
        """Stable identifier used in mapping files."""
        return f"{self.kind[0]}{self.report_id}@{self.bit_offset}+{self.bit_size}"

    def extract(self, payload: bytes) -> Optional[int]:
        """Pull this field's value out of a report payload (report ID stripped).

        Fields are packed little-endian at bit granularity: bit 0 of the payload
        is the least significant bit of byte 0. Returns None if the report is too
        short to contain the field (short reports happen, e.g. over Bluetooth).
        """
        end_bit = self.bit_offset + self.bit_size
        if end_bit > len(payload) * 8:
            return None
        first, last = self.bit_offset // 8, (end_bit - 1) // 8
        chunk = int.from_bytes(payload[first:last + 1], "little")
        value = (chunk >> (self.bit_offset % 8)) & ((1 << self.bit_size) - 1)
        if self.is_signed and value & (1 << (self.bit_size - 1)):
            value -= 1 << self.bit_size
        return value

    def describe_value(self, value: Optional[int]) -> str:
        if value is None:
            return "n/a"
        if self.is_hat:
            if self.logical_min <= value <= self.logical_max:
                steps = self.logical_max - self.logical_min + 1
                if steps == 8:
                    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
                    return f"{value} ({names[value - self.logical_min]})"
                return str(value)
            return f"{value} (centered/null)"
        if self.is_array and self.array_usages:
            idx = value - self.logical_min
            if 0 <= idx < len(self.array_usages):
                return f"{value} ({usage_name(*self.array_usages[idx])})" if value else "0 (none)"
        return str(value)


@dataclass
class _Globals:
    usage_page: int = 0
    logical_min: int = 0
    logical_max: int = 0
    logical_max_unsigned: int = 0
    physical_min: int = 0
    physical_max: int = 0
    unit_exponent: int = 0
    unit: int = 0
    report_size: int = 0
    report_id: int = 0
    report_count: int = 0


@dataclass
class Descriptor:
    raw: bytes
    items: List[Item]
    fields: List[Field]
    report_ids: List[int]
    warnings: List[str]
    # Size in bits of each (kind, report_id) payload, not counting the ID byte.
    report_bits: Dict[Tuple[str, int], int]

    @property
    def uses_report_ids(self) -> bool:
        return bool(self.report_ids)

    def input_fields(self, report_id: Optional[int] = None, include_padding: bool = False) -> List[Field]:
        return [
            f for f in self.fields
            if f.kind == "Input"
            and (report_id is None or f.report_id == report_id)
            and (include_padding or not f.is_constant)
        ]

    def max_input_report_len(self) -> int:
        """Largest Input report in bytes, including the report ID byte if used."""
        sizes = [bits for (kind, _), bits in self.report_bits.items() if kind == "Input"]
        payload = (max(sizes) + 7) // 8 if sizes else 0
        return payload + (1 if self.uses_report_ids else 0)

    def split_report(self, report: bytes) -> Tuple[int, bytes]:
        """Split a raw report as delivered by hidapi into (report_id, payload).

        With numbered reports, hidapi (on macOS, via IOKit) delivers the report
        ID as byte 0. With unnumbered reports there is no ID byte at all.
        """
        if self.uses_report_ids and report:
            return report[0], bytes(report[1:])
        return 0, bytes(report)

    def application_collections(self) -> List[str]:
        """Top-level collections, e.g. ['Generic Desktop / Game Pad']."""
        out = []
        page = 0
        depth = 0
        pending_usages: List[Tuple[int, int]] = []
        for it in self.items:
            if it.type == TYPE_GLOBAL and it.tag == 0x0:
                page = it.udata
            elif it.type == TYPE_LOCAL and it.tag == 0x0:
                pending_usages.append(_full_usage(it, page))
            elif it.type == TYPE_MAIN:
                if it.tag == 0xA:
                    if depth == 0 and pending_usages:
                        p, u = pending_usages[0]
                        out.append(f"{page_name(p)} / {usage_name(p, u)}")
                    depth += 1
                elif it.tag == 0xC:
                    depth = max(0, depth - 1)
                pending_usages = []
        return out


def _full_usage(item: Item, current_page: int) -> Tuple[int, int]:
    """A 4-byte Usage carries its own page in the high 16 bits ("extended usage")."""
    if item.size == 4:
        return item.udata >> 16, item.udata & 0xFFFF
    return current_page, item.udata


def parse_descriptor(desc: bytes) -> Descriptor:
    """Run the descriptor "program" and produce a field table."""
    desc = bytes(desc)
    items = parse_items(desc)
    g = _Globals()
    stack: List[_Globals] = []
    usages: List[Tuple[int, int]] = []
    usage_min: Optional[Tuple[int, int]] = None
    collections: List[str] = []
    fields: List[Field] = []
    warnings: List[str] = []
    bit_cursor: Dict[Tuple[str, int], int] = {}
    report_ids: List[int] = []

    def reset_locals() -> None:
        nonlocal usages, usage_min
        usages = []
        usage_min = None

    for it in items:
        if it.type == TYPE_GLOBAL:
            t = it.tag
            if t == 0x0:
                g.usage_page = it.udata
            elif t == 0x1:
                g.logical_min = it.sdata
            elif t == 0x2:
                g.logical_max = it.sdata
                g.logical_max_unsigned = it.udata
            elif t == 0x3:
                g.physical_min = it.sdata
            elif t == 0x4:
                g.physical_max = it.sdata
            elif t == 0x5:
                g.unit_exponent = it.sdata
            elif t == 0x6:
                g.unit = it.udata
            elif t == 0x7:
                g.report_size = it.udata
            elif t == 0x8:
                g.report_id = it.udata
                if it.udata == 0:
                    warnings.append(f"offset {it.offset}: Report ID 0 is reserved")
                if it.udata not in report_ids:
                    report_ids.append(it.udata)
            elif t == 0x9:
                g.report_count = it.udata
            elif t == 0xA:
                stack.append(replace(g))
            elif t == 0xB:
                if not stack:
                    raise DescriptorError(f"offset {it.offset}: Pop without Push")
                g = stack.pop()
        elif it.type == TYPE_LOCAL:
            t = it.tag
            if t == 0x0:
                usages.append(_full_usage(it, g.usage_page))
            elif t == 0x1:
                usage_min = _full_usage(it, g.usage_page)
            elif t == 0x2:
                usage_max = _full_usage(it, g.usage_page)
                if usage_min is None:
                    warnings.append(f"offset {it.offset}: Usage Maximum without Usage Minimum")
                else:
                    page = usage_min[0]
                    usages.extend((page, u) for u in range(usage_min[1], usage_max[1] + 1))
                    usage_min = None
        elif it.type == TYPE_MAIN:
            t = it.tag
            if t == 0xA:
                ctype = COLLECTION_TYPES.get(it.udata, f"0x{it.udata:02X}")
                label = usage_name(*usages[0]) if usages else "?"
                collections.append(f"{label} ({ctype})")
            elif t == 0xC:
                if not collections:
                    warnings.append(f"offset {it.offset}: End Collection without Collection")
                else:
                    collections.pop()
            elif t in (0x8, 0x9, 0xB):
                kind = MAIN_TAGS[t]
                lmin, lmax = g.logical_min, g.logical_max
                # Common descriptor bug/idiom: "Logical Maximum (255)" encoded in a
                # single byte reads as -1 when treated as signed. Like the Linux
                # kernel, only treat the maximum as signed if the minimum is.
                if lmin >= 0 and lmax < 0:
                    lmax = g.logical_max_unsigned
                key = (kind, g.report_id)
                cursor = bit_cursor.get(key, 0)
                is_const = bool(it.udata & 0x01)
                is_var = bool(it.udata & 0x02)
                size, count = g.report_size, g.report_count
                path = tuple(collections)
                if is_const or not usages:
                    # Padding (or data with no usage, which we treat the same way).
                    if size * count:
                        fields.append(Field(kind, g.report_id, cursor, size * count, g.usage_page, 0,
                                            lmin, lmax, it.udata | 0x01, path))
                elif is_var:
                    for n in range(count):
                        page, usage = usages[min(n, len(usages) - 1)]
                        fields.append(Field(kind, g.report_id, cursor + n * size, size, page, usage,
                                            lmin, lmax, it.udata, path))
                else:
                    # Array: each slot holds an index into the usage list
                    # (value - logical_min). Used by keyboards for "keys down".
                    for n in range(count):
                        fields.append(Field(kind, g.report_id, cursor + n * size, size, usages[0][0],
                                            usages[0][1], lmin, lmax, it.udata, path, list(usages)))
                bit_cursor[key] = cursor + size * count
            reset_locals()

    if collections:
        warnings.append(f"{len(collections)} collection(s) not closed")
    if stack:
        warnings.append(f"{len(stack)} Push(es) without Pop")
    for (kind, rid), bits in bit_cursor.items():
        if bits % 8:
            warnings.append(f"{kind} report {rid}: {bits} bits is not byte-aligned")
    if report_ids and any(f.report_id == 0 for f in fields):
        warnings.append("some fields appear before the first Report ID item")

    return Descriptor(desc, items, fields, report_ids, warnings, dict(bit_cursor))


def format_items(items: List[Item]) -> str:
    """Pretty-print items with indentation, in the style of hidrd / usb.org's tool."""
    lines = []
    indent = 0
    page = 0
    for it in items:
        if it.type == TYPE_MAIN and it.tag == 0xC:
            indent = max(0, indent - 1)
        value = ""
        if it.type == TYPE_GLOBAL and it.tag == 0x0:
            page = it.udata
            value = page_name(page)
        elif it.type == TYPE_LOCAL and it.tag in (0x0, 0x1, 0x2):
            p, u = _full_usage(it, page)
            value = usage_name(p, u)
        elif it.type == TYPE_MAIN and it.tag in (0x8, 0x9, 0xB):
            value = main_flags_str(it.udata)
        elif it.type == TYPE_MAIN and it.tag == 0xA:
            value = COLLECTION_TYPES.get(it.udata, f"0x{it.udata:02X}")
        elif it.type == TYPE_GLOBAL and it.tag == 0x5:
            # The spec's examples encode the exponent as a 4-bit signed nibble:
            # 0x0E means -2 (units of 10^-2), not 14.
            value = str(nibble_signed(it.udata)) if it.udata <= 0xF else str(it.sdata)
        elif it.type == TYPE_GLOBAL and it.tag == 0x6:
            value = f"0x{it.udata:X} = {unit_name(it.udata)}"
        elif it.type == TYPE_GLOBAL and it.tag in (0x1, 0x2, 0x3, 0x4):
            value = f"{it.sdata}" + (f" / {it.udata}" if it.sdata != it.udata else "")
        elif it.type == TYPE_GLOBAL and it.tag in (0x7, 0x8, 0x9):
            value = str(it.udata)
        elif it.size:
            value = f"{it.udata} (0x{it.udata:X})"
        hexbytes = " ".join(f"{b:02X}" for b in it.raw)
        text = f"{it.name} ({value})" if value else it.name
        lines.append(f"{it.offset:4d}  {hexbytes:<15} {'  ' * indent}{text}")
        if it.type == TYPE_MAIN and it.tag == 0xA:
            indent += 1
    return "\n".join(lines)


def format_fields(desc: Descriptor, kinds=("Input", "Output", "Feature")) -> str:
    """Table of every field, grouped by report. This is the 'decoded layout'."""
    lines = []
    for kind in kinds:
        groups: Dict[int, List[Field]] = {}
        for f in desc.fields:
            if f.kind == kind:
                groups.setdefault(f.report_id, []).append(f)
        for rid, flist in groups.items():
            bits = desc.report_bits.get((kind, rid), 0)
            id_note = f"report ID {rid} (0x{rid:02X})" if desc.uses_report_ids else "no report ID"
            lines.append(f"{kind} {id_note}: payload {bits} bits = {(bits + 7) // 8} bytes"
                         + (" (+1 ID byte on the wire)" if desc.uses_report_ids else ""))
            lines.append(f"  {'key':<14} {'byte.bit':<9} {'bits':>4}  {'range':<16} {'name':<24} flags")
            for f in flist:
                pos = f"{f.bit_offset // 8}.{f.bit_offset % 8}"
                rng = "" if f.is_constant else f"{f.logical_min}..{f.logical_max}"
                lines.append(f"  {f.key:<14} {pos:<9} {f.bit_size:>4}  {rng:<16} {f.name:<24} "
                             f"{short_flags_str(f.flags)}")
            lines.append("")
    return "\n".join(lines).rstrip()
