"""EFL keyframes as Blender F-curves.

Every typed keyframe of a record ("track": a keyframe offset field of its generator / particle / life / move block)
is edited with Blender's own animation tools:
- the generator's position / rotation / scale keyframes are location / rotation_euler (the game's Euler order) /
  scale keys on the record Empty (the rotation on its RelationType 2 companion when it has one);
- every other track is a custom property on the record Empty named "<Block> <Field>" ("Particle Intensity",
  "Move Speed"; colours are 4 floats, vectors 3) keyed with F-curves. Its random part is the sibling property
  "<track> Rand" (colour: "<track> B", the second colour the game mixes toward): static, or keyed on the same frames.
- key frames are timeline frames counted from the effect's start (root['efl_start_frame'], the start marker):
  scene frame = start + game frame x scene fps / 60; export rounds back to whole game frames. Generator-timer tracks
  (RefType 1) are shifted by the generator's WaitFrame (base value), because the game's generator timer stands
  still through the wait (efl/sim.py clock): the curve shows when the key plays. Particle-age tracks get the same
  shift: they are drawn for the first particle, born when the wait ends. The shift each track's curves
  carry is stored in efl_key_offsets ({track id: game frames}), so export is right whatever WaitFrame says now;
  sync_offsets moves the curves when WaitFrame or the timer changes;
- the game's interpolation type maps to the keys' interpolation (0 linear = LINEAR, 1 hermite / 2 spline = BEZIER,
  which keep the stored type on export), LoopFlag to a Cycles modifier; the timer (RefType) and InitOnlyFlag have no
  Blender equivalent and stay in the stored keyframe header (efl_kf, edited in the Effect Editor's Keys tab).
The record's efl_kf property (efl/edit.py keyframe_props) keeps the file's keyframes and every track's header; export
(keyframe_props_of) replaces the frames / params of each track that has curves, so an untouched track stays
byte-identical. A record Empty built by this module carries efl_keys = 1; older imports (baked generator samples,
keys only in efl_kf) export from efl_kf until a track is animated, which rebuilds their curves first.
"""
import math

import bpy

from .efl import keyframe as kfm
from .efl import schema
from .efl.edit import KF_FLAGS, as_list, keyframe_value_type, kf_from_prop, kf_same, kf_to_prop
from .efl.field_help import lookup as field_help
from .efl.model import SLOTS
from .efl.sim import ROT_ORDERS

SCALE = 0.01
GAME_FPS = 60.0
VERSION_KEY = "efl_keys"   # record Empties whose keyframes are F-curves (this module's layout)
OFFSETS_KEY = "efl_key_offsets"   # {track id: game frames its curves are shifted by (generator-timer tracks: WaitFrame)}
SLOT_LABELS = {"gen": "Generator", "ptcl": "Particle", "life": "Life", "move": "Move"}
RAND = " Rand"
COLOR_B = " B"
TRANSFORM = {("gen", "KeyframePosParamOffset"): "location", ("gen", "KeyframeRotParamOffset"): "rotation_euler",
             ("gen", "KeyframeScaleParamOffset"): "scale"}
SIZES = {"f32": 1, "u32": 1, "color": 4, "vec3": 3, "fixangle": 3}
_KEYABLE_TYPES = ("rangef", "rangef[3]", "rangeu16", "f32", "vec3", "color[2]", "color")


# -- names ------------------------------------------------------------------------------------------

def pretty(field):
    out = field
    if out.startswith("Keyframe"):
        out = out[len("Keyframe"):]
    for suffix in ("ParamOffset", "Offset"):
        out = out[:-len(suffix)] if out.endswith(suffix) else out
    return out or field


def track_name(slot, field):
    return f"{SLOT_LABELS.get(slot, slot)} {pretty(field)}"


def track_id(slot, field):
    return f"{slot}:{field}"


def parse_track(ident):
    slot, _, field = ident.partition(":")
    return slot, field


