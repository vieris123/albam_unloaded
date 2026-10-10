"""DMC4 placement (.pla) import / export. The format itself is the vendored dmc4xml package (albam_vendor/dmc4xml,
maintained upstream in dmc4_xml); this module only maps it to Blender objects.

Every container track (group, unit, object) becomes an Empty under the root Empty `PLA_<file>`; its value tracks are
custom properties on it. Each Empty keeps the track's own fields in `pla_track` and the order of its children (value
tracks and child containers) in `pla_layout` (JSON), so export rebuilds the file exactly; untouched files come back
byte-identical.
- An `mPos` vector moves the Empty (game cm, Y up -> Blender m, Z up). `mRotY` (degrees about the game's up axis,
  enemy create data: uEnemy::setup 0x7303F6) or `mAngle` (uCoord::setAngle 0xA32930: radians, Euler order ZXY in
  game axes for the default uCoord::mOrder 4) turns it. Moving or turning the Empty in the viewport writes them back.
  A unit without its own position sits on its first positioned descendant (e.g. an enemy unit on its
  mEnemyCreateData), so moving the unit moves the enemy.
- Ref values (a track index, e.g. a set's mGroupLV1 -> a group) are object pointers, so they survive reordering.
- Duplicating a unit (with its children) adds it right after the original; deleting one removes its tracks.
"""
import json
import math

import bpy
from mathutils import Euler, Matrix, Vector

from dmc4xml import pla as pla_codec
from dmc4xml.dti import dti_id as _dti_id, dti_name as _dti_name

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.vfs import VirtualFileData

TRACK_PROP = "pla_track"        # JSON: the container track's own fields
LAYOUT_PROP = "pla_layout"      # JSON: [{"child": index} | value entry, ...] in file order
ROOT_PROP = "pla_root"          # JSON on the root Empty: header fields
POSITION_NAMES = ("mPos",)
ROTATION_NAMES = ("mRotY",)    # float, degrees about the game's up axis
ANGLE_NAMES = ("mAngle",)       # vector, radians, game-axis Euler
ANGLE_ORDER = "ZXY"             # uCoord::mOrder 4 (its default; no .pla sets mOrder)
EPSILON_CM = 0.01            # float32 matrices lose ~1e-3 cm at stage-sized coordinates
EPSILON_DEG = 1e-4
EPSILON_RAD = 2e-6
GAME_AXES = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))   # game (Y up) -> Blender (Z up)


def game_to_blender(v):
    return Vector((v[0] * 0.01, -v[2] * 0.01, v[1] * 0.01))


def blender_to_game(v):
    return (v[0] * 100.0, v[2] * 100.0, -v[1] * 100.0)


