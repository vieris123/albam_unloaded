"""Editable views of EFL blocks and their write-back (pure Python).

Property values are what the Blender side stores on record objects (ID-property friendly):
- block fields: `block_props` gives every schema field and bit-field except the offsets into the block (those are
  layout, rewritten by apply_keyframes), nested arrays flattened (rangef[3] -> 6 floats), integers beyond 32 bits as
  hex strings;
- keyframes: `keyframe_props` gives {offset field name: {vtype, header, InpType, RefType, LoopFlag, InitOnlyFlag,
  frames, params}} with params flattened per key (f32/u32 2, color 8 = bytes b,g,r,a of A then B, vec3/fixangle 6);
- sub-structs (collision / culling): `sub_props` gives {offset field name: {field: value}}.
The apply_* functions write back only what differs from the block, so an untouched block stays byte-identical.
A keyframe that grows is appended at the end of its block and its offset repointed; nothing else moves, so offsets
the schema doesn't know about stay valid. An empty frame list removes a keyframe (offset 0). `restructure` drops,
reorders and appends records.
"""
import math
import struct

from . import keyframe as kfm
from . import schema
from .model import Block, Record, SLOTS

READ_ONLY_KEYS = ("type", "type_name")   # "struct" is informational: it follows LineType / ClothType
KF_FLAGS = {"InpType": (27, 7), "RefType": (24, 7), "LoopFlag": (30, 1), "InitOnlyFlag": (31, 1)}
KF_PARAM_LIMITS = {"u32": (0, 0xFFFF), "color": (0, 0xFF), "fixangle": (-2 ** 31, 2 ** 31 - 1)}


# -- values ---------------------------------------------------------------------------------------

def to_prop(value):
    """A decoded field value as an ID property: 32-bit ints, flat numeric arrays."""
    if isinstance(value, (list, tuple)):
        flat = list(_leaves(value))
        if any(isinstance(v, int) and not -2 ** 31 <= v < 2 ** 31 for v in flat):
            return [float(v) for v in flat]
        return flat
    if isinstance(value, int) and not -2 ** 31 <= value < 2 ** 31:
        return f"{value:#010x}"
    return value


def _leaves(value):
    for item in value:
        if isinstance(item, (list, tuple)):
            yield from _leaves(item)
        else:
            yield item


def as_list(prop):
    """A property value as a Python list, or None for scalars/strings."""
    if isinstance(prop, (str, bytes)) or not hasattr(prop, "__len__"):
        return None
    if hasattr(prop, "to_list"):
        return list(prop.to_list())
    return list(prop)


def _same(a, b):
    la, lb = (a if isinstance(a, list) else as_list(a)), (b if isinstance(b, list) else as_list(b))
    if la is not None or lb is not None:
        return la is not None and lb is not None and len(la) == len(lb) and all(_same(x, y) for x, y in zip(la, lb))
    if isinstance(a, str) or isinstance(b, str):
        if isinstance(a, str) and isinstance(b, str):
            return a == b
        try:   # a hex string against a number
            return int(a, 0) == int(b) if isinstance(a, str) else int(a) == int(b, 0)
        except (TypeError, ValueError):
            return False
    try:
        fa, fb = float(a), float(b)
        if math.isnan(fa) or math.isnan(fb):   # stored NaNs (unused floats) stay untouched
            return math.isnan(fa) and math.isnan(fb)
        return math.isclose(fa, fb, rel_tol=1e-7, abs_tol=1e-9)
    except (TypeError, ValueError):
        return False


def _scalar(template, value):
    if isinstance(template, str):
        if not isinstance(value, str):
            raise ValueError("expected text")
        return value
    if isinstance(value, str):
        value = int(value, 0)
    if isinstance(template, int):
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"expected a whole number, got {value}")
        return int(value)
    return float(value)


