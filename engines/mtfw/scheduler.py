"""DMC4 scheduler (.sdl) import / export. The format is the vendored dmc4xml package (albam_vendor/dmc4xml, maintained
upstream in dmc4_xml); this module maps it to Blender.

Same object layout as placement.py: the root Empty `SDL_<file>` and one Empty per container track (unit, system, the
second root, object), with `sdl_track` (the track's fields) and `sdl_layout` (its children in file order, JSON).
- Numeric value tracks (int, float, bool, vector) are custom properties on their container, keyed with F-curves:
  one keyframe per key, on the key's frame (scene frame = scheduler frame = 1/60 s). Edit them in the Dope Sheet /
  Graph Editor; the property alone (no F-curve) exports as one key at frame 0.
- Key modes (DX9 rScheduler::keying 0x90AF00, Vibed/RE/sdl_scheduler_runtime.md): key i's mode governs the segment
  i -> i+1, like a Blender keyframe's interpolation. 0 step and 2 step-once (written only when the key is reached)
  -> CONSTANT; 3 linear -> LINEAR; 5 uniform Catmull-Rom -> BEZIER with the exact Catmull-Rom handles; 1 / 4 counter
  (value + elapsed frames) -> LINEAR (exact only when the next key continues the count). Source modes are kept per
  frame; new keys take KEY_MODES[interpolation] (BEZIER -> Catmull-Rom: the game ignores hand-edited handles).
- Other tracks (resource, string, ref, event, custom) keep their keys in the layout entry. A single-key resource is
  also a string property (its path), editable.
- Ref values and the header's marker (cut) track are track indices: export renumbers them when tracks were added or
  removed (`track` = source index in each layout entry / sdl_track).
- Units with an `mPos` / `mAngle` property (uStageSetMoveFloor and the other uCoord units) get drivers from those
  properties on their Empty's location / rotation (cm, Y up -> m, Z up; mAngle = radians, game Euler ZXY = Blender
  'YXZ' on (x, -z, y)), and an `mpParent` ref becomes a Child Of constraint on the referenced unit (the game composes
  mWmat with the parent's), so the units move with their keys. Parent a collision root (`.sbc`, exported relative to
  its root) to such a unit to preview a moving floor. Drivers only show the keys: edit mPos / mAngle themselves.
Untouched files export byte-identical.
"""
import json

import bpy

from dmc4xml import sdl as sdl_codec
from dmc4xml.dti import dti_id as _dti_id, dti_name as _dti_name

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.vfs import VirtualFileData
from .placement import ordered_children, own_collection

TRACK_PROP = "sdl_track"
LAYOUT_PROP = "sdl_layout"
ROOT_PROP = "sdl_root"
NUMERIC = (sdl_codec.INT, sdl_codec.FLOAT, sdl_codec.BOOL, sdl_codec.VECTOR)
UNIT_TYPES = (sdl_codec.UNIT, sdl_codec.SYSTEM)

# key mode byte -> Blender interpolation, and back for keys added in Blender (see the module docstring)
KEY_INTERPOLATION = {0: "CONSTANT", 1: "LINEAR", 2: "CONSTANT", 3: "LINEAR", 4: "LINEAR", 5: "BEZIER"}
KEY_MODES = {"CONSTANT": 0, "LINEAR": 3, "BEZIER": 5}
CATMULL_ROM = 5