def _data_path(name):
    return f'["{name}"]'


def tracks(ob):
    """[(slot, offset field, value type)] for every typed keyframe offset of a record object's blocks."""
    out = []
    for slot in SLOTS:
        props = ob.get(f"efl_{slot}")
        if props is None:
            continue
        struct = schema.struct_for_props(slot, int(props["type"]), props)
        for f in struct.offset_fields():
            vtype = keyframe_value_type(f)
            if vtype:
                out.append((slot, f.name, vtype))
    return out


def animated_field(struct, offset_field):
    """The block field a keyframe track animates (its value is the first key's value), or None."""
    name = pretty(offset_field)
    target = struct.by_name.get(name)
    if target is None and name.startswith("Line"):
        target = struct.by_name.get(name[4:])
    return target.name if target is not None and target.type in _KEYABLE_TYPES else None


def field_tracks(ob):
    """{(slot, field name): track id} for the fields of a record object that have a keyframe track."""
    out = {}
    for slot in SLOTS:
        props = ob.get(f"efl_{slot}")
        if props is None:
            continue
        struct = schema.struct_for_props(slot, int(props["type"]), props)
        for f in struct.offset_fields():
            if keyframe_value_type(f):
                name = animated_field(struct, f.name)
                if name is not None:
                    out[(slot, name)] = track_id(slot, f.name)
    return out


# -- timing -----------------------------------------------------------------------------------------

def timing(root, scene=None):
    """(start scene frame, game frames per scene frame) of an effect."""
    scene = scene or bpy.context.scene
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    start = int(root.get("efl_start_frame", scene.frame_current)) if root is not None else scene.frame_current
    return start, GAME_FPS / fps


def scene_frame(game_frame, start, rate):
    return start + game_frame / rate


def game_frame(frame, start, rate):
    return int(round((frame - start) * rate))


# -- stored keyframes (efl_kf) ------------------------------------------------------------------------

def stored(ob, slot, field):
    """The record's stored keyframe prop for a track (older field names included), or None."""
    kfs = ob.get("efl_kf")
    if kfs is None or slot not in kfs:
        return None
    prop = kfs[slot].get(field)
    if prop is None:
        old = next((o for o, n in schema.FIELD_ALIASES.items() if n == field), None)
        prop = kfs[slot].get(old) if old else None
    return prop


def _header_of(prop):
    if prop is None:
        return 0
    header = prop.get("header", 0)
    header = int(header, 0) if isinstance(header, str) else int(header)
    for name, (shift, mask) in KF_FLAGS.items():
        if name in prop:
            header = (header & ~(mask << shift)) | ((int(prop[name]) & mask) << shift)
    return header


def set_header(ob, slot, field, vtype, **flags):
    """Set header flags (InpType / RefType / LoopFlag / InitOnlyFlag) of a track's stored keyframe, creating an empty
    entry for a track the file has no keyframe for."""
    if ob.get("efl_kf") is None:
        ob["efl_kf"] = {}
    kfs = ob["efl_kf"]
    if slot not in kfs:
        kfs[slot] = {}
    prop = stored(ob, slot, field)
    data = prop.to_dict() if hasattr(prop, "to_dict") else (dict(prop) if prop is not None else None)
    if data is None:
        data = {"vtype": vtype, "header": "0x0", "frames": [], "params": [],
                **{name: 0 for name in KF_FLAGS}}
    for name, value in flags.items():
        data[name] = int(value)
    kfs[slot][field] = data
    return kfs[slot][field]


def header_flags(ob, slot, field):
    """{InpType, RefType, LoopFlag, InitOnlyFlag} of a track."""
    header = _header_of(stored(ob, slot, field))
    return {name: header >> shift & mask for name, (shift, mask) in KF_FLAGS.items()}


# -- the generator's wait -----------------------------------------------------------------------------

