"""DMC4 .ean (rEffectAnim) flipbook tables: which pixel rectangles of an effect texture are animation frames.

Layout (names from the SE PDB, rEffectAnim::EAN_HEADER / SEQ_INDEX / SEQ_PAT; checked against every DX9 and SE file,
822 + 3,305, all parse exactly):
    0x00 'EAN\0'   0x04 Version (DX9 0x20060501, SE 0x20120224)   0x08 ParamBuffSize (file size - 0x10)
    0x0C SeqNum : 24, OptionFlag : 8 (0 in every file)
    0x10 SEQ_INDEX[SeqNum], 32 bytes each:
        +0x00 u32 SeqPatTopOffset (relative to 0x10)
        +0x04 u16 SeqPatNum         +0x06 u16 DefaultAnimFlag (ANIM_FLAG; 0, 8 FINISH, 3 MOVE|LOOP, 9, 1 in the files)
        +0x08 MtPoint DefaultPatCenter (s32 x, y: the frame's pivot in pixels, e.g. the cell centre)
        +0x10 MtPoint ConPatBasePoint   +0x18 u16 ConPatColNum, u16 ConPatTotalNum   +0x1C u16 ConPatSizeW, ConPatSizeH
        The ConPat fields describe the grid the frames were cut from (base point, columns, cell size): in every DX9
        sequence whose ConPatTotalNum equals SeqPatNum, the patterns are exactly that grid.
    SEQ_PAT: s16 (U, V, W, H) pixel rect; SE appends f32 U0, V0, U1, V1 (the rect in texture UVs), so SE
    patterns are 24 bytes, DX9 ones 8.
ANIM_FLAG (SE enum): 0x1 MOVE, 0x2 LOOP, 0x4 REVERSE, 0x8 FINISH, 0x10 REVERSE_RAND, 0x100 HFLIP, 0x200 VFLIP,
0x400 HFLIP_RAND, 0x800 VFLIP_RAND, 0x1000 ROT, 0x2000 NO_INP, 0x8000 KEYFRAME.
The game turns a pattern into UVs in sub_9632F0: u = x / texture width, v = y / texture height, with AnimFlag
0x100 = flip U, 0x200 = flip V, 0x1000 = rotate the cell. Sequences are picked by SeqNoMin (+ random SeqNoRange),
patterns by PatNoMin (+ random PatNoRange), animated over time by PatSpeed.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"EAN\0"
VERSION_DX9 = 0x20060501
VERSION_SE = 0x20120224
HEADER_SIZE = 0x10
SEQUENCE_SIZE = 0x20
PATTERN_SIZE = {VERSION_DX9: 8, VERSION_SE: 0x18}   # SE adds U0, V0, U1, V1

ANIM_FLIP_U = 0x100
ANIM_FLIP_V = 0x200
ANIM_ROTATE = 0x1000


class EanError(Exception):
    pass


@dataclass
class Sequence:
    patterns: list = field(default_factory=list)   # (x, y, w, h) in pixels
    default_anim_flag: int = 0
    default_pat_center: tuple = (0, 0)             # pixels
    con_pat_base_point: tuple = (0, 0)             # the grid the patterns were cut from
    con_pat_col_num: int = 0
    con_pat_total_num: int = 0
    con_pat_size: tuple = (0, 0)                   # cell width, height
    uvs: list = field(default_factory=list)        # SE only: (U0, V0, U1, V1) per pattern, as stored


@dataclass
class EffectAnim:
    version: int
    sequences: list
    option_flag: int = 0

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
    version, size, word = struct.unpack_from("<III", data, 4)
    count, option_flag = word & 0xFFFFFF, word >> 24
    pattern_size = PATTERN_SIZE.get(version, 8)
    if size != len(data) - HEADER_SIZE:
        raise EanError(f"data size {size:#x} != file size - 0x10 ({len(data) - HEADER_SIZE:#x})")
    if HEADER_SIZE + count * SEQUENCE_SIZE > len(data):
        raise EanError("sequence table runs past the end of the file")
    sequences = []
    for i in range(count):
        base = HEADER_SIZE + i * SEQUENCE_SIZE
        table, num, flag = struct.unpack_from("<IHH", data, base)
        cx, cy, bx, by = struct.unpack_from("<4i", data, base + 8)
        cols, total, cw, ch = struct.unpack_from("<4H", data, base + 0x18)
        start = HEADER_SIZE + table
        if start + num * pattern_size > len(data):
            raise EanError(f"sequence {i}: {num} patterns at {start:#x} run past the end of the file")
        patterns = [struct.unpack_from("<4h", data, start + j * pattern_size) for j in range(num)]
        uvs = [struct.unpack_from("<4f", data, start + j * pattern_size + 8) for j in range(num)]             if pattern_size == 0x18 else []
        sequences.append(Sequence(patterns, flag, (cx, cy), (bx, by), cols, total, (cw, ch), uvs))
    return EffectAnim(version, sequences, option_flag)


def texture_size(anim):
    """(width, height) in pixels implied by an SE file's stored UVs (U0 = U / width), or None."""
    w = h = None
    for seq in anim.sequences:
        for (u, v, pw, ph), (u0, v0, u1, v1) in zip(seq.patterns, seq.uvs):
            if w is None and u1 != u0 and pw:
                w = round(pw / (u1 - u0))
            if h is None and v1 != v0 and ph:
                h = round(ph / (v1 - v0))
    return (w, h) if w and h else None


