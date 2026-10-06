"""Change a particle or move block's type (pure Python).

Every type has its own layout, so changing only the type byte would make the game misread the block. Instead a
new block of the target type is built:
1. its bytes start from a template, a real block of that type (and LineType / ClothType extension) from the game's
   files, or else from zeros plus DEFAULTS;
2. every field that exists in both types (same name and type) is copied from the old block, except the fields
   that choose the extension (LineType, LineOfsNum, ClothType);
3. the old block's keyframes and collision / culling data are appended for offset fields the new type also has;
   the template's keyframes are dropped, its collision / culling data is kept where the old block had none.
Generator and life blocks share one layout for every type and what their types change isn't known, so they
aren't offered.
"""
from . import keyframe as kfm
from . import schema
from .model import Block

RETYPE_SLOTS = ("ptcl", "move")
EXTENSION_BITS = ("LineType", "LineOfsNum", "ClothType")
TEMPLATE_ONLY = (9, 11)      # Filter, Hit: layouts not known beyond a minimum size
NOT_OFFERED = {"ptcl": (14,), "move": (7,)}   # ClothLine has no ClothType and no corpus records; move 7 unknown
LINE_VARIANTS = [(0, "FOLLOW"), (1, "FIX"), (2, "FIX_END"), (3, "CHAIN"), (4, "LENGTH")]
CLOTH_VARIANTS = [(0, "CHAIN"), (1, "CURVE"), (2, "ZIGZAG")]

_ONE = [1.0, 0.0]
_WHITE = [255, 255, 255, 255]
# Values for a block built without a template (anything else is 0). Keys: "<field>" or "<slot>.<type>:<field>".
DEFAULTS = {
    "TransMode": 1, "BlendSrc": 4, "BlendDst": 5, "Intensity": _ONE, "Scale": _ONE, "Color0": _WHITE,
    "Color1": _WHITE, "PlaceColor": [_WHITE, _WHITE], "PlaceColor1": _WHITE, "PlaceColor2": _WHITE,
    "AspectRatio": _ONE, "HeadSize": [4.0, 0.0], "PlaceSize": _ONE, "LineOfsNum": 8,
    "Width": [10.0, 0.0], "Height": [10.0, 0.0], "ModelScale": [_ONE, _ONE, _ONE],
    "ptcl.6:Radius": [[10.0, 0.0], [20.0, 0.0]], "ptcl.6:Height": [[0.0, 0.0], [0.0, 0.0]],
    "RotDivNum": 16, "RotDrawEnd": 16, "HoriDivNum": 1, "HoriDrawEnd": 1,
    "AttenuateEnd": [100.0, 0.0], "LightColorW": 1.0,
    "SpeedCoef": _ONE, "Path3DScaleX": _ONE, "Path3DScaleY": _ONE, "Path3DScaleZ": _ONE, "PathLengthScale": _ONE,
    "ChainPosNum": 8, "Length": [100.0, 0.0], "FrameInf": [0.9, 0.0], "VertexInf": [0.5, 0.0],
    "FixModelScale": [_ONE, _ONE, _ONE], "LineLength": [100.0, 0.0],
}


class RetypeError(Exception):
    pass


def offered_types(slot):
    """[(type, name)] a block of this slot can be changed to."""
    if slot not in RETYPE_SLOTS:
        return []
    known = schema.PTCL_TYPES if slot == "ptcl" else schema.MOVE_TAILS
    return [(t, schema.type_name(slot, t)) for t in sorted(known) if t not in NOT_OFFERED[slot]]


def variants(slot, btype):
    """[(value, name)] of the extension choice of a type (LineType / ClothType), or []."""
    if slot != "ptcl":
        return []
    if btype in schema.LINE_PTCL_TYPES:
        return LINE_VARIANTS
    if btype in schema.CLOTH_PTCL_TYPES:
        return CLOTH_VARIANTS
    return []


def variant_of(block):
    """The block's LineType / ClothType when its type has that choice, else None."""
    if block is None or not variants(block.kind, block.type):
        return None
    name = "ClothType" if block.type in schema.CLOTH_PTCL_TYPES else "LineType"
    return block.get(name) if block.has(name) else None


def template_score(block):
    """Lower is better: fewer keyframes (they're dropped, so a keyed template may lose its look)."""
    return sum(1 for sub in block.subblocks() if sub.kind == "kf")


def struct_bytes(block):
    """The block's own bytes without its trailing keyframe / sub-struct data."""
    starts = [sub.offset for sub in block.subblocks()]
    end = min(starts + [len(block.data)])
    return bytearray(block.data[:max(end, min(block.struct.size, len(block.data)))])


def _zero_offsets(block):
    for f in block.struct.fields:
        if f.sub and f.offset + f.size <= len(block.data):
            block.set(f.name, 0)


def _append(block, field, data):
    block.data.extend(bytes(-len(block.data) % 16))
    target = len(block.data)
    block.data.extend(data)
    try:
        block.set(field.name, target - field.rel_base)
    except Exception:
        raise RetypeError(f"the new block is too large for its {field.name} offset")


def _default_for(slot, btype, name):
    return DEFAULTS.get(f"{slot}.{btype}:{name}", DEFAULTS.get(name))