def wait_frames(ob):
    """The record's generator WaitFrame base value (game frames; its random part isn't known before spawn)."""
    gen = ob.get("efl_gen")
    flat = as_list(gen.get("WaitFrame")) if gen is not None else None
    return int(flat[0]) if flat else 0


def wanted_offset(ob, slot, field, ref_type=None):
    """Game frames a track's curves should be shifted by: the WaitFrame for generator-timer tracks (the timer stands
    still through the wait) and for particle-age tracks (drawn for the first particle, born when the wait ends);
    0 for the effect timers."""
    if ref_type is None:
        ref_type = header_flags(ob, slot, field)["RefType"]
    return wait_frames(ob) if ref_type == 1 or ref_type in kfm.REF_PARTICLE_AGE else 0


def applied_offset(ob, slot, field):
    offsets = ob.get(OFFSETS_KEY)
    return int(offsets.get(track_id(slot, field), 0)) if offsets is not None else 0


def _set_applied(ob, slot, field, offset):
    offsets = ob.get(OFFSETS_KEY)
    offsets = offsets.to_dict() if hasattr(offsets, "to_dict") else dict(offsets or {})
    if offset:
        offsets[track_id(slot, field)] = int(offset)
    else:
        offsets.pop(track_id(slot, field), None)
    ob[OFFSETS_KEY] = offsets


def _shift_track(ob, slot, field, delta):
    """Move a track's keys (value and random part) by delta scene frames."""
    if not delta:
        return
    value_path, owner, rand_path, _ = _paths(ob, slot, field)
    for curves in (_curves(owner, value_path), _curves(ob, rand_path)):
        for fc in curves.values():
            for kp in fc.keyframe_points:
                kp.co.x += delta
                kp.handle_left.x += delta
                kp.handle_right.x += delta
            fc.update()


def sync_offsets(ob, root=None):
    """Shift every keyed track whose WaitFrame offset changed (WaitFrame edited, a track's timer changed)."""
    from .effect_export import effect_root
    _start, rate = timing(root or effect_root(ob))
    for slot, field, _vtype in tracks(ob):
        if not has_keys(ob, slot, field):
            continue
        old, new = applied_offset(ob, slot, field), wanted_offset(ob, slot, field)
        if old != new:
            _shift_track(ob, slot, field, (new - old) / rate)
            _set_applied(ob, slot, field, new)


# -- values -----------------------------------------------------------------------------------------

def _rot_target(ob):
    """Where a generator's rotation lives: its RelationType 2 companion, else itself."""
    handle = ob.get("efl_rot_handle")
    return handle if handle is not None and handle.get("efl_rot_handle_of") == ob else ob


def _blender_values(vtype, param):
    """(value, random part) of one key in Blender units: scalars, or tuples for colour / vector tracks."""
    if vtype == "f32":
        return float(param[0]), float(param[1])
    if vtype == "u32":
        return int(param[0]), int(param[1])
    if vtype == "color":
        b, g, r, a = param[:4]
        b2, g2, r2, a2 = param[4:8]
        return (r / 255, g / 255, b / 255, a / 255), (r2 / 255, g2 / 255, b2 / 255, a2 / 255)
    if vtype == "fixangle":
        u = kfm.FIX_ANGLE_UNIT
        return tuple(param[2 * i] * u for i in range(3)), tuple(param[2 * i + 1] * u for i in range(3))
    return tuple(float(param[2 * i]) for i in range(3)), tuple(float(param[2 * i + 1]) for i in range(3))


def _game_values(vtype, value, rand):
    """Inverse of _blender_values: the flat key params."""
    if vtype == "f32":
        return [float(value), float(rand)]
    if vtype == "u32":
        return [int(round(value)), int(round(rand))]
    if vtype == "color":
        out = []
        for color in (value, rand):
            r, g, b, a = (min(max(int(round(c * 255)), 0), 255) for c in color)
            out += [b, g, r, a]
        return out
    if vtype == "fixangle":
        u = kfm.FIX_ANGLE_UNIT
        return [int(round(x / u)) for pair in zip(value, rand) for x in pair]
    return [float(x) for pair in zip(value, rand) for x in pair]