def _signed(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= 1 << 31 else v


def _data_path(key):
    return '["%s"]' % key.replace("\\", "\\\\").replace('"', '\\"')


# ---- import ------------------------------------------------------------------------------------------------------

@blender_registry.register_import_function(app_id="dmc4", extension="sdl", file_category="SCHEDULE")
def load_sdl(file_item, context):
    build_sdl_objects(file_item.get_bytes(), file_item.display_name.split(".")[0], file_item, context)
    return None     # linked into its own collection


def build_sdl_objects(data, stem, asset, context, collection=None):
    """.sdl bytes -> the root Empty `SDL_<stem>` and its track Empties, linked into their own collection (or
    `collection`) and added to the export list. `asset` gives app_id / relative_path / extension."""
    try:
        sdl = sdl_codec.read(data)
    except sdl_codec.SdlError as err:
        raise AlbamCheckFailure("Can't read this scheduler file", details=str(err),
                                solution="Only DX9 DMC4 .sdl files (version 16) are supported; Special Edition "
                                         "files are version 22.")
    tracks = sdl.tracks
    kids = {}
    for i, t in enumerate(tracks[1:], 1):
        kids.setdefault(0 if t.type in UNIT_TYPES else t.parent, []).append(i)

    root_ob = bpy.data.objects.new(f"SDL_{stem}", None)
    root_ob.empty_display_size = 0.5
    objects = {}
    root_ob[ROOT_PROP] = json.dumps({"frames": sdl.frames, "flags": sdl.flags, "marker_track": sdl.marker_track,
                                     "name": tracks[0].name, "str_ofs": tracks[0].name_ofs,
                                     "encoding": tracks[0].encoding})

    def build(ob, index):
        layout, names_seen = [], {}
        for c in kids.get(index, []):
            if tracks[c].type not in sdl_codec.CONTAINERS:
                names_seen[tracks[c].name] = names_seen.get(tracks[c].name, 0) + 1
        for c in kids.get(index, []):
            t = tracks[c]
            if t.type in sdl_codec.CONTAINERS:
                layout.append({"child": c})
                child = bpy.data.objects.new(t.name, None)
                child.parent = ob
                child.empty_display_size = 0.15
                objects[c] = child
                child[TRACK_PROP] = json.dumps({"index": c, "type": t.type, "prop_type": t.prop_type,
                                                "dti": t.dti if t.type == sdl_codec.OBJECT else _dti_name(t.dti),
                                                "parent": t.parent if t.type in UNIT_TYPES else None,
                                                "name": t.name, "str_ofs": t.name_ofs, "encoding": t.encoding})
                build(child, c)
                continue
            entry = {"track": c, "name": t.name, "type": t.type, "prop_type": t.prop_type, "index": t.dti,
                     "str_ofs": t.name_ofs, "encoding": t.encoding}
            key = t.name if names_seen[t.name] == 1 else f"{t.name}[{t.dti}]"
            entry["key"] = key
            if t.type in NUMERIC:
                entry["frames"] = [k.frame for k in t.keys]
                entry["modes"] = [k.mode for k in t.keys]
                entry["values"] = [_raw_value(t.type, k.value) for k in t.keys]
                _key_numeric(ob, t, key)
            else:
                entry["keys"] = [_other_key(t.type, k) for k in t.keys]
                if t.type == sdl_codec.RESOURCE and len(t.keys) == 1:
                    ob[key] = t.keys[0].value[1] if t.keys[0].value else ""
            layout.append(entry)
        ob[LAYOUT_PROP] = json.dumps(layout)

    build(root_ob, 0)
    own_collection(root_ob, context, collection)
    for ob in objects.values():
        _drive_transform(ob, objects)
    root_ob.albam_asset.original_bytes = data
    root_ob.albam_asset.app_id = asset.app_id
    root_ob.albam_asset.relative_path = asset.relative_path
    root_ob.albam_asset.extension = asset.extension
    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = root_ob
    context.scene.albam.exportable.file_list.update()
    return root_ob


POSITION_NAMES = ("mPos",)
ANGLE_NAMES = ("mAngle",)
PARENT_NAMES = ("mpParent",)
CONSTRAINT_NAME = "ALBAM_SDL_Parent"


def _drive_transform(ob, objects):
    """mPos / mAngle drivers and the mpParent constraint (see the module docstring)."""
    pos = angle = parent = None
    for entry in json.loads(ob.get(LAYOUT_PROP, "[]")):
        if "child" in entry:
            continue
        if entry["type"] == sdl_codec.VECTOR and entry["name"] in POSITION_NAMES and pos is None:
            pos = entry["key"]
        elif entry["type"] == sdl_codec.VECTOR and entry["name"] in ANGLE_NAMES and angle is None:
            angle = entry["key"]
        elif entry["type"] == sdl_codec.REF and entry["name"] in PARENT_NAMES and entry.get("keys"):
            target = next((k[2] for k in entry["keys"] if k[2]), 0)
            parent = objects.get(target)
    if pos is None and angle is None:
        return

    def drive(path, index, key, component, expression):
        fc = ob.driver_add(path, index)
        drv = fc.driver
        drv.type = "SCRIPTED"
        var = drv.variables.new()
        var.name = "v"
        var.type = "SINGLE_PROP"
        var.targets[0].id = ob
        var.targets[0].data_path = '%s[%d]' % (_data_path(key), component)
        drv.expression = expression

    if pos is not None:
        drive("location", 0, pos, 0, "v * 0.01")
        drive("location", 1, pos, 2, "-v * 0.01")
        drive("location", 2, pos, 1, "v * 0.01")
    if angle is not None:
        ob.rotation_mode = "YXZ"
        drive("rotation_euler", 0, angle, 0, "v")
        drive("rotation_euler", 1, angle, 2, "-v")
        drive("rotation_euler", 2, angle, 1, "v")
    if parent is not None and parent is not ob:
        con = ob.constraints.new("CHILD_OF")
        con.name = CONSTRAINT_NAME
        con.target = parent
        con.inverse_matrix.identity()
    ob.empty_display_type = "ARROWS"
    ob.empty_display_size = 0.5


def _raw_value(ttype, value):
    if ttype == sdl_codec.VECTOR:
        return list(value)
    return value


def _prop_value(ttype, value):
    if ttype == sdl_codec.BOOL:
        return bool(value)
    if ttype == sdl_codec.INT:
        return _signed(value)
    if ttype == sdl_codec.FLOAT:
        return float(value)
    return [float(x) for x in value]


def _other_key(ttype, k):
    if ttype == sdl_codec.RESOURCE:
        if k.value is None:
            return [k.frame, k.mode, None, None, None]
        return [k.frame, k.mode, _dti_name(k.value[0]), k.value[1], k.ref_ofs]
    if ttype == sdl_codec.CUSTOM:
        return [k.frame, k.mode, bytes(k.value).hex()]
    if ttype == sdl_codec.STRING:
        return [k.frame, k.mode, k.value, k.ref_ofs]
    return [k.frame, k.mode, k.value]


def _key_numeric(ob, t, key):
    """Custom property with the first key's value, one keyframe per key."""
    ob[key] = _prop_value(t.type, t.keys[0].value) if t.keys else _prop_value(t.type, (0.0,) * 4 if t.type == sdl_codec.VECTOR else 0)
    if not t.keys:
        return
    if ob.animation_data is None:
        ob.animation_data_create()
    if ob.animation_data.action is None:
        ob.animation_data.action = bpy.data.actions.new(f"{ob.name}_sdl")
    action = ob.animation_data.action
    channels = 4 if t.type == sdl_codec.VECTOR else 1
    path = _data_path(key)
    # a track can hold two keys on one frame (an instant jump); an F-curve can't, so it gets the later one and
    # export puts both back while that keyframe is unchanged
    keys = sorted({k.frame: k for k in t.keys}.values(), key=lambda k: k.frame)
    for ch in range(channels):
        fc = action.fcurves.new(path, index=ch, action_group=ob.name)
        fc.keyframe_points.add(len(keys))
        values = [k.value[ch] if t.type == sdl_codec.VECTOR else
                  (_signed(k.value) if t.type == sdl_codec.INT else float(k.value)) for k in keys]
        for kp, k, v in zip(fc.keyframe_points, keys, values):
            kp.co = (k.frame, v)
            kp.interpolation = KEY_INTERPOLATION.get(k.mode, "CONSTANT")
            if t.type == sdl_codec.BOOL:
                kp.interpolation = "CONSTANT"     # bools ignore the mode
        fc.update()
        _catmull_rom_handles(fc, keys, values)


def _catmull_rom_handles(fc, keys, values):
    """Mode 5 segments: uniform Catmull-Rom (tangent at key k = (v[k+1] - v[k-1]) / 2, ends clamped) as Bezier
    handles a third of the segment away, which reproduces the game's cubic exactly."""
    n = len(keys)
    tangent = [(values[min(k + 1, n - 1)] - values[max(k - 1, 0)]) * 0.5 for k in range(n)]
    points = fc.keyframe_points
    for k in range(n - 1):
        if keys[k].mode != CATMULL_ROM:
            continue
        third = (keys[k + 1].frame - keys[k].frame) / 3.0
        a, b = points[k], points[k + 1]
        a.handle_right_type = b.handle_left_type = "FREE"
        a.handle_right = (keys[k].frame + third, values[k] + tangent[k] / 3.0)
        b.handle_left = (keys[k + 1].frame - third, values[k + 1] - tangent[k + 1] / 3.0)


# ---- export ------------------------------------------------------------------------------------------------------

def _fcurves(ob, key, channels):
    ad = ob.animation_data
    if ad is None or ad.action is None:
        return None
    path = _data_path(key)
    curves = [ad.action.fcurves.find(path, index=ch) for ch in range(channels)]
    return curves if any(c is not None and len(c.keyframe_points) for c in curves) else None


def _numeric_keys(ob, entry, problems):
    """[(frame, mode, value)] from the F-curves (or the property alone)."""
    ttype = entry["type"]
    key = entry["key"]
    channels = 4 if ttype == sdl_codec.VECTOR else 1
    keys_at = {}       # frame -> [(mode, value)] of the source keys (usually one)
    for f, m, v in zip(entry.get("frames", []), entry.get("modes", []), entry.get("values", [])):
        keys_at.setdefault(f, []).append((m, v))
    old = {f: ks[-1] for f, ks in keys_at.items()}
    curves = _fcurves(ob, key, channels)
    if curves is None:
        if key not in ob:
            problems.append(f"{ob.name}: property {key} is missing")
            return []
        if not entry.get("frames"):
            return []
        value = ob[key]
        value = list(value) if ttype == sdl_codec.VECTOR else value
        return [(0, old.get(0, (0, None))[0], _file_value(ttype, value, old.get(0, (0, None))[1]))]
    frames, interp = {}, {}
    for c in curves:
        if c is None:
            continue
        for kp in c.keyframe_points:
            f = int(round(kp.co[0]))
            frames.setdefault(f, None)
            interp.setdefault(f, kp.interpolation)
    out = []
    for f in sorted(frames):
        if f < 0 or f > 0xFFFFFF:
            problems.append(f"{ob.name}: {key} has a key on frame {f}")
            continue
        if ttype == sdl_codec.VECTOR:
            value = []
            for ch, c in enumerate(curves):
                if c is None:
                    value.append(old.get(f, (0, [0.0] * 4))[1][ch] if f in old else 0.0)
                else:
                    value.append(c.evaluate(f))
        else:
            value = curves[0].evaluate(f)
        mode = old[f][0] if f in old else KEY_MODES.get(interp[f], 0)
        value = _file_value(ttype, value, old[f][1] if f in old else None)
        if f in old and len(keys_at[f]) > 1 and value == _file_value(ttype, old[f][1], old[f][1]):
            out.extend((f, m, _file_value(ttype, v, v)) for m, v in keys_at[f])   # an unchanged jump
        else:
            out.append((f, mode, value))
    # unchanged curves give the source keys back in their own order (some files don't sort them by frame)
    source = [(f, m, _file_value(ttype, v, v)) for f, m, v in
              zip(entry.get("frames", []), entry.get("modes", []), entry.get("values", []))]
    if sorted(out, key=lambda k: k[0]) == sorted(source, key=lambda k: k[0]) and len(out) == len(source):
        return source
    return out


def _file_value(ttype, value, original):
    """Blender value -> file value; the original when Blender's float copy of it is unchanged."""
    if ttype == sdl_codec.VECTOR:
        v = [float(x) for x in value] + [0.0] * (4 - len(value))
        if original is not None and all(abs(a - b) <= 1e-6 * max(1.0, abs(b)) for a, b in zip(v, original)):
            return tuple(original)
        return tuple(v[:4])
    if ttype == sdl_codec.FLOAT:
        v = float(value)
        if original is not None and abs(v - original) <= 1e-6 * max(1.0, abs(original)):
            return original
        return v
    if ttype == sdl_codec.BOOL:
        b = int(round(float(value))) != 0
        return original if original is not None and bool(original) == b else int(b)
    v = int(round(float(value)))
    if original is not None and _signed(original) == _signed(v):
        return original
    return v & 0xFFFFFFFF


def build_sdl(root_ob):
    """Root Empty -> (Sdl, notes)."""
    notes, problems = [], []
    head = json.loads(root_ob.get(ROOT_PROP, "{}"))
    sdl = sdl_codec.Sdl(frames=head.get("frames", 0), flags=head.get("flags", 0),
                        marker_track=head.get("marker_track", head.get("dti_table_offset", 0)))
    index_map = {0: 0}         # source track index -> new index (first copy wins)
    ref_tracks = []
    sdl.tracks.append(sdl_codec.Track(sdl_codec.ROOT, 0, 0, head.get("name", "Root"), name_ofs=head.get("str_ofs", 0),
                                      encoding=head.get("encoding", "utf-8")))

    def emit(ob, index):
        for entry, child in ordered_children(ob, TRACK_PROP, LAYOUT_PROP):
            if child is not None:
                info = json.loads(child[TRACK_PROP])
                dti = info["dti"] if info["type"] == sdl_codec.OBJECT else _dti_id(info["dti"])
                parent = info["parent"] if info["type"] in UNIT_TYPES else index
                t = sdl_codec.Track(info["type"], info["prop_type"], parent, info["name"], dti,
                                    name_ofs=info.get("str_ofs") if entry is not None else None,
                                    encoding=info.get("encoding", "utf-8"))
                new = len(sdl.tracks)
                index_map.setdefault(info["index"], new)
                sdl.tracks.append(t)
                emit(child, new)
                continue
            if entry.get("track") is not None:
                index_map.setdefault(entry["track"], len(sdl.tracks))
            t = sdl_codec.Track(entry["type"], entry["prop_type"], index, entry["name"], entry["index"],
                                name_ofs=entry.get("str_ofs"), encoding=entry.get("encoding", "utf-8"))
            if t.type in NUMERIC:
                t.keys = [sdl_codec.Key(f, m, v) for f, m, v in _numeric_keys(ob, entry, problems)]
            else:
                keys = entry.get("keys", [])
                if t.type == sdl_codec.RESOURCE and len(keys) == 1 and entry["key"] in ob:
                    path = str(ob[entry["key"]])
                    k = keys[0]
                    if path != (k[3] or ""):
                        keys = [[k[0], k[1], k[2] or "rTexture", path, None] if path else [k[0], k[1], None, None, None]]
                        notes.append(f"{ob.name}: {entry['name']} -> {path or '(none)'}")
                for k in keys:
                    if t.type == sdl_codec.RESOURCE:
                        value = (_dti_id(k[2]), k[3]) if k[3] else None
                        t.keys.append(sdl_codec.Key(k[0], k[1], value, k[4] if k[3] else None))
                    elif t.type == sdl_codec.CUSTOM:
                        t.keys.append(sdl_codec.Key(k[0], k[1], bytes.fromhex(k[2])))
                    elif t.type == sdl_codec.STRING:
                        t.keys.append(sdl_codec.Key(k[0], k[1], k[2], k[3] if k[2] is not None else None))
                    else:
                        t.keys.append(sdl_codec.Key(k[0], k[1], k[2]))
                if t.type == sdl_codec.REF:
                    ref_tracks.append((ob, t))
            sdl.tracks.append(t)

    emit(root_ob, 0)
    # ref values and the marker track are track indices: follow the tracks to their new places
    for ob, t in ref_tracks:
        for k in t.keys:
            if k.value:
                if k.value in index_map:
                    k.value = index_map[k.value]
                else:
                    problems.append(f"{ob.name}: {t.name} refers to track {k.value}, which was deleted")
    if sdl.marker_track:
        if sdl.marker_track in index_map:
            sdl.marker_track = index_map[sdl.marker_track]
        else:
            notes.append(f"the marker (cut) track {sdl.marker_track} was deleted: no cut adjustment")
            sdl.marker_track = 0
    if problems:
        raise AlbamCheckFailure(f"Scheduler {root_ob.name} can't be exported", details="\n".join(problems),
                                solution="Fix the listed tracks.")
    return sdl, notes


@blender_registry.register_export_function(app_id="dmc4", extension="sdl")
def export_sdl(bl_obj):
    sdl, notes = build_sdl(bl_obj)
    try:
        data = sdl_codec.write(sdl)
    except sdl_codec.SdlError as err:
        raise AlbamCheckFailure(f"Scheduler {bl_obj.name} can't be exported", details=str(err),
                                solution="Fix the listed tracks.")
    asset = bl_obj.albam_asset
    print(f"SDL export {asset.relative_path}: {len(sdl.tracks)} tracks")
    for note in notes:
        print("  " + note)
    bl_obj["sdl_export_notes"] = notes[:200]
    return [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]
