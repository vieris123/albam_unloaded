"""Effect Editor panel (3D View > Albam [Beta]): schema-driven editing of an imported .efl's records.

The active record's fields are loaded into `scene.albam.efl_editor` (one item per schema field / bit-field, with a
widget for its type) when a record becomes active. Every edit is written straight into the record object's
efl_* custom properties, which export (effect_export.py) writes back into the file; Apply replays the preview
(rebuilding the effect when an edit needs it). Keyframes are edited one at a time (any typed keyframe offset of the record, existing or not).
"""
import bpy
from bpy.app.handlers import persistent

from albam.registry import blender_registry
from .efl import schema
from .efl.field_help import lookup as field_help
from .efl.edit import as_list, keyframe_value_type, to_prop, upgrade_props
from .efl.model import SLOTS
from .efl.sim import ROT_ORDER_NAMES, ROT_ORDERS
from . import effect_filter
from .effect_export import all_record_objects, effect_root, ordered_record_objects, record_object

MAX_VALUES = 8
_TUPLE_SIZE = {"rangef": 2, "rangeu16": 2, "vec3": 3, "vec4": 4, "color": 4, "point": 2, "easecurve": 2}
_FLOAT_BASES = ("f32", "rangef", "vec3", "vec4", "easecurve")
_ELEMENT_LABELS = {"rangef": ("", "+rand"), "rangeu16": ("", "+rand"), "vec3": ("X", "Y", "Z"),
                   "vec4": ("X", "Y", "Z", "W"), "point": ("X", "Y"), "easecurve": ("A", "B")}
_ROW_LABELS = ("X", "Y", "Z", "W", "5", "6", "7", "8")
# RotOrder dropdowns: the order the axes are applied in (Blender's Euler order), and the game's name for it
_ORDER_LABELS = tuple(f"{order} (game {name})" for order, name in zip(ROT_ORDERS, ROT_ORDER_NAMES))

READ_ONLY = {
    ("gen", "Pos"): "move the record's Empty",
    ("gen", "Quat"): "rotate the record's Empty (RelationType 2 on a bone: its _rot companion)",
    ("gen", "ParentNo"): "parent the record's Empty to a bone",
}
TIER_ICONS = {"dx9": "CHECKMARK", "se": "INFO", "prior": "QUESTION", "unknown": "QUESTION"}
VERIFIED_TIERS = ("dx9", "se")

_D3DBLEND = ("ZERO", "ONE", "SRCCOLOR", "INVSRCCOLOR", "SRCALPHA", "INVSRCALPHA", "DESTALPHA", "INVDESTALPHA",
             "DESTCOLOR", "INVDESTCOLOR", "SRCALPHASAT")
_AXES = ("+X", "-X", "+Y", "-Y", "+Z", "-Z", "None (+Z)")
_ENUM_LABELS = {
    "BlendSrc": _D3DBLEND, "BlendDst": _D3DBLEND, "BlendOp": ("ADD", "SUBTRACT", "REVSUBTRACT", "MIN", "MAX"),
    "RangeType": ("Point", "Box, steps along X", "Box, steps along Y", "Box, steps along Z", "Cylinder X",
                  "Cylinder Y", "Cylinder Z",
                  "Sphere", "Hemisphere"),
    "RangeDirType": ("None", "Diffuse", "Converge", "Unit"),
    "LineType": ("FOLLOW", "FIX", "FIX_END", "CHAIN", "LENGTH", "CLOTH"),
    "ClothType": ("CHAIN", "CURVE", "ZIGZAG"),
    "RotOrder": _ORDER_LABELS, "Order": _ORDER_LABELS, "CullingRotOrder": _ORDER_LABELS,
    "RotAxisType": _AXES, "AxisType": _AXES, "Axis": _AXES, "DirAxisType": _AXES, "CullingRotAxisType": _AXES,
    "ChainRotAxisType": _AXES, "ChainBlendRotAxisType": _AXES, "LineRotAxisType": _AXES, "CurveRotAxisType": _AXES,
    "CurveDirAxisType": _AXES, "ChainRotOrder": _ORDER_LABELS, "ChainBlendRotOrder": _ORDER_LABELS,
    "LineRotOrder": _ORDER_LABELS, "FixRotOrder": _ORDER_LABELS, "CurveRotOrder": _ORDER_LABELS,
    "CurveType": ("Two Hermite halves", "Sine", "Sine", "Sine", "Sine", "Sine", "Sine", "Sine", "Sine", "Sine",
                  "Sine", "Sine", "Sine", "Sine", "Sine", "Sine"),
    "CollType": ("KILL", "MOVE_STOP", "COLL_STOP"),
    "PolygonAxis": ("YZ plane (+X)", "YZ plane (-X)", "XZ plane (+Y)", "XZ plane (-Y)", "XY plane (+Z)",
                    "XY plane (-Z)", "XY plane (+Z, 6)"),
    "PolygonFixType": ("Centre", "Top-left", "Top-right", "Bottom-left", "Bottom-right", "Top-centre",
                       "Bottom-centre", "Left-centre", "Right-centre", "PatCenter"),
    "SizePlaceType": ("None", "Linear", "Peak at No", "From No", "Up to No"),
    "ColorPlaceType": ("None", "Linear", "Peak at No", "From No", "Up to No"),
    "SizePlaceInpType": ("Linear", "Sin", "1 - cos", "Smooth"),
    "ColorPlaceInpType": ("Linear", "Sin", "1 - cos", "Smooth"),
    "PrimModelType": ("Ring", "TexRing", "Sphere", "TexSphere", "Grid", "TexGrid"),
    "LightType": ("Point", "Spot"),
    "PathStripType": ("0", "Linear", "Hermite", "Spline"),
    "ReleaseType": ("0", "WORK_SPEED", "PATH_SPEED"),
}
# EnumProperty items must stay referenced while Blender uses them
_ENUM_ITEMS = {name: [(str(i), f"{i} {label}", "") for i, label in enumerate(labels)]
               for name, labels in _ENUM_LABELS.items()}
_NO_ITEMS = [("0", "0", "")]
# integer fields shown as one checkbox per named bit (bits without a name keep their value)
_FLAG_LABELS = {
    "TransMode": ((0x1, "World (main view)"), (0x2, "Reflection"), (0x4, "Shadow Receive"), (0x8, "Shadow Cast"),
                  (0x10, "Environment Map"), (0x20, "Motion Blur")),   # cTrans::MODE
    "ColorFlag": ((0x1, "Blend Red"), (0x2, "Blend Green"), (0x4, "Blend Blue"), (0x8, "Blend Alpha"),
                  (0x10, "Each Channel Random")),   # nEffect::COLOR_FLAG (0x20 CHOICE isn't in DX9)
    "AnimFlag": ((0x1, "Play"), (0x2, "Loop"), (0x4, "Backwards"), (0x8, "Remove at End"),
                 (0x100, "Flip Horizontal"), (0x200, "Flip Vertical"), (0x400, "Random Flip Horizontal"),
                 (0x800, "Random Flip Vertical"), (0x1000, "Rotate 90°")),   # rEffectAnim::ANIM_FLAG, DX9 bits
    "ParticleOptionFlag": (   # rEffectList::PARTICLE_OPTION_FLAG, the bits the DX9 game reads
        (0x1, "Sort Each Particle"), (0x2, "Fixed Sort Depth"), (0x100, "Sort at Owner"), (0x40, "Keep Behind Camera"),
        (0x80000000, "Sort Bias Toward Camera"), (0x4, "Soft Edges"), (0x10, "Refraction"), (0x20, "Full Resolution"),
        (0x80, "No Depth Test"), (0x1000, "No Fog"), (0x400000, "Face Culling"), (0x400, "Parallax Volume"),
        (0x800, "Depth Volume"), (0x200, "World Scale"), (0x40000, "Scale After Rotation"), (0x100000, "Ignore Generator Rotation"),
        (0x200000, "Keep Spawn Rotation"), (0x10000, "Pivot at PatCenter"), (0x20000, "Extended Line Position"),
        (0x80000, "Fade Edges")),
    "LightAttribute": ((0x2, "SH"), (0x8, "Per-Pixel"), (0x10, "Simple")),   # rEffectList::LIGHT_ATTR
    "CullingFlag": ((0x1, "Distance / Angle Fade"), (0x2, "Occlusion Test"), (0x4, "Per Particle"),
                    (0x80, "Angle Fade")),   # rEffectList::CULLING_FLAG
    "ModelAnimFlag": ((0x1, "Play Parts"), (0x2, "Loop"), (0x4, "Backwards"), (0x8, "Remove at End"),
                      (0x10, "UV Scroll"), (0x10000, "Use ModelZofs")),   # nEffect::MODEL_ANIM_FLAG; 0x10 per DX9
}