def _signed(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= 1 << 31 else v


def _children_of(tracks):
    kids = {}
    for i, t in enumerate(tracks[1:], 1):
        kids.setdefault(t.parent, []).append(i)
    return kids


def _value_key(entry, names_seen):
    name = entry["name"]
    return name if names_seen[name] == 1 else f"{name}[{entry['index']}]"


# ---- import ------------------------------------------------------------------------------------------------------

def own_collection(root_ob, context, collection=None):
    """Link root_ob and everything under it into its own collection (named like the root, under the active
    collection), or into `collection` (a rebuild keeps the old one)."""
    if collection is None:
        collection = bpy.data.collections.new(root_ob.name)
        context.collection.children.link(collection)
    for ob in [root_ob] + list(root_ob.children_recursive):
        if ob.name not in collection.objects:
            collection.objects.link(ob)
    return collection


@blender_registry.register_import_function(app_id="dmc4", extension="pla", file_category="PLACEMENT")
def load_pla(file_item, context):
    data = file_item.get_bytes()
    build_pla_objects(data, file_item.display_name.split(".")[0], file_item, context)
    return None     # linked into its own collection


def build_pla_objects(data, stem, asset, context, collection=None):
    """.pla bytes -> the root Empty `PLA_<stem>` and its track Empties, linked into their own collection (or
    `collection`) and added to the export list. `asset` gives app_id / relative_path / extension."""
    try:
        pla = pla_codec.read(data)
    except pla_codec.PlaError as err:
        raise AlbamCheckFailure("Can't read this placement file", details=str(err),
                                solution="Only DX9 DMC4 .pla files (version 17) are supported.")
    tracks = pla.tracks
    kids = _children_of(tracks)

    root_ob = bpy.data.objects.new(f"PLA_{stem}", None)
    root_ob.empty_display_size = 0.5
    root_ob[ROOT_PROP] = json.dumps({"dti_table_offset": pla.dti_table_offset, "name": tracks[0].name,
                                     "str_ofs": tracks[0].name_ofs})
    objects = {0: root_ob}
    pending_refs = []

    def build(ob, index):
        layout, names_seen = [], {}
        for c in kids.get(index, []):
            if tracks[c].type in pla_codec.VALUE_TYPES:
                names_seen[tracks[c].name] = names_seen.get(tracks[c].name, 0) + 1
        for c in kids.get(index, []):
            t = tracks[c]
            if t.type in pla_codec.CONTAINERS:
                layout.append({"child": c})
                child = bpy.data.objects.new(t.name, None)
                child.parent = ob
                child[TRACK_PROP] = json.dumps({"index": c, "type": t.type, "prop_type": t.prop_type,
                                                "dti": _dti_name(t.dti), "move_line": t.move_line, "name": t.name,
                                                "str_ofs": t.name_ofs, "encoding": t.encoding})
                child.empty_display_size = 0.15
                objects[c] = child
                build(child, c)
                continue
            entry = {"name": t.name, "type": t.type, "prop_type": t.prop_type, "index": t.dti,
                     "move_line": t.move_line, "str_ofs": t.name_ofs, "encoding": t.encoding}
            key = _value_key(entry, names_seen)
            entry["key"] = key
            if t.type == pla_codec.BOOL:
                ob[key] = bool(t.value)
                entry["raw"] = t.value
            elif t.type == pla_codec.INT:
                ob[key] = _signed(t.value)
            elif t.type == pla_codec.FLOAT:
                ob[key] = t.value
            elif t.type == pla_codec.VECTOR:
                ob[key] = list(t.value)
            elif t.type == pla_codec.REF:
                ob[key] = _signed(t.value)
                pending_refs.append((ob, key, t.value))
            elif t.type == pla_codec.RESOURCE:
                ob[key] = t.value[1] if t.value else ""
                if t.value:
                    entry["ref_dti"] = _dti_name(t.value[0])
                    entry["ref_ofs"] = t.ref_ofs
            layout.append(entry)
        ob[LAYOUT_PROP] = json.dumps(layout)

    build(root_ob, 0)
    for ob, key, target in pending_refs:
        if target in objects and target != 0:
            ob[key] = objects[target]
    own_collection(root_ob, context, collection)
    _place(root_ob)

    root_ob.albam_asset.original_bytes = data
    root_ob.albam_asset.app_id = asset.app_id
    root_ob.albam_asset.relative_path = asset.relative_path
    root_ob.albam_asset.extension = asset.extension
    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = root_ob
    context.scene.albam.exportable.file_list.update()
    return root_ob


def angle_to_matrix(angle):
    """mAngle (game-axis Euler, radians) -> Blender rotation matrix (3x3)"""
    return GAME_AXES @ Euler(tuple(angle[:3]), ANGLE_ORDER).to_matrix() @ GAME_AXES.transposed()


def _own_transform(ob):
    """(location, rotation 3x3) from the Empty's own mPos and mRotY / mAngle props, None for missing ones."""
    loc = rot = None
    for entry in json.loads(ob.get(LAYOUT_PROP, "[]")):
        if "child" in entry:
            continue
        if loc is None and entry["name"] in POSITION_NAMES and entry["type"] == pla_codec.VECTOR:
            loc = game_to_blender(ob[entry["key"]])
        if rot is None and entry["name"] in ROTATION_NAMES and entry["type"] == pla_codec.FLOAT:
            rot = Matrix.Rotation(math.radians(ob[entry["key"]]), 3, "Z")
        if rot is None and entry["name"] in ANGLE_NAMES and entry["type"] == pla_codec.VECTOR:
            rot = angle_to_matrix(ob[entry["key"]])
    return loc, rot


def _place(root_ob):
    """World transforms from the props: positioned Empties at their mPos, others on their first positioned
    descendant (or their parent)."""
    def first_position(ob):
        loc, rot = _own_transform(ob)
        if loc is not None:
            return loc, rot
        for c in ob.children:
            found = first_position(c)
            if found:
                return found
        return None

    def visit(ob, parent_world):
        loc, rot = _own_transform(ob)
        positioned = loc is not None
        if not positioned and ob is not root_ob:
            found = first_position(ob)
            if found:
                loc, rot = found
        world = parent_world.copy()
        if loc is not None:
            world = Matrix.Translation(loc) @ (rot.to_4x4() if rot is not None else Matrix.Identity(4))
        if ob is not root_ob:
            # local transform from our own world matrices (the parents' matrix_world isn't evaluated yet)
            ob.matrix_parent_inverse = Matrix.Identity(4)
            ob.matrix_basis = parent_world.inverted() @ world
            ob.empty_display_type = "ARROWS" if positioned else "PLAIN_AXES"
            ob.empty_display_size = 0.5 if positioned else 0.15
        for c in ob.children:
            visit(c, world)

    visit(root_ob, Matrix.Identity(4))


# ---- export ------------------------------------------------------------------------------------------------------

def _sync_transform(ob, notes):
    """Write a moved / turned Empty back into its mPos and mRotY / mAngle props."""
    layout = json.loads(ob.get(LAYOUT_PROP, "[]"))
    loc, rot = _own_transform(ob)
    world = ob.matrix_world
    for entry in layout:
        if "child" in entry:
            continue
        key = entry["key"]
        if loc is not None and entry["name"] in POSITION_NAMES and entry["type"] == pla_codec.VECTOR:
            new = blender_to_game(world.translation)
            old = list(ob[key])
            if any(abs(a - b) > EPSILON_CM for a, b in zip(new, old[:3])):
                ob[key] = list(new) + old[3:]
                notes.append(f"{ob.name}: {entry['name']} from its location")
            loc = None
        if rot is not None and entry["name"] in ROTATION_NAMES and entry["type"] == pla_codec.FLOAT:
            new = math.degrees(world.to_euler("XYZ").z)
            old = ob[key]
            diff = (new - old + 180.0) % 360.0 - 180.0
            if abs(diff) > EPSILON_DEG:
                ob[key] = old + diff
                notes.append(f"{ob.name}: {entry['name']} from its rotation")
            rot = None
        if rot is not None and entry["name"] in ANGLE_NAMES and entry["type"] == pla_codec.VECTOR:
            old = list(ob[key])
            current = world.to_3x3().normalized()
            if any(abs(a - b) > EPSILON_RAD for ra, rb in zip(current, angle_to_matrix(old)) for a, b in zip(ra, rb)):
                game = GAME_AXES.transposed() @ current @ GAME_AXES
                new = game.to_euler(ANGLE_ORDER, Euler(tuple(old[:3]), ANGLE_ORDER))
                ob[key] = list(new) + old[3:]
                notes.append(f"{ob.name}: {entry['name']} from its rotation")
            rot = None


def ordered_children(ob, track_prop=TRACK_PROP, layout_prop=LAYOUT_PROP):
    """[(layout entry or None, child Empty or None)] in file order: value entries (child None) and child Empties as
    the layout lists them; a duplicate of a child (same source index) right after it, entry None; children the layout
    doesn't know at the end. Shared with scheduler.py."""
    layout = json.loads(ob.get(layout_prop, "[]"))
    pool = {}
    for c in sorted(ob.children, key=lambda c: c.name):
        if track_prop in c:
            pool.setdefault(json.loads(c[track_prop])["index"], []).append(c)
    order = []
    for entry in layout:
        if "child" not in entry:
            order.append((entry, None))
        elif pool.get(entry["child"]):
            first, *copies = pool.pop(entry["child"])
            order.append((entry, first))
            order.extend((None, c) for c in copies)
    order.extend((None, c) for cs in pool.values() for c in cs)
    return order


def build_pla(root_ob):
    """Root Empty -> (Pla, notes)."""
    # positions come from matrix_world: make sure it's evaluated (right after an import it's still identity)
    bpy.context.view_layer.update()
    notes, problems = [], []
    head = json.loads(root_ob.get(ROOT_PROP, "{}"))
    pla = pla_codec.Pla(dti_table_offset=head.get("dti_table_offset", 0))
    pla.tracks.append(pla_codec.Track(pla_codec.ROOT, name=head.get("name", "Root"), name_ofs=head.get("str_ofs", 0)))
    new_index = {root_ob.name: 0}
    ref_fixups = []

    def emit(ob, index):
        _sync_transform(ob, notes)
        for entry, child in ordered_children(ob):
            if child is not None:
                info = json.loads(child[TRACK_PROP])
                t = pla_codec.Track(info["type"], info["prop_type"], index, info["move_line"], info["name"],
                                    _dti_id(info["dti"]), name_ofs=info.get("str_ofs"),
                                    encoding=info.get("encoding", "utf-8"))
                if entry is None:
                    t.name_ofs = None
                new_index[child.name] = len(pla.tracks)
                pla.tracks.append(t)
                emit(child, new_index[child.name])
                continue
            key = entry["key"]
            if key not in ob:
                problems.append(f"{ob.name}: property {key} is missing")
                continue
            value = ob[key]
            t = pla_codec.Track(entry["type"], entry["prop_type"], index, entry.get("move_line", 0), entry["name"],
                                entry["index"], name_ofs=entry.get("str_ofs"), encoding=entry.get("encoding", "utf-8"))
            if t.type == pla_codec.BOOL:
                raw = entry.get("raw")
                t.value = raw if raw is not None and bool(raw) == bool(value) else int(bool(value))
            elif t.type in (pla_codec.INT, pla_codec.REF):
                if isinstance(value, bpy.types.Object):
                    ref_fixups.append((t, value))
                    value = 0
                t.value = int(value) & 0xFFFFFFFF
            elif t.type == pla_codec.FLOAT:
                t.value = float(value)
            elif t.type == pla_codec.VECTOR:
                v = [float(x) for x in value]
                if len(v) not in (3, 4):
                    problems.append(f"{ob.name}: {key} needs 3 or 4 numbers")
                    continue
                t.value = tuple(v + [0.0] * (4 - len(v)))
            elif t.type == pla_codec.RESOURCE:
                path = str(value)
                if path:
                    t.value = (_dti_id(entry.get("ref_dti", "0")), path)
                    t.ref_ofs = entry.get("ref_ofs")
            pla.tracks.append(t)

    emit(root_ob, 0)
    for t, target in ref_fixups:
        if target.name in new_index:
            t.value = new_index[target.name]
        else:
            problems.append(f"{t.name} points at {target.name}, which isn't part of this placement")
    if problems:
        raise AlbamCheckFailure(f"Placement {root_ob.name} can't be exported", details="\n".join(problems),
                                solution="Fix the listed properties.")
    return pla, notes


@blender_registry.register_export_function(app_id="dmc4", extension="pla")
def export_pla(bl_obj):
    pla, notes = build_pla(bl_obj)
    try:
        data = pla_codec.write(pla)
    except pla_codec.PlaError as err:
        raise AlbamCheckFailure(f"Placement {bl_obj.name} can't be exported", details=str(err),
                                solution="Fix the listed tracks.")
    asset = bl_obj.albam_asset
    print(f"PLA export {asset.relative_path}: {len(pla.tracks)} tracks")
    for note in notes:
        print("  " + note)
    bl_obj["pla_export_notes"] = notes[:200]
    return [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]