def from_prop(template, prop):
    """Inverse of to_prop, shaped like template (the field's decoded value)."""
    if not isinstance(template, list):
        if as_list(prop) is not None:
            raise ValueError("expected a single value")
        return _scalar(template, prop)
    flat = as_list(prop)
    leaves = list(_leaves(template))
    if flat is None or len(flat) != len(leaves):
        raise ValueError(f"expected {len(leaves)} values, got {1 if flat is None else len(flat)}")
    it = iter(zip(leaves, flat))

    def rebuild(t):
        if isinstance(t, list):
            return [rebuild(x) for x in t]
        leaf, value = next(it)
        return _scalar(leaf, value)

    return rebuild(template)


def _write_fields(fields, decoded, props, write, label=""):
    """Shared by blocks and sub-structs: write changed props through write(field, value)."""
    changes, problems = [], []
    for f in fields:
        if f.name not in decoded or f.name not in props:
            continue
        old = decoded[f.name]
        if _same(to_prop(old), props[f.name]):
            continue
        if f.sub:   # only in props stored by older imports
            problems.append(f"{label}{f.name} is an offset into the block and can't be edited "
                            "(edit keyframes in the Effect Editor instead)")
            continue
        try:
            new = from_prop(old, props[f.name])
            write(f, new)
        except (ValueError, TypeError, struct.error) as err:
            problems.append(f"{label}{f.name}: {err}")
            continue
        changes.append((label + f.name, old, new))
    return changes, problems


# -- block fields ---------------------------------------------------------------------------------

def block_props(block):
    props = {"type": block.type, "type_name": block.type_name, "struct": block.struct.name}
    fields = block.fields()
    for f in block.struct.fields:
        if f.name in fields and not f.sub:
            props[f.name] = to_prop(fields[f.name])
    for name, value in block.bits().items():
        props[name] = to_prop(value)
    return props


# fields renamed since older imports stored their props: old name -> new name
RENAMED_PROPS = {"KeepFlags": "KeepOptions", "KeepHoldFlag": "HoldUntilEffectEnds", "KeepHoldFrame": "HoldFrameLimit"}


def upgrade_props(props):
    """Props stored by older imports, in today's field names: the particle CullingFlag was a u16 holding
    VolumeBlendRate in its high byte, OtDepthBias was the u32 uknDraw_0x14, and RENAMED_PROPS were renamed. Returns
    props unchanged when nothing is old."""
    if props is None or ("VolumeBlendRate" in props or "CullingFlag" not in props) and "uknDraw_0x14" not in props \
            and not any(old in props for old in RENAMED_PROPS):
        return props
    out = dict(props)
    for old, new in RENAMED_PROPS.items():
        if old in out:
            value = out.pop(old)
            out.setdefault(new, value)
    if "VolumeBlendRate" not in out and "CullingFlag" in out:
        word = _scalar(0, out["CullingFlag"])
        out["CullingFlag"], out["VolumeBlendRate"] = word & 0xFF, word >> 8 & 0xFF
    if "uknDraw_0x14" in out:
        raw = _scalar(0, out.pop("uknDraw_0x14")) & 0xFFFFFFFF
        out["OtDepthBias"] = struct.unpack("<f", struct.pack("<I", raw))[0]
    return out


def apply_props(block, props):
    """Write changed values of props (a mapping like block_props) into block.
    Returns (changes, problems): changes = [(name, old, new)], problems = [message]."""
    props = upgrade_props(props)
    problems = []
    current = {"type": block.type, "type_name": block.type_name, "struct": block.struct.name}
    for key in READ_ONLY_KEYS:
        if key in props and props[key] != current[key]:
            problems.append(f"{key} can't be changed (it's {block.type_name})")
    bits = block.bits()   # before any write: bits are compared with the original
    changes, field_problems = _write_fields(block.struct.fields, block.fields(), props,
                                            lambda f, v: block.set(f.name, v))
    problems += field_problems
    for b in block.struct.bits:
        if b.name not in bits or b.name not in props or _same(bits[b.name], props[b.name]):
            continue
        try:
            new = _scalar(0, props[b.name])
            if not 0 <= new < 1 << b.width:
                raise ValueError(f"must be 0..{(1 << b.width) - 1}")
            block.set(b.name, new)
        except (ValueError, TypeError) as err:
            problems.append(f"{b.name}: {err}")
            continue
        changes.append((b.name, bits[b.name], new))
    return changes, problems


