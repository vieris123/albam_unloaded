"""EFL container: header, record table and blocks, with an exact byte round-trip.

Each block keeps its full byte span (the struct plus any trailing keyframe/culling/collision data),
and schema fields are read and written as views onto those bytes, so unknown bytes are never lost.
Writing lays the blocks out again in their original order and recomputes every record offset and
the header counts, so blocks may change size later without breaking the file.
"""
from __future__ import annotations

import struct

from . import schema

MAGIC = b"EFL\0"
VERSION_DX9 = 0x20070801
VERSION_SE = 0x20120306
HEADER_SIZE = 0x20
RECORD_SIZE = 0x10
SLOTS = ("gen", "ptcl", "life", "move")


class EflError(Exception):
    pass


class SubBlock:
    """Data reached through a self-relative offset field of a block."""

    __slots__ = ("block", "field", "offset", "end")

    def __init__(self, block, field, offset, end):
        self.block = block
        self.field = field      # schema.Field (or schema.Bits) holding the offset
        self.offset = offset    # start, relative to the block
        self.end = end          # next sub-block start or the block end (an upper bound, not a size)

    @property
    def kind(self):
        return self.field.sub.split(":")[0]

    @property
    def value_type(self):
        parts = self.field.sub.split(":")
        return parts[1] if len(parts) > 1 else None

    @property
    def data(self):
        return self.block.data[self.offset:self.end]

    def header(self):
        if self.kind != "kf":
            return None
        return schema.keyframe_header(struct.unpack_from("<I", self.block.data, self.offset)[0])

    def fields(self):
        sub_struct = schema.SUB_STRUCTS.get(self.kind)
        if sub_struct is None:
            return None
        if self.offset + sub_struct.size > len(self.block.data):
            raise EflError(f"{self.field.name}: {sub_struct.name} at {self.offset:#x} runs past the block")
        return {f.name: schema.decode(f.type, self.block.data, self.offset + f.offset) for f in sub_struct.fields}


class Block:
    __slots__ = ("kind", "type", "data", "offset", "struct")

    def __init__(self, kind, btype, data, offset=None):
        self.kind = kind            # 'gen' / 'ptcl' / 'life' / 'move' / 'raw'
        self.type = btype           # record type byte
        self.data = bytearray(data)
        self.offset = offset        # content offset in the source file (None for new blocks)
        self.struct = schema.struct_for_data(kind, btype, self.data) if kind != "raw" else None

    def __repr__(self):
        name = schema.type_name(self.kind, self.type) if self.struct else "raw"
        where = "new" if self.offset is None else f"{self.offset:#x}"
        return f"<Block {self.kind}:{name} @{where} len={len(self.data):#x}>"

    @property
    def type_name(self):
        return schema.type_name(self.kind, self.type)

    def has(self, name):
        if name in self.struct.bits_by_name:
            name = self.struct.bits_by_name[name].field
        f = self.struct.by_name.get(name)
        return f is not None and f.offset + f.size <= len(self.data)

    def get(self, name):
        if name in self.struct.bits_by_name:
            b = self.struct.bits_by_name[name]
            return (self.get(b.field) >> b.shift) & ((1 << b.width) - 1)
        f = self.struct.by_name[name]
        return schema.decode(f.type, self.data, f.offset)

    def set(self, name, value):
        if name in self.struct.bits_by_name:
            b = self.struct.bits_by_name[name]
            mask = ((1 << b.width) - 1) << b.shift
            self.set(b.field, (self.get(b.field) & ~mask) | ((value << b.shift) & mask))
            return
        f = self.struct.by_name[name]
        schema.encode(f.type, self.data, f.offset, value)

    def fields(self):
        """name -> value for every schema field that fits in the block."""
        return {f.name: schema.decode(f.type, self.data, f.offset)
                for f in self.struct.fields if f.offset + f.size <= len(self.data)}

    def bits(self):
        return {b.name: self.get(b.name) for b in self.struct.bits if self.has(b.field)}

    def subblocks(self):
        """Non-zero self-relative offsets of this block, sorted by target, with upper bounds."""
        refs = []
        for f in self.struct.offset_fields():
            if not self.has(f.name):
                continue
            rel = self.get(f.name)
            if rel:
                refs.append((f.rel_base + rel, f))
        refs.sort(key=lambda r: r[0])
        out = []
        for i, (target, f) in enumerate(refs):
            nxt = next((t for t, _ in refs[i + 1:] if t > target), len(self.data))
            out.append(SubBlock(self, f, target, nxt))
        return out


class Record:
    __slots__ = SLOTS

    def __init__(self, gen=None, ptcl=None, life=None, move=None):
        self.gen, self.ptcl, self.life, self.move = gen, ptcl, life, move

    def blocks(self):
        return [(slot, getattr(self, slot)) for slot in SLOTS]


