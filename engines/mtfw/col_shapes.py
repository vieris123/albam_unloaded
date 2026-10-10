"""DMC4 collision shapes (`.col` = rCollisionShape) import: the spheres and capsules on a model's joints that the game
uses for hitboxes (attack / hurt / push / grab groups, `Collision\\pl000.col`, `wp*.col`, enemies) and for model
chains (`model\\game\\pl000\\pl000_03.col`: the body capsules Nero's coat collides with). Format: the vendored
dmc4xml.col (byte-exact on the 110 DX9 files); runtime: Vibed/RE/chain_cnschain.md section 4.

Import makes an Empty `COL_<file>` in its own collection and, on the armature the shapes hang on, one object per
shape: a sphere Empty (radius = the shape's) parented to the joint at the shape's offset, or for a capsule two such
Empties (one per end, each on its own joint) and a wire tube between them, hooked to both ends so it follows the
pose. Objects are coloured by their group's flags. The armature is found by itself (find_col_armature): a chain
model's .col (pl000_03.col next to pl000_03_00.phs) belongs to the body (pl000.mod), any other to the imported model
named like it (em010shl.col -> em010.mod); else the active armature. The shapes' joint numbers must all exist on it.
Without one the Empty waits and the shapes are built when the model is imported (cns_chain_preview.wire_scene), or
with Attach to Armature.

Import only: the shapes aren't written back yet (hitbox editing, with .atk / .dfd, is a ROADMAP item).
"""
import json
import math
import re

import bpy
from mathutils import Matrix, Vector

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.engines.mtfw.cns_chain import (ARMATURE_PROP, _folder, _joint_bones, _stem, find_model_armature,
                                          model_armatures)

SCALE = 0.01
NO_JOINT = 255
MODEL_ORIGIN = 0xFFFFFFFF       # hitbox shapes with joint -1 (Collision\pl000.col): placed in the model's own space
SHAPES_PROP = "col_shapes"      # root: JSON [[type, object a, object b ("" for a sphere), radius m, group], ...]
ROOT_PROP = "col_root"          # shape objects: their COL_ Empty
TUBE_SEGMENTS = 12
FLAG_NAMES = ((0x1, "attack"), (0x2, "hurt"), (0x4, "push"), (0x8, "grab"), (0x10, "0x10"), (0x20, "friendly attack"))
FLAG_COLORS = ((0x1, (1.0, 0.2, 0.15, 1.0)), (0x8, (1.0, 0.8, 0.1, 1.0)), (0x2, (0.2, 0.45, 1.0, 1.0)),
               (0x4, (0.2, 0.9, 0.3, 1.0)))


def flag_text(flags):
    names = [name for bit, name in FLAG_NAMES if flags & bit]
    other = flags & ~sum(bit for bit, _ in FLAG_NAMES)
    if other:
        names.append(hex(other))
    return ", ".join(names) or "none"


def _color(flags):
    for bit, color in FLAG_COLORS:
        if flags & bit:
            return color
    return (0.7, 0.7, 0.7, 1.0)


def is_col_root(ob):
    return ob is not None and ob.type == "EMPTY" and ob.albam_asset.extension == "col"


def col_root_of(ob):
    if is_col_root(ob):
        return ob
    root = ob.get(ROOT_PROP) if ob is not None else None
    return root if isinstance(root, bpy.types.Object) else None


def read_col(root):
    from dmc4xml import col as col_codec
    return col_codec.read(bytes(root.albam_asset.original_bytes))


def shape_joints(col):
    out = set()
    for group in col.groups:
        for shape in group.shapes:
            if shape.type in (0, 3):
                out.add(shape.bone0)
            if shape.type == 3:
                out.add(shape.bone1)
    out.discard(NO_JOINT)
    out.discard(MODEL_ORIGIN)
    return out