def _from_defaults(slot, btype, variant):
    base = schema.struct_for(slot, btype)
    if btype in TEMPLATE_ONLY:
        raise RetypeError(f"{schema.type_name(slot, btype)} blocks can only be made from an example in the "
                          "game's files (its layout isn't fully known)")
    probe = Block(slot, btype, bytearray(base.size))
    if variant is None and variants(slot, btype):   # the game reads the extension of LineType / ClothType 0
        variant = variants(slot, btype)[0][0]
    if variant is not None:   # pick the extension first, then size the block for it
        name = "ClothType" if btype in schema.CLOTH_PTCL_TYPES else "LineType"
        probe.set(name, variant)
        if name == "LineType":
            probe.set("LineOfsNum", DEFAULTS["LineOfsNum"])
        key = schema.extension_key(btype, lambda n: probe.get(n) if probe.has(n) else None)
        if key is not None:
            probe.data.extend(bytes(schema.extended_struct(base, key).size - base.size))
    block = Block(slot, btype, probe.data)
    for f in block.struct.fields:
        value = _default_for(slot, btype, f.name)
        if value is not None and not f.sub:
            try:
                block.set(f.name, value)
            except Exception:
                pass
    for b in block.struct.bits:
        value = _default_for(slot, btype, b.name)
        if value is not None and b.name not in EXTENSION_BITS:
            block.set(b.name, value)
    if block.has("FixFlags"):   # FIX: stored points along +Y
        for i in range(block.get("LineOfsNum") if block.has("LineOfsNum") else 0):
            if block.has(f"FixPoint{i}"):
                block.set(f"FixPoint{i}", [0.0, 10.0 * i, 0.0])
    return block


def _extension_names(block):
    """Fields and bit-fields that choose the extension of a block's type."""
    if block.type not in schema.LINE_PTCL_TYPES + schema.CLOTH_PTCL_TYPES:
        return set(), set()
    bits = {b for b in EXTENSION_BITS if b in block.struct.bits_by_name}
    words = {block.struct.bits_by_name[b].field for b in bits}
    fields = {b for b in EXTENSION_BITS if b in block.struct.by_name}
    return words | fields, bits


def retype(old, new_type, template=None, variant=None):
    """New Block of new_type for old's slot. template: a Block of that type (and variant), or None for DEFAULTS.
    Returns (block, notes)."""
    slot = old.kind
    if slot not in RETYPE_SLOTS:
        raise RetypeError(f"{slot} block types can't be changed")
    notes = []
    if template is not None:
        if template.kind != slot or template.type != new_type:
            raise RetypeError("the template is a different kind of block")
        block = Block(slot, new_type, struct_bytes(template))
        notes.append("unique values from a game example")
    else:
        block = _from_defaults(slot, new_type, variant)
        notes.append("no example of this type found in the game files: unique values are defaults, check them")
    _zero_offsets(block)
    if variant is not None and variant_of(block) != variant:
        raise RetypeError("the template has a different line / cloth type")

    # 1. shared fields and bit-fields
    skip_fields, skip_bits = _extension_names(block)
    copied = []
    old_fields = old.fields()
    for f in block.struct.fields:
        of = old.struct.by_name.get(f.name)
        if f.sub or f.name in skip_fields or of is None or of.sub or of.type != f.type or f.name not in old_fields:
            continue
        block.set(f.name, old_fields[f.name])
        copied.append(f.name)
    for b in block.struct.bits:
        ob = old.struct.bits_by_name.get(b.name)
        if b.field in skip_fields and b.name not in skip_bits and ob is not None and old.has(ob.field) \
                and ob.width == b.width:
            block.set(b.name, old.get(b.name))
            copied.append(b.name)
    notes.append(f"{len(copied)} shared field(s) kept")

    # 2. keyframes and collision / culling data
    old_subs = {sub.field.name: sub for sub in old.subblocks()}
    template_subs = {sub.field.name: sub for sub in template.subblocks()} if template is not None else {}
    dropped = []
    for f in block.struct.fields:
        if not f.sub:
            continue
        sub = old_subs.get(f.name)
        if sub is not None and sub.field.sub == f.sub:
            if sub.kind == "kf":
                if not sub.value_type:
                    dropped.append(f.name)
                    continue
                _append(block, f, kfm.encode(kfm.read(sub)))
            else:
                size = schema.SUB_STRUCTS[sub.kind].size
                _append(block, f, bytes(old.data[sub.offset:sub.offset + size]))
            continue
        sub = template_subs.get(f.name)
        if sub is not None and sub.kind in schema.SUB_STRUCTS:
            size = schema.SUB_STRUCTS[sub.kind].size
            _append(block, f, bytes(template.data[sub.offset:sub.offset + size]))
    lost = [name for name, sub in old_subs.items() if block.struct.by_name.get(name) is None
            or block.struct.by_name[name].sub != sub.field.sub]
    if lost or dropped:
        notes.append("dropped (the new type has no place for them): " + ", ".join(sorted(lost + dropped)))

    check = Block(slot, new_type, block.data)   # the struct must still match the extension it was built for
    if check.struct.name != block.struct.name:
        raise RetypeError(f"internal: built {block.struct.name} but it reads back as {check.struct.name}")
    return check, notes