def _prop_shape(vtype, field):
    """(size, id_properties_ui subtype) of a track property."""
    if vtype == "color":
        return 4, "COLOR"
    if vtype in ("vec3", "fixangle"):
        return 3, "EULER" if "Rot" in field or vtype == "fixangle" else "XYZ"
    return 1, None


def _ensure_prop(ob, name, value, vtype, field, description):
    size, subtype = _prop_shape(vtype, field)
    ob[name] = list(value) if size > 1 else value
    ui = {"description": description}
    if subtype:
        ui["subtype"] = subtype
    if vtype == "color":
        ui.update(min=0.0, max=1.0)
    try:
        ob.id_properties_ui(name).update(**ui)
    except Exception:
        pass


def _value_of(ob, name, size):
    value = ob.get(name)
    if value is None:
        return (0.0,) * size if size > 1 else 0.0
    flat = as_list(value)
    return tuple(flat[:size]) if size > 1 and flat is not None else (value if size == 1 else (0.0,) * size)


# -- curves -----------------------------------------------------------------------------------------

def _action(ob, create=False):
    ad = ob.animation_data
    if ad is None:
        if not create:
            return None
        ad = ob.animation_data_create()
    if ad.action is None and create:
        ad.action = bpy.data.actions.new(f"{ob.name}_keys")
    return ad.action


def _curves(ob, data_path):
    action = _action(ob)
    if action is None:
        return {}
    return {fc.array_index: fc for fc in action.fcurves if fc.data_path == data_path}


def _remove_curves(ob, data_path):
    action = _action(ob)
    if action is None:
        return
    for fc in [fc for fc in action.fcurves if fc.data_path == data_path]:
        action.fcurves.remove(fc)


def _write_curves(ob, data_path, size, frames, values, interpolation, loop, group):
    """Replace the F-curves at data_path with keys (frames, values: per key a tuple of `size` or a scalar)."""
    _remove_curves(ob, data_path)
    action = _action(ob, create=True)
    for index in range(size):
        fc = action.fcurves.new(data_path, index=index, action_group=group)
        fc.keyframe_points.add(len(frames))
        for kp, frame, value in zip(fc.keyframe_points, frames, values):
            kp.co = (frame, value[index] if size > 1 else value)
            kp.interpolation = interpolation
            kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
        if loop:
            fc.modifiers.new("CYCLES")
        fc.update()


def _paths(ob, slot, field):
    """(value path, value owner, random path, size key) of a track: transform tracks use the Empty's channels."""
    name = track_name(slot, field)
    channel = TRANSFORM.get((slot, field))
    if channel is not None:
        owner = _rot_target(ob) if channel == "rotation_euler" else ob
        return channel, owner, _data_path(name + RAND), name
    return _data_path(name), ob, _data_path(name + (COLOR_B if field.endswith("ColorParamOffset") else RAND)), name


def rand_name(slot, field, vtype):
    return track_name(slot, field) + (COLOR_B if vtype == "color" else RAND)


def _description(slot, field, vtype, rand=False):
    label = pretty(field)
    if rand:
        what = ("The second colour of each key: the game mixes the key's colour toward it by a random amount per "
                "particle" if vtype == "color" else
                f"The random part of each {label} key: the game adds it x a random number (0-1) drawn once per "
                "particle. Key it on the same frames as the value, or leave it unkeyed for one value at every key")
    else:
        what = (f"Keys of {label} ({SLOT_LABELS.get(slot, slot)} block). Key frames are timeline frames from the "
                "effect's start marker" + (" (the effect's own timer)" if slot == "gen" else
                                           "; particle-age keys count from each particle's birth, shown from the "
                                           "start") + ". Edit in the Graph Editor or Dope Sheet; the timer and "
                "init-only settings are in the Effect Editor's Keys tab")
    help_text = field_help(f"{slot}:{label}")
    return what + (". " + help_text if help_text else "")