# -- keyframes ------------------------------------------------------------------------------------

def keyframe_value_type(field):
    """Declared value type of a keyframe offset field ('f32', 'vec3', ...), or None if unknown."""
    if not field.sub or not field.sub.startswith("kf"):
        return None
    parts = field.sub.split(":")
    return parts[1] if len(parts) > 1 else None


def kf_to_prop(kf):
    prop = {"vtype": kf.vtype, "header": f"{kf.header:#010x}", "frames": list(kf.frames),
            "params": [v for param in kf.params for v in param]}
    for name, (shift, mask) in KF_FLAGS.items():
        prop[name] = kf.header >> shift & mask
    return prop


def kf_from_prop(prop, vtype):
    """Keyframe from a kf_to_prop-style mapping; raises ValueError on bad values."""
    vtype = str(prop.get("vtype", vtype) or "")
    if vtype not in kfm.PARAM_COUNT:
        raise ValueError(f"unknown keyframe value type {vtype!r}")
    header = prop.get("header", 0)
    header = int(header, 0) if isinstance(header, str) else int(header)
    for name, (shift, mask) in KF_FLAGS.items():
        if name in prop:
            header = (header & ~(mask << shift)) | ((int(prop[name]) & mask) << shift)
    frames = [int(f) for f in (as_list(prop.get("frames")) or [])]
    flat = as_list(prop.get("params")) or []
    per = kfm.PARAM_COUNT[vtype]
    if len(flat) != per * len(frames):
        raise ValueError(f"{len(frames)} keys need {per * len(frames)} values, got {len(flat)}")
    if any(b <= a for a, b in zip(frames, frames[1:])):
        raise ValueError("key frames must increase")
    if any(not 0 <= f < 2 ** 32 for f in frames):
        raise ValueError("key frames must be 0 or more")
    if vtype in kfm.INTEGER_TYPES:
        lo, hi = KF_PARAM_LIMITS[vtype]
        for v in flat:
            if not float(v).is_integer() or not lo <= int(v) <= hi:
                raise ValueError(f"{vtype} key values must be whole numbers in {lo}..{hi}, got {v}")
        flat = [int(v) for v in flat]
    else:
        flat = [float(v) for v in flat]
    params = [tuple(flat[i * per:(i + 1) * per]) for i in range(len(frames))]
    return kfm.Keyframe(header, vtype, frames, params)


def _kf_same(a, b):
    return (a.header & ~0xFF) == (b.header & ~0xFF) and a.vtype == b.vtype and a.frames == b.frames and \
        all(_same(list(x), list(y)) for x, y in zip(a.params, b.params)) and len(a.params) == len(b.params)


def keyframe_props(block):
    """{offset field name: keyframe prop} for the typed keyframes of a block."""
    out = {}
    for sub in block.subblocks():
        if sub.kind == "kf" and sub.value_type:
            try:
                out[sub.field.name] = kf_to_prop(kfm.read(sub))
            except (struct.error, KeyError):
                continue
    return out


