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

The DX9 IDB's EFL_GENERATOR and EFL_PARTICLE_* types were retyped to these offsets on 2026-10-05
(confirmed in initParticleBillboard 0x977E60 and by the corpus round-trip).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field, replace

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
    "color": "<4B",      # MtColor stored as D3DCOLOR: bytes b, g, r, a (use efl.schema.bgra_to_rgba)
    "point": "<2i",      # MtPoint
    "easecurve": "<2f",  # MtEaseCurve
}
STR_SIZE = 64


def bgra_to_rgba(color):
    """MtColor bytes (b, g, r, a) -> (r, g, b, a)."""
    return (color[2], color[1], color[0], color[3])


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
    sub: str | None = None   # bits holding a self-relative offset (like Field.sub; the life KeepFrame keyframe)
    rel_base: int = 0


@dataclass
class Struct:
    name: str
    size: int            # struct size; the block span may be longer (trailing sub-blocks)
    size_tier: str
    fields: list = field(default_factory=list)
    bits: list = field(default_factory=list)
    base_size: int = None   # extended structs: where the extension starts (= the plain struct's size)

    def __post_init__(self):
        if self.base_size is None:
            self.base_size = self.size
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

    def offset_fields(self):
        """Fields and bit-fields holding a self-relative offset (sub=), in declaration order."""
        return [f for f in self.fields if f.sub] + [b for b in self.bits if b.sub]

    def offset_field(self, name):
        f = self.by_name.get(name) or self.bits_by_name.get(name)
        return f if f is not None and f.sub else None

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
    F(0x00, "GroupFlag", "u32", "dx9", "record built only if & caller's group mask != 0 (matchGeneratorFilter 0x9DD560)"),
    F(0x04, "MaterialFlag", "u32", "dx9", "& caller's ground-surface bit (cUtil::getEfctMtrlFlg 0x45F780) != 0"),
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
    F(0xA8, "SetNum", "rangeu16", "dx9", "particles per spawning frame; uknGenBehaviorFunc1 0x9DDDC7"),
    F(0xAC, "BurstNum", "rangeu16", "dx9", "bursts before the generator finishes, 0 = forever; 0x9DDD36 -> mLoopCtr"),
    F(0xB0, "LoopNum", "rangeu16", "dx9", "frames each burst spawns for (1 in 99%); uknGeneratorTimerFunc 0x9DE250"),
    F(0xB4, "SetFrame", "rangeu16", "dx9", "pause frames between bursts; uknGenLoopFunc 0x9DE360"),
    F(0xB8, "LoopFrameDist", "f32", "dx9", "movss 0x9DE25C"),
    F(0xBC, "SetFrameDist", "f32", "dx9", "uknGenLoopFunc"),
    F(0xC0, "ParticleScale", "rangef", "dx9", "-> Gen.mParticleScaleBase"),
    F(0xC8, "RangeType", "u8", "dx9", "spawn shape (sub_999040): 0 point, 1-3 box, 4-6 cylinder X/Y/Z, 7 sphere, 8 hemisphere"),
    F(0xC9, "RangeDirType", "u8", "dx9", "RANGE_DIR_TYPE: 0 none, 1 diffuse, 2 converge, 3 unit"),
    F(0xCA, "RangeOptionFlags", "u8", "dx9",
      "RANGE_OPTION_FLAG; DX9 reads 1 EACH_FRAME only: initGeneratorParam 0x96AFA9 -> Generator mFlags 0x20000 -> "
      "openParticle 0x9DF333 numbers particles by spawning frame (mSetFrameTotal) instead of by particle "
      "(mSetParticleTotal); that serial picks the RangeDivideNum slot and the ORDER / REVERSE strip index"),
    F(0xCB, "RangeDisperseType", "u8", "dx9",
      "SE RANGE_DISPERSE_TYPE 0 NONE, 1 OLD, 2 SUB: uknGenBehaviorFunc2 0x998F00 shifts each spawn by (previous / "
      "sub-step generator position - current) x its place in the frame's batch (i / count); 2 also sets mFlags 0x8000"),
    F(0xCC, "RangeStripType", "u8", "dx9",
      "sampler (sub_963220): 0 point, 1 linear segment, 2 3-point curve, 3 4-point cubic (sub_ADC1E0), 4 triangle"),
    F(0xCD, "RangeStripFlag", "u8", "dx9",
      "rEffectStrip::STRIP_FLAG (sub_99B270 / 99A8A0 / 99AFD0): 1 ORDER, 2 REVERSE, 8 PATH_LOOP, 0x10 CENTER_FIX "
      "(midpoint / centroid), 0x20 ALL_PARTS (random part; with RangeDivideNum the slots run across all parts), "
      "0x40 SKINING (points follow the owner model's skinning); 4 NORM_OFF no reader found"),
    F(0xCE, "RangeStripPartsNo", "s16", "dx9", "the part sampled unless ALL_PARTS"),
    F(0xD0, "RangeStripPath", "str64", "dx9", ".efs, createGeneratorResources"),
    F(0x110, "UknRangeThing", "rangef[4]", "dx9", "[0] = range-dir blend factor, [1..3] = spawn-shape scale (sub_999040)"),
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
    F(0x1D0, "KeyframeSetNumParamOffset", "rel32", "dx9", "mStatus 0x20; replaces SetNum (uknGenBehaviorFunc1 0x9DDD7C)", sub="kf:u32"),
    F(0x1D4, "KeyframeRangeParamOffset", "rel32", "dx9", "mStatus 0x40: replaces Range s and r at spawn (sub_999640), generator timer", sub="kf:vec3"),
    F(0x1D8, "KeyframePosParamOffset", "rel32", "dx9", "mStatus 0x80; position, generator timer (updateWorldMatrix 0x96BE10)", sub="kf:vec3"),
    F(0x1DC, "KeyframeRotParamOffset", "rel32", "dx9", "mStatus 0x100; Euler rotation in AxisFlags order (updateWorldMatrix 0x96BE10)", sub="kf:vec3"),
], [
    B("Order", "AxisFlags", 0, 4, "prior"),
    B("AxisType", "AxisFlags", 4, 4, "prior"),
    B("RelationType", "AxisFlags", 8, 4, "dx9", "Generator+0x110 (initChildGenerator 0x96BC3F) -> setQuatParentOfs "
      "0x9687B0: 2 = parent position (Pos turned by the joint), own Quat in world axes; 3 = ignore the parent; "
      "else full parenting. Files: 0 (32,074), 2 (2,609), 1 (20)"),
])