def build_track(ob, slot, field, kf, start, rate):
    """Create the F-curves (and properties) of a stored keyframe on a record Empty."""
    vtype = kf.vtype
    if not kf.frames:
        return
    offset = wanted_offset(ob, slot, field, kf.ref_type)
    frames = [scene_frame(f + offset, start, rate) for f in kf.frames]
    _set_applied(ob, slot, field, offset)
    pairs = [_blender_values(vtype, p) for p in kf.params]
    values = [v for v, _ in pairs]
    rands = [r for _, r in pairs]
    interpolation = "LINEAR" if kf.inp_type == 0 else "BEZIER"
    value_path, owner, rand_path, name = _paths(ob, slot, field)
    size = SIZES[vtype]
    channel = TRANSFORM.get((slot, field))
    if channel == "location":
        values = [tuple(c * SCALE for c in v) for v in values]
    elif channel == "rotation_euler":
        props = ob.get("efl_gen")
        order = int(props.get("Order", 0)) if props is not None else 0
        owner.rotation_mode = ROT_ORDERS[order] if 0 <= order < len(ROT_ORDERS) else "XYZ"
    if channel is None:
        _ensure_prop(ob, name, values[0], vtype, field, _description(slot, field, vtype))
    _write_curves(owner, value_path, size, frames, values, interpolation, kf.loop, name)
    rname = rand_name(slot, field, vtype)
    _ensure_prop(ob, rname, rands[0], vtype, field, _description(slot, field, vtype, rand=True))
    if any(r != rands[0] for r in rands):   # a varying random part is keyed too; a constant one stays static
        _write_curves(ob, rand_path, size, frames, rands, interpolation, kf.loop, name)
    else:
        _remove_curves(ob, rand_path)
    ob[VERSION_KEY] = 1


def remove_track(ob, slot, field, vtype=None):
    """Drop a track's keys: its curves and (custom tracks) its properties."""
    value_path, owner, rand_path, name = _paths(ob, slot, field)
    _remove_curves(owner, value_path)
    _remove_curves(ob, rand_path)
    if (slot, field) not in TRANSFORM:
        ob.pop(name, None)
    for suffix in (RAND, COLOR_B):
        ob.pop(name + suffix, None)
    _set_applied(ob, slot, field, 0)


def rebuild_tracks(ob, root=None, slots=SLOTS):
    """Build every track of the given slots from the stored keyframes (efl_kf), replacing their curves."""
    from .effect_export import effect_root
    root = root or effect_root(ob)
    start, rate = timing(root)
    if VERSION_KEY not in ob:   # an older import: baked transform samples; replace them
        for channel in ("location", "rotation_quaternion", "rotation_euler", "scale"):
            _remove_curves(ob, channel)
            _remove_curves(_rot_target(ob), channel)
    for slot, field, vtype in tracks(ob):
        if slot not in slots:
            continue
        remove_track(ob, slot, field, vtype)
        prop = stored(ob, slot, field)
        if prop is None:
            continue
        try:
            kf = kf_from_prop(prop, vtype)
        except ValueError:
            continue
        build_track(ob, slot, field, kf, start, rate)
    ob[VERSION_KEY] = 1


def key_count(ob, slot, field):
    value_path, owner, _, _ = _paths(ob, slot, field)
    curves = _curves(owner, value_path)
    return max((len(fc.keyframe_points) for fc in curves.values()), default=0)


def has_keys(ob, slot, field):
    return key_count(ob, slot, field) > 0