# Particle tab sections: (key, label, tooltip, field and bit-field names). Fields of a Line / Cloth extension go in
# "line"; anything not listed goes in "other". A bit-field not listed goes with the word it lives in.
PTCL_SECTIONS = [
    ("draw", "Drawing & Blending", "When and how the particle is drawn: views, blending, draw order, culling",
     ("TransMode", "PrimMaterialFlags", "BlendSrc", "BlendDst", "BlendOp", "PassBits", "ParticleOptionFlag",
      "CullingFlag", "VolumeBlendRate", "FixOtDepth", "OtDepthBias", "zOfs", "EntryType", "DrawFlags_0x41",
      "DiffuseFactor",
      "LightGroupFlag")),
    ("tex", "Texture & Flipbook", "Textures, the .ean flipbook and how its frames play",
     ("BaseMapPath", "MaskMapPath", "NormalMapPath", "TexturePath", "LensFlarePath", "AnimPath", "AnimFlag",
      "SeqNoMin", "SeqNoRange", "PatNoMin", "PatNoMax", "PatNoRange", "PatSpeed", "PatCenter", "TextureInvW",
      "TextureInvH", "ScrollU", "ScrollV", "HoriTexDivNum", "RotTexDivNum")),
    ("color", "Colour", "Colours, intensity and fading",
     ("Color0", "Color1", "ColorFlag", "Intensity", "ColorPlaceNo", "ColorPlaceType", "ColorPlaceInpType",
      "HoriColorPlaceNo", "PlaceColor", "PlaceColor1", "PlaceColor2", "StripColorFlags", "LayerDivideNum",
      "NormAttenuateFlag", "NormAttenuateAngleStart", "NormAttenuateAngleEnd", "NormAttenuateCurve")),
    ("size", "Size & Shape", "Scale, size and the shape of polygons and PrimModels",
     ("Scale", "ScaleAdd", "AspectRatio", "AspectRatioAdd", "Width", "WidthAdd", "Height", "HeightAdd", "Radius",
      "RadiusAdd", "HeadSize", "HeadSizeAdd", "PlaceSize", "PlaceSizeAdd", "WidthPlaceRate", "DistortRate",
      "PolygonFlags", "PolygonAxis", "PolygonBillBoardType", "PolygonDivideNum", "PolygonFixType", "PrimFlags",
      "PrimModelType", "HoriDivNum", "HoriDrawStart", "HoriDrawEnd", "RotDivNum", "RotDrawStart", "RotDrawEnd",
      "SplineDivideNum", "SizePlaceType", "SizePlaceInpType", "SizePlaceNo", "ModelScale", "ModelScaleAdd")),
    ("rot", "Rotation", "Angle, rotation, spin and which way the particle faces",
     ("Angle", "AngleAdd", "Rot", "RotAdd", "RotAddCoef", "RotAxisOrder", "RotAxisType", "RotOrder", "Axis",
      "DirAxisType", "ModelBillboardType")),
    ("model", "Model", "The .mod drawn by Model particles and its animation",
     ("ModelPath", "ModelFlags", "ModelAnimFlag", "ModelZofs", "AnimSpeed", "PartsNoMin", "PartsNoRange",
      "PartsNoMax")),
    ("line", "Line & Cloth", "Line, trail and cloth settings, including the LineType / ClothType extension",
     ("LineFlags", "LineType", "LineOfsNum", "SizePlaceFlags", "ClothType", "ClothParam", "FollowFrame")),
    ("light", "Light", "Light particles: colour, range and spot settings",
     ("LightAttribute", "LightColorW", "LightMaskY", "LightTypeFlags", "LightType",
      "AttenuateStart", "AttenuateStartAdd", "AttenuateEnd", "AttenuateEndAdd", "SpotFlags")),
    ("other", "Other", "Fields not sorted into a section, mostly not understood yet", ()),
]
_PTCL_SECTION_OF = {name: key for key, _, _, names in PTCL_SECTIONS for name in names}
_PTCL_SECTION_INDEX = {key: i for i, (key, *_) in enumerate(PTCL_SECTIONS)}


def ptcl_section(name, word=None, extension=False):
    """Section key of a particle field (or of a bit-field living in word)."""
    if extension:
        return "line"
    return _PTCL_SECTION_OF.get(name) or _PTCL_SECTION_OF.get(word) or "other"
INP_TYPES = [("0", "Linear", "Straight lines between keys"),
             ("1", "Hermite", "A smooth curve through the keys"),
             ("2", "Lagrange", "A 4-point cubic through the keys")]
REF_TYPES = [("0", "Particle age", "Key frames count from each particle's birth"),
             ("1", "Generator timer", "Key frames count on the generator's timer"),
             ("2", "Effect timer", "Key frames count from the effect's start"),
             ("3", "Parent effect timer", "Key frames count on the parent effect's timer"),
             ("4", "Global effect timer", "Key frames count on the global effect timer"),
             ("5", "Particle age (5)", "Treated like Particle age"),
             ("6", "Particle age (6)", "Treated like Particle age"),
             ("7", "Particle age (7)", "Treated like Particle age")]
VALUE_TIP = "The field's value. Hover the field's name for what it does and how to edit it"
TIER_TIPS = {"dx9": "Verified in the DX9 game code",
             "se": "From the Special Edition symbols; not confirmed in the DX9 code",
             "prior": "Name from an earlier reverse-engineering pass; its meaning isn't verified",
             "unknown": "Meaning unknown"}
_KEY_DEFAULTS = {"f32": [1.0, 0.0], "u32": [0, 0], "vec3": [0.0] * 6, "fixangle": [0] * 6,
                 "color": [255, 255, 255, 255, 255, 255, 255, 255]}

_loading = False
_kf_items = {}   # target name -> enum items (kept alive for Blender)


def _state(context=None):
    return (context or bpy.context).scene.albam.efl_editor


# -- write-back -------------------------------------------------------------------------------------

def _container(ob, slot):
    if ":" in slot:
        block_slot, field = slot.split(":", 1)
        return ob["efl_sub"][block_slot][field]
    return ob[f"efl_{slot}"]