# --- particle param (slot 1) -- plan 3.4/3.5; chain = COMMON [+ DRAW [+ PRIM]] + tail ------------

PTCL_COMMON = [
    F(0x00, "TransMode", "u8", "dx9", "cTrans::MODE pass mask as on every uModel (not a blend mode): 0x1 WORLD, 0x2 REFLECTION, "
                                       "0x4 SHADOW_RECV, 0x8 SHADOW_CAST, 0x10 ENV, 0x20 MOTIONBLUR; corpus: 1, 0, once 3"),
    F(0x01, "EntryType", "u8", "se"),
    F(0x02, "CullingFlag", "u8", "dx9",
      "rEffectList::CULLING_FLAG: 0x1 ON (culling draw variant, mTransType 0x11..), 0x2 OCCLUSION (prim ATTR_OCCLUSION, "
      "checked before refraction; initGeneratorParam 0x96B603), 0x4 PARTICLE, 0x80 ANGLE (direction computed once per "
      "generator unless PARTICLE, 0x96B6A2)"),
    F(0x03, "VolumeBlendRate", "u8", "dx9",
      "SE BlendState; != 0 -> prim ATTR_VOLUME (PRIM_EX_VOLUME), ATTR_DEPTHVOLUME with option 0x800, ATTR_PARALLAX "
      "with option 0x400, unless refraction / occlusion (initGeneratorParam 0x96B61F); the value goes into every "
      "vertex (sub_961250 and the other builders). Corpus 0-100, non-zero on 26,626 of 34,703 particles"),
    F(0x04, "ParticleOptionFlag", "u32", "dx9",
      "rEffectList::PARTICLE_OPTION_FLAG, DX9 readers: 0x1 OT_DEPTH sort per particle, 0x2 OT_FIX = FixOtDepth, 0x100 "
      "OT_UNIT sort at the unit, 0x40 NO_CLIP keep negative depths, sign bit = OtDepthBias toward the camera "
      "(setPrimEnv 0x99DB60); 0x4 ATTR_DEPTHBLEND, 0x10 ATTR_REFRACT (SE ALPHA_BLUR), 0x20 ATTR_NOREDUCTION, 0x80 "
      "ATTR_NOZTEST, 0x1000 ATTR_NOFOG, 0xC00000 ATTR_CULLING, 0x400 / 0x800 PARALLAX / DEPTH_VOLUME with "
      "VolumeBlendRate, 0x200 WMAT_SCALE, 0x40000 MDLSCL_AFTER (scale after rotation), 0x100000 ROT_LOCAL (no generator "
      "rotation: world axes), 0x200000 ROT_INIT (+ ROT_LOCAL; Rot += Euler of the spawn-time generator rotation) (initGeneratorParam 0x96B560, calcParticleMatrix "
      "0x98A77F / 0x98B3FE), 0x10000 PAT_CENTER, 0x20000 EXT_LINE_POS (line renderers), 0x80000 = border vertices get alpha 0 "
      "(buildPrimModelRing 0x9CDB1B; SE calls it EDGE_ALPHA_OFF but in DX9 set means fade); "
      "0x8 INV_VOLUME has no DX9 reader"),
    F(0x08, "LightGroupFlag", "u32", "dx9",
      "light-group mask, the same one models use: Light particles hand it to their light (updateParticleLight "
      "0x99C1BB; 0xFFFFFFFF on 153 of 177), other particles are lit when != 0 (prim ATTR_LIGHTING, "
      "initGeneratorParam 0x96B5E1; 337 Model, 21 Polygon)"),
    F(0x0C, "zOfs", "s32", "se"),
    F(0x10, "FixOtDepth", "u16", "dx9", "draw-order key with ParticleOptionFlag 0x2 (setPrimEnv 0x99DBEE)"),
    F(0x12, "PrimMaterialFlags", "u16", "dx9", "blend nibbles -> calcPrimMaterial 0x9DEBF0 -> render blend state"),
]
PTCL_COMMON_BITS = [
    B("BlendSrc", "PrimMaterialFlags", 0, 4, "dx9", "D3DBLEND - 1 (4 = SRCALPHA); sRender::dispatchCommands 0x8F48A6"),
    B("BlendDst", "PrimMaterialFlags", 4, 4, "dx9", "D3DBLEND - 1 (5 = INVSRCALPHA alpha blend, 1 = ONE additive)"),
    B("BlendOp", "PrimMaterialFlags", 8, 4, "dx9", "D3DBLENDOP - 1 (0 = ADD, 2 = REVSUBTRACT)"),
    B("PassBits", "PrimMaterialFlags", 12, 4, "dx9", "Generator+24 bits 8-11 (initGeneratorParam), ANDed with the view's "
                                                     "cTrans CONTEXT.mMode bits 8-11 by isGeneratorVisible 0x53D460; not a cTrans::PASS"),
]
PTCL_DRAW = [
    F(0x14, "OtDepthBias", "f32", "dx9", "sort position moved this far toward the camera when ParticleOptionFlag's "
                                           "sign bit is set (setPrimEnv 0x99DC38); 0 in every DX9 file"),
    F(0x18, "Intensity", "rangef", "dx9"),
    F(0x20, "Scale", "rangef", "dx9"),
    F(0x28, "ScaleAdd", "rangef", "dx9"),
    F(0x30, "KeyframeIntensityParamOffset", "rel32", "dx9", "initParticleBillboard 0x978145", sub="kf:f32"),
    F(0x34, "KeyframeScaleParamOffset", "rel32", "dx9", sub="kf:f32"),
    F(0x38, "member_0x38", "s32", "unknown"),
    F(0x3C, "member_0x3c", "s32", "unknown"),
    F(0x40, "ColorFlag", "u8", "dx9", "nEffect::COLOR_FLAG: 1/2/4/8 mix R/G/B/A toward Color1 by a random t, 0x10 re-roll "
                                       "t per channel (calcSrcColor 0x9801B0); 0x20 CHOICE not in DX9"),
    F(0x41, "DrawFlags_0x41", "u8", "dx9", "bit0 KeyframePatSpeedParamFlag (test dword@0x40 & 0x100)"),
    F(0x42, "KeyframeColorParamOffset", "rel16", "se", sub="kf:color"),
    F(0x44, "KeyframePatNoParamOffset", "rel16", "dx9", "initParticleBillboard 0x977E71; 12-byte keys (corpus)", sub="kf:f32"),
    F(0x46, "CullingParamOffset", "rel16", "dx9", "SE marks this padding", sub="culling"),
    F(0x48, "Color0", "color", "dx9"),
    F(0x4C, "Color1", "color", "dx9"),
]
PTCL_LIGHT_HEAD = [
    F(0x40, "LightAttribute", "u32", "dx9",
      "rEffectList::LIGHT_ATTR: 0x2 SH, 0x8 PERPIXEL (dropped when the light can't), 0x10 SIMPLE (every DX9 file); "
      "updateParticleLight 0x99C19E writes low byte | 0x40 into the light"),
    F(0x44, "ColorFlag", "u8", "dx9"),
    F(0x45, "LightTypeFlags", "u8", "dx9"),
    F(0x46, "KeyframeColorParamOffset", "rel16", "dx9", sub="kf:color"),
    F(0x48, "Color0", "color", "dx9"),
    F(0x4C, "Color1", "color", "dx9"),
]
PTCL_PRIM = [
    F(0x50, "AnimFlag", "u16", "dx9",
      "rEffectAnim::ANIM_FLAG: 1 MOVE, 2 LOOP, 4 REVERSE, 8 FINISH (sub_961DB0), 0x100 / 0x200 flip U / V, 0x1000 "
      "rotate (sub_9632F0), 0x400 / 0x800 flip U / V at random per particle (getAnimFlag 0x980140); REVERSE_RAND "
      "0x10 not in DX9, 0x8000 KEYFRAME is runtime-only"),
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

# Polyline / Line header (file 0x170 / 0x50): LINE_TYPE 0 FOLLOW, 1 FIX, 2 FIX_END, 3 CHAIN, 4 LENGTH, 5 CLOTH.
# A per-LineType extension follows the block's struct (LENGTH 0x50 bytes, FIX 0x70 + 16 per point); efl/sim.py
# reads it from the raw bytes.
LINE_BITS = [
    B("LineType", "LineFlags", 0, 8, "dx9"),
    B("LineOfsNum", "LineFlags", 8, 8, "dx9", "points per particle"),
    B("ColorPlaceType", "LineFlags", 16, 4, "dx9", "colour gradient: as SizePlaceType"),
    B("ColorPlaceInpType", "LineFlags", 20, 4, "dx9"),
    B("ColorPlaceNo", "LineFlags", 24, 8, "dx9"),
]
LINE_TYPES = {0: "FOLLOW", 1: "FIX", 2: "FIX_END", 3: "CHAIN", 4: "LENGTH", 5: "CLOTH"}

PTCL_TAILS = {
    0: ("Billboard", 0x1A0, "dx9", [
        F(0x170, "Angle", "rangef", "prior"),
        F(0x178, "AngleAdd", "rangef", "prior"),
        F(0x180, "AspectRatio", "rangef", "prior"),
        F(0x188, "AspectRatioAdd", "rangef", "prior"),
        F(0x190, "KeyframeAngleParamOffset", "rel32", "dx9", "initParticleBillboard 0x977E60 (calcKeyframeF32)",
          sub="kf:f32"),
    ], []),
    1: ("Polyline", 0x1B0, "corpus", [
        F(0x170, "LineFlags", "u32", "dx9", "initParticlePolyline 0x9786D0 / move sub_98E3E0"),
        F(0x174, "SizePlaceFlags", "u32", "dx9"),
        F(0x178, "PlaceColor", "color[2]", "dx9", "random pair, like Color0/1"),
        F(0x180, "HeadSize", "rangef", "dx9", "ribbon half-width at the head, x Scale"),
        F(0x188, "HeadSizeAdd", "rangef", "dx9"),
        F(0x190, "PlaceSize", "rangef", "dx9"),
        F(0x198, "PlaceSizeAdd", "rangef", "dx9"),
        F(0x1A0, "KeyframePlaceColorParamOffset", "rel32", "dx9", "always 0 in the corpus", sub="kf:color"),
        F(0x1A4, "KeyframeHeadSizeParamOffset", "rel32", "dx9", sub="kf:f32"),
        F(0x1A8, "KeyframePlaceSizeParamOffset", "rel32", "dx9", sub="kf:f32"),
        F(0x1AC, "member_0x1ac", "u32", "unknown"),
    ], LINE_BITS + [
        B("SizePlaceType", "SizePlaceFlags", 0, 4, "dx9", "0 none, 1 linear, 2 peak at No, 3 from No, 4 up to No"),
        B("SizePlaceInpType", "SizePlaceFlags", 4, 4, "dx9", "0 linear, 1 sin, 2 1-cos, 3 smooth"),
        B("SizePlaceNo", "SizePlaceFlags", 8, 8, "dx9"),
        B("ClothType", "SizePlaceFlags", 16, 8, "dx9", "LineType 5 only"),
        B("ClothParam", "SizePlaceFlags", 24, 8, "dx9"),
    ]),
    2: ("Polygon", 0x1E0, "dx9", [
        F(0x170, "Rot", "rangef[3]", "dx9", "radians; initParticlePolygon 0x9792F0, move sub_98EAA0, quad sub_9B54C0"),
        F(0x188, "RotAdd", "rangef[3]", "dx9", "per frame, without a Rot keyframe"),
        F(0x1A0, "PolygonFlags", "u32", "dx9", "bitfield word; bits 12-15 (SE RotResetFlag) have no DX9 reader, 0 in "
                                               "every file"),
        F(0x1A4, "KeyframeRotParamOffset", "rel32", "dx9", "absolute angles", sub="kf:vec3"),
        F(0x1A8, "KeyframeWidthParamOffset", "rel32", "dx9", "replaces Width, clamped >= 0", sub="kf:f32"),
        F(0x1AC, "KeyframeHeightParamOffset", "rel32", "dx9", "replaces Height, clamped >= 0", sub="kf:f32"),
        F(0x1B0, "Width", "rangef", "dx9", "half-extent: a centred quad is 2W wide"),
        F(0x1B8, "Height", "rangef", "dx9", "half-extent"),
        F(0x1C0, "WidthAdd", "rangef", "dx9", "per frame; <= 0 kills (non-keyed, Add != 0)"),
        F(0x1C8, "HeightAdd", "rangef", "dx9", "per frame; <= 0 kills (non-keyed, Add != 0)"),
        F(0x1D0, "DistortRate", "f32[4]", "dx9", "per-corner scale of the corner offset (c0 a0b1, c1 a1b1, c2 a0b0, c3 a1b0)"),
    ], [
        B("PolygonAxis", "PolygonFlags", 0, 4, "dx9", "plane: 0 YZ (+X), 1 YZ (-X), 2 XZ (+Y), 3 XZ (-Y), 4/6 XY (+Z), 5 XY (-Z)"),
        B("RotOrder", "PolygonFlags", 4, 4, "dx9"),
        B("DirAxisType", "PolygonFlags", 8, 4, "dx9", "6 = no velocity alignment"),
        B("PolygonFixType", "PolygonFlags", 16, 4, "dx9", "pivot: 0 centre, 1-8 corners/edges, 9 PatCenter"),
        B("PolygonBillBoardType", "PolygonFlags", 20, 4, "dx9", "renderPolygon 0x99E9F6 -> build_view_basis: as ModelBillboardType"),
        B("PolygonDivideNum", "PolygonFlags", 24, 8, "dx9", "split into n + 1 strips (sub_9CCDB0)"),
    ]),
    3: ("Texline", 0x180, "dx9", [
        F(0x170, "LineFlags", "u32", "dx9", "init 0x97A0B0, move sub_98F0C0; a textured 1-pixel line strip"),
        F(0x174, "KeyframePlaceColorParamOffset", "rel16", "dx9", sub="kf:color"),
        F(0x176, "ClothType", "u8", "dx9", "LineType 5 only"),
        F(0x177, "ClothParam", "u8", "dx9"),
        F(0x178, "PlaceColor", "color[2]", "dx9"),
    ], LINE_BITS),
    15: ("PolygonStrip", 0x1D0, "dx9", [
        F(0x170, "LineOfsNum", "u8", "dx9", "trail samples, one per move tick (init 0x97E800, move sub_9915E0)"),
        F(0x171, "StripColorFlags", "u8", "dx9"),
        F(0x172, "ColorPlaceNo", "u8", "se", "not read in DX9"),
        F(0x173, "SplineDivideNum", "u8", "dx9", "sub-quads per segment"),
        F(0x174, "RotAxisOrder", "u8", "dx9", "width axis (getAxisVector) / RotOrder"),
        F(0x175, "DirAxisType", "u8", "dx9", "6 = no velocity alignment"),
        F(0x176, "KeyframePlaceColorParamOffset", "rel16", "dx9", sub="kf:color"),
        F(0x178, "KeyframeRotParamOffset", "rel16", "dx9", sub="kf:vec3"),
        F(0x17A, "KeyframeWidthParamOffset", "rel16", "dx9", sub="kf:f32"),
        F(0x17C, "WidthPlaceRate", "f32", "dx9", "pivot across the width: 0.5 centred"),
        F(0x180, "PlaceColor", "color[2]", "dx9", "tail colour when ColorPlaceType != 0"),
        F(0x188, "RotAddCoef", "f32", "se", "not read in DX9"),
        F(0x18C, "FollowFrame", "rangeu16", "se", "not read in DX9"),
        F(0x190, "Rot", "rangef[3]", "dx9", "radians"),
        F(0x1A8, "RotAdd", "rangef[3]", "dx9"),
        F(0x1C0, "Width", "rangef", "dx9", "full width, cm"),
        F(0x1C8, "WidthAdd", "rangef", "dx9", "per frame; width <= 0 ends the particle"),
    ], [
        B("ColorPlaceType", "StripColorFlags", 0, 4, "dx9", "!= 0: the tail colour is PlaceColor"),
        B("LayerDivideNum", "StripColorFlags", 4, 4, "se", "not read in DX9"),
        B("RotAxisType", "RotAxisOrder", 0, 4, "dx9"),
        B("RotOrder", "RotAxisOrder", 4, 4, "dx9"),
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
        B("ColorPlaceInpType", "PrimFlags", 20, 4, "dx9", "calc_color_gradient 0x9B52A0 easing (buildPrimModelRing "
                                                          "0x9CD9BE); SE leaves it unnamed (PPrimModel04172)"),
        B("ModelBillboardType", "PrimFlags", 24, 4, "dx9"),
        B("NormAttenuateFlag", "PrimFlags", 28, 4, "dx9", "bit 29 = one-sided"),
    ]),
    4: ("Line", 0x60, "dx9", [
        F(0x50, "LineFlags", "u32", "dx9", "same header as Polyline 0x170; drawn as a 1-pixel line strip"),
        F(0x54, "KeyframePlaceColorParamOffset", "rel16", "dx9",
          "colour B (PlaceColor at 0x58) -> particle +0x64, initParticleLine 0x97ABA8 (calcKeyframeColor; without "
          "keys calcSrcColor of PlaceColor); never set in the files", sub="kf:color"),
        F(0x56, "member_0x56", "u16", "unknown", "always 0; no DX9 reader found"),
        F(0x58, "PlaceColor", "color[2]", "dx9"),
    ], LINE_BITS),
    5: ("Model", 0x130, "dx9", [
        F(0x50, "ModelPath", "str64", "dx9", "rModel; initParticleModel 0x97AF80, move 0x98F9C0, renderModel 0x9A20C0"),
        F(0x90, "ModelScale", "rangef[3]", "dx9"),
        F(0xA8, "ModelScaleAdd", "rangef[3]", "dx9", "per frame"),
        F(0xC0, "Rot", "rangef[3]", "dx9", "radians"),
        F(0xD8, "RotAdd", "rangef[3]", "dx9", "radians per frame"),
        F(0xF0, "ModelFlags", "u32", "dx9"),
        F(0xF4, "PartsNoMax", "f32", "dx9", "clamp for the PatNo keyframe"),
        F(0xF8, "AnimSpeed", "f32", "dx9", "part index step per frame"),
        F(0xFC, "ModelAnimFlag", "u32", "dx9",
          "nEffect::MODEL_ANIM_FLAG 1 MOVE, 2 LOOP, 4 REVERSE, 8 FINISH; in DX9 0x10 is UV scroll (initParticleModel "
          "0x97BB04, move 0x99008D, renderModel 0x9A228B), not SE's REVERSE_RAND; 0x10000 ModelZofs; 0x10000000+ "
          "runtime"),
        F(0x100, "ScrollU", "rangef", "dx9", "UV per frame"),
        F(0x108, "ScrollV", "rangef", "dx9"),
        F(0x110, "ModelZofs", "f32", "dx9", "cm along camera->particle; negative pulls toward the camera"),
        F(0x120, "KeyframeRotParamOffset", "rel32", "dx9", sub="kf:vec3"),
        F(0x124, "KeyframeModelScaleParamOffset", "rel32", "dx9", sub="kf:vec3"),
        F(0x128, "KeyframeScrollUParamOffset", "rel32", "dx9", sub="kf:f32"),
        F(0x12C, "KeyframeScrollVParamOffset", "rel32", "dx9", sub="kf:f32"),
    ], [
        B("RotOrder", "ModelFlags", 0, 4, "dx9"),
        B("DirAxisType", "ModelFlags", 4, 4, "dx9", "6 = no velocity alignment"),
        B("ModelBillboardType", "ModelFlags", 8, 4, "dx9",
          "renderModel 0x9A2270 -> build_view_basis 0x9A2973: 1 = the camera's rotation (view-inverse, context +0x100), "
          "2 / 3 / 4 = world X / Y / Z kept, the rest turned to the camera; the matrix is the particle's times it"),
        B("PartsNoMin", "ModelFlags", 12, 10, "dx9", "mesh group drawn: first mesh with this idx_group"),
        B("PartsNoRange", "ModelFlags", 22, 10, "dx9"),
    ]),
    10: ("Light", 0x80, "dx9", [
        F(0x50, "AttenuateStart", "rangef", "dx9", "cm; init 0x97DE80, move 0x991190, updateParticleLight 0x99C120"),
        F(0x58, "AttenuateStartAdd", "rangef", "dx9", "per frame"),
        F(0x60, "AttenuateEnd", "rangef", "dx9", "cm; linear falloff from start to end"),
        F(0x68, "AttenuateEndAdd", "rangef", "dx9"),
        F(0x70, "LightColorW", "f32", "dx9", "-> uLight colour w (1 or 2)"),
        F(0x74, "LightMaskY", "f32", "se", "not read"),
        F(0x78, "DiffuseFactor", "f32", "se", "not read"),
        F(0x7C, "SpotFlags", "u16", "dx9", "spot lights only (none in the corpus)"),
        F(0x7E, "KeyframeSpotRotParamOffset", "rel16", "dx9", sub="kf:vec3"),
    ], []),
    7: ("LensFlare", 0xE0, "dx9", [
        F(0xA0, "LensFlarePath", "str64", "dx9", "resource loader"),
    ], []),
    8: ("MassBillboard", 0xA0, "dx9", [
        F(0x60, "TexturePath", "str64", "dx9", "resource loader; no PRIM_COMMON"),
    ], []),
}
PTCL_TAILS[12] = ("ClothPolyline",) + PTCL_TAILS[1][1:]   # same init as Polyline, LineType 5 (CLOTH)
PTCL_TAILS[13] = ("ClothTexline",) + PTCL_TAILS[3][1:]
PTCL_TAILS[14] = ("ClothLine",) + PTCL_TAILS[4][1:]

# type -> (name, chain); chain says which shared parts the block starts with
PTCL_TYPES = {
    0: ("Billboard", "prim"), 1: ("Polyline", "prim"), 2: ("Polygon", "prim"), 3: ("Texline", "prim"),
    4: ("Line", "draw"), 5: ("Model", "draw"), 6: ("PrimModel", "prim"), 7: ("LensFlare", "draw"),
    8: ("MassBillboard", "draw"), 9: ("Filter", "common"), 10: ("Light", "draw"), 11: ("Hit", "common"),
    12: ("ClothPolyline", "prim"), 13: ("ClothTexline", "prim"), 14: ("ClothLine", "draw"),
    15: ("PolygonStrip", "prim"), 16: ("LiteBillboard", "prim"), 17: ("SizeBillboard", "prim"),
}
# minimum sizes seen in the corpus for types without a typed tail
_PTCL_OBSERVED_SIZE = {9: 0x80, 11: 0x50}
_CHAIN_SIZE = {"common": 0x14, "draw": 0x50, "prim": 0x170}


def _particle_struct(ptype):
    name, chain = PTCL_TYPES.get(ptype, (f"Unknown{ptype}", "common"))
    fields = list(PTCL_COMMON)
    bits = list(PTCL_COMMON_BITS)
    if ptype == 10:   # Light: DRAW_COMMON up to 0x3F, then light fields (updateParticleLight 0x99C120)
        fields += [f for f in PTCL_DRAW if f.offset < 0x40] + PTCL_LIGHT_HEAD
        bits += [B("LightType", "LightTypeFlags", 0, 4, "dx9", "0 point, 1 spot")]
    elif chain in ("draw", "prim"):
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


# --- life param (slot 2): always 0x10 in the corpus; SE rEffectList::EFL_LIFE_FRAME -----------------
# DX9: spawn uEffectVFR::initParticleLifeFrame 0x9729B0 (each range s + rand % (r + 1); work +0 appear, +2 keep,
# +4 vanish, +6 counter, +8 hold limit, +0xA phase 0 appear / 1 keep / 2 vanish / 3 dead, +0xB bit 0 held), per frame
# uEffectVFR::moveParticleLifeFrame 0x998C30 (life types 1 / 2; 3 / 4 use the keyframe pair 0x972B70 / 0x998E20).
# The hold: Generator::restart 0x9DF230 copies bit 0 into Generator mFlags 0x40000; while it's set the Keep phase
# doesn't count down. Released by uEffectVFR::doFinish / doKeepHoldOff (called by checkEnd when the effect's owner
# ends it, e.g. the motion that spawned it ends), a path move's PathOptionFlag 4 at the path end, a collision with
# CollFlag 4 (moveParticlePosCollision 0x99A210), or the hold limit running out; then KeepFrame, then VanishFrame.

LIFE = Struct("EFL_LIFE_FRAME", 0x10, "dx9", [
    F(0x00, "AppearFrame", "rangeu16", "dx9", "fade-in frames; alpha = counter / appear"),
    F(0x04, "KeepFrame", "rangeu16", "dx9", "full-alpha frames (after a hold: the frames left once released)"),
    F(0x08, "VanishFrame", "rangeu16", "dx9", "fade-out frames; alpha = counter / vanish, then the particle dies"),
    F(0x0C, "KeepOptions", "u32", "dx9", "bitfield word"),
], [
    B("HoldUntilEffectEnds", "KeepOptions", 0, 1, "dx9",
      "SE KeepHoldFlag -> Generator mFlags 0x40000 (Generator::restart 0x9DF230); the Keep phase waits for a release "
      "(doFinish / doKeepHoldOff, PathOptionFlag 4, CollFlag 4); 1,506 particles in 236 files"),
    B("KeyframeKeepFrameParamOffset", "KeepOptions", 1, 15, "dx9",
      "u32 keyframe for KeepFrame, read at spawn (initParticleLifeFrame 0x972A0C: life + bits); never set in the "
      "files", sub="kf:u32"),
    B("HoldFrameLimit", "KeepOptions", 16, 16, "dx9",
      "SE KeepHoldFrame: counted down while held; reaching 0 ends the Keep phase at once; 0 = no limit "
      "(1,433 of the 1,506 holds)"),
])
LIFE_TYPES = {1: "FrameAlpha", 2: "FrameColor", 3: "KeyframeAlpha", 4: "KeyframeColor"}   # SE rEffectList::LIFE_TYPE

# --- move param (slot 3) -- Vibed/RE/particle_move_param.md "On-disk move param" -------------------

MOVE_COMMON = [
    F(0x00, "MoveOptionFlag", "u32", "dx9",
      "MOVE_OPTION_FLAG; DX9 reads only 2 GRAVITY_NO_SCALE (Add / Mul / PathLine), 4 HIGH_ACCURACY (initGeneratorParam, "
      "sub_967850) and 8 ALWAYS_CORRECT (initParticleMoveAdd / Mul). 1 COLLISION isn't read: collision is on when "
      "CollParamOffset is set (get_coll_param 0x9DD933, move types 0-2, 4, 6)"),
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
    F(0x50, "Path3DScaleX", "rangef", "dx9", "rolled once per generator start (initGeneratorParam 0x96B9C3)"),
    F(0x58, "Path3DScaleY", "rangef", "dx9", "rolled once per generator start (initGeneratorParam 0x96B9C3)"),
    F(0x60, "Path3DScaleZ", "rangef", "dx9", "rolled once per generator start (initGeneratorParam 0x96B9C3)"),
    F(0x68, "PathLengthScale", "rangef", "dx9", "rolled once per generator start (initGeneratorParam 0x96B9C3)"),
]
_CHAIN = 0x80   # EFL_PARAM_CHAIN inside EFL_MOVE_PATH_CHAIN
MOVE_CHAIN_PARAM = [
    F(_CHAIN + 0x00, "ChainOptionFlag", "u16", "dx9"),
    F(_CHAIN + 0x02, "member_chain_0x02", "u16", "unknown", "not read by the chain code"),
    F(_CHAIN + 0x04, "ChainRotAxis", "u8", "dx9", "nibbles: RotAxisType, RotOrder"),
    F(_CHAIN + 0x05, "ChainBlendRotAxis", "u8", "dx9", "nibbles: BlendRotAxisType, BlendRotOrder"),
    F(_CHAIN + 0x06, "PreUpdateLoopNum", "u16", "dx9", "rope steps run at spawn (0x98510A)"),
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



# --- particle extensions after the struct, chosen by LineType / ClothType ----------------------------
# Polyline/Texline/Line (1, 3, 4) carry a per-LineType extension right after the struct (base_size): FIX = stored
# points, CHAIN = an EFL_PARAM_CHAIN, LENGTH = a rigid stick. The cloth variants (12-14) always run as cloth and
# carry a per-ClothType extension (initParticlePolyline 0x9786D0 switch; CHAIN 0x981530, CURVE 0x9820D0,
# ZIGZAG 0x983330). Keyframe offsets in them are relative to the particle block, like the struct's own.

CHAIN_PARAM_BITS = [
    B("ChainRotAxisType", "ChainRotAxis", 0, 4, "dx9", "calcDir axis"),
    B("ChainRotOrder", "ChainRotAxis", 4, 4, "dx9"),
    B("ChainBlendRotAxisType", "ChainBlendRotAxis", 0, 4, "dx9"),
    B("ChainBlendRotOrder", "ChainBlendRotAxis", 4, 4, "dx9"),
]
_CHAIN_EXT = [replace(f, offset=f.offset - _CHAIN) for f in MOVE_CHAIN_PARAM]
_LENGTH_EXT = [
    F(0x00, "LineRot", "rangef[3]", "dx9", "stick direction: axis rotated by this (moveParticlePolyline LENGTH)"),
    F(0x18, "LineRotAdd", "rangef[3]", "dx9", "per frame"),
    F(0x30, "LineRotFlags", "u32", "dx9"),
    F(0x34, "member_line_0x34", "u32", "unknown"),
    F(0x38, "LineLength", "rangef", "dx9", "cm"),
    F(0x40, "LineLengthAdd", "rangef", "dx9", "per frame"),
    F(0x48, "LineKeyframeRotParamOffset", "rel32", "dx9", sub="kf:vec3"),
    F(0x4C, "LineKeyframeLengthParamOffset", "rel32", "dx9", sub="kf:f32"),
]
_LENGTH_BITS = [B("LineRotAxisType", "LineRotFlags", 0, 4, "dx9"), B("LineRotOrder", "LineRotFlags", 4, 4, "dx9")]
_FIX_EXT = [
    F(0x00, "FixModelScale", "rangef[3]", "dx9", "scales the stored points"),
    F(0x18, "FixModelScaleAdd", "rangef[3]", "dx9", "per frame"),
    F(0x30, "FixRot", "rangef[3]", "dx9"),
    F(0x48, "FixRotAdd", "rangef[3]", "dx9", "per frame"),
    F(0x60, "FixFlags", "u32", "dx9"),
    F(0x64, "member_fix_0x64", "u32[3]", "unknown"),
]
_FIX_BITS = [B("FixRotOrder", "FixFlags", 4, 4, "dx9")]
_CLOTH_SUB = [
    F(0x00, "ClothSubRange", "rangef[3]", "dx9", "tail point P1 = generator x SubOfs, drawn with sub_999040"),
    F(0x18, "ClothSubRangeType", "u32", "dx9", "RangeType shapes"),
    F(0x1C, "ClothSubRangeDivideNum", "u16", "dx9"),
]
_CLOTH_CHAIN_EXT = _CHAIN_EXT + [
    F(0x90, "ClothConstOffFrame", "rangeu16", "dx9", "ClothParam 1/2: release the head/tail after this many frames"),
    F(0x94, "ClothDistConvFrame", "rangeu16", "dx9", "ClothParam 4: length converges to |P0-P1| over this"),
    F(0x98, "ClothDistExpansion", "rangef", "dx9", "added to |P0-P1|"),
] + [replace(f, offset=f.offset + 0xA0) for f in _CLOTH_SUB]
_CURVE_EXT = [
    F(0x00, "CurveRot", "rangef[3]", "dx9", "bend direction (calcDir)"),
    F(0x18, "CurveRotAdd", "rangef[3]", "dx9", "per frame"),
    F(0x30, "CurveRotAxis", "u8", "dx9"),
    F(0x31, "CurveDirFlags", "u8", "dx9"),
    F(0x32, "CurveOptionFlag", "u16", "dx9", "1 = amplitude x |P1-P0|; ZIGZAG 0x100 ease, 0x200 limit, 0x400 once"),
    F(0x34, "CurveKeyframeRotParamOffset", "rel32", "dx9", sub="kf:vec3"),
    F(0x38, "CurveCoef", "rangef", "dx9", "bend amplitude"),
] + [replace(f, offset=f.offset + 0x40) for f in _CLOTH_SUB]
_CURVE_BITS = [
    B("CurveRotAxisType", "CurveRotAxis", 0, 4, "dx9"), B("CurveRotOrder", "CurveRotAxis", 4, 4, "dx9"),
    B("CurveDirAxisType", "CurveDirFlags", 0, 4, "dx9", "6 = fixed, else aligned to the velocity"),
    B("CurveType", "CurveDirFlags", 4, 4, "dx9", "0 two Hermite halves, else sine"),
]
_ZIGZAG_EXT = _CURVE_EXT + [
    F(0x60, "ZigzagVertexAmplitude", "rangef[3]", "dx9", "per-vertex jitter"),
    F(0x78, "ZigzagVertexUpdateFrame", "rangeu16", "dx9", "frames between jitter updates"),
    F(0x7C, "member_zigzag_0x7c", "u32", "unknown", "0 in the corpus"),
    F(0x80, "ZigzagEase", "rangef", "unknown", "(1, 1) in the corpus; probably the ease curve"),
]
EXTENSIONS = {   # key -> (label, size, fields, bits)
    ("line", 1): ("FIX", 0x70, _FIX_EXT, _FIX_BITS),
    ("line", 3): ("CHAIN", 0x90, _CHAIN_EXT, CHAIN_PARAM_BITS),
    ("line", 4): ("LENGTH", 0x50, _LENGTH_EXT, _LENGTH_BITS),
    ("cloth", 0): ("ClothCHAIN", 0xC0, _CLOTH_CHAIN_EXT, CHAIN_PARAM_BITS),
    ("cloth", 1): ("ClothCURVE", 0x60, _CURVE_EXT, _CURVE_BITS),
    ("cloth", 2): ("ClothZIGZAG", 0x90, _ZIGZAG_EXT, _CURVE_BITS),
}
CLOTH_PTCL_TYPES = (12, 13)   # ClothLine (14) has no ClothType field and no corpus records
LINE_PTCL_TYPES = (1, 3, 4)
_EXT_CACHE = {}


def extension_key(btype, get):
    """(kind, type[, point count]) of the extension a particle block carries, from get(field name) (None if the
    value is missing), or None."""
    try:
        if btype in CLOTH_PTCL_TYPES:
            cloth = get("ClothType")
            return ("cloth", int(cloth)) if cloth is not None and ("cloth", int(cloth)) in EXTENSIONS else None
        if btype in LINE_PTCL_TYPES:
            line = get("LineType")
            if line is None or ("line", int(line)) not in EXTENSIONS:
                return None
            if int(line) == 1:
                return ("line", 1, int(get("LineOfsNum") or 0))
            return ("line", int(line))
    except (TypeError, ValueError, KeyError):
        return None
    return None


def extended_struct(base, key):
    """The particle struct followed by the extension `key` (cached)."""
    cache_key = (base.name, key)
    if cache_key not in _EXT_CACHE:
        label, size, fields, bits = EXTENSIONS[key[:2]]
        fields = list(fields)
        if key[:2] == ("line", 1):   # FIX: LineOfsNum stored points (vec3 + pad)
            fields += [F(0x70 + 16 * i, f"FixPoint{i}", "vec3", "dx9", "stored point, x FixModelScale")
                       for i in range(key[2])]
            size += 16 * key[2]
        at = base.size
        _EXT_CACHE[cache_key] = Struct(
            f"{base.name}+{label}", at + size, base.size_tier,
            base.fields + [replace(f, offset=f.offset + at) for f in fields], base.bits + list(bits),
            base_size=base.size)
    return _EXT_CACHE[cache_key]


def struct_for_data(kind, btype, data):
    """Struct for a block's bytes: particle blocks get their LineType / ClothType extension when it fits."""
    base = struct_for(kind, btype)
    if kind != "ptcl" or btype not in LINE_PTCL_TYPES + CLOTH_PTCL_TYPES:
        return base

    def get(name):
        bits = base.bits_by_name.get(name)
        f = base.by_name.get(bits.field if bits else name)
        if f is None or f.offset + f.size > len(data):
            return None
        value = decode(f.type, data, f.offset)
        return (value >> bits.shift) & ((1 << bits.width) - 1) if bits else value

    key = extension_key(btype, get)
    if key is None:
        return base
    struct = extended_struct(base, key)
    return struct if struct.size <= len(data) else base


def struct_for_props(kind, btype, props):
    """Struct for stored block properties (block_props), the same one struct_for_data picked."""
    base = struct_for(kind, btype)
    if kind != "ptcl":
        return base
    key = extension_key(btype, lambda name: props.get(name) if name in props else None)
    if key is None:
        return base
    struct = extended_struct(base, key)
    # the extension was only used if the block was long enough: its first field is in the props then
    first = min(struct.fields[len(base.fields):], key=lambda f: f.offset, default=None)
    return struct if first is not None and first.name in props else base


# old field names -> current ones (props stored by older imports)
FIELD_ALIASES = {
    "uknKeyframeOffset": "KeyframeWidthParamOffset",
    "KeyframeParamOffset_1d4": "KeyframeRangeParamOffset",
    "KeyframeParamOffset_1d8": "KeyframePosParamOffset",
    "KeyframeParamOffset_1dc": "KeyframeRotParamOffset",
}


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

CULLING = Struct("EFL_PARAM_CULLING", 0x30, "se", [   # uEffectVFR::calc_culling_fade 0x963BD0 (alpha factor)
    F(0x00, "CullingFlags", "u32", "dx9", "calcDir(CullingRot, order >>12, axis >>8 & 0xF): calcDirWrapper 0x962510 / "
                                          "init_culling_dir 0x962F40"),
    F(0x04, "CullingRot", "vec3", "dx9"),
    F(0x10, "CullingDistNearStart", "f32", "dx9", "cm; d <= NearStart or d >= FarEnd -> 0 (with option 0x2000)"),
    F(0x14, "CullingDistNearEnd", "f32", "dx9", "(d - NearStart) / (NearEnd - NearStart) below it, 0 with 0x4000"),
    F(0x18, "CullingDistFarStart", "f32", "dx9", "1 - (d - FarStart) / (FarEnd - FarStart) above it, 0 with 0x8000"),
    F(0x1C, "CullingDistFarEnd", "f32", "dx9"),
    F(0x20, "CullingAngleStart", "f32", "dx9", "radians; option 0x800: 1 up to it, then 1 - (a - Start) / Rate"),
    F(0x24, "CullingAngleEnd", "f32", "dx9", "a = acos(dir . to camera); 0 from it on; without 0x800: 1 - a / End"),
    F(0x28, "CullingRate", "f32", "dx9"),
    F(0x2C, "OcclusionRadius", "f32", "se"),
], [
    B("CullingFlag", "CullingFlags", 0, 8, "dx9", "CULLING_FLAG: 0x4 per particle, 0x80 angle fade, 0x2 occlusion"),
    B("CullingRotAxisType", "CullingFlags", 8, 4, "dx9"),
    B("CullingRotOrder", "CullingFlags", 12, 4, "dx9"),
    B("CullingOptionFlag", "CullingFlags", 16, 16, "dx9",
      "CULLING_OPTION_FLAG: 0x2000 DIST, 0x4000 NEAR_CLIP, 0x8000 FAR_CLIP, 0x1 BOTH_DIR (max of the two), 0x1000 "
      "ANGLE_OVERLAP (min), 0x800 angle range (no SE name)"),
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