def _has_chain_files(context, folder, stem):
    """are there <stem>_*.phs chains in this Game Files folder (i.e. is <stem> a chain model like Nero's coat)"""
    prefix = "dmc4::" + "::".join(p for p in folder.split("\\") if p) + "::" + stem + "_"
    prefix = prefix.lower()
    return any(item.name.lower().startswith(prefix) and item.name.lower().endswith((".phs", ".clt"))
               for item in context.scene.albam.rfs.file_list)


def body_model_stem(context, relative_path):
    """pl000_03.col next to pl000_03_NN.phs chains: the body capsules the chain model collides with -> pl000"""
    stem, folder = _stem(relative_path), _folder(relative_path)
    m = re.match(r"^(.*)_\d+$", stem)
    return m.group(1) if m and _has_chain_files(context, folder, stem) else None


def col_model_stems(context, relative_path):
    """model names to try for a .col, best first"""
    stem = _stem(relative_path)
    body = body_model_stem(context, relative_path)
    if body is not None:
        return [body]                   # only the body: the chain model has the same joint numbers
    out = [stem]
    for ob in sorted(model_armatures(context.scene), key=lambda o: -len(_stem(o.albam_asset.relative_path))):
        model = _stem(ob.albam_asset.relative_path)
        if stem.startswith(model) and model not in out:
            out.append(model)           # em010shl.col -> em010.mod
    return out


def find_col_armature(context, root):
    path = root.albam_asset.relative_path
    chain_body = body_model_stem(context, path) is not None
    return find_model_armature(context, col_model_stems(context, path), shape_joints(read_col(root)), _folder(path),
                               allow_active=not chain_body, partial=not chain_body)


def _end(name, armature, bone, pos, radius, coll, root, group, index):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = "SPHERE"
    ob.empty_display_size = max(radius, 1e-4)
    ob.parent = armature
    if bone is None:
        # no joint: the model's own space (game axes, cm)
        ob.matrix_parent_inverse = Matrix.Identity(4)
        ob.matrix_basis = Matrix.Translation(Vector((pos[0], -pos[2], pos[1])) * SCALE)
    else:
        ob.parent_type = "BONE"
        ob.parent_bone = bone.name
        # BONE parenting starts at the bone's tail; the offset is in the joint's frame (bone frame = joint frame)
        ob.matrix_parent_inverse = Matrix.Translation((0.0, -bone.length, 0.0))
        ob.matrix_basis = Matrix.Translation(Vector(pos[:3]) * SCALE)
    ob.hide_render = True
    ob[ROOT_PROP] = root
    ob["col_group"] = group
    ob["col_shape"] = index
    coll.objects.link(ob)
    return ob