def _collect(ob, slot, field, vtype, start, rate):
    """(game frames, values, rands, bezier, loop) from a track's curves, or None when it has no value keys."""
    value_path, owner, rand_path, name = _paths(ob, slot, field)
    curves = _curves(owner, value_path)
    if not curves or not any(len(fc.keyframe_points) for fc in curves.values()):
        return None
    size = SIZES[vtype]
    frames = sorted({kp.co.x for fc in curves.values() for kp in fc.keyframe_points})
    channel = TRANSFORM.get((slot, field))
    static = (owner.location if channel == "location" else owner.rotation_euler if channel == "rotation_euler"
              else owner.scale if channel == "scale" else None)
    rand_curves = _curves(ob, rand_path)
    rand_static = _value_of(ob, rand_name(slot, field, vtype), size)
    values, rands = [], []
    for frame in frames:
        if size > 1:
            value = tuple(curves[i].evaluate(frame) if i in curves else
                          (static[i] if static is not None else _value_of(ob, name, size)[i]) for i in range(size))
            rand = tuple(rand_curves[i].evaluate(frame) if i in rand_curves else rand_static[i] for i in range(size))
        else:
            value = curves[0].evaluate(frame) if 0 in curves else (ob.get(name) or 0.0)
            rand = rand_curves[0].evaluate(frame) if 0 in rand_curves else rand_static
        if channel == "location":
            value = tuple(c / SCALE for c in value)
        values.append(value)
        rands.append(rand)
    bezier = any(kp.interpolation not in ("LINEAR", "CONSTANT") for fc in curves.values() for kp in fc.keyframe_points)
    loop = any(m.type == "CYCLES" for fc in curves.values() for m in fc.modifiers)
    offset = applied_offset(ob, slot, field)
    return [game_frame(f, start, rate) - offset for f in frames], values, rands, bezier, loop


def track_prop(ob, slot, field, vtype, start, rate):
    """The keyframe prop export writes for a track: the stored one when the curves still describe it (or the
    record predates F-curve keys), else one rebuilt from the curves ([] frames when the keys were removed)."""
    prop = stored(ob, slot, field)
    if VERSION_KEY not in ob:
        return prop
    collected = _collect(ob, slot, field, vtype, start, rate)
    if collected is None:
        if prop is not None and as_list(prop.get("frames")):
            return {**kf_to_prop(kf_from_prop(prop, vtype)), "frames": [], "params": []}
        return prop
    frames, values, rands, bezier, loop = collected
    header = _header_of(prop)
    flags = {name: header >> shift & mask for name, (shift, mask) in KF_FLAGS.items()}
    flags["InpType"] = (flags["InpType"] if flags["InpType"] in (1, 2) else 1) if bezier else 0
    flags["LoopFlag"] = int(loop)
    stored_vtype = str(prop.get("vtype", vtype)) if prop is not None else vtype
    vtype = stored_vtype if stored_vtype in SIZES else vtype
    new = {"vtype": vtype, "header": f"{header:#010x}", **flags, "frames": frames,
           "params": [v for value, rand in zip(values, rands) for v in _game_values(vtype, value, rand)]}
    if prop is not None and as_list(prop.get("frames")):
        try:
            if kf_same(kf_from_prop(prop, vtype), kf_from_prop(new, vtype)):
                return prop
        except ValueError:
            pass
    return new


def keyframe_props_of(ob, root=None):
    """{slot: {offset field: keyframe prop}} for export: efl_kf with every track's curves written over it."""
    from .effect_export import effect_root
    root = root or effect_root(ob)
    start, rate = timing(root)
    kfs = ob.get("efl_kf")
    out = {slot: {field: kfs[slot][field] for field in kfs[slot].keys()} for slot in kfs.keys()} if kfs else {}
    if VERSION_KEY not in ob:
        return out
    for slot, field, vtype in tracks(ob):
        prop = track_prop(ob, slot, field, vtype, start, rate)
        if prop is None:
            continue
        out.setdefault(slot, {})
        old = next((o for o, n in schema.FIELD_ALIASES.items() if n == field), None)
        if old and old in out[slot] and field not in out[slot]:
            del out[slot][old]
        out[slot][field] = prop
    return out


