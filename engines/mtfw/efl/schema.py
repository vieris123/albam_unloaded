"""On-disk layout of DMC4 DX9 .efl blocks (version 0x20070801).

Single source of truth for the parser, the JSON dump and the corpus checker. Offsets are
**file offsets relative to the block start**, taken from DX9 code unless the tier says otherwise.
Do not copy SE offsets: the builds diverge (see Vibed/RE/efl_import_plan.md section 3).

Evidence tiers:
    dx9      read by DX9 code at this offset (address in the note where known)
    se       name/type from the SE PDB, DX9 layout agrees or is assumed
    prior    name inherited from earlier community/IDB work, unverified
    corpus   inferred from value statistics over the 1,109-file DX9 corpus
    unknown  placeholder; the bytes are kept raw anyway

The IDB's particle types (EFL_PARTICLE_*) are 4 bytes short from 0x14 on; the offsets here are
the file offsets (IDB offset + 4 past 0x14), confirmed in initParticleBillboard 0x977E60.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------------------------
# value types

_SCALARS = {
    "u8": "<B", "s8": "<b", "u16": "<H", "s16": "<h", "u32": "<I", "s32": "<i", "f32": "<f",
    "rel16": "<H",   # self-relative offset (from the block start, or Field.rel_base), 0 = none
    "rel32": "<i",
}
_TUPLES = {
    "rangef": "<2f",     # MtRangeF {s, r}: value = s + rand * r
    "rangeu16": "<2H",   # MtRangeU16 {s, r}: value = s + rand % (r + 1)
    "vec3": "<3f",
    "vec4": "<4f",       # quaternions are stored (x, y, z, w)
    "color": "<4B",      # MtColor r, g, b, a
    "point": "<2i",      # MtPoint
    "easecurve": "<2f",  # MtEaseCurve
}
STR_SIZE = 64


def parse_type(ftype):
    """'rangef[3]' -> ('rangef', 3); 'u16' -> ('u16', None)."""
    if ftype.endswith("]"):
        base, n = ftype[:-1].split("[")
        return base, int(n)
    return ftype, None


def type_size(ftype):
    base, n = parse_type(ftype)
    if base == "str64":
        size = STR_SIZE
    elif base in _SCALARS:
        size = struct.calcsize(_SCALARS[base])
    else:
        size = struct.calcsize(_TUPLES[base])
    return size * (n or 1)


def _decode_one(base, buf, off):
    if base == "str64":
        raw = bytes(buf[off:off + STR_SIZE])
        return raw.split(b"\0", 1)[0].decode("latin-1")
    if base in _SCALARS:
        return struct.unpack_from(_SCALARS[base], buf, off)[0]
    return list(struct.unpack_from(_TUPLES[base], buf, off))


def _encode_one(base, buf, off, value):
    if base == "str64":
        raw = value.encode("latin-1")
        if len(raw) >= STR_SIZE:
            raise ValueError(f"path longer than {STR_SIZE - 1} bytes: {value!r}")
        # write only text + NUL, so bytes after the terminator (often stale) survive a round-trip
        buf[off:off + len(raw) + 1] = raw + b"\0"
    elif base in _SCALARS:
        struct.pack_into(_SCALARS[base], buf, off, value)
    else:
        struct.pack_into(_TUPLES[base], buf, off, *value)


def decode(ftype, buf, off):
    base, n = parse_type(ftype)
    if n is None:
        return _decode_one(base, buf, off)
    step = type_size(base)
    return [_decode_one(base, buf, off + i * step) for i in range(n)]


def encode(ftype, buf, off, value):
    base, n = parse_type(ftype)
    if n is None:
        _encode_one(base, buf, off, value)
        return
    if len(value) != n:
        raise ValueError(f"{ftype} needs {n} values, got {len(value)}")
    step = type_size(base)
    for i, v in enumerate(value):
        _encode_one(base, buf, off + i * step, v)


# ---------------------------------------------------------------------------------------------
# keyframe blocks (reached through rel16/rel32 fields with sub="kf:<value type>")
#
# Header = EFL_KEYFRAME_INDEX (dword, same bitfields in DX9 and SE). Keys follow from +4.
# Key layouts are SE's nEffect::KEYFRAME_* (Frame u32 + Param). Corpus check (2026-10-05): with each
# keyframe block padded to 16 bytes, these key sizes fill the blocks exactly in DX9 too.

KEYFRAME_HEADER_BITS = (
    ("KeyframeNum", 0, 8), ("FixAngleFlag", 8, 1), ("SingleParamFlag", 9, 1),
    ("RefType", 24, 3), ("InpType", 27, 3), ("LoopFlag", 30, 1), ("InitOnlyFlag", 31, 1),
)
KEY_SIZE = {"f32": 12, "u32": 8, "color": 12, "vec2": 20, "vec3": 28}


def keyframe_header(word):
    return {name: (word >> shift) & ((1 << width) - 1) for name, shift, width in KEYFRAME_HEADER_BITS}


# ---------------------------------------------------------------------------------------------
# struct tables

@dataclass(frozen=True)
class Field:
    offset: int
    name: str
    type: str
    tier: str
    note: str = ""
    sub: str | None = None   # rel fields: "kf:<vtype>", "kf" (value type unknown), "culling", "collision"
    rel_base: int = 0        # rel fields: offset the stored value is relative to

    @property
    def size(self):
        return type_size(self.type)


@dataclass(frozen=True)
class Bits:
    name: str
    field: str     # name of the integer Field holding the bits
    shift: int
    width: int
    tier: str
    note: str = ""


@dataclass
class Struct:
    name: str
    size: int            # struct size; the block span may be longer (trailing sub-blocks)
    size_tier: str
    fields: list = field(default_factory=list)
    bits: list = field(default_factory=list)

    def __post_init__(self):
        self.by_name = {f.name: f for f in self.fields}
        self.bits_by_name = {b.name: b for b in self.bits}
        assert len(self.by_name) == len(self.fields), f"duplicate field name in {self.name}"
        end = 0
        for f in sorted(self.fields, key=lambda f: f.offset):
            assert f.offset >= end, f"{self.name}.{f.name} overlaps the previous field"
            end = f.offset + f.size
        assert end <= self.size, f"{self.name} fields run past its size"
        for b in self.bits:
            assert b.field in self.by_name, f"{self.name}: bits {b.name} on unknown field {b.field}"

    def gaps(self):
        """(start, end) byte ranges inside the struct not covered by a field."""
        out, pos = [], 0
        for f in sorted(self.fields, key=lambda f: f.offset):
            if f.offset > pos:
                out.append((pos, f.offset))
            pos = f.offset + f.size
        if pos < self.size:
            out.append((pos, self.size))
        return out


F = Field
B = Bits

# --- generator (record slot 0, and header unit generator) -- efl_import_plan.md 3.3 ----------

GENERATOR = Struct("EFL_GENERATOR", 0x1E0, "dx9", [
    F(0x00, "GroupFlag", "u32", "prior"),
    F(0x04, "MaterialFlag", "u32", "prior"),
    F(0x0B, "RandomNoNum", "u8", "dx9", "count for RandomNo selection (initGeneratorParam)"),
    F(0x10, "RandomNo", "u32[8]", "dx9", "indexed table; element size inferred"),
    F(0x30, "Pos", "vec3", "dx9", "moveUnitGenerator 0x96FF00 -> setQuatParentOfs"),
    F(0x3C, "ParentNo", "s32", "dx9", "joint index (setRequest 0x9DDF40)"),
    F(0x40, "Quat", "vec4", "dx9", "(x, y, z, w)"),
    F(0x50, "member_0x50", "vec3", "prior"),
    F(0x5C, "someJointIdx", "s32", "prior"),
    F(0x60, "member_0x60", "vec4", "prior"),
    F(0x70, "AxisFlags", "u32", "prior", "bitfield word"),
    F(0x74, "WaitFrame", "rangeu16", "dx9", "initGeneratorParam 0x96B1C0 -> Gen+0xCE"),
    F(0x78, "Scale", "rangef[3]", "dx9", "0x96B339 -> Gen mLscaleBase"),
    F(0x90, "Range", "rangef[3]", "dx9", "spawn-shape extents, uknGenBehaviorFunc2 0x998F5F"),
    F(0xA8, "SetNum", "rangeu16", "corpus", "probable: prior name shifted -4 like Scale/Range"),
    F(0xAC, "uknRangeU16_0xac", "rangeu16", "unknown", "corpus: base usually 1"),
    F(0xB0, "LoopNum", "rangeu16", "dx9", "uknGeneratorTimerFunc 0x9DE250"),
    F(0xB4, "SetFrame", "rangeu16", "dx9", "uknGenLoopFunc 0x9DE360"),
    F(0xB8, "LoopFrameDist", "f32", "dx9", "movss 0x9DE25C"),
    F(0xBC, "SetFrameDist", "f32", "dx9", "uknGenLoopFunc"),
    F(0xC0, "ParticleScale", "rangef", "dx9", "-> Gen.mParticleScaleBase"),
    F(0xC8, "RangeType", "u8", "dx9", "spawn-shape switch (sub_999640); SE name"),
    F(0xC9, "RangeDirType", "u8", "dx9"),
    F(0xCA, "RangeOptionFlags", "u8", "dx9"),
    F(0xCB, "uknRangeFlag", "u8", "dx9"),
    F(0xCC, "RangeStripType", "u8", "dx9", "SE name"),
    F(0xCD, "RangeStripFlag", "u8", "dx9", "SE name"),
    F(0xCE, "RangeStripPartsNo", "s16", "dx9", "SE name"),
    F(0xD0, "RangeStripPath", "str64", "dx9", ".efs, createGeneratorResources"),
    F(0x110, "UknRangeThing", "rangef[4]", "dx9", "[1..3] -> Gen+0x1D0..0x1D8"),
    F(0x130, "RangeDivideNum", "u32", "dx9", "sub_999640 modulus"),
    F(0x134, "member_0x134", "f32", "unknown"),
    F(0x138, "member_0x138", "u32", "unknown"),
    F(0x13C, "VibReqType", "u8", "dx9", "VIB_REQ_TYPE: 0 none, 1 default, 2 viewport pos, 3 viewport parent"),
    F(0x13D, "member_0x13d", "u8", "unknown"),
    F(0x13E, "VibReqArg0", "u8", "dx9"),
    F(0x13F, "VibReqArg1", "u8", "dx9"),
    F(0x140, "ExtVibrationPath", "str64", "dx9", ".vib"),
    F(0x180, "SoundRequestPath", "str64", "dx9", ".srq"),
    F(0x1C0, "VibReqNo", "u16", "dx9"),
    F(0x1C2, "VibOptionFlag", "u16", "dx9", "bit0 SYNCHRO_STOP"),
    F(0x1C4, "VibPriority", "u32", "dx9"),
    F(0x1C8, "SeReqNo", "u16", "dx9"),
    F(0x1CA, "SeOptionFlag", "u16", "dx9", "bit0 = stop SE on finish"),
    F(0x1CC, "KeyframeScaleParamOffset", "rel32", "dx9", "mStatus 0x10; replaces Scale eval", sub="kf:vec3"),
    F(0x1D0, "KeyframeParamOffset_1d0", "rel32", "dx9", "mStatus 0x20; 8-byte keys (corpus 106/106): SetNum?", sub="kf:u32"),
    F(0x1D4, "KeyframeParamOffset_1d4", "rel32", "dx9", "mStatus 0x40; vec3 keys (corpus 15/15)", sub="kf:vec3"),
    F(0x1D8, "KeyframeParamOffset_1d8", "rel32", "dx9", "mStatus 0x80; vec3 keys (corpus 150/150): Range?", sub="kf:vec3"),
    F(0x1DC, "KeyframeParamOffset_1dc", "rel32", "dx9", "mStatus 0x100; vec3 keys (corpus 39/39): Ofs?", sub="kf:vec3"),
], [
    B("Order", "AxisFlags", 0, 4, "prior"),
    B("AxisType", "AxisFlags", 4, 4, "prior"),
    B("RelationType", "AxisFlags", 8, 4, "prior"),
])

# --- particle param (slot 1) -- plan 3.4/3.5; chain = COMMON [+ DRAW [+ PRIM]] + tail ------------

PTCL_COMMON = [
    F(0x00, "TransMode", "u8", "se"),
    F(0x01, "EntryType", "u8", "se"),
    F(0x02, "CullingFlag", "u16", "dx9", "bit0 ON -> culling draw variant"),
    F(0x04, "ParticleOptionFlag", "u32", "dx9", "PARTICLE_OPTION_FLAG; 0x80000 EDGE_ALPHA_OFF"),
    F(0x08, "LightGroupFlag", "u32", "se"),
    F(0x0C, "zOfs", "s32", "se"),
    F(0x10, "FixOtDepth", "u16", "se"),
    F(0x12, "PrimMaterialFlags", "u16", "dx9", "nibbles -> calcPrimMaterial (initParticleBillboard 0x978110)"),
]
PTCL_COMMON_BITS = [
    B("PrimMaterialA", "PrimMaterialFlags", 0, 4, "dx9", "HIWORD(dword@0x10) & 0xF"),
    B("PrimMaterialB", "PrimMaterialFlags", 8, 4, "dx9", "HIBYTE(dword@0x10) & 0xF"),
]
PTCL_DRAW = [
    F(0x14, "uknDraw_0x14", "u32", "unknown", "missing from the IDB type"),
    F(0x18, "Intensity", "rangef", "dx9"),
    F(0x20, "Scale", "rangef", "dx9"),
    F(0x28, "ScaleAdd", "rangef", "dx9"),
    F(0x30, "KeyframeIntensityParamOffset", "rel32", "dx9", "initParticleBillboard 0x978145", sub="kf:f32"),
    F(0x34, "KeyframeScaleParamOffset", "rel32", "dx9", sub="kf:f32"),
    F(0x38, "member_0x38", "s32", "unknown"),
    F(0x3C, "member_0x3c", "s32", "unknown"),
    F(0x40, "ColorFlag", "u8", "se"),
    F(0x41, "DrawFlags_0x41", "u8", "dx9", "bit0 KeyframePatSpeedParamFlag (test dword@0x40 & 0x100)"),
    F(0x42, "KeyframeColorParamOffset", "rel16", "se", sub="kf:color"),
    F(0x44, "KeyframePatNoParamOffset", "rel16", "dx9", "initParticleBillboard 0x977E71; 12-byte keys (corpus)", sub="kf:f32"),
    F(0x46, "CullingParamOffset", "rel16", "dx9", "SE marks this padding", sub="culling"),
    F(0x48, "Color0", "color", "dx9"),
    F(0x4C, "Color1", "color", "dx9"),
]
PTCL_PRIM = [
    F(0x50, "AnimFlag", "u16", "dx9"),
    F(0x52, "SeqNoMin", "u8", "dx9", "initParticleBillboard 0x978090"),
    F(0x53, "SeqNoRange", "u8", "dx9"),
    F(0x54, "PatNoMin", "u16", "dx9"),
    F(0x56, "PatNoRange", "u16", "dx9"),
    F(0x58, "PatSpeed", "f32", "dx9"),
    F(0x5C, "PatNoMax", "f32", "prior"),
    F(0x60, "PatCenter", "point", "prior"),
    F(0x68, "TextureInvW", "f32", "prior"),
    F(0x6C, "TextureInvH", "f32", "prior"),
    F(0x70, "BaseMapPath", "str64", "dx9", "no extension; effect\\tex\\..."),
    F(0xB0, "NormalMapPath", "str64", "dx9"),
    F(0xF0, "MaskMapPath", "str64", "dx9"),
    F(0x130, "AnimPath", "str64", "dx9", ".ean"),
]

PTCL_TAILS = {
    0: ("Billboard", 0x1A0, "dx9", [
        F(0x170, "Angle", "rangef", "prior"),
        F(0x178, "AngleAdd", "rangef", "prior"),
        F(0x180, "AspectRatio", "rangef", "prior"),
        F(0x188, "AspectRatioAdd", "rangef", "prior"),
        F(0x190, "KeyframeAngleParamOffset", "rel32", "prior", "width unverified", sub="kf:f32"),
    ], []),
    1: ("Polyline", 0x1B0, "corpus", [
        F(0x170, "LineFlags", "u32", "prior", "bitfield word"),
        F(0x178, "PlaceColor", "color[2]", "prior"),
        F(0x180, "HeadSize", "rangef", "prior"),
        F(0x188, "HeadSizeAdd", "rangef", "prior"),
        F(0x190, "PlaceSize", "rangef", "prior"),
        F(0x198, "PlaceSizeAdd", "rangef", "prior"),
        F(0x1A4, "KeyframeHeadSizeParamOffset", "rel32", "prior", sub="kf:f32"),
        F(0x1A8, "KeyframePlaceSizeParamOffset", "rel32", "prior", sub="kf:f32"),
    ], [
        B("LineType", "LineFlags", 0, 8, "prior"),
        B("LineOfsNum", "LineFlags", 8, 8, "prior"),
        B("ColorPlaceType", "LineFlags", 16, 4, "prior"),
        B("ColorPlaceInpType", "LineFlags", 20, 4, "prior"),
        B("ColorPlaceNo", "LineFlags", 24, 8, "prior"),
    ]),
    2: ("Polygon", 0x1E0, "dx9", [
        F(0x170, "Rot", "rangef[3]", "prior"),
        F(0x188, "RotAdd", "rangef[3]", "prior"),
        F(0x1A0, "PolygonFlags", "u32", "prior", "bitfield word"),
        F(0x1A4, "KeyframeRotParamOffset", "rel32", "prior", sub="kf:vec3"),
        F(0x1A8, "uknKeyframeOffset", "rel32", "prior", sub="kf"),
        F(0x1B0, "Width", "rangef", "prior"),
        F(0x1B8, "Height", "rangef", "prior"),
        F(0x1C0, "WidthAdd", "rangef", "prior"),
        F(0x1C8, "HeightAdd", "rangef", "prior"),
        F(0x1D0, "DistortRate", "f32[4]", "prior"),
    ], [
        B("RotAxisType", "PolygonFlags", 0, 4, "prior"),
        B("RotOrder", "PolygonFlags", 4, 4, "prior"),
        B("DirAxisType", "PolygonFlags", 8, 4, "prior"),
        B("PolygonFixType", "PolygonFlags", 16, 4, "prior"),
        B("PolygonBillBoardType", "PolygonFlags", 20, 4, "prior"),
        B("CullingRotAxisType", "PolygonFlags", 24, 4, "prior"),
        B("CullingRotOrder", "PolygonFlags", 28, 4, "prior"),
    ]),
    6: ("PrimModel", 0x25C, "dx9", [
        F(0x170, "PrimFlags", "u32", "dx9", "nibble word"),
        F(0x174, "HoriColorPlaceNo", "u16", "dx9"),
        F(0x176, "PrimFlags2", "u16", "se", "RotResetFlag / ModelBillboardOrder / LookAt; no DX9 reader"),
        F(0x178, "PlaceColor1", "color", "dx9"),
        F(0x17C, "PlaceColor2", "color", "dx9"),
        F(0x180, "RotDivNum", "u16", "dx9"),
        F(0x182, "RotTexDivNum", "u16", "dx9"),
        F(0x184, "RotDrawStart", "u16", "dx9"),
        F(0x186, "RotDrawEnd", "u16", "dx9"),
        F(0x188, "HoriDivNum", "u16", "dx9"),
        F(0x18A, "HoriTexDivNum", "u16", "dx9"),
        F(0x18C, "HoriDrawStart", "u16", "dx9"),
        F(0x18E, "HoriDrawEnd", "u16", "dx9"),
        F(0x190, "ModelScale", "rangef[3]", "dx9"),
        F(0x1A8, "ModelScaleAdd", "rangef[3]", "dx9"),
        F(0x1C0, "Rot", "rangef[3]", "dx9"),
        F(0x1D8, "RotAdd", "rangef[3]", "dx9"),
        F(0x1F0, "Radius", "rangef[2]", "dx9", "shape.x/.y"),
        F(0x200, "RadiusAdd", "rangef[2]", "dx9"),
        F(0x210, "Height", "rangef[2]", "dx9", "shape.z/.w"),
        F(0x220, "HeightAdd", "rangef[2]", "dx9"),
        F(0x230, "NormAttenuateAngleStart", "f32", "dx9"),
        F(0x234, "NormAttenuateAngleEnd", "f32", "dx9"),
        F(0x238, "NormAttenuateCurve", "easecurve", "se"),
        F(0x240, "KeyframePlaceColorParamOffset", "rel32", "dx9", sub="kf:color"),
        F(0x244, "KeyframeRotParamOffset", "rel32", "dx9", sub="kf:vec3"),
        F(0x248, "KeyframeModelScaleParamOffset", "rel32", "dx9", sub="kf:vec3"),
        F(0x24C, "KeyframeRadius0ParamOffset", "rel32", "dx9", sub="kf:f32"),
        F(0x250, "KeyframeRadius1ParamOffset", "rel32", "dx9", sub="kf:f32"),
        F(0x254, "KeyframeHeight0ParamOffset", "rel32", "dx9", sub="kf:f32"),
        F(0x258, "KeyframeHeight1ParamOffset", "rel32", "dx9", sub="kf:f32"),
    ], [
        B("PrimModelType", "PrimFlags", 0, 4, "dx9", "0 Ring, 1 TexRing, 2 Sphere, 3 TexSphere, 4 Grid, 5 TexGrid"),
        B("Axis", "PrimFlags", 4, 4, "dx9"),
        B("RotOrder", "PrimFlags", 8, 4, "dx9"),
        B("DirAxisType", "PrimFlags", 12, 4, "dx9"),
        B("ColorPlaceType", "PrimFlags", 16, 4, "dx9"),
        B("ModelBillboardType", "PrimFlags", 24, 4, "dx9"),
        B("NormAttenuateFlag", "PrimFlags", 28, 4, "dx9", "bit 29 = one-sided"),
    ]),
    5: ("Model", 0x90, "dx9", [
        F(0x50, "ModelPath", "str64", "dx9", "resource loader; no PRIM_COMMON"),
    ], []),
    7: ("LensFlare", 0xE0, "dx9", [
        F(0xA0, "LensFlarePath", "str64", "dx9", "resource loader"),
    ], []),
    8: ("MassBillboard", 0xA0, "dx9", [
        F(0x60, "TexturePath", "str64", "dx9", "resource loader; no PRIM_COMMON"),
    ], []),
}
# type -> (name, chain); chain says which shared parts the block starts with
PTCL_TYPES = {
    0: ("Billboard", "prim"), 1: ("Polyline", "prim"), 2: ("Polygon", "prim"), 3: ("Texline", "prim"),
    4: ("Line", "draw"), 5: ("Model", "draw"), 6: ("PrimModel", "prim"), 7: ("LensFlare", "draw"),
    8: ("MassBillboard", "draw"), 9: ("Filter", "common"), 10: ("Light", "common"), 11: ("Hit", "common"),
    12: ("PolygonStrip", "prim"), 13: ("Texline(alt)", "prim"), 14: ("Line(alt)", "draw"),
    15: ("PolygonStrip(alt)", "prim"), 16: ("LiteBillboard", "prim"), 17: ("SizeBillboard", "prim"),
}
# minimum sizes seen in the corpus for types without a typed tail
_PTCL_OBSERVED_SIZE = {3: 0x1D0, 4: 0x60, 9: 0x80, 10: 0x80, 11: 0x50, 12: 0x210, 15: 0x1D0}
_CHAIN_SIZE = {"common": 0x14, "draw": 0x50, "prim": 0x170}


def _particle_struct(ptype):
    name, chain = PTCL_TYPES.get(ptype, (f"Unknown{ptype}", "common"))
    fields = list(PTCL_COMMON)
    bits = list(PTCL_COMMON_BITS)
    if chain in ("draw", "prim"):
        fields += PTCL_DRAW
    if chain == "prim":
        fields += PTCL_PRIM
    size, tier = _CHAIN_SIZE[chain], "dx9"
    if ptype in PTCL_TAILS:
        _, size, tier, tail, tail_bits = PTCL_TAILS[ptype]
        fields += tail
        bits += tail_bits
    elif ptype in _PTCL_OBSERVED_SIZE:
        size, tier = _PTCL_OBSERVED_SIZE[ptype], "corpus"
    return Struct(f"EFL_PARTICLE_{name}", size, tier, fields, bits)


# --- life param (slot 2): always 0x10 in the corpus; names from the IDB (EFL_LIFE_FRAME) -----------

LIFE = Struct("EFL_LIFE_FRAME", 0x10, "corpus", [
    F(0x00, "AppearFrame", "rangeu16", "prior"),
    F(0x04, "KeepFrame", "rangeu16", "prior"),
    F(0x08, "VanishFrame", "rangeu16", "prior"),
    F(0x0C, "KeepFlags", "u32", "prior", "bitfield word"),
], [
    B("KeepHoldFlag", "KeepFlags", 0, 1, "prior"),
    B("KeyframeKeepFrameParamOffset", "KeepFlags", 1, 15, "prior"),
    B("KeepHoldFrame", "KeepFlags", 16, 16, "prior"),
])
LIFE_TYPES = {1: "Frame", 2: "Type2"}

# --- move param (slot 3) -- Vibed/RE/particle_move_param.md "On-disk move param" -------------------

MOVE_COMMON = [
    F(0x00, "MoveOptionFlag", "u32", "dx9", "MOVE_OPTION_FLAG: 2 GRAVITY_NO_SCALE, 4 HIGH_ACCURACY, 8 ALWAYS_CORRECT"),
    F(0x04, "ForceType", "u8", "dx9", "FORCE_TYPE (& 0xF)"),
    F(0x05, "RotAxisOrder", "u8", "dx9", "nibbles: RotAxisType, RotOrder"),
    F(0x06, "CollParamOffset", "rel16", "dx9", "get_coll_param 0x960650", sub="collision"),
    F(0x08, "ForceRate", "rangef", "dx9"),
]
MOVE_COMMON_BITS = [
    B("RotAxisType", "RotAxisOrder", 0, 4, "se"),
    B("RotOrder", "RotAxisOrder", 4, 4, "se"),
]
MOVE_BASE = [
    F(0x10, "Rot", "rangef[3]", "dx9"),
    F(0x28, "Speed", "rangef", "dx9"),
    F(0x30, "Gravity", "rangef", "dx9"),
    F(0x38, "KeyframeRotParamOffset", "rel16", "dx9", sub="kf:vec3"),
    F(0x3A, "KeyframeSpeedParamOffset", "rel16", "dx9", sub="kf:f32"),
    F(0x3C, "KeyframeFallSpeedParamOffset", "rel16", "dx9", sub="kf:f32"),
    F(0x3E, "member_0x3e", "u16", "unknown"),
]
MOVE_PATH = [
    F(0x40, "ReleaseType", "u8", "dx9", "PATH_RELEASE_TYPE: 1 WORK_SPEED, 2 PATH_SPEED"),
    F(0x41, "PathOptionFlag", "u8", "dx9", "1 RELEASE_PATH_END, 2 KILL_PATH_END, 4 KEEP_HOLD_OFF_PATH_END"),
    F(0x42, "KeyframeReleaseFrameParamOffset", "rel16", "dx9", sub="kf:u32"),
    F(0x44, "ReleaseFrame", "rangeu16", "dx9"),
    F(0x48, "Acceleration", "rangef", "dx9"),
    F(0x50, "Path3DScaleX", "rangef", "se", "no DX9 reader"),
    F(0x58, "Path3DScaleY", "rangef", "se", "no DX9 reader"),
    F(0x60, "Path3DScaleZ", "rangef", "se", "no DX9 reader"),
    F(0x68, "PathLengthScale", "rangef", "se", "no DX9 reader"),
]
_CHAIN = 0x80   # EFL_PARAM_CHAIN inside EFL_MOVE_PATH_CHAIN
MOVE_CHAIN_PARAM = [
    F(_CHAIN + 0x00, "ChainOptionFlag", "u16", "dx9"),
    F(_CHAIN + 0x02, "PreUpdateLoopNum", "u16", "dx9"),
    F(_CHAIN + 0x04, "ChainRotAxis", "u8", "dx9", "nibbles: RotAxisType, RotOrder"),
    F(_CHAIN + 0x05, "ChainBlendRotAxis", "u8", "dx9", "nibbles: BlendRotAxisType, BlendRotOrder"),
    F(_CHAIN + 0x06, "HoldPosNum", "u8", "dx9"),
    F(_CHAIN + 0x07, "ParamChain0807", "u8", "se"),
    F(_CHAIN + 0x08, "Length", "rangef", "dx9"),
    F(_CHAIN + 0x10, "LengthAdd", "rangef", "dx9"),
    F(_CHAIN + 0x18, "BlendRate", "rangef", "dx9"),
    F(_CHAIN + 0x20, "ChainAcceleration", "rangef", "dx9"),
    F(_CHAIN + 0x28, "FrameInf", "rangef", "dx9"),
    F(_CHAIN + 0x30, "VertexInf", "rangef", "dx9"),
    F(_CHAIN + 0x38, "ChainRot", "rangef[3]", "dx9"),
    F(_CHAIN + 0x50, "BlendRot", "rangef[3]", "dx9"),
    F(_CHAIN + 0x68, "ChainForceRate", "rangef", "dx9"),
    F(_CHAIN + 0x70, "ForceVertexAttenuateRate", "rangef", "dx9"),
    F(_CHAIN + 0x78, "StretchScale", "f32", "dx9"),
    F(_CHAIN + 0x7C, "ShrinkCoef", "f32", "dx9"),
    F(_CHAIN + 0x80, "KeyframeLengthParamOffset", "rel32", "dx9", "dword in DX9 (u16 in SE); relative to the move block, not the chain param", sub="kf:f32"),
    F(_CHAIN + 0x84, "KeyframeChainRotParamOffset", "rel32", "dx9", sub="kf:vec3"),
    F(_CHAIN + 0x88, "KeyframeBlendRotParamOffset", "rel32", "dx9", sub="kf:vec3"),
    F(_CHAIN + 0x8C, "KeyframeBlendRateParamOffset", "rel32", "dx9", sub="kf:f32"),
]
MOVE_TAILS = {
    0: ("None", 0x10, [], "common"),
    1: ("Add", 0x48, [F(0x40, "Acceleration", "rangef", "dx9", "speed += accel")], "base"),
    2: ("Mul", 0x48, [F(0x40, "SpeedCoef", "rangef", "dx9", "speed *= coef")], "base"),
    3: ("PathStrip", 0xC0, [
        F(0x70, "Distance", "rangef", "dx9"),
        F(0x78, "PathStripType", "u8", "dx9", "STRIP_TYPE: 1 linear, 2 hermite, 3 spline"),
        F(0x79, "PathStripFlag", "u8", "dx9", "STRIP_FLAG: 0x08 PATH_LOOP, 0x40 SKINING"),
        F(0x7A, "PathStripPartsNo", "u16", "dx9"),
        F(0x7C, "PathCurveDivideNum", "u32", "dx9"),
        F(0x80, "PathStripPath", "str64", "dx9", ".efs"),
    ], "path"),
    4: ("PathChain", 0x110, [
        F(0x70, "Distance", "rangef", "dx9"),
        F(0x78, "ChainPosNum", "u8", "dx9"),
        F(0x79, "MPathChain0879", "u8", "se"),
        F(0x7A, "MPathChain087a", "u8", "se"),
        F(0x7B, "MPathChain087b", "u8", "se"),
        F(0x7C, "MPathChain327c", "u32", "se"),
    ] + MOVE_CHAIN_PARAM, "path"),
    5: ("PathKeyframe", 0x74, [
        F(0x70, "KeyframeOfsParamOffset", "rel32", "dx9", "position offset", sub="kf:vec3"),
    ], "path"),
    6: ("PathLine", 0x7C, [
        F(0x70, "Distance", "rangef", "dx9"),
        F(0x78, "PathLength", "f32", "dx9", "distance clamp"),
    ], "path"),
}


def _move_struct(mtype):
    if mtype not in MOVE_TAILS:
        return Struct(f"EFL_MOVE_Unknown{mtype}", 0x10, "unknown", list(MOVE_COMMON), list(MOVE_COMMON_BITS))
    name, size, tail, chain = MOVE_TAILS[mtype]
    fields = list(MOVE_COMMON)
    if chain in ("base", "path"):
        fields += MOVE_BASE
    if chain == "path":
        fields += MOVE_PATH
    return Struct(f"EFL_MOVE_{name}", size, "dx9", fields + tail, list(MOVE_COMMON_BITS))


# --- sub-blocks ----------------------------------------------------------------------------------

COLLISION = Struct("EFL_PARAM_COLLISION", 0xB0, "dx9", [
    F(0x00, "CollType", "u8", "dx9", "COLL_TYPE: 0 KILL, 1 MOVE_STOP, 2 COLL_STOP"),
    F(0x01, "CollFlag", "u8", "dx9", "bit0 FIN_ANIM_STOP"),
    F(0x02, "CollCancelFrame", "u8", "dx9"),
    F(0x03, "member_0x3", "u8", "unknown", "no DX9 reader"),
    F(0x04, "CollRadiusAdd", "f32", "dx9", "per-frame growth, clamped at CollRadius s+r"),
    F(0x08, "CollRadius", "rangef", "dx9"),
    F(0x10, "BounceEffectParam", "f32[2]", "dx9"),
    F(0x18, "FinishEffectParam", "f32[2]", "dx9"),
    F(0x20, "BounceEffectMode", "u8", "dx9", "nibble pair"),
    F(0x21, "FinishEffectMode", "u8", "dx9", "nibble pair"),
    F(0x22, "BounceCallbackFlag", "u8", "dx9"),
    F(0x23, "FinishCallbackFlag", "u8", "dx9"),
    F(0x24, "BounceNumBase", "u8", "dx9"),
    F(0x25, "member_0x25", "u8", "unknown", "no DX9 reader"),
    F(0x26, "BounceNumRange", "u16", "dx9"),
    F(0x28, "BounceRate", "rangef", "dx9"),
    F(0x30, "BounceEffectPath", "str64", "dx9", ".efl"),
    F(0x70, "FinishEffectPath", "str64", "dx9", ".efl"),
])

CULLING = Struct("EFL_PARAM_CULLING", 0x30, "se", [
    F(0x00, "CullingFlags", "u32", "dx9", "DX9 reads >>8 and >>12 as calcDir modes"),
    F(0x04, "CullingRot", "vec3", "se"),
    F(0x10, "CullingDistNearStart", "f32", "se"),
    F(0x14, "CullingDistNearEnd", "f32", "se"),
    F(0x18, "CullingDistFarStart", "f32", "se"),
    F(0x1C, "CullingDistFarEnd", "f32", "se"),
    F(0x20, "CullingAngleStart", "f32", "se"),
    F(0x24, "CullingAngleEnd", "f32", "se"),
    F(0x28, "CullingRate", "f32", "se"),
    F(0x2C, "OcclusionRadius", "f32", "se"),
], [
    B("CullingFlag", "CullingFlags", 0, 8, "se"),
    B("CullingRotAxisType", "CullingFlags", 8, 4, "se"),
    B("CullingRotOrder", "CullingFlags", 12, 4, "se"),
    B("CullingOptionFlag", "CullingFlags", 16, 16, "se"),
])

SUB_STRUCTS = {"collision": COLLISION, "culling": CULLING}

# ---------------------------------------------------------------------------------------------

_PTCL_CACHE, _MOVE_CACHE = {}, {}


def struct_for(kind, btype):
    """Struct describing a block of kind 'gen' / 'ptcl' / 'life' / 'move' with record type byte btype."""
    if kind == "gen":
        return GENERATOR
    if kind == "life":
        return LIFE
    if kind == "ptcl":
        if btype not in _PTCL_CACHE:
            _PTCL_CACHE[btype] = _particle_struct(btype)
        return _PTCL_CACHE[btype]
    if kind == "move":
        if btype not in _MOVE_CACHE:
            _MOVE_CACHE[btype] = _move_struct(btype)
        return _MOVE_CACHE[btype]
    raise KeyError(kind)


def type_name(kind, btype):
    if kind == "ptcl":
        return PTCL_TYPES.get(btype, (f"Unknown{btype}",))[0]
    if kind == "move":
        return MOVE_TAILS[btype][0] if btype in MOVE_TAILS else f"Unknown{btype}"
    if kind == "life":
        return LIFE_TYPES.get(btype, f"Unknown{btype}")
    return f"Type{btype}"


def all_structs():
    """Every distinct struct, for schema dumps and coverage reports."""
    out = [GENERATOR, LIFE, COLLISION, CULLING]
    out += [struct_for("ptcl", t) for t in PTCL_TYPES]
    out += [struct_for("move", t) for t in MOVE_TAILS]
    return out