def to_bytes(anim, tex_size=None):
    """.ean bytes: header, sequence table, then every sequence's patterns in order. SE files store each
    pattern's UVs too: kept as stored while its rect is unchanged, else recomputed over tex_size (or the
    texture size the stored UVs imply)."""
    pattern_size = PATTERN_SIZE.get(anim.version, 8)
    se = pattern_size == 0x18
    if se and tex_size is None:
        tex_size = texture_size(anim)
    table = len(anim.sequences) * SEQUENCE_SIZE
    head, pats, at = bytearray(), bytearray(), table
    for seq in anim.sequences:
        cx, cy = seq.default_pat_center
        bx, by = seq.con_pat_base_point
        cw, ch = seq.con_pat_size
        head += struct.pack("<IHH4i4H", at, len(seq.patterns), seq.default_anim_flag, cx, cy, bx, by,
                            seq.con_pat_col_num, seq.con_pat_total_num, cw, ch)
        for j, rect in enumerate(seq.patterns):
            pats += struct.pack("<4h", *rect)
            if se:
                if j < len(seq.uvs) and _uv_matches(rect, seq.uvs[j], tex_size):
                    uv = seq.uvs[j]
                elif tex_size:
                    u, v, w, h = rect
                    uv = (u / tex_size[0], v / tex_size[1], (u + w) / tex_size[0], (v + h) / tex_size[1])
                else:
                    raise EanError("an SE .ean needs the texture size to write changed frames")
                pats += struct.pack("<4f", *uv)
        at += len(seq.patterns) * pattern_size
    body = bytes(head) + bytes(pats)
    word = (len(anim.sequences) & 0xFFFFFF) | ((anim.option_flag & 0xFF) << 24)
    return MAGIC + struct.pack("<III", anim.version, len(body), word) + body


def _uv_matches(rect, uv, tex_size):
    """True if stored UVs still describe rect (always true without a texture size to check against)."""
    if not tex_size:
        return True
    u, v, w, h = rect
    expect = (u / tex_size[0], v / tex_size[1], (u + w) / tex_size[0], (v + h) / tex_size[1])
    return all(abs(a - b) < 0.5 / max(tex_size) for a, b in zip(uv, expect))


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
    """Map a cell-local UV (0..1, v down) into a pattern's UV rectangle (v down).
    Rotate follows sub_9632F0's corner assignment: local (u, v) -> (1 - v, u)."""
    u, v = uv
    if rotate:
        u, v = 1.0 - v, u
    u0, v0, u1, v1 = rect
    return u0 + (u1 - u0) * u, v0 + (v1 - v0) * v


def uv_affine(pattern, tex_width, tex_height, anim_flag=0):
    """Blender-space UV transform for a pattern: rows (a, b, off) with u' = a*u + b*v + off_u, v' likewise.
    Input and output are Blender UVs (v up); the cell-local UV is the 0..1 square of the source mesh."""
    (u0, v0, u1, v1), rotate = pattern_uv_rect(pattern, tex_width, tex_height, anim_flag)
    du, dv = u1 - u0, v1 - v0
    if rotate:
        return (0.0, du, u0), (-dv, 0.0, 1.0 - v0)
    return (du, 0.0, u0), (0.0, dv, 1.0 - v0 - dv)


IDENTITY_AFFINE = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