# -- editing ----------------------------------------------------------------------------------------

def field_key_values(ob, slot, field, vtype, from_field=True):
    """(value, random part) a new key takes, in Blender units: the block field the track animates (from_field,
    a track's first key), else the track's own properties / transform channel (what the user set since)."""
    props = ob.get(f"efl_{slot}")
    struct = schema.struct_for_props(slot, int(props["type"]), props) if props is not None else None
    name = animated_field(struct, field) if struct is not None else None
    size = SIZES[vtype]
    if (slot, field) in TRANSFORM:   # the Empty's transform is what the generator shows
        name = None
    if from_field and name is not None and name in props:
        flat = as_list(props[name])
        f = struct.by_name[name]
        if vtype == "color":
            if f.type == "color[2]" and flat is not None and len(flat) >= 8:
                b, g, r, a = flat[:4]
                b2, g2, r2, a2 = flat[4:8]
                return (r / 255, g / 255, b / 255, a / 255), (r2 / 255, g2 / 255, b2 / 255, a2 / 255)
            if flat is not None and len(flat) >= 4:
                b, g, r, a = flat[:4]
                return (r / 255, g / 255, b / 255, a / 255), (r / 255, g / 255, b / 255, a / 255)
        elif f.type in ("rangef", "rangeu16") and flat is not None and len(flat) >= 2:
            return (int(flat[0]), int(flat[1])) if vtype == "u32" else (float(flat[0]), float(flat[1]))
        elif f.type == "rangef[3]" and flat is not None and len(flat) >= 6 and size == 3:
            return tuple(float(flat[2 * i]) for i in range(3)), tuple(float(flat[2 * i + 1]) for i in range(3))
        elif f.type == "f32" and size == 1:
            return float(props[name]), 0.0
        elif f.type == "vec3" and flat is not None and size == 3:
            return tuple(float(c) for c in flat[:3]), (0.0, 0.0, 0.0)
    channel = TRANSFORM.get((slot, field))
    if channel is not None:
        owner = _rot_target(ob) if channel == "rotation_euler" else ob
        value = tuple(getattr(owner, channel))
        if channel == "location":
            value = tuple(c / SCALE for c in value)
        return value, _value_of(ob, rand_name(slot, field, vtype), size)
    if vtype == "color":
        return _value_of(ob, track_name(slot, field), 4) if track_name(slot, field) in ob else (1.0,) * 4, \
            _value_of(ob, rand_name(slot, field, vtype), 4) if rand_name(slot, field, vtype) in ob else (1.0,) * 4
    default = (1.0 if vtype == "f32" else 0) if size == 1 else (0.0,) * 3
    return (_value_of(ob, track_name(slot, field), size) if track_name(slot, field) in ob else default,
            _value_of(ob, rand_name(slot, field, vtype), size))


