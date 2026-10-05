"""Structural checks and corpus coverage for parsed EFL files (efl_import_plan.md section 7).

check(efl) returns the invariant violations of one file. Coverage accumulates, over many files,
how often each schema field is non-zero, which unknown gaps carry data, and how keyframe blocks
fit the assumed (SE) key sizes. These are RE leads, not errors.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from . import schema

MAX_PTCL_TYPE, MAX_MOVE_TYPE, MAX_PRIM_MODEL_TYPE = 17, 6, 5


def _is_float_type(ftype):
    base, _ = schema.parse_type(ftype)
    return base in ("f32", "rangef", "vec3", "vec4", "easecurve")


def _floats(value):
    if isinstance(value, list):
        for v in value:
            yield from _floats(v)
    else:
        yield value


def _path_problem(block, f):
    raw = bytes(block.data[f.offset:f.offset + schema.STR_SIZE])
    if b"\0" not in raw:
        return "unterminated"
    text = raw.split(b"\0", 1)[0]
    if not text:
        return None
    if not all(0x20 <= c < 0x7F for c in text):
        return "non-printable"
    if "." in text.decode("ascii").replace("/", "\\").rsplit("\\", 1)[-1]:
        return "has an extension"
    return None


def check(efl):
    """List of (code, where, detail) for one parsed file."""
    issues = []

    def add(code, where, detail=""):
        issues.append((code, where, detail))

    for owner, slot, block in efl.iter_blocks():
        where = f"{owner}.{slot}:{block.type_name}"
        st = block.struct
        if slot == "ptcl" and block.type > MAX_PTCL_TYPE:
            add("enum-range", where, f"particle type {block.type}")
        if slot == "move" and block.type > MAX_MOVE_TYPE:
            add("enum-range", where, f"move type {block.type}")
        if len(block.data) < st.size:
            add("block-short", where, f"{len(block.data):#x} < {st.name} {st.size:#x}")
        for f in st.fields:
            if f.offset + f.size > len(block.data):
                continue
            if f.type == "str64":
                problem = _path_problem(block, f)
                if problem:
                    add("path-bad", f"{where}.{f.name}", problem)
            elif _is_float_type(f.type):
                if not all(math.isfinite(v) for v in _floats(block.get(f.name))):
                    add("float-nonfinite", f"{where}.{f.name}")
        if block.has("PrimFlags") and block.get("PrimModelType") > MAX_PRIM_MODEL_TYPE:
            add("enum-range", where, f"PrimModelType {block.get('PrimModelType')}")

        for sub in block.subblocks():
            swhere = f"{where}.{sub.field.name}"
            if not 0 <= sub.offset < len(block.data):
                add("sub-outside", swhere, f"target {sub.offset:#x}, block {len(block.data):#x}")
                continue
            if sub.offset < st.size:
                add("sub-in-struct", swhere, f"target {sub.offset:#x} < struct size {st.size:#x}")
            if sub.offset % 4:
                add("sub-unaligned", swhere, f"target {sub.offset:#x}")
            if sub.kind == "kf":
                if sub.offset + 4 > len(block.data):
                    add("sub-outside", swhere, "keyframe header past the block")
                    continue
                num = sub.header()["KeyframeNum"]
                if num == 0:
                    add("kf-empty", swhere)
                elif sub.value_type and 4 + num * schema.KEY_SIZE[sub.value_type] > sub.end - sub.offset:
                    add("kf-overflow", swhere,
                        f"{num} x {sub.value_type} keys need {4 + num * schema.KEY_SIZE[sub.value_type]:#x}, "
                        f"have {sub.end - sub.offset:#x}")
            else:
                sub_struct = schema.SUB_STRUCTS[sub.kind]
                if sub.offset + sub_struct.size > len(block.data):
                    add("sub-outside", swhere, f"{sub_struct.name} runs past the block")
                else:
                    for f in sub_struct.fields:
                        if f.type == "str64":
                            raw = bytes(block.data[sub.offset + f.offset:sub.offset + f.offset + schema.STR_SIZE])
                            if b"\0" not in raw:
                                add("path-bad", f"{swhere}.{f.name}", "unterminated")
    return issues


class Coverage:
    """Corpus-wide field usage and keyframe-fit statistics."""

    def __init__(self):
        self.blocks = Counter()                     # struct name -> blocks seen
        self.nonzero = defaultdict(Counter)         # struct name -> field -> non-zero count
        self.gap_nonzero = defaultdict(Counter)     # struct name -> (start, end) -> non-zero count
        self.kf_fit = defaultdict(Counter)          # (struct, field) -> 'exact' / 'aligned' / 'slack' / 'short'
        self.kf_size_match = defaultdict(Counter)   # (struct, field) -> value type whose padded size fits exactly
        self.kf_headers = defaultdict(Counter)      # (struct, field) -> (SingleParam, FixAngle, InpType)
        self.sub_seen = Counter()                   # (struct, field) -> count

    def add(self, efl):
        for _, _, block in efl.iter_blocks():
            st = block.struct
            self.blocks[st.name] += 1
            data = block.data
            for f in st.fields:
                if f.offset + f.size <= len(data) and any(data[f.offset:f.offset + f.size]):
                    self.nonzero[st.name][f.name] += 1
            for gap in st.gaps():
                if gap[0] < len(data) and any(data[gap[0]:min(gap[1], len(data))]):
                    self.gap_nonzero[st.name][gap] += 1
            for sub in block.subblocks():
                key = (st.name, sub.field.name)
                self.sub_seen[key] += 1
                if sub.kind != "kf" or sub.offset + 4 > len(data):
                    continue
                h = sub.header()
                num, extent = h["KeyframeNum"], sub.end - sub.offset
                self.kf_headers[key][(h["SingleParamFlag"], h["FixAngleFlag"], h["InpType"])] += 1
                if not num:
                    continue
                # keyframe blocks look padded to 16 bytes: header (4) + num keys, rounded up
                for vtype, size in schema.KEY_SIZE.items():
                    if _align16(4 + num * size) == extent:
                        self.kf_size_match[key][vtype] += 1
                if sub.value_type:
                    need = 4 + num * schema.KEY_SIZE[sub.value_type]
                    self.kf_fit[key]["exact" if need == extent else "aligned" if _align16(need) == extent
                                     else "slack" if need < extent else "short"] += 1


def _align16(n):
    return (n + 15) & ~15