class EffectList:
    def __init__(self):
        self.version = VERSION_DX9
        self.base_fps = 60.0
        self.header_unk = 0          # dword at 0x1C, 0 in every DX9 file
        self.records = []
        self.unit_gen = None         # header 0x10 (child/unit generator), rare
        self.unit_move = None        # header 0x14
        self.blocks = []             # every block in file order (record blocks, unit blocks, raw gaps)

    # -- reading ----------------------------------------------------------------------------

    @classmethod
    def from_bytes(cls, data):
        data = bytes(data)
        if len(data) < HEADER_SIZE or data[:4] != MAGIC:
            raise EflError("not an EFL file (bad magic)")
        (version, content_size, count, unit_gen, unit_move,
         base_fps, header_unk) = struct.unpack_from("<IIIIIfI", data, 4)
        if version != VERSION_DX9:
            hint = " (Special Edition)" if version == VERSION_SE else ""
            raise EflError(f"unsupported EFL version {version:#x}{hint}; only DX9 {VERSION_DX9:#x} is supported")
        content = data[HEADER_SIZE:]
        if content_size != len(content):
            raise EflError(f"contentSize {content_size:#x} != file size - 0x20 ({len(content):#x})")
        table_end = count * RECORD_SIZE
        if table_end > len(content):
            raise EflError("record table runs past the end of the file")

        efl = cls()
        efl.version, efl.base_fps, efl.header_unk = version, base_fps, header_unk

        # every packed dword (offset << 8 | type) that points at a block
        refs = []   # (record index or 'unit_gen'/'unit_move', slot, offset, type)
        for i in range(count):
            for slot, dword in zip(SLOTS, struct.unpack_from("<4I", content, i * RECORD_SIZE)):
                if dword >> 8:
                    refs.append((i, slot, dword >> 8, dword & 0xFF))
        if unit_gen >> 8:
            refs.append(("unit_gen", "gen", unit_gen >> 8, unit_gen & 0xFF))
        if unit_move >> 8:
            refs.append(("unit_move", "move", unit_move >> 8, unit_move & 0xFF))

        kinds = {}
        for _, slot, off, btype in refs:
            if not table_end <= off < len(content):
                raise EflError(f"{slot} block offset {off:#x} is outside the content")
            if kinds.setdefault(off, (slot, btype)) != (slot, btype):
                raise EflError(f"block at {off:#x} is referenced as both {kinds[off]} and {(slot, btype)}")

        # slice: each block runs to the next block start (the last one to the end of the content)
        starts = sorted(kinds)
        by_offset = {}
        if starts and starts[0] > table_end:
            efl.blocks.append(Block("raw", 0, content[table_end:starts[0]], table_end))
        elif not starts and table_end < len(content):
            efl.blocks.append(Block("raw", 0, content[table_end:], table_end))
        for i, off in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(content)
            slot, btype = kinds[off]
            block = Block(slot, btype, content[off:end], off)
            by_offset[off] = block
            efl.blocks.append(block)

        efl.records = [Record() for _ in range(count)]
        for owner, slot, off, _ in refs:
            if owner == "unit_gen":
                efl.unit_gen = by_offset[off]
            elif owner == "unit_move":
                efl.unit_move = by_offset[off]
            else:
                setattr(efl.records[owner], slot, by_offset[off])
        return efl

    @classmethod
    def from_file(cls, path):
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    # -- writing ----------------------------------------------------------------------------

    def to_bytes(self):
        table_end = len(self.records) * RECORD_SIZE
        referenced = {id(b) for r in self.records for _, b in r.blocks() if b is not None}
        referenced |= {id(b) for b in (self.unit_gen, self.unit_move) if b is not None}
        listed = {id(b) for b in self.blocks}
        if referenced - listed:
            raise EflError("a record references a block missing from EffectList.blocks")

        new_offset, pos = {}, table_end
        for block in self.blocks:
            if id(block) in referenced and pos % 4:
                raise EflError(f"{block!r} would start unaligned at {pos:#x}")
            new_offset[id(block)] = pos
            pos += len(block.data)
        if pos >= 1 << 24:
            raise EflError("content too large for 24-bit block offsets")

        def packed(block):
            return 0 if block is None else (new_offset[id(block)] << 8) | block.type

        content = bytearray(pos)
        for i, rec in enumerate(self.records):
            struct.pack_into("<4I", content, i * RECORD_SIZE, *(packed(b) for _, b in rec.blocks()))
        for block in self.blocks:
            content[new_offset[id(block)]:new_offset[id(block)] + len(block.data)] = block.data

        header = MAGIC + struct.pack("<IIIIIfI", self.version, len(content), len(self.records),
                                     packed(self.unit_gen), packed(self.unit_move),
                                     self.base_fps, self.header_unk)
        return header + bytes(content)

    # -- convenience ------------------------------------------------------------------------

    def iter_blocks(self):
        """(owner, slot, block) for every referenced block; owner is a record index or 'unit'."""
        for i, rec in enumerate(self.records):
            for slot, block in rec.blocks():
                if block is not None:
                    yield i, slot, block
        if self.unit_gen is not None:
            yield "unit", "gen", self.unit_gen
        if self.unit_move is not None:
            yield "unit", "move", self.unit_move