def insert_key(ob, slot, field, vtype, frame, value=None, rand=None, interpolation=None):
    """Insert (or replace) a key at a scene frame; a track without keys is created, taking its value and random
    part from the field it animates unless given. A frame before the track's first playable frame (the start marker
    plus its WaitFrame shift: game frame 0 of its timer) is moved there. Returns the frame used."""
    if VERSION_KEY not in ob:
        rebuild_tracks(ob)
    if value is None or rand is None:
        field_value, field_rand = field_key_values(ob, slot, field, vtype, from_field=not has_keys(ob, slot, field))
        value = field_value if value is None else value
        rand = field_rand if rand is None else rand
    value_path, owner, rand_path, name = _paths(ob, slot, field)
    size = SIZES[vtype]
    channel = TRANSFORM.get((slot, field))
    flags = header_flags(ob, slot, field)
    if not has_keys(ob, slot, field):   # a new track: its curve shows when the keys play (the wait included)
        _set_applied(ob, slot, field, wanted_offset(ob, slot, field, flags["RefType"]))
    from .effect_export import effect_root
    start, rate = timing(effect_root(ob))
    first = scene_frame(applied_offset(ob, slot, field), start, rate)
    if frame < first - 1e-6:   # before game frame 0 of the track's timer: nothing plays there
        frame = first
    if interpolation is None:
        interpolation = "LINEAR" if flags["InpType"] == 0 else "BEZIER"
    if channel is not None:
        if channel == "location":
            value = tuple(c * SCALE for c in value)
        elif channel == "rotation_euler" and owner.rotation_mode not in ROT_ORDERS:
            props = ob.get("efl_gen")
            order = int(props.get("Order", 0)) if props is not None else 0
            owner.rotation_euler = owner.matrix_basis.to_euler(ROT_ORDERS[order] if 0 <= order < 6 else "XYZ")
            owner.rotation_mode = ROT_ORDERS[order] if 0 <= order < len(ROT_ORDERS) else "XYZ"
        setattr(owner, channel, value)
        owner.keyframe_insert(channel, frame=frame, group=name)
    else:
        if name not in ob:
            _ensure_prop(ob, name, value, vtype, field, _description(slot, field, vtype))
        else:
            ob[name] = list(value) if size > 1 else value
        ob.keyframe_insert(_data_path(name), frame=frame, group=name)
    curves = _curves(owner, value_path)
    for fc in curves.values():
        for kp in fc.keyframe_points:
            if abs(kp.co.x - frame) < 1e-4:
                kp.interpolation = interpolation
                kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
        if flags["LoopFlag"] and not any(m.type == "CYCLES" for m in fc.modifiers):
            fc.modifiers.new("CYCLES")
        fc.update()
    rname = rand_name(slot, field, vtype)
    if rname not in ob:
        _ensure_prop(ob, rname, rand, vtype, field, _description(slot, field, vtype, rand=True))
    elif _curves(ob, rand_path):
        ob[rname] = list(rand) if size > 1 else rand
        ob.keyframe_insert(rand_path, frame=frame, group=name)
    set_header(ob, slot, field, vtype)
    ob[VERSION_KEY] = 1
    return frame


def set_interpolation(ob, slot, field, vtype, inp_type):
    """0 linear / 1 hermite / 2 spline: stored in the header and applied to the track's keys."""
    set_header(ob, slot, field, vtype, InpType=inp_type)
    value_path, owner, rand_path, _ = _paths(ob, slot, field)
    for fcs in (_curves(owner, value_path), _curves(ob, rand_path)):
        for fc in fcs.values():
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR" if inp_type == 0 else "BEZIER"
                kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
            fc.update()


def set_loop(ob, slot, field, vtype, on):
    """LoopFlag: a Cycles modifier on the track's curves."""
    set_header(ob, slot, field, vtype, LoopFlag=int(bool(on)))
    value_path, owner, rand_path, _ = _paths(ob, slot, field)
    for fcs in (_curves(owner, value_path), _curves(ob, rand_path)):
        for fc in fcs.values():
            cycles = [m for m in fc.modifiers if m.type == "CYCLES"]
            if on and not cycles:
                fc.modifiers.new("CYCLES")
            for m in ([] if on else cycles):
                fc.modifiers.remove(m)


def select_track(ob, slot, field):
    """Select the track's curves (and nothing else of the record) for the Graph Editor."""
    value_path, owner, rand_path, _ = _paths(ob, slot, field)
    for target in {ob, owner}:
        action = _action(target)
        if action is None:
            continue
        for fc in action.fcurves:
            fc.select = fc.data_path in (value_path, rand_path) and (target is owner or fc.data_path == rand_path)
            fc.hide = False


def shift(ob, delta):
    """Move every key of an object's action by delta frames."""
    action = _action(ob)
    if action is None or not delta:
        return
    for fc in action.fcurves:
        for kp in fc.keyframe_points:
            kp.co.x += delta
            kp.handle_left.x += delta
            kp.handle_right.x += delta
        fc.update()