def _as_int(value):
    return int(value, 0) if isinstance(value, str) else int(value)


def _item_value(item):
    """The property value an editor item stands for; raises ValueError."""
    multi = item.is_array or item.per > 1
    if item.kind == "floats":
        values = [float(v) for v in item.floats[:item.count]]
    elif item.kind in ("ints", "bit"):
        values = [int(v) for v in item.ints[:item.count]]
        if item.kind == "bit" and not 0 <= values[0] < 1 << item.width:
            raise ValueError(f"must be 0..{(1 << item.width) - 1}")
    elif item.kind == "enum":
        values = [int(item.enum_value)]
    elif item.kind == "flags":
        return to_prop(sum(1 << i for i in range(32) if item.flags[i]))
    elif item.kind == "hex":
        parts = [p.strip() for p in item.text.replace(";", ",").split(",") if p.strip()]
        values = [int(p, 0) for p in parts]
        if len(values) != item.count:
            raise ValueError(f"expected {item.count} value(s)")
        if any(not 0 <= v < 2 ** 32 for v in values):
            raise ValueError("values must be 0..0xFFFFFFFF")
        return to_prop(values if multi else values[0])
    elif item.kind == "color":
        values = []
        for color in (item.color_a, item.color_b)[:item.count // 4]:
            r, g, b, a = (min(max(round(c * 255), 0), 255) for c in color)
            values += [b, g, r, a]
    elif item.kind == "text":
        if len(item.text.encode("latin-1", "replace")) >= schema.STR_SIZE:
            raise ValueError(f"at most {schema.STR_SIZE - 1} characters")
        return item.text
    else:
        raise ValueError("read-only")
    return values if multi else values[0]


def _show(item, value):
    """Set an item's widgets from a property value (no write-back)."""
    flat = as_list(value)
    if flat is None:
        flat = [value]
    if item.kind == "floats":
        for i, v in enumerate(flat[:MAX_VALUES]):
            item.floats[i] = float(v)
    elif item.kind in ("ints", "bit"):
        for i, v in enumerate(flat[:MAX_VALUES]):
            item.ints[i] = _as_int(v)
    elif item.kind == "enum":
        v = _as_int(flat[0])
        item.enum_value = str(v)
    elif item.kind == "flags":
        v = _as_int(flat[0]) & 0xFFFFFFFF
        for i in range(32):
            item.flags[i] = bool(v >> i & 1)
    elif item.kind == "hex":
        item.text = ", ".join(f"{_as_int(v):#x}" for v in flat)
    elif item.kind == "color":
        ints = [_as_int(v) for v in flat]
        for target, chunk in (("color_a", ints[0:4]), ("color_b", ints[4:8])):
            if len(chunk) == 4:
                b, g, r, a = chunk
                setattr(item, target, (r / 255, g / 255, b / 255, a / 255))
    elif item.kind in ("text", "readonly"):
        item.text = str(value) if item.kind == "text" else _summary(value)


def _summary(value):
    flat = as_list(value)
    if flat is None:
        return f"{value:.6g}" if isinstance(value, float) else str(value)
    return ", ".join(f"{v:.4g}" if isinstance(v, float) else str(v) for v in flat)


def _on_item_edit(item, context):
    global _loading
    if _loading:
        return
    state = _state(context)
    ob = state.target
    if ob is None:
        return
    try:
        value = _item_value(item)
    except ValueError as err:
        item.error = str(err)
        return
    item.error = ""
    container = _container(ob, item.slot)
    container[item.label] = value
    _loading = True
    try:
        if item.kind == "bit" or item.parent:   # keep the word and its bit-fields in step
            word = state.fields.get(f"{item.slot}/{item.parent}")
            old = _as_int(container[item.parent])
            mask = ((1 << item.width) - 1) << item.shift
            new = (old & ~mask) | ((_as_int(value) << item.shift) & mask)
            container[item.parent] = to_prop(new)
            if word is not None:
                _show(word, container[item.parent])
        for bit in (b for b in state.fields if b.slot == item.slot and b.parent == item.label):
            bit_value = (_as_int(value) >> bit.shift) & ((1 << bit.width) - 1)
            container[bit.label] = bit_value
            _show(bit, bit_value)
        if item.slot == "gen" and item.label == "Scale":   # the base scale is the Empty's scale
            ob.scale = item.floats[0], item.floats[2], item.floats[4]
    finally:
        _loading = False
    if item.slot == "gen" and item.label in ("GroupFlag", "MaterialFlag"):
        root = effect_root(ob)
        if root is not None:
            effect_filter.apply_filter(root)


def _enum_items(item, context):
    return _ENUM_ITEMS.get(item.label, _NO_ITEMS)


@blender_registry.register_blender_prop
class AlbamEflFieldItem(bpy.types.PropertyGroup):
    slot: bpy.props.StringProperty()      # gen / ptcl / life / move, or "<slot>:<offset field>" for sub-structs
    ftype: bpy.props.StringProperty()
    tier: bpy.props.StringProperty()
    note: bpy.props.StringProperty()
    kind: bpy.props.StringProperty()      # floats / ints / hex / text / color / enum / bit / readonly
    element: bpy.props.StringProperty()   # tuple base type, for labels
    is_array: bpy.props.BoolProperty()
    per: bpy.props.IntProperty(default=1)
    count: bpy.props.IntProperty(default=1)
    parent: bpy.props.StringProperty()   # bit-fields: the word they live in
    shift: bpy.props.IntProperty()
    width: bpy.props.IntProperty()
    error: bpy.props.StringProperty()
    help_key: bpy.props.StringProperty()   # "<slot>:<field>" in efl.field_help
    section: bpy.props.StringProperty()    # Particle tab: PTCL_SECTIONS key
    floats: bpy.props.FloatVectorProperty(size=MAX_VALUES, precision=4, description=VALUE_TIP,
                                          update=_on_item_edit)
    ints: bpy.props.IntVectorProperty(size=MAX_VALUES, description=VALUE_TIP, update=_on_item_edit)
    text: bpy.props.StringProperty(description=VALUE_TIP, update=_on_item_edit)
    color_a: bpy.props.FloatVectorProperty(size=4, subtype="COLOR_GAMMA", min=0.0, max=1.0,
                                           description=VALUE_TIP, update=_on_item_edit)
    color_b: bpy.props.FloatVectorProperty(size=4, subtype="COLOR_GAMMA", min=0.0, max=1.0,
                                           description=VALUE_TIP, update=_on_item_edit)
    enum_value: bpy.props.EnumProperty(items=_enum_items, description=VALUE_TIP, update=_on_item_edit)
    flags: bpy.props.BoolVectorProperty(size=32, update=_on_item_edit,
                                        description="Tick to set this flag. Hover the field's name for what each does")
    # name (PropertyGroup.name) = "<slot>/<field>", label = the field name
    label: bpy.props.StringProperty()


# -- keyframes --------------------------------------------------------------------------------------

def _kf_parse(identifier):
    slot, _, field = identifier.partition(":")
    return slot, field


def _pretty_kf(name):
    out = name
    for prefix in ("Keyframe",):
        out = out[len(prefix):] if out.startswith(prefix) else out
    for suffix in ("ParamOffset", "Offset"):
        out = out[:-len(suffix)] if out.endswith(suffix) else out
    return out or name


def keyframe_fields(ob):
    """[(slot, field, value type)] for every typed keyframe offset of a record object's blocks."""
    out = []
    for slot in SLOTS:
        props = ob.get(f"efl_{slot}")
        if props is None:
            continue
        struct = schema.struct_for_props(slot, int(props["type"]), props)
        for f in struct.fields:
            vtype = keyframe_value_type(f)
            if vtype:   # every block spans its offset fields (corpus: 68,167 blocks)
                out.append((slot, f.name, vtype))
    return out


def _kf_prop(ob, slot, field):
    kfs = ob.get("efl_kf")
    if kfs is None or slot not in kfs:
        return None
    prop = kfs[slot].get(field)
    if prop is None:   # stored under an older field name
        old = next((o for o, n in schema.FIELD_ALIASES.items() if n == field), None)
        prop = kfs[slot].get(old) if old else None
    return prop


def _kf_field_items(state, context):
    ob = state.target
    if ob is None:
        return _NO_ITEMS
    items = []
    for slot, field, vtype in keyframe_fields(ob):
        prop = _kf_prop(ob, slot, field)
        count = len(as_list(prop.get("frames")) or []) if prop is not None else 0
        label = f"{_pretty_kf(field)} ({slot}, {vtype})" + (f" - {count} keys" if count else "")
        items.append((f"{slot}:{field}", label, field, "KEYFRAME_HLT" if count else "KEYFRAME", len(items)))
    _kf_items[ob.name] = items or _NO_ITEMS
    return _kf_items[ob.name]


def load_keyframe(state):
    global _loading
    _loading = True
    try:
        state.keys.clear()
        state.kf_vtype = ""
        ob = state.target
        if ob is None or not state.kf_field or ":" not in state.kf_field:
            return
        slot, field = _kf_parse(state.kf_field)
        vtype = next((v for s, f, v in keyframe_fields(ob) if (s, f) == (slot, field)), None)
        prop = _kf_prop(ob, slot, field)
        if prop is not None and prop.get("vtype"):
            vtype = str(prop["vtype"])
        state.kf_vtype = vtype or ""
        if prop is None:
            state.kf_inp, state.kf_ref, state.kf_loop, state.kf_init_only = "0", "0", False, False
            return
        state.kf_inp = str(int(prop.get("InpType", 0)) if int(prop.get("InpType", 0)) < 3 else 0)
        state.kf_ref = str(int(prop.get("RefType", 0)))
        state.kf_loop = bool(prop.get("LoopFlag", 0))
        state.kf_init_only = bool(prop.get("InitOnlyFlag", 0))
        frames = as_list(prop.get("frames")) or []
        params = as_list(prop.get("params")) or []
        per = len(params) // len(frames) if frames else 0
        for i, frame in enumerate(frames):
            key = state.keys.add()
            key.frame = int(frame)
            values = params[i * per:(i + 1) * per]
            if vtype == "color":
                b, g, r, a = values[0:4]
                key.color_a = (r / 255, g / 255, b / 255, a / 255)
                b, g, r, a = values[4:8]
                key.color_b = (r / 255, g / 255, b / 255, a / 255)
            else:
                for j, v in enumerate(values[:6]):
                    key.values[j] = float(v)
    finally:
        _loading = False


def write_keyframe(state):
    ob = state.target
    if ob is None or not state.kf_vtype or ":" not in state.kf_field:
        return
    slot, field = _kf_parse(state.kf_field)
    vtype = state.kf_vtype
    old = _kf_prop(ob, slot, field)
    frames, params = [], []
    for key in state.keys:
        frames.append(int(key.frame))
        if vtype == "color":
            for color in (key.color_a, key.color_b):
                r, g, b, a = (min(max(round(c * 255), 0), 255) for c in color)
                params += [b, g, r, a]
        elif vtype in ("u32", "fixangle"):
            params += [int(round(v)) for v in key.values[:2 if vtype == "u32" else 6]]
        else:
            params += [float(v) for v in key.values[:2 if vtype == "f32" else 6]]
    prop = {"vtype": vtype, "header": old.get("header", "0x0") if old is not None else "0x0",
            "InpType": int(state.kf_inp), "RefType": int(state.kf_ref), "LoopFlag": int(state.kf_loop),
            "InitOnlyFlag": int(state.kf_init_only), "frames": frames, "params": params}
    if ob.get("efl_kf") is None:
        ob["efl_kf"] = {}
    if slot not in ob["efl_kf"]:
        ob["efl_kf"][slot] = {}
    ob["efl_kf"][slot][field] = prop


def _on_kf_field(state, context):
    if not _loading:
        load_keyframe(state)


def _on_kf_edit(owner, context):
    if not _loading:
        write_keyframe(_state(context))


@blender_registry.register_blender_prop
class AlbamEflKeyItem(bpy.types.PropertyGroup):
    frame: bpy.props.IntProperty(
        min=0, update=_on_kf_edit,
        description="Game frame (60 fps) of this key, counted on the keyframe's Timer. Frames must increase")
    values: bpy.props.FloatVectorProperty(
        size=6, precision=4, update=_on_kf_edit,
        description="The key's value and its random part: the game uses value + random x rand "
                    "(X Y Z keys: one pair per axis)")
    color_a: bpy.props.FloatVectorProperty(
        size=4, subtype="COLOR_GAMMA", min=0.0, max=1.0, update=_on_kf_edit,
        description="Colour A of this key. The game mixes colours A and B by a random amount")
    color_b: bpy.props.FloatVectorProperty(
        size=4, subtype="COLOR_GAMMA", min=0.0, max=1.0, update=_on_kf_edit,
        description="Colour B of this key. The game mixes colours A and B by a random amount")


def _on_record_index(state, context):
    """Clicking a row of the records list makes that record active and loads it."""
    if _loading or not 0 <= state.records_index < len(state.records):
        return
    ob = state.records[state.records_index].ob
    if ob is None or ob.name not in context.view_layer.objects:
        return
    for other in context.selected_objects:
        if other is not None:   # a rebuild may have just removed it
            other.select_set(False)
    context.view_layer.objects.active = ob
    ob.select_set(True)
    if state.target != ob:
        load_record(state, ob)


@blender_registry.register_blender_prop
class AlbamEflRecordItem(bpy.types.PropertyGroup):
    # name (PropertyGroup.name) = the row label, so the list's name filter searches it
    ob: bpy.props.PointerProperty(type=bpy.types.Object)
    index: bpy.props.IntProperty()
    is_new: bpy.props.BoolProperty()


TABS = [("gen", "Generator", "Generator block: where, when and how many particles spawn"),
        ("ptcl", "Particle", "Particle block: the particle type and its look (texture, blending, colour, size)"),
        ("life", "Life", "Life block: how long particles live and how they fade in and out"),
        ("move", "Move", "Move block: how particles move after they spawn"),
        ("keys", "Keys", "Keyframes: animate a field over time"),
        ("more", "More", "The record's collision and culling settings")]


def _on_filter_edit(state, context):
    """Spawn filter widgets: store the masks on the effect and re-filter its records."""
    if _loading or state.records_root is None:
        return
    effect_filter.set_masks(state.records_root, *effect_filter.masks_from_options(state))
    effect_filter.apply_filter(state.records_root)


@blender_registry.register_blender_prop_albam(name="efl_editor")
class AlbamEflEditor(bpy.types.PropertyGroup):
    target: bpy.props.PointerProperty(type=bpy.types.Object)
    tab: bpy.props.EnumProperty(items=TABS, default="ptcl", description="Which part of the record to edit")
    search: bpy.props.StringProperty(name="Search", options={"TEXTEDIT_UPDATE"},
                                     description="Show only the fields whose name contains this text")
    show_unverified: bpy.props.BoolProperty(
        name="Unverified", description="Also show fields whose meaning isn't verified in the DX9 code")
    show_notes: bpy.props.BoolProperty(name="Notes", description="Show the reverse-engineering note of each field")
    show_records: bpy.props.BoolProperty(name="Records", default=True,
                                         description="Show the list of the effect's records")
    show_filter: bpy.props.BoolProperty(
        name="Spawn Filter", default=True,
        description="Show the spawn filter: which records the game builds for a given spawn call")
    group_all: effect_filter.group_all_prop(_on_filter_edit)
    group_bits: effect_filter.group_bits_prop(_on_filter_edit)
    surface: effect_filter.surface_prop(_on_filter_edit)
    records_root: bpy.props.PointerProperty(type=bpy.types.Object)
    records: bpy.props.CollectionProperty(type=AlbamEflRecordItem)
    records_index: bpy.props.IntProperty(update=_on_record_index,
                                         description="Click a record to make it active and edit it")
    fields: bpy.props.CollectionProperty(type=AlbamEflFieldItem)
    kf_field: bpy.props.EnumProperty(
        name="Keyframe", items=_kf_field_items, update=_on_kf_field,
        description="Which keyframe of the record to edit. A field with keys uses them instead of its plain value")
    kf_vtype: bpy.props.StringProperty()
    kf_inp: bpy.props.EnumProperty(name="Interpolation", items=INP_TYPES, update=_on_kf_edit,
                                   description="How the value changes between keys")
    kf_ref: bpy.props.EnumProperty(name="Timer", items=REF_TYPES, update=_on_kf_edit,
                                   description="Which clock the key frames count on")
    kf_loop: bpy.props.BoolProperty(name="Loop", update=_on_kf_edit,
                                    description="Start over after the last key instead of holding its value")
    kf_init_only: bpy.props.BoolProperty(
        name="Init only", update=_on_kf_edit,
        description="Evaluate the keys once, when the particle spawns; after that the field's Add value applies. "
                    "Off: the keys set the value every frame (and Add is ignored)")
    keys: bpy.props.CollectionProperty(type=AlbamEflKeyItem)
    key_index: bpy.props.IntProperty(description="Click a key to select it")
    ptcl_open: bpy.props.BoolVectorProperty(
        size=len(PTCL_SECTIONS), default=[key in ("tex", "color", "size") for key, *_ in PTCL_SECTIONS],
        description="Click to show or hide this group of particle fields")


# -- loading ----------------------------------------------------------------------------------------

def _add_field(state, slot, f, value):
    item = state.fields.add()
    item.name, item.label, item.slot = f"{slot}/{f.name}", f.name, slot
    item.ftype, item.tier, item.note = f.type, f.tier, f.note
    item.help_key = f"{slot}:{f.name}"
    base, n = schema.parse_type(f.type)
    item.element, item.is_array = base, n is not None
    item.per = _TUPLE_SIZE.get(base, 1)
    item.count = item.per * (n or 1)
    reason = READ_ONLY.get((slot, f.name))
    if reason or (item.count > MAX_VALUES and base != "u32"):
        item.kind = "readonly"
        item.note = reason or item.note
    elif base == "str64":
        item.kind = "text"
    elif f.name in _FLAG_LABELS and slot in ("ptcl", "gen", "life", "move") and n is None and \
            base in ("u8", "u16", "u32", "s8", "s16", "s32"):
        item.kind = "flags"
    elif base == "u32":
        item.kind = "hex"
    elif base == "color" and item.count <= 8:
        item.kind = "color"
    elif f.name in _ENUM_ITEMS and n is None and item.per == 1 and _as_int(value) < len(_ENUM_LABELS[f.name]):
        item.kind = "enum"
    elif base in _FLOAT_BASES:
        item.kind = "floats"
    else:
        item.kind = "ints"
    _show(item, value)
    return item


def _add_bit(state, slot, b, value):
    item = state.fields.add()
    item.name, item.label, item.slot = f"{slot}/{b.name}", b.name, slot
    item.tier, item.note, item.ftype = b.tier, b.note, f"bits {b.shift}..{b.shift + b.width - 1}"
    item.help_key = f"{slot}:{b.name}"
    item.parent, item.shift, item.width = b.field, b.shift, b.width
    if b.name in _ENUM_ITEMS and _as_int(value) < len(_ENUM_LABELS[b.name]):
        item.kind = "enum"
    else:
        item.kind = "bit"
    _show(item, value)
    return item


def load_record(state, ob):
    """Fill the editor with a record object's fields."""
    global _loading
    _loading = True
    try:
        state.fields.clear()
        state.target = ob
        if ob is None:
            return
        for slot in SLOTS:
            props = ob.get(f"efl_{slot}")
            if props is None:
                continue
            upgraded = upgrade_props(props.to_dict() if hasattr(props, "to_dict") else props)
            if upgraded is not props and set(upgraded) != set(props.keys()):   # an older import: store today's fields
                ob[f"efl_{slot}"] = upgraded
                props = ob[f"efl_{slot}"]
            struct = schema.struct_for_props(slot, int(props["type"]), props)
            bits = {}
            for b in struct.bits:
                bits.setdefault(b.field, []).append(b)
            for f in struct.fields:
                if f.name not in props or f.sub:   # offsets are layout (older imports stored them)
                    continue
                item = _add_field(state, slot, f, props[f.name])
                extension = f.offset >= struct.base_size
                item.section = ptcl_section(f.name, extension=extension)
                for b in bits.get(f.name, []):
                    if b.name in props:
                        _add_bit(state, slot, b, props[b.name]).section = ptcl_section(b.name, f.name, extension)
            subs = (ob.get("efl_sub") or {}).get(slot) or {}
            for offset_field in subs.keys():
                f = struct.by_name.get(offset_field)
                sub_struct = schema.SUB_STRUCTS.get(f.sub) if f is not None else None
                if sub_struct is None:
                    continue
                for sf in sub_struct.fields:
                    if sf.name in subs[offset_field]:
                        item = _add_field(state, f"{slot}:{offset_field}", sf, subs[offset_field][sf.name])
                        item.help_key = f"{f.sub}:{sf.name}"
    finally:
        _loading = False
    root = effect_root(ob)
    if root is not None and (state.records_root != root or all(item.ob != ob for item in state.records)):
        sync_records(state, root, ob)
    else:
        global_index = next((i for i, item in enumerate(state.records) if item.ob == ob), None)
        if global_index is not None and state.records_index != global_index:
            _loading = True
            try:
                state.records_index = global_index
            finally:
                _loading = False
    items = _kf_field_items(state, bpy.context)
    if items and items is not _NO_ITEMS and state.kf_field not in {i[0] for i in items}:
        _set_kf_field(state, items[0][0])
    load_keyframe(state)


def _set_kf_field(state, identifier):
    global _loading
    _loading = True
    try:
        state.kf_field = identifier
    finally:
        _loading = False


def sync_records(state, root, active=None):
    """Mirror the effect's record objects into the scrollable records list."""
    global _loading
    _loading = True
    try:
        state.records.clear()
        state.records_root = root
        if root is None:
            return
        state.group_all, state.group_bits, state.surface = effect_filter.options_from_masks(
            *effect_filter.get_masks(root))
        try:
            obs = ordered_record_objects(root)
        except Exception:   # duplicated records: still list them
            obs = sorted(all_record_objects(root), key=lambda o: (int(o["efl_record"]) < 0, int(o["efl_record"])))
        for index, ob in enumerate(obs):
            item = state.records.add()
            item.ob, item.index, item.is_new = ob, index, int(ob["efl_record"]) < 0
            item.name = (f"{index:02d}  {ob.get('efl_particle_type', '?')} / {ob.get('efl_move_type', '?')}"
                         + ("  (new)" if item.is_new else ""))
            if ob == active:
                state.records_index = index
    finally:
        _loading = False


def refresh_editor(context):
    """Load the active record and the record list (after the effect's objects were rebuilt)."""
    active = context.view_layer.objects.active
    load_record(_state(context), record_object(active))
    sync_records(_state(context), effect_root(active), record_object(active))


# -- operators --------------------------------------------------------------------------------------

@blender_registry.register_blender_type
class ALBAM_OT_EflSelectRecord(bpy.types.Operator):
    """Make this record active and edit it"""
    bl_idname = "albam.efl_select_record"
    bl_label = "Edit Record"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty()

    def execute(self, context):
        ob = bpy.data.objects.get(self.name) if self.name else record_object(context.active_object)
        if ob is None or "efl_record" not in ob:
            return {"CANCELLED"}
        if ob.name in context.view_layer.objects:
            for other in context.selected_objects:
                if other is not None:   # a rebuild may have just removed it
                    other.select_set(False)
            context.view_layer.objects.active = ob
            ob.select_set(True)
        load_record(_state(context), ob)
        return {"FINISHED"}


def _linked_changes(root):
    try:
        from .effect_export import linked_changes
        return linked_changes(root)
    except Exception:   # e.g. a strip mid-edit with a branch: drawing must not fail
        return []


@blender_registry.register_blender_type
class ALBAM_OT_EflSelectLinked(bpy.types.Operator):
    """Select this .efs strip or .ean flipbook to edit it. A strip is a mesh: edit its points in Edit Mode. A
    flipbook is a mesh whose faces' UVs are the frames: Select Frames in the Image Editor's Albam tab (Flipbook
    panel), then edit them in the UV editor. Press Apply afterwards to see the edits in the effect's preview"""
    bl_idname = "albam.efl_select_linked"
    bl_label = "Edit Linked File"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        ob = bpy.data.objects.get(self.name)
        if ob is None or ob.name not in context.view_layer.objects:
            return {"CANCELLED"}
        for other in context.selected_objects:
            if other is not None:   # a rebuild may have just removed it
                other.select_set(False)
        ob.hide_set(False)
        context.view_layer.objects.active = ob
        ob.select_set(True)
        if ob.albam_asset.extension == "ean":
            from .effect_ean import load_target
            load_target(context.scene.albam.ean_editor, ob)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EflSyncRecords(bpy.types.Operator):
    """List the records of the active effect"""
    bl_idname = "albam.efl_sync_records"
    bl_label = "Refresh Records"

    def execute(self, context):
        active = context.view_layer.objects.active
        sync_records(_state(context), effect_root(active), record_object(active))
        return {"FINISHED"}


_USAGE = {
    "rangef": "Range: base and +rand. The game uses base + random x rand (a new random each time it's used)",
    "rangeu16": "Range of whole numbers: base and +rand. The game uses base + random x rand",
    "vec3": "X Y Z in game axes (Y is up)",
    "vec4": "X Y Z W",
    "point": "X Y",
    "easecurve": "Ease curve: two shape values A and B",
    "f32": "A number",
    "u32": "A 32-bit word in hex (0x...). Arrays: comma-separated words",
    "str64": "Text, at most 63 characters. Paths are relative to the arc root, without an extension",
}


def field_tooltip(item):
    """Tooltip for an editor field: what it does (schema note), how to edit it, and how sure the layout is."""
    lines = []
    help_text = field_help(item.help_key)
    read_only = item.kind == "readonly" and item.note in READ_ONLY.values()
    if help_text:
        lines.append(help_text)
    if read_only:
        lines.append(f"Read-only here: {item.note}")
    elif item.note and not help_text:
        lines.append(item.note[0].upper() + item.note[1:])
    if item.kind == "bit":
        lines.append(f"Bits {item.shift}..{item.shift + item.width - 1} of {item.parent} "
                     f"(0..{(1 << item.width) - 1}). Editing it updates {item.parent}, and the other way round")
    elif item.kind == "enum":
        lines.append("Pick one of the values the game handles")
        if item.parent:
            lines.append(f"Stored in bits {item.shift}..{item.shift + item.width - 1} of {item.parent}")
    elif item.kind == "flags":
        lines.append("Tick the flags to set them; bits without a checkbox keep their value")
    elif item.kind == "color":
        lines.append("Colour (stored as B, G, R, A bytes)" + (". Two colours: the game mixes A and B by a "
                                                              "random amount" if item.count > 4 else ""))
    else:
        usage = _USAGE.get(item.element)
        if item.element in ("rangef", "rangeu16") and "rand" in help_text:   # the help explains this range
            usage = None
        if usage:
            lines.append(usage)
        if item.is_array:
            lines.append(f"{item.count // max(item.per, 1)} values")
    if item.slot == "gen" and item.label in ("GroupFlag", "MaterialFlag"):
        lines.append("Change the Spawn Filter above to preview which spawn calls build this record")
    lines.append(f"Type {item.ftype}. {TIER_TIPS.get(item.tier, TIER_TIPS['unknown'])}")
    if help_text and item.note and not read_only:
        lines.append(f"RE note: {item.note}")
    return ".\n".join(line.rstrip(".") for line in lines) + "."


@blender_registry.register_blender_type
class ALBAM_OT_EflFieldInfo(bpy.types.Operator):
    """What this field does and how to edit it"""
    bl_idname = "albam.efl_field_info"
    bl_label = "Field Info"
    bl_options = {"INTERNAL"}

    field: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        item = _state(context).fields.get(properties.field)
        return field_tooltip(item) if item is not None else cls.__doc__

    def execute(self, context):
        item = _state(context).fields.get(self.field)
        if item is not None:   # clicking shows the tooltip in the status bar too
            self.report({"INFO"}, f"{item.label}: " + field_tooltip(item).replace("\n", " "))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_UL_EflRecords(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.ob is None:
            layout.label(text=item.name + "  (deleted)", icon="ERROR")
            return
        if item.ob.get("efl_filtered"):
            layout.label(text=item.name + "  (filtered out)", icon="HIDE_ON")
        else:
            layout.label(text=item.name, icon="ADD" if item.is_new else "PARTICLES")


@blender_registry.register_blender_type
class ALBAM_OT_EflRevertRecord(bpy.types.Operator):
    """Reset the record's fields, keyframes and collision/culling values to the effect's current source data
    (the Empty's transform and parent are kept)"""
    bl_idname = "albam.efl_revert_record"
    bl_label = "Revert Fields"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _state(context).target is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from .efl import EffectList
        from .efl.edit import block_props, keyframe_props, record_from_raw, sub_props
        from .efl.model import Block
        from .effect_export import _raw_of, _replaced_of, source_bytes
        ob = _state(context).target
        index = int(ob["efl_record"])
        if index >= 0:
            record = EffectList.from_bytes(source_bytes(effect_root(ob))).records[index]
            for slot, (btype, data) in (_replaced_of(ob) or {}).items():   # a changed type not applied yet
                setattr(record, slot, Block(slot, btype, bytearray(data)))
        else:
            record = record_from_raw(_raw_of(ob))
        keyframes, subs = {}, {}
        for slot, block in record.blocks():
            if block is not None:
                ob[f"efl_{slot}"] = block_props(block)
                keyframes[slot], subs[slot] = keyframe_props(block), sub_props(block)
        ob["efl_kf"], ob["efl_sub"] = keyframes, subs
        load_record(_state(context), ob)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EflKeyAdd(bpy.types.Operator):
    """Add a key after the active one (a copy of it, 10 frames later), or the first key of a new keyframe"""
    bl_idname = "albam.efl_key_add"
    bl_label = "Add Key"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        state = _state(context)
        return state.target is not None and bool(state.kf_vtype) and len(state.keys) < 255

    def execute(self, context):
        global _loading
        state = _state(context)
        _loading = True
        try:
            if len(state.keys):
                src = state.keys[min(state.key_index, len(state.keys) - 1)]
                key = state.keys.add()
                key.frame = max(k.frame for k in state.keys) + 10
                key.values, key.color_a, key.color_b = src.values[:], src.color_a[:], src.color_b[:]
            else:
                key = state.keys.add()
                defaults = _KEY_DEFAULTS[state.kf_vtype]
                if state.kf_vtype == "color":
                    key.color_a = key.color_b = (1.0, 1.0, 1.0, 1.0)
                else:
                    for i, v in enumerate(defaults):
                        key.values[i] = v
            state.key_index = len(state.keys) - 1
        finally:
            _loading = False
        write_keyframe(state)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EflKeyRemove(bpy.types.Operator):
    """Remove the active key (removing every key removes the keyframe)"""
    bl_idname = "albam.efl_key_remove"
    bl_label = "Remove Key"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        state = _state(context)
        return state.target is not None and len(state.keys) > 0

    def execute(self, context):
        state = _state(context)
        state.keys.remove(min(state.key_index, len(state.keys) - 1))
        state.key_index = max(min(state.key_index, len(state.keys) - 1), 0)
        write_keyframe(state)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EflKeySort(bpy.types.Operator):
    """Sort the keys by frame (the game needs increasing frames)"""
    bl_idname = "albam.efl_key_sort"
    bl_label = "Sort Keys"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(_state(context).keys) > 1

    def execute(self, context):
        state = _state(context)
        write_keyframe(state)
        slot, field = _kf_parse(state.kf_field)
        prop = _kf_prop(state.target, slot, field)
        frames, params = as_list(prop["frames"]), as_list(prop["params"])
        per = len(params) // len(frames)
        order = sorted(range(len(frames)), key=lambda i: frames[i])
        prop["frames"] = [frames[i] for i in order]
        prop["params"] = [v for i in order for v in params[i * per:(i + 1) * per]]
        load_keyframe(state)
        return {"FINISHED"}


# -- panel ------------------------------------------------------------------------------------------

@blender_registry.register_blender_type
class ALBAM_UL_EflKeys(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        state = data
        row = layout.row(align=True)
        row.prop(item, "frame", text="")
        vtype = state.kf_vtype
        if vtype == "color":
            row.prop(item, "color_a", text="")
            row.prop(item, "color_b", text="")
        elif vtype in ("f32", "u32"):
            row.prop(item, "values", index=0, text="")
            row.prop(item, "values", index=1, text="+rand")
        else:
            for axis in range(3):
                row.prop(item, "values", index=2 * axis, text="XYZ"[axis])


def _draw_sections(layout, state, items, searching):
    """Particle tab: the fields in collapsible groups (all open while searching)."""
    groups = {}
    for item in items:
        groups.setdefault(item.section if item.section in _PTCL_SECTION_INDEX else "other", []).append(item)
    for index, (key, label, _, _) in enumerate(PTCL_SECTIONS):
        group = groups.get(key)
        if not group:
            continue
        box = layout.box()
        is_open = searching or state.ptcl_open[index]
        box.prop(state, "ptcl_open", index=index, text=f"{label} ({len(group)})", emboss=False,
                 icon="TRIA_DOWN" if is_open else "TRIA_RIGHT")
        if is_open:
            col = box.column(align=False)
            for item in group:
                _draw_field(col, item, state.show_notes)


def _draw_field(layout, item, show_notes):
    box_row = layout.row(align=True)
    split = box_row.split(factor=0.42, align=True)
    label = ("    " + item.label) if item.kind == "bit" or item.parent else item.label
    split.operator("albam.efl_field_info", text=label, emboss=False,
                   icon="ERROR" if item.error else TIER_ICONS.get(item.tier, "QUESTION")).field = item.name
    right = split.column(align=True)
    if item.kind in ("floats", "ints"):
        prop = "floats" if item.kind == "floats" else "ints"
        if item.per > 1:
            names = _ELEMENT_LABELS.get(item.element, ())
            rows = item.count // item.per
            for r in range(rows):
                row = right.row(align=True)
                if rows > 1:
                    row.label(text=_ROW_LABELS[r])
                for e in range(item.per):
                    row.prop(item, prop, index=r * item.per + e, text=names[e] if e < len(names) else "")
        else:
            row = right.row(align=True)
            for i in range(item.count):
                row.prop(item, prop, index=i, text="")
    elif item.kind == "bit":
        right.prop(item, "ints", index=0, text="")
    elif item.kind == "enum":
        right.prop(item, "enum_value", text="")
    elif item.kind == "flags":
        named = 0
        for bit, text in _FLAG_LABELS.get(item.label, ()):
            right.prop(item, "flags", index=bit.bit_length() - 1, text=text)
            named |= bit
        value = sum(1 << i for i in range(32) if item.flags[i])
        other = value & ~named
        right.label(text=f"= {value:#x}" + (f"  (other bits {other:#x} kept)" if other else ""))
    elif item.kind in ("hex", "text"):
        right.prop(item, "text", text="")
    elif item.kind == "color":
        right.prop(item, "color_a", text="")
        if item.count > 4:
            right.prop(item, "color_b", text="")
    else:
        right.label(text=item.text or "-")
    if item.error:
        layout.label(text=f"{item.label}: {item.error}", icon="ERROR")
    elif show_notes and item.note:
        layout.label(text=item.note[:120])


@blender_registry.register_blender_type
class ALBAM_PT_EflEditor(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_EflEditor"
    bl_label = "Effect Editor"
    bl_region_type = "UI"
    bl_space_type = "VIEW_3D"

    @classmethod
    def poll(cls, context):
        return effect_root(context.active_object) is not None

    def draw(self, context):
        layout = self.layout
        state = _state(context)
        root = effect_root(context.active_object)
        row = layout.row(align=True)
        row.label(text=root.albam_asset.relative_path or root.name, icon="PARTICLES")
        layout.operator("albam.efl_apply_edits", text="Apply", icon="PLAY")
        layout.prop(context.scene.albam.import_options_efl, "darken_strength")
        missing = list(root.get("efl_missing_textures") or [])
        if missing:
            box = layout.box()
            box.label(text=f"{len(missing)} texture(s) missing: particles show as solid shapes", icon="ERROR")
            for path in missing[:3]:
                box.label(text=path)
            if len(missing) > 3:
                box.label(text=f"... and {len(missing) - 3} more")
            box.label(text="Add the folder containing effect\\tex (e.g. the base game's) as a Game Files root,")
            box.label(text="then press Apply")
        from .effect import linked_objects
        linked = linked_objects(root)
        box = layout.box()
        box.label(text="Linked files (exported with the effect when changed)", icon="LINKED")
        changed = {ob.name for ob, _ in _linked_changes(root)}
        for key, ob in sorted(linked.items()):
            row = box.row(align=True)
            icon = "CURVE_PATH" if key.startswith("efs:") else "IMAGE_DATA"
            label = ob.albam_asset.relative_path + ("  (edited: Apply to preview)" if ob.name in changed else "")
            row.operator("albam.efl_select_linked", text=label, icon=icon, emboss=False).name = ob.name
        row = box.row(align=True)
        row.operator("albam.efs_new", icon="CURVE_PATH")
        row.operator("albam.ean_new", icon="IMAGE_DATA")

        box = layout.box()
        box.row().prop(state, "show_filter", icon="TRIA_DOWN" if state.show_filter else "TRIA_RIGHT",
                       emboss=False)
        if state.show_filter:
            if state.records_root != root:
                box.operator("albam.efl_sync_records", text="Load this effect's filter", icon="FILE_REFRESH")
            else:
                effect_filter.draw_filter(box, state, root)
                total = len(state.records)
                shown = int(root.get("efl_filter_shown", total))
                if shown == 0:
                    box.label(text="No record passes: the game shows nothing", icon="ERROR")
                else:
                    box.label(text=f"Showing {shown} of {total} records", icon="HIDE_OFF")

        box = layout.box()
        header = box.row()
        header.prop(state, "show_records", icon="TRIA_DOWN" if state.show_records else "TRIA_RIGHT", emboss=False)
        active = record_object(context.active_object)
        if state.show_records:
            if state.records_root != root or any(item.ob is None for item in state.records):
                box.operator("albam.efl_sync_records", text="List this effect's records", icon="FILE_REFRESH")
            else:
                box.template_list("ALBAM_UL_EflRecords", "", state, "records", state, "records_index",
                                  rows=6, maxrows=12)
        row = box.row(align=True)
        row.operator("albam.efl_duplicate_record", text="Duplicate", icon="DUPLICATE")
        row.operator("albam.efl_copy_record_to", text="Copy to", icon="PASTEDOWN")
        row.operator("albam.efl_remove_record", text="Remove", icon="X")

        if active is None:
            layout.label(text="Pick a record to edit it")
            return
        if state.target != active:
            layout.operator("albam.efl_select_record", text=f"Edit {active.name}", icon="GREASEPENCIL").name = active.name
            return

        layout.row().prop(state, "tab", expand=True)
        if state.tab == "keys":
            self.draw_keys(layout, state)
            return
        if state.tab in ("ptcl", "move"):
            props = active.get(f"efl_{state.tab}")
            row = layout.row(align=True)
            row.label(text=f"Type: {props.get('type_name', '?') if props is not None else 'none'}",
                      icon="PARTICLES" if state.tab == "ptcl" else "FORCE_FORCE")
            if props is not None:
                row.operator("albam.efl_change_type", text="Change Type", icon="FILE_REFRESH").slot = state.tab
        row = layout.row(align=True)
        row.prop(state, "search", text="", icon="VIEWZOOM")
        row.prop(state, "show_unverified", toggle=True)
        row.prop(state, "show_notes", toggle=True)
        row.operator("albam.efl_revert_record", text="", icon="LOOP_BACK")
        search = state.search.lower()
        visible = []
        for item in state.fields:
            in_tab = (":" in item.slot) if state.tab == "more" else item.slot == state.tab
            if not in_tab:
                continue
            if not state.show_unverified and item.tier not in VERIFIED_TIERS:
                continue
            if search and search not in item.label.lower():
                continue
            visible.append(item)
        shown = len(visible)
        if state.tab == "ptcl":
            _draw_sections(layout, state, visible, bool(search))
        else:
            col = layout.column(align=False)
            for i, item in enumerate(visible):
                if state.tab == "more" and (i == 0 or visible[i - 1].slot != item.slot):
                    col.label(text=item.slot.split(":", 1)[1].replace("ParamOffset", ""), icon="MOD_PHYSICS")
                _draw_field(col, item, state.show_notes)
        if not shown:
            layout.label(text="Nothing to show here" + ("" if state.show_unverified else
                                                         " (try Unverified)"))

    def draw_keys(self, layout, state):
        layout.prop(state, "kf_field", text="")
        if not state.kf_vtype:
            layout.label(text="This record has no keyframe slots")
            return
        row = layout.row(align=True)
        row.prop(state, "kf_inp", text="")
        row.prop(state, "kf_ref", text="")
        row = layout.row(align=True)
        row.prop(state, "kf_loop", toggle=True)
        row.prop(state, "kf_init_only", toggle=True)
        labels = {"f32": "frame | value | +rand", "u32": "frame | value | +rand",
                  "color": "frame | colour A | colour B (random mix)",
                  "vec3": "frame | X Y Z (+rand: expand below)", "fixangle": "frame | X Y Z (4096 = 360 deg)"}
        layout.label(text=labels.get(state.kf_vtype, ""))
        row = layout.row()
        row.template_list("ALBAM_UL_EflKeys", "", state, "keys", state, "key_index", rows=4)
        col = row.column(align=True)
        col.operator("albam.efl_key_add", text="", icon="ADD")
        col.operator("albam.efl_key_remove", text="", icon="REMOVE")
        col.operator("albam.efl_key_sort", text="", icon="SORTSIZE")
        if state.kf_vtype in ("vec3", "fixangle") and len(state.keys):
            key = state.keys[min(state.key_index, len(state.keys) - 1)]
            box = layout.box()
            box.label(text=f"Key at frame {key.frame}")
            for axis in range(3):
                row = box.row(align=True)
                row.label(text="XYZ"[axis])
                row.prop(key, "values", index=2 * axis, text="")
                row.prop(key, "values", index=2 * axis + 1, text="+rand")
        frames = [k.frame for k in state.keys]
        if any(b <= a for a, b in zip(frames, frames[1:])):
            layout.label(text="Key frames must increase (use Sort)", icon="ERROR")
        if not len(state.keys):
            layout.label(text="No keys: the field's plain value is used", icon="INFO")


# -- auto-loading the active record -----------------------------------------------------------------

_msgbus_owner = object()


def _on_active_changed():
    context = bpy.context
    scene = getattr(context, "scene", None)
    if scene is None or not hasattr(scene, "albam"):
        return
    active = context.view_layer.objects.active if context.view_layer else None
    ob = record_object(active)
    state = scene.albam.efl_editor
    if ob is not None and state.target != ob:
        load_record(state, ob)
    elif ob is None:
        root = effect_root(active)
        if root is not None and state.records_root != root:
            sync_records(state, root)


def _subscribe():
    bpy.msgbus.clear_by_owner(_msgbus_owner)
    bpy.msgbus.subscribe_rna(key=(bpy.types.LayerObjects, "active"), owner=_msgbus_owner, args=(),
                             notify=_on_active_changed)


@persistent
def _on_load(_dummy=None):
    _kf_items.clear()
    _subscribe()


def register_editor():
    _subscribe()
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister_editor():
    bpy.msgbus.clear_by_owner(_msgbus_owner)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