def _tube(name, a, b, radius, coll, root, color):
    """wire tube between capsule ends a and b, each half hooked to its end so it follows the pose"""
    pa, pb = a.matrix_world.translation, b.matrix_world.translation
    axis = pb - pa
    if axis.length < 1e-6:
        axis = Vector((0.0, 0.0, 1.0))
    axis.normalize()
    side = axis.orthogonal().normalized()
    up = axis.cross(side)
    verts = []
    for centre in (pa, pb):
        for k in range(TUBE_SEGMENTS):
            t = 6.283185307179586 * k / TUBE_SEGMENTS
            verts.append(centre + (side * math.cos(t) + up * math.sin(t)) * radius)
    n = TUBE_SEGMENTS
    faces = [(k, (k + 1) % n, n + (k + 1) % n, n + k) for k in range(n)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    ob = bpy.data.objects.new(name, mesh)
    coll.objects.link(ob)
    ob.display_type = "WIRE"
    ob.color = color
    ob.hide_render = True
    ob[ROOT_PROP] = root
    for end, indices in ((a, range(n)), (b, range(n, 2 * n))):
        hook = ob.modifiers.new(f"ALBAM_COL_{end.name[-1]}", "HOOK")
        hook.object = end
        hook.vertex_indices_set(list(indices))
        # mat = tube^-1 . end . inverse: identity at the pose the tube was built in, so each ring follows its end
        hook.matrix_inverse = end.matrix_world.inverted() @ ob.matrix_world
    return ob


def clear_shapes(root):
    for entry in json.loads(root.get(SHAPES_PROP, "[]")):
        for name in entry[1:3]:
            ob = bpy.data.objects.get(name) if name else None
            if ob is not None:
                bpy.data.objects.remove(ob)
        tube = bpy.data.objects.get(entry[5]) if len(entry) > 5 and entry[5] else None
        if tube is not None:
            bpy.data.objects.remove(tube)
    root[SHAPES_PROP] = "[]"


def build_shapes(root, armature, context):
    """(Re)build root's shape objects on armature. Returns the joint numbers it doesn't have."""
    clear_shapes(root)
    col = read_col(root)
    coll = root.users_collection[0] if root.users_collection else context.collection
    root.parent = armature
    root.matrix_parent_inverse = Matrix.Identity(4)
    root[ARMATURE_PROP] = armature
    bones = _joint_bones(armature)
    missing, entries, ends = set(), [], []
    stem = root.name
    for gi, group in enumerate(col.groups):
        for si, shape in enumerate(group.shapes):
            radius = shape.radius * SCALE
            name = f"{stem}_{gi}_{si}"
            joints = [shape.bone0] if shape.type == 0 else [shape.bone0, shape.bone1] if shape.type == 3 else []
            if not joints:
                continue                        # type 1 (6 shapes in the game's files): not used by the chains
            lost = [j for j in joints if j != MODEL_ORIGIN and j not in bones]
            if lost:
                missing.update(lost)
                continue
            if shape.type == 0:
                a = _end(name, armature, bones.get(shape.bone0), shape.pos0, radius, coll, root, gi, si)
                entries.append(["sphere", a.name, "", radius, gi, ""])
            else:
                a = _end(name + "_a", armature, bones.get(shape.bone0), shape.pos0, radius, coll, root, gi, si)
                b = _end(name + "_b", armature, bones.get(shape.bone1), shape.pos1, radius, coll, root, gi, si)
                entries.append(["capsule", a.name, b.name, radius, gi, ""])
                ends.append((len(entries) - 1, name, a, b, radius, _color(group.flags)))
    context.view_layer.update()
    for index, name, a, b, radius, color in ends:
        entries[index][5] = _tube(name, a, b, radius, coll, root, color).name
    root[SHAPES_PROP] = json.dumps(entries)
    if missing:
        root["col_missing_joints"] = sorted(missing)
    elif "col_missing_joints" in root:
        del root["col_missing_joints"]
    return sorted(missing)


def shapes_world(root):
    """[("sphere", centre, r) | ("capsule", a, b, r)] in world space, file order (for the chain preview)"""
    out = []
    for entry in json.loads(root.get(SHAPES_PROP, "[]")):
        a = bpy.data.objects.get(entry[1])
        if a is None:
            continue
        if entry[0] == "sphere":
            out.append(("sphere", a.matrix_world.translation.copy(), entry[3]))
        else:
            b = bpy.data.objects.get(entry[2])
            if b is not None:
                out.append(("capsule", a.matrix_world.translation.copy(), b.matrix_world.translation.copy(), entry[3]))
    return out


# ---- which groups are on: the motion's first event table ------------------------------------------------------------
#
# An LMT animation's first event table is (value, duration) runs; bit k (k < 8) of the value switches on .col group
# events_params_01[k] of that animation (Albam: "Hitbox Slot Values"). XOR-ing consecutive values shows which slots
# change on that frame. Seen in Nero's files: idle / walk slots 0 / 1 = groups 5 / 6 (hurt + push on the body), the
# Snatch turns on grab groups 120 / 121 / 122 one frame after another (pl000_02 block 30). Matches the data; the game
# code that reads it wasn't traced.

FOLLOW_PROP = "col_follow_events"


def _event_value(action, frame):
    """(slot values, event value at frame) of an LMT action's first event table, or None without events"""
    from albam.engines.mtfw.animation import find_event_marker, get_lmt_props
    try:
        props = get_lmt_props(action)
    except Exception:                       # noqa: BLE001 - not an LMT action
        return None
    best = None
    for i, event in enumerate(props.event_markers):
        if event.param_ev_type not in ("", "Hitbox"):
            continue
        marker = find_event_marker(action, event, i)
        if marker is not None and marker.frame <= frame and (best is None or marker.frame >= best[0]):
            best = (marker.frame, event.encode())
    return None if best is None else (list(props.events_params_01), best[1])


def active_groups(root, frame):
    """the .col groups the animation on root's armature has on at frame, or None (show every group)"""
    arm = root.get(ARMATURE_PROP)
    if not root.get(FOLLOW_PROP, False) or not isinstance(arm, bpy.types.Object):
        return None
    action = arm.animation_data.action if arm.animation_data else None
    found = _event_value(action, frame) if action is not None else None
    if found is None:
        return None
    params, value = found
    return {params[k] for k in range(len(params)) if value >> k & 1}


def update_visibility(scene):
    """hide the shape objects of groups that are off at the current frame (eye icon only: they stay evaluated)"""
    for root in scene.objects:
        if not is_col_root(root):
            continue
        groups = active_groups(root, scene.frame_current)
        for entry in json.loads(root.get(SHAPES_PROP, "[]")):
            hidden = groups is not None and entry[4] not in groups
            for name in (entry[1], entry[2], entry[5] if len(entry) > 5 else ""):
                ob = scene.objects.get(name) if name else None
                if ob is not None and ob.hide_get() != hidden:
                    ob.hide_set(hidden)


@blender_registry.register_import_function(app_id="dmc4", extension="col", file_category="HITBOX")
def load_col(file_item, context):
    from dmc4xml import col as col_codec
    data = file_item.get_bytes()
    try:
        col = col_codec.read(bytes(data))
    except col_codec.ColError as err:
        raise AlbamCheckFailure("Can't read this collision shape file", details=str(err),
                                solution="Only DX9 DMC4 .col files (COL version 2) are supported.")
    stem = file_item.display_name.split(".")[0]
    coll = bpy.data.collections.new(f"COL_{stem}")
    context.collection.children.link(coll)
    root = bpy.data.objects.new(f"COL_{stem}", None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.05
    coll.objects.link(root)
    root.albam_asset.original_bytes = data
    root.albam_asset.app_id = file_item.app_id
    root.albam_asset.relative_path = file_item.relative_path
    root.albam_asset.extension = file_item.extension
    root[SHAPES_PROP] = "[]"
    root["col_group_kinds"] = [g.kind for g in col.groups] or [0]
    root["col_group_flags"] = [g.flags for g in col.groups] or [0]
    root.id_properties_ui("col_group_kinds").update(description="cCollisionGroup.mKind of each group (0-6)")
    root.id_properties_ui("col_group_flags").update(
        description="Flags of each group: 1 attack, 2 hurt, 4 push, 8 grab, 0x20 friendly attack")
    # hitbox files follow the animation's events; a chain model's body shapes (pl000_03.col) aren't switched by them
    root[FOLLOW_PROP] = body_model_stem(context, file_item.relative_path) is None
    root.id_properties_ui(FOLLOW_PROP).update(
        description="Show only the groups the playing animation has on (bit k of its first event table's value = "
                    "group 'Hitbox Slot Values'[k]); off = show every group")
    armature = find_col_armature(context, root)
    if armature is not None:
        build_shapes(root, armature, context)
    from albam.engines.mtfw.cns_chain_preview import wire_scene
    wire_scene(context)
    return None     # linked into its own collection
