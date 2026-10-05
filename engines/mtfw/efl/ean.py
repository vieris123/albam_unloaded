"""DMC4 .ean (rEffectAnim) flipbook tables: which pixel rectangles of an effect texture are animation frames.

Layout (DX9, version 0x20060501; checked against every DX9 .ean in the corpus):
    0x00 'EAN\\0'   0x04 version   0x08 data size (file size - 0x10)   0x0C sequence count
    0x10 sequences, 32 bytes each:
        +0x00 u32 pattern table offset (relative to 0x10)
        +0x04 u16 pattern count, u16 unknown
        +0x08 u32[4] unknown (pivot/bounds?)
        +0x18 u16 x2 unknown (grid?)   +0x1C u16 cell width, cell height
    patterns: s16 (x, y, w, h) in texture pixels.
The game turns a pattern into UVs in sub_9632F0: u = x / texture width, v = y / texture height, with AnimFlag
0x100 = flip U, 0x200 = flip V, 0x1000 = rotate the cell. Sequences are picked by SeqNoMin (+ random SeqNoRange),
patterns by PatNoMin (+ random PatNoRange), animated over time by PatSpeed.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"EAN\0"
HEADER_SIZE = 0x10
SEQUENCE_SIZE = 0x20
PATTERN_SIZE = 8

ANIM_FLIP_U = 0x100
ANIM_FLIP_V = 0x200
ANIM_ROTATE = 0x1000


class EanError(Exception):
    pass


@dataclass
class Sequence:
    patterns: list = field(default_factory=list)   # (x, y, w, h) in pixels
    unknown: tuple = ()                            # the remaining header fields, kept for RE


@dataclass
class EffectAnim:
    version: int
    sequences: list

    def pattern(self, seq_no, pat_no):
        """(x, y, w, h) for a sequence/pattern, clamped like the game; None if the table is empty."""
        if not self.sequences:
            return None
        seq = self.sequences[min(max(seq_no, 0), len(self.sequences) - 1)]
        if not seq.patterns:
            return None
        return seq.patterns[min(max(pat_no, 0), len(seq.patterns) - 1)]


def parse(data):
    data = bytes(data)
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        raise EanError("not an EAN file (bad magic)")
    version, size, count = struct.unpack_from("<III", data, 4)
    if size != len(data) - HEADER_SIZE:
        raise EanError(f"data size {size:#x} != file size - 0x10 ({len(data) - HEADER_SIZE:#x})")
    if HEADER_SIZE + count * SEQUENCE_SIZE > len(data):
        raise EanError("sequence table runs past the end of the file")
    sequences = []
    for i in range(count):
        base = HEADER_SIZE + i * SEQUENCE_SIZE
        table, num = struct.unpack_from("<IH", data, base)
        unknown = struct.unpack_from("<H4I4H", data, base + 6)
        start = HEADER_SIZE + table
        if start + num * PATTERN_SIZE > len(data):
            raise EanError(f"sequence {i}: {num} patterns at {start:#x} run past the end of the file")
        patterns = [struct.unpack_from("<4h", data, start + j * PATTERN_SIZE) for j in range(num)]
        sequences.append(Sequence(patterns, unknown))
    return EffectAnim(version, sequences)


def pattern_uv_rect(pattern, tex_width, tex_height, anim_flag=0):
    """UV rectangle (u0, v0, u1, v1) in texture space (v down), as sub_9632F0 computes it; rotate flag returned too."""
    x, y, w, h = pattern
    u0, u1 = x / tex_width, (x + w) / tex_width
    v0, v1 = y / tex_height, (y + h) / tex_height
    if anim_flag & ANIM_FLIP_U:
        u0, u1 = u1, u0
    if anim_flag & ANIM_FLIP_V:
        v0, v1 = v1, v0
    return (u0, v0, u1, v1), bool(anim_flag & ANIM_ROTATE)


def map_uv(uv, rect, rotate=False):
    """Map a cell-local UV (0..1, v down) into a pattern's UV rectangle (v down)."""
    u, v = uv
    if rotate:
        u, v = v, u
    u0, v0, u1, v1 = rect
    return u0 + (u1 - u0) * u, v0 + (v1 - v0) * v