def apply_keyframes(block, props):
    """Write keyframe props (like keyframe_props; may name offset fields that have no keyframe yet)."""
    changes, problems = [], []
    subs = {sub.field.name: sub for sub in block.subblocks() if sub.kind == "kf"}
    for name, prop in props.items():
        name = schema.FIELD_ALIASES.get(name, name)   # keyframes stored under an older field name
        f = block.struct.by_name.get(name)
        if f is None or not f.sub or not f.sub.startswith("kf") or f.offset + f.size > len(block.data):
            problems.append(f"{name} isn't a keyframe offset of {block.struct.name}")
            continue
        sub = subs.get(name)
        old = kfm.read(sub) if sub is not None else None
        vtype = old.vtype if old is not None else keyframe_value_type(f)
        if vtype is None:
            problems.append(f"{name}: the keyframe value type isn't known, it can't be edited")
            continue
        try:
            new = kf_from_prop(prop, vtype)
            if old is None:   # new keyframes start from the header of the prop only
                pass
            elif _kf_same(old, new):
                continue
            if not new.frames:
                if sub is not None:
                    block.set(name, 0)
                    changes.append((name, f"{len(old.frames)} keys", "removed"))
                continue
            data = kfm.encode(new)
            if old is not None:
                old_len = len(kfm.encode(old))
                if len(data) <= old_len and sub.offset + old_len <= sub.end:
                    block.data[sub.offset:sub.offset + old_len] = data + bytes(old_len - len(data))
                    changes.append((name, f"{len(old.frames)} keys", f"{len(new.frames)} keys"))
                    continue
            size_before = len(block.data)
            block.data.extend(bytes(-len(block.data) % 16))
            target = len(block.data)
            block.data.extend(data)
            rel = target - f.rel_base
            try:
                block.set(name, rel)
            except struct.error:
                del block.data[size_before:]
                raise ValueError("the block is too large for this offset field")
            changes.append((name, f"{len(old.frames)} keys" if old else "none", f"{len(new.frames)} keys"))
        except ValueError as err:
            problems.append(f"{name}: {err}")
    return changes, problems


# -- sub-structs (collision, culling) -------------------------------------------------------------

def sub_props(block):
    out = {}
    for sub in block.subblocks():
        if sub.kind in schema.SUB_STRUCTS:
            try:
                out[sub.field.name] = {k: to_prop(v) for k, v in sub.fields().items()}
            except Exception:
                continue
    return out


def apply_subs(block, props):
    changes, problems = [], []
    subs = {sub.field.name: sub for sub in block.subblocks() if sub.kind in schema.SUB_STRUCTS}
    for name, prop in props.items():
        sub = subs.get(name)
        if sub is None:
            problems.append(f"{name}: no {name} data in this block (adding it isn't supported)")
            continue
        sub_struct = schema.SUB_STRUCTS[sub.kind]
        try:
            decoded = sub.fields()
        except Exception as err:
            problems.append(f"{name}: {err}")
            continue

        def write(f, value, base=sub.offset):
            schema.encode(f.type, block.data, base + f.offset, value)

        c, p = _write_fields(sub_struct.fields, decoded, prop, write, label=f"{name}.")
        changes += c
        problems += p
    return changes, problems


# -- records --------------------------------------------------------------------------------------

def record_raw(record):
    """{slot: (type, bytes)} for a record's blocks."""
    return {slot: (block.type, bytes(block.data)) for slot, block in record.blocks() if block is not None}


def record_from_raw(raw):
    return Record(**{slot: Block(slot, btype, bytearray(data)) for slot, (btype, data) in raw.items()
                     if slot in SLOTS})


def restructure(efl, keep, extra=()):
    """Keep efl.records[i] for i in keep (in that order), then append the extra records."""
    efl.records = [efl.records[i] for i in keep] + list(extra)
    referenced = {id(b) for r in efl.records for _, b in r.blocks() if b is not None}
    referenced |= {id(b) for b in (efl.unit_gen, efl.unit_move) if b is not None}
    blocks = [b for b in efl.blocks if b.kind == "raw" or id(b) in referenced]
    listed = {id(b) for b in blocks}
    for record in extra:
        for _, block in record.blocks():
            if block is not None and id(block) not in listed:
                blocks.append(block)
                listed.add(id(block))
    efl.blocks = blocks
    return efl
