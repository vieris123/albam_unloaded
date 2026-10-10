"""DMC4 collision shapes (`.col` = rCollisionShape): import, export and new files. The spheres and capsules on a
model's joints that the game uses for hitboxes (attack / hurt / push / grab groups, `Collision\\pl000.col`, `wp*.col`,
enemies) and for model chains (`model\\game\\pl000\\pl000_03.col`: the body capsules Nero's coat collides with).
Format: the vendored dmc4xml.col (byte-exact on the 110 DX9 files); runtime: Vibed/RE/chain_cnschain.md section 4.

Objects (all in the file's own collection `COL_<file>`, all carrying `col_root` = the root Empty `COL_<file>`):
- a sphere: an Empty (display Sphere, size = radius) parented to its joint's bone at the shape's offset (`col_kind`
  "sphere"), or to the armature itself for joint -1 (the model's own space);
- a capsule: two such Empties, end "a" (joint 0 / pos 0) and end "b", sharing a key `col_capsule`, plus a wire tube
  (`col_kind` "tube", same key) hooked to both ends. The tube is display only: sync_tubes rebuilds it whenever the
  capsule changes (Shift+D, delete, scale), and keeps both ends the same size. (Not object pointers: Blender's
  duplicate re-points ID properties of the originals too, tested in 4.2.)
Every end carries `col_name` (its name when made): after a Shift+D the objects still carrying their own names are
the originals, the copies (Blender suffixes .001 ...) pair up by suffix and get a new key (adopt_copies). Each
sphere / end a carries `col_group` (its group), `col_id` / `col_shrink` (the shape's mID / mShrink) and, for shapes
read from the file, `col_src` = [group, index] (dropped from copies, so a copy is a new shape). The groups (kind,
flags) are `root.albam_col.groups`.

Editing is plain Blender: move / scale the spheres, Shift+D to add one (a whole capsule: select both ends), X to
delete, re-parent to another bone (Ctrl+P > Bone) to change its joint, Collision Shapes panel for the group. Export
(build_col) starts from the source file and writes only what changed, so untouched files come back byte-identical;
source shapes without objects (type 1, or on joints the armature lacks) are kept as they were. New files: New
Collision Shapes on an armature (Object Properties > Collision Shapes), Add Sphere / Add Capsule at the selected
bones.

The armature is found by itself on import (find_col_armature): a chain model's .col (pl000_03.col next to
pl000_03_00.phs) belongs to the body (pl000.mod), any other to the imported model named like it (em010shl.col ->
em010.mod); else the active armature. Without one the Empty waits and the shapes are built when the model is
imported (cns_chain_preview.wire_scene), or with Attach to Armature.
"""
import math
import re
import uuid

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.vfs import VirtualFileData
from albam.engines.mtfw.cns_chain import (ARMATURE_PROP, JOINT_PROP, _folder, _joint_bones, _stem, apply_tips,
                                          find_model_armature, model_armatures)

SCALE = 0.01
NO_JOINT = 255
MODEL_ORIGIN = 0xFFFFFFFF       # joint -1 (Collision\pl000.col hitboxes, a sphere's unused second end)
ROOT_PROP = "col_root"          # every shape object: its COL_ Empty
KIND_PROP = "col_kind"          # "sphere" | "a" | "b" | "tube"
CAP_PROP = "col_capsule"        # capsule ends and tube: the capsule's key
GROUP_PROP = "col_group"
SRC_PROP = "col_src"            # [group, index] of the source shape
NAME_PROP = "col_name"          # an end's name when made (a Shift+D copy has another name)
ID_PROP = "col_id"
SHRINK_PROP = "col_shrink"
RADIUS_PROP = "col_radius"      # end a / b: radius (cm) last synced, to tell which end was resized
UNBUILT_PROP = "col_unbuilt"    # root: flat [group, index, ...] of source shapes without objects (kept as they are)
BUILT_PROP = "col_built"        # root: its shapes are objects (until then export keeps the source's shapes as they are)
TUBE_SEGMENTS = 12
FLAG_BITS = (0x1, 0x2, 0x4, 0x8, 0x10, 0x20)
FLAG_NAMES = ("attack", "hurt", "push", "grab", "0x10", "friendly attack")
FLAG_COLORS = ((0x1, (1.0, 0.2, 0.15, 1.0)), (0x8, (1.0, 0.8, 0.1, 1.0)), (0x2, (0.2, 0.45, 1.0, 1.0)),
               (0x4, (0.2, 0.9, 0.3, 1.0)))
DEFAULT_FLAGS = 0x4             # a new group: push


def flag_text(flags):
    names = [name for bit, name in zip(FLAG_BITS, FLAG_NAMES) if flags & bit]
    other = flags & ~sum(FLAG_BITS)
    if other:
        names.append(hex(other))
    return ", ".join(names) or "none"


def _color(flags):
    for bit, color in FLAG_COLORS:
        if flags & bit:
            return color
    return (0.7, 0.7, 0.7, 1.0)


# ---- groups: a property group on the root --------------------------------------------------------------------------

def _get_flag_bits(self):
    return [bool(self.flags & bit) for bit in FLAG_BITS]


def _set_flag_bits(self, values):
    flags = self.flags & ~sum(FLAG_BITS)
    for bit, on in zip(FLAG_BITS, values):
        if on:
            flags |= bit
    self.flags = flags


def _group_changed(self, context):
    root = self.id_data
    _signatures.pop(root.name, None)            # recolour the tubes
    _schedule_sync()


@blender_registry.register_blender_prop_albam(name="col_ui")
class AlbamColUi(bpy.types.PropertyGroup):
    target: bpy.props.StringProperty(
        name="Shapes", description="The collision shape file (COL_ object) Add Sphere / Add Capsule put shapes into "
                                   "when the armature carries more than one")


@blender_registry.register_blender_prop
class AlbamColGroup(bpy.types.PropertyGroup):
    kind: bpy.props.IntProperty(
        name="Kind", min=0, max=255, update=_group_changed,
        description="cCollisionGroup.mKind: what the group belongs to (0-6 in the game's files; meaning per value "
                    "not decoded)")
    flags: bpy.props.IntProperty(
        name="Flags", min=0, update=_group_changed,
        description="Group flags: 1 attack, 2 hurt (takes damage), 4 push (keeps bodies apart), 8 grab, 0x20 "
                    "friendly attack")
    flag_bits: bpy.props.BoolVectorProperty(
        name="Flags", size=len(FLAG_BITS), get=_get_flag_bits, set=_set_flag_bits,
        description="Attack: deals hits. Hurt: can be hit. Push: keeps bodies apart. Grab: grabs (Snatch). "
                    "0x10: unnamed. Friendly attack: hits allies")


def _follow_changed(self, context):
    if context is not None and context.scene is not None:
        update_visibility(context.scene)


@blender_registry.register_blender_props_to_type("Object", "albam_col")
class AlbamColSettings(bpy.types.PropertyGroup):
    groups: bpy.props.CollectionProperty(type=AlbamColGroup)
    follow_events: bpy.props.BoolProperty(
        name="Follow Animation Events", update=_follow_changed,
        description="Show only the groups the playing animation has on (bit k of its first event table's value = "
                    "group 'Hitbox Slot Values'[k]); off = show every group")


def is_col_root(ob):
    return ob is not None and ob.type == "EMPTY" and ob.albam_asset.extension == "col"


def col_root_of(ob):
    if is_col_root(ob):
        return ob
    root = ob.get(ROOT_PROP) if ob is not None else None
    return root if isinstance(root, bpy.types.Object) else None


def shapes_armature(root):
    arm = root.get(ARMATURE_PROP) if root is not None else None
    return arm if isinstance(arm, bpy.types.Object) and arm.type == "ARMATURE" else None


def read_col(root):
    """the source file (None for a new one)"""
    from dmc4xml import col as col_codec
    data = bytes(root.albam_asset.original_bytes)
    return col_codec.read(data) if data else None


def shape_joints(col):
    out = set()
    for group in (col.groups if col is not None else []):
        for shape in group.shapes:
            if shape.type in (0, 3):
                out.add(shape.bone0)
            if shape.type == 3:
                out.add(shape.bone1)
    out.discard(NO_JOINT)
    out.discard(MODEL_ORIGIN)
    return out


# ---- which armature ------------------------------------------------------------------------------------------------

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


# ---- shape objects -------------------------------------------------------------------------------------------------

def members(root):
    return [ob for ob in bpy.data.objects if ob.get(ROOT_PROP) == root]


def _place(ob, armature, bone, pos):
    """parent ob to bone (None: the armature itself, model space) at pos (cm, the joint's frame / game axes)"""
    ob.parent = armature
    if bone is None:
        ob.parent_type = "OBJECT"
        ob.matrix_parent_inverse = Matrix.Identity(4)
        ob.matrix_basis = Matrix.Translation(Vector((pos[0], -pos[2], pos[1])) * SCALE)
    else:
        ob.parent_type = "BONE"
        ob.parent_bone = bone.name
        # BONE parenting starts at the bone's tail; the offset is in the joint's frame (bone frame = joint frame)
        ob.matrix_parent_inverse = Matrix.Translation((0.0, -bone.length, 0.0))
        ob.matrix_basis = Matrix.Translation(Vector(pos[:3]) * SCALE)


def _new_end(name, kind, armature, bone, pos, radius_cm, coll, root):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = "SPHERE"
    ob.empty_display_size = max(radius_cm * SCALE, 1e-4)
    _place(ob, armature, bone, pos)
    ob.hide_render = True
    ob[ROOT_PROP] = root
    ob[KIND_PROP] = kind
    ob[RADIUS_PROP] = float(radius_cm)
    coll.objects.link(ob)
    ob[NAME_PROP] = ob.name
    apply_tips(ob)
    return ob


def _new_capsule_key():
    return uuid.uuid4().hex[:12]


def _mark_shape(ob, group, src=None, shape_id=0, shrink=0.0):
    ob[GROUP_PROP] = group
    ob.id_properties_ui(GROUP_PROP).update(min=0, description="Group of the shape (Collision Shapes panel)")
    ob[ID_PROP] = shape_id
    ob.id_properties_ui(ID_PROP).update(description="cCollPrim mID (0 in most of the game's shapes)")
    ob[SHRINK_PROP] = float(shrink)
    ob.id_properties_ui(SHRINK_PROP).update(description="cCollPrim mShrink (0 in most of the game's shapes)")
    if src is not None:
        ob[SRC_PROP] = list(src)
    apply_tips(ob)


def radius_cm(ob):
    """an end's radius: its display size times its own (largest) scale"""
    return ob.empty_display_size * max(abs(s) for s in ob.matrix_basis.to_scale()) / SCALE


def _set_radius(ob, r_cm):
    scale = max(abs(s) for s in ob.matrix_basis.to_scale()) or 1.0
    ob.empty_display_size = max(r_cm * SCALE / scale, 1e-4)
    ob[RADIUS_PROP] = float(r_cm)


def joint_and_local(ob):
    """(joint number, position in the joint's frame, cm) of a shape end; joint -1 (MODEL_ORIGIN) = parented to the
    armature itself: position in the model's space, game axes. Pose-independent: from the parent relation only.
    None if it isn't parented to its armature."""
    root = col_root_of(ob)
    arm = shapes_armature(root)
    if arm is None or ob.parent != arm:
        return None
    m = ob.matrix_parent_inverse @ ob.matrix_basis
    if ob.parent_type == "BONE":
        bone = arm.data.bones.get(ob.parent_bone)
        if bone is None or bone.get(JOINT_PROP) is None:
            return None
        local = (Matrix.Translation((0.0, bone.length, 0.0)) @ m).translation / SCALE
        return int(bone[JOINT_PROP]), (local.x, local.y, local.z)
    if ob.parent_type == "OBJECT":
        v = m.translation / SCALE
        return MODEL_ORIGIN, (v.x, v.z, -v.y)
    return None


def _is_copy(ob):
    return ob.name != ob.get(NAME_PROP, ob.name)


def _suffix(ob):
    """Blender's duplicate suffix of a copy (".001") relative to its original name, or the name"""
    base = ob.get(NAME_PROP, "")
    return ob.name[len(base):] if base and ob.name.startswith(base) else ob.name


def _capsule_pairs(obs, problems):
    """[(a, b)] from the capsule ends: by key; within a key the originals pair together, copies by suffix"""
    by_key = {}
    for o in obs:
        if o.get(KIND_PROP) in ("a", "b"):
            by_key.setdefault(o.get(CAP_PROP, ""), {"a": [], "b": []})[o[KIND_PROP]].append(o)
    pairs = []
    for key, ends in by_key.items():
        a_s, b_s = ends["a"], ends["b"]
        if len(a_s) == 1 and len(b_s) == 1:
            pairs.append((a_s[0], b_s[0]))
            continue
        b_left = list(b_s)
        for a in a_s:
            want = None if not _is_copy(a) else _suffix(a)
            match = next((b for b in b_left if (want is None and not _is_copy(b)) or
                          (want is not None and _is_copy(b) and _suffix(b) == want)), None)
            if match is None:
                problems.append(f"{a.name}: capsule end without its other end (duplicate / delete both ends together)")
                continue
            b_left.remove(match)
            pairs.append((a, match))
        for b in b_left:
            problems.append(f"{b.name}: capsule end without its other end (duplicate / delete both ends together)")
    return pairs


def shape_records(root, problems=None):
    """the shapes as objects say: [{kind: sphere | capsule, a, b, group, src}], in file order (source shapes in
    their place, new ones after). problems collects broken capsules."""
    problems = problems if problems is not None else []
    obs = members(root)
    records = [{"kind": "sphere", "a": o, "b": None} for o in obs if o.get(KIND_PROP) == "sphere"]
    records += [{"kind": "capsule", "a": a, "b": b} for a, b in _capsule_pairs(obs, problems)]
    for r in records:
        a = r["a"]
        r["group"] = int(a.get(GROUP_PROP, 0))
        src = a.get(SRC_PROP)
        r["src"] = tuple(int(v) for v in src) if src is not None and not _is_copy(a) else None
    records.sort(key=lambda r: (r["src"] or (1 << 30, 0), r["a"].name))
    return records


def shapes_world(root):
    """[("sphere", centre, r) | ("capsule", a, b, r)] in world space, file order (metres)"""
    out = []
    for r in shape_records(root):
        a = r["a"]
        if r["kind"] == "sphere":
            out.append(("sphere", a.matrix_world.translation.copy(), radius_cm(a) * SCALE))
        else:
            out.append(("capsule", a.matrix_world.translation.copy(), r["b"].matrix_world.translation.copy(),
                        radius_cm(a) * SCALE))
    return out


def _tube(name, a, b, r_m, coll, root, color):
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
            t = 2.0 * math.pi * k / TUBE_SEGMENTS
            verts.append(centre + (side * math.cos(t) + up * math.sin(t)) * r_m)
    n = TUBE_SEGMENTS
    faces = [(k, (k + 1) % n, n + (k + 1) % n, n + k) for k in range(n)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    ob = bpy.data.objects.new(name, mesh)
    coll.objects.link(ob)
    ob.display_type = "WIRE"
    ob.color = color
    ob.hide_render = True
    ob.hide_select = True
    ob[ROOT_PROP] = root
    ob[KIND_PROP] = "tube"
    ob[CAP_PROP] = a.get(CAP_PROP, "")
    apply_tips(ob)
    for end, indices, label in ((a, range(n), "a"), (b, range(n, 2 * n), "b")):
        hook = ob.modifiers.new(f"ALBAM_COL_{label}", "HOOK")
        hook.object = end
        hook.vertex_indices_set(list(indices))
        # mat = tube^-1 . end . inverse: identity at the pose the tube was built in, so each ring follows its end
        hook.matrix_inverse = end.matrix_world.inverted() @ ob.matrix_world
    return ob


def _group_flags(root, group):
    groups = root.albam_col.groups
    return groups[group].flags if group < len(groups) else DEFAULT_FLAGS


def adopt_copies(root):
    """Shift+D copies become shapes of their own: a copied capsule's two ends get a new key, every copy its own name
    as `col_name` and no `col_src` (it's a new shape in the file)"""
    obs = members(root)
    problems = []
    for a, b in _capsule_pairs(obs, problems):
        if _is_copy(a) or _is_copy(b):
            key = _new_capsule_key()
            for o in (a, b):
                o[CAP_PROP] = key
                apply_tips(o)
    for o in obs:
        if o.get(KIND_PROP) in ("sphere", "a", "b") and _is_copy(o):
            o[NAME_PROP] = o.name
            if SRC_PROP in o:
                del o[SRC_PROP]
            apply_tips(o)


def sync_tubes(root, context=None):
    """make every capsule have exactly one tube on its own two ends, with its radius and group colour, and both
    ends the same size (the one resized last wins); remove the tubes of capsules that are gone"""
    context = context or bpy.context
    adopt_copies(root)
    records = shape_records(root)
    tubes = [o for o in members(root) if o.get(KIND_PROP) == "tube"]
    keep = set()
    rebuild = []
    for r in records:
        if r["kind"] != "capsule":
            continue
        a, b = r["a"], r["b"]
        ra, rb = radius_cm(a), radius_cm(b)
        if abs(ra - rb) > 1e-4:
            if abs(ra - a.get(RADIUS_PROP, ra)) > 1e-4:
                _set_radius(b, ra)              # a was resized
            else:
                _set_radius(a, rb)
                ra = rb
        a[RADIUS_PROP] = b[RADIUS_PROP] = float(ra)
        good = None
        for t in tubes:
            if t in keep or t.get(CAP_PROP) != a.get(CAP_PROP):
                continue
            hooks = [m.object for m in t.modifiers if m.type == "HOOK"]
            if hooks == [a, b] and abs(t.get(RADIUS_PROP, -1.0) - ra) < 1e-4:
                good = t
                break
        if good is not None:
            keep.add(good)
            good.color = _color(_group_flags(root, r["group"]))
        else:
            rebuild.append(r)
    for t in tubes:
        if t not in keep:
            mesh = t.data
            bpy.data.objects.remove(t)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    if rebuild:
        context.view_layer.update()
        for r in rebuild:
            a, b = r["a"], r["b"]
            coll = a.users_collection[0] if a.users_collection else context.collection
            t = _tube(f"{a.name}_tube", a, b, radius_cm(a) * SCALE, coll, root, _color(_group_flags(root, r["group"])))
            t[RADIUS_PROP] = float(radius_cm(a))
            apply_tips(t)
            t.parent = root
            t.matrix_parent_inverse = root.matrix_world.inverted()
    _signatures[root.name] = _signature(root)


def clear_shapes(root):
    for ob in members(root):
        mesh = ob.data if ob.type == "MESH" else None
        bpy.data.objects.remove(ob)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def _ensure_groups(root, count):
    groups = root.albam_col.groups
    while len(groups) < count:
        g = groups.add()
        g.kind, g.flags = 0, DEFAULT_FLAGS


def build_shapes(root, armature, context):
    """(Re)build root's shape objects from its source file on armature. Returns the joints it doesn't have."""
    clear_shapes(root)
    col = read_col(root)
    coll = root.users_collection[0] if root.users_collection else context.collection
    root.parent = armature
    root.matrix_parent_inverse = Matrix.Identity(4)
    root[ARMATURE_PROP] = armature
    bones = _joint_bones(armature)
    missing, unbuilt = set(), []
    stem = root.name
    for gi, group in enumerate(col.groups if col is not None else []):
        for si, shape in enumerate(group.shapes):
            name = f"{stem}_{gi}_{si}"
            joints = [shape.bone0] if shape.type == 0 else [shape.bone0, shape.bone1] if shape.type == 3 else []
            lost = [j for j in joints if j != MODEL_ORIGIN and j not in bones]
            pos_ok = all(math.isfinite(v) for v in tuple(shape.pos0[:3]) + (tuple(shape.pos1[:3]) if shape.type == 3
                                                                               else ()))
            if not joints or lost or not pos_ok or not math.isfinite(shape.radius):
                missing.update(lost)
                unbuilt += [gi, si]             # type 1 (6 shapes in the game's files), or not placeable here
                continue
            if shape.type == 0:
                a = _new_end(name, "sphere", armature, bones.get(shape.bone0), shape.pos0, shape.radius, coll, root)
            else:
                a = _new_end(name + "_a", "a", armature, bones.get(shape.bone0), shape.pos0, shape.radius, coll, root)
                b = _new_end(name + "_b", "b", armature, bones.get(shape.bone1), shape.pos1, shape.radius, coll, root)
                a[CAP_PROP] = b[CAP_PROP] = _new_capsule_key()
                apply_tips(a)
                apply_tips(b)
            _mark_shape(a, gi, (gi, si), shape.id, shape.shrink)
    root[UNBUILT_PROP] = unbuilt
    root[BUILT_PROP] = True
    apply_tips(root)
    if missing:
        root["col_missing_joints"] = sorted(missing)
    elif "col_missing_joints" in root:
        del root["col_missing_joints"]
    sync_tubes(root, context)
    return sorted(missing)


def attach_shapes(root, armature, context):
    """Put root's shapes on another armature: existing shape objects move to the bones with the same joint numbers
    (edits kept); a file whose shapes were never built is built from its source. Returns the joints it lacks."""
    obs = [o for o in members(root) if o.get(KIND_PROP) in ("sphere", "a", "b")]
    if not obs:
        return build_shapes(root, armature, context)
    bones = _joint_bones(armature)
    placed = [(o, joint_and_local(o)) for o in obs]
    missing = sorted({j for _, found in placed if found is not None and found[0] != MODEL_ORIGIN
                      for j in [found[0]] if j not in bones})
    if missing:
        return missing
    root.parent = armature
    root.matrix_parent_inverse = Matrix.Identity(4)
    root[ARMATURE_PROP] = armature
    for o, found in placed:
        if found is not None:
            joint, local = found
            _place(o, armature, None if joint == MODEL_ORIGIN else bones[joint], local)
    for t in [o for o in members(root) if o.get(KIND_PROP) == "tube"]:
        bpy.data.objects.remove(t)
    sync_tubes(root, context)
    return []


# ---- export --------------------------------------------------------------------------------------------------------

def _close(a, b, tol):
    if math.isnan(a) and math.isnan(b):
        return True
    return abs(a - b) <= tol


def _shape_from(record, base, problems):
    """dmc4xml Shape for a record; base = the source shape (raw values kept where they didn't change) or None"""
    from dmc4xml import col as col_codec
    a, b = record["a"], record["b"]
    shape = col_codec.Shape.from_words(base.words()) if base is not None else col_codec.Shape(
        type=0 if b is None else 3, bone0=0, bone1=MODEL_ORIGIN if b is None else 0, radius=1.0,
        pos0=(0.0, 0.0, 0.0, 0.0), pos1=(0.0, 0.0, 0.0, 0.0), unk=0, id=0, shrink=0.0, unk2=0xFFFFFFFF)
    shape.type = 0 if b is None else 3
    for end, bone_attr, pos_attr in ((a, "bone0", "pos0"), (b, "bone1", "pos1")):
        if end is None:
            continue
        found = joint_and_local(end)
        if found is None:
            problems.append(f"{end.name}: not parented to the shapes' armature (or to a bone without a joint number)")
            continue
        joint, local = found
        setattr(shape, bone_attr, joint)
        old = getattr(shape, pos_attr)
        if not all(_close(n, o, 1e-3) for n, o in zip(local, old[:3])):
            setattr(shape, pos_attr, tuple(local) + (old[3],))
    r = radius_cm(a)
    if not _close(r, shape.radius, 1e-3):
        shape.radius = r
    shape.id = int(a.get(ID_PROP, shape.id)) & 0xFFFFFFFF
    shrink = float(a.get(SHRINK_PROP, shape.shrink))
    if not _close(shrink, shape.shrink, 1e-6):
        shape.shrink = shrink
    return shape


def build_col(root):
    """COL_ root -> .col bytes: the source file with the objects' shapes and the panel's groups"""
    from dmc4xml import col as col_codec
    problems = []
    if shapes_armature(root) is None and members(root):
        problems.append("the shapes aren't on an armature (Attach to Armature)")
    source = read_col(root)
    records = shape_records(root, problems)
    groups = root.albam_col.groups
    count = max([len(groups)] + [r["group"] + 1 for r in records])
    unbuilt = root.get(UNBUILT_PROP, [])
    unbuilt = {(unbuilt[i], unbuilt[i + 1]) for i in range(0, len(unbuilt) - 1, 2)}
    if not root.get(BUILT_PROP) and source is not None:     # never on an armature: every source shape as it is
        unbuilt = {(g, s) for g, group in enumerate(source.groups) for s in range(len(group.shapes))}
    by_src = {r["src"]: r for r in records if r["src"] is not None}
    out = col_codec.Col(version=source.version, a=source.a, b=source.b) if source is not None else col_codec.Col()
    for gi in range(count):
        src_group = source.groups[gi] if source is not None and gi < len(source.groups) else None
        if gi < len(groups):
            kind, flags = groups[gi].kind, groups[gi].flags
        else:
            kind, flags = 0, DEFAULT_FLAGS
        group = col_codec.Group(kind=kind, flags=flags, pad=src_group.pad if src_group is not None else 0xFFFFFFFF)
        done = set()
        for si, base in enumerate(src_group.shapes if src_group is not None else []):
            if (gi, si) in unbuilt:
                group.shapes.append(base)       # never had objects: kept as it was
                continue
            r = by_src.get((gi, si))
            if r is not None and r["group"] == gi:
                group.shapes.append(_shape_from(r, base, problems))
                done.add(id(r))
        for r in records:                       # new shapes, and source shapes moved to this group
            if r["group"] == gi and id(r) not in done and (r["src"] is None or r["src"][0] != gi):
                base = None
                if r["src"] is not None and source is not None:
                    g, s = r["src"]
                    base = source.groups[g].shapes[s] if g < len(source.groups) and \
                        s < len(source.groups[g].shapes) else None
                group.shapes.append(_shape_from(r, base, problems))
        out.groups.append(group)
    if problems:
        raise AlbamCheckFailure(f"Collision shapes {root.name} can't be exported", details="\n".join(problems),
                                solution="Fix the listed shapes.")
    return col_codec.write(out)


@blender_registry.register_export_function(app_id="dmc4", extension="col")
def export_col(bl_obj):
    data = build_col(bl_obj)
    asset = bl_obj.albam_asset
    print(f"COL export {asset.relative_path}: {len(shape_records(bl_obj))} shapes")
    return [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]


# ---- keeping tubes in step with Shift+D / X / scaling ---------------------------------------------------------------

_signatures = {}            # root name -> what its capsules looked like at the last sync
_sync_pending = [False]


def _signature(root):
    out = []
    for o in members(root):
        kind = o.get(KIND_PROP)
        out.append((o.name, kind, o.get(CAP_PROP, ""),
                    round(radius_cm(o), 4) if kind in ("a", "b", "sphere") else 0, o.get(GROUP_PROP, -1)))
    return tuple(sorted(out))


def sync_all(context=None):
    for root in [o for o in bpy.data.objects if is_col_root(o)]:
        if _signatures.get(root.name) != _signature(root):
            try:
                sync_tubes(root, context)
            except Exception as err:            # noqa: BLE001 - never break editing
                print(f"COL sync {root.name}: {err}")


def _timer():
    _sync_pending[0] = False
    sync_all()
    return None


def _schedule_sync():
    if not _sync_pending[0]:
        _sync_pending[0] = True
        bpy.app.timers.register(_timer, first_interval=0.0)


@persistent
def _on_depsgraph(scene, depsgraph):
    for update in depsgraph.updates:
        ob = update.id.original if isinstance(update.id, bpy.types.Object) else None
        if (ob is not None and ROOT_PROP in ob) or isinstance(update.id, bpy.types.Collection):
            _schedule_sync()
            return


@persistent
def _on_load(_dummy=None):
    _signatures.clear()


def register_handlers():
    for handlers, fn in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
                         (bpy.app.handlers.load_post, _on_load)):
        if fn not in handlers:
            handlers.append(fn)


def unregister_handlers():
    for handlers, fn in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
                         (bpy.app.handlers.load_post, _on_load)):
        for handler in list(handlers):
            if getattr(handler, "__name__", "") == fn.__name__ and \
                    getattr(handler, "__module__", "") == fn.__module__:
                handlers.remove(handler)


# ---- which groups are on: the motion's first event table ------------------------------------------------------------
#
# An LMT animation's first event table is (value, duration) runs; bit k (k < 8) of the value switches on .col group
# events_params_01[k] of that animation (Albam: "Hitbox Slot Values"). XOR-ing consecutive values shows which slots
# change on that frame. Seen in Nero's files: idle / walk slots 0 / 1 = groups 5 / 6 (hurt + push on the body), the
# Snatch turns on grab groups 120 / 121 / 122 one frame after another (pl000_02 block 30). Matches the data; the game
# code that reads it wasn't traced. (The second table is sound effects, same scheme, events_params_02.)

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
    arm = shapes_armature(root)
    if not root.albam_col.follow_events or arm is None:
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
        hidden_key = {}
        for r in shape_records(root):
            hidden = groups is not None and r["group"] not in groups
            if r["b"] is not None:
                hidden_key[r["a"].get(CAP_PROP)] = hidden
            for ob in (r["a"], r["b"]):
                if ob is not None and ob.name in scene.objects and ob.hide_get() != hidden:
                    ob.hide_set(hidden)
        for ob in members(root):
            if ob.get(KIND_PROP) == "tube" and ob.name in scene.objects:
                hidden = hidden_key.get(ob.get(CAP_PROP), False)
                if ob.hide_get() != hidden:
                    ob.hide_set(hidden)


# ---- import and new files ------------------------------------------------------------------------------------------

def _new_root(context, stem, app_id, relative_path, data, armature=None):
    coll = bpy.data.collections.new(f"COL_{stem}")
    context.collection.children.link(coll)
    root = bpy.data.objects.new(f"COL_{stem}", None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.05
    coll.objects.link(root)
    root.albam_asset.original_bytes = data
    root.albam_asset.app_id = app_id
    root.albam_asset.relative_path = relative_path
    root.albam_asset.extension = "col"
    root[UNBUILT_PROP] = []
    if armature is not None:
        root.parent = armature
        root[ARMATURE_PROP] = armature
    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = root
    context.scene.albam.exportable.file_list.update()
    apply_tips(root)
    return root


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
    root = _new_root(context, stem, file_item.app_id, file_item.relative_path, data)
    for g in col.groups:
        item = root.albam_col.groups.add()
        item.kind, item.flags = g.kind, g.flags
    # hitbox files follow the animation's events; a chain model's body shapes (pl000_03.col) aren't switched by them
    root.albam_col.follow_events = body_model_stem(context, file_item.relative_path) is None
    armature = find_col_armature(context, root)
    if armature is not None:
        build_shapes(root, armature, context)
    from albam.engines.mtfw.cns_chain_preview import wire_scene
    wire_scene(context)
    return None     # linked into its own collection


def _armature_in(context):
    ob = context.object
    if ob is not None and ob.type == "ARMATURE":
        return ob
    root = col_root_of(ob)
    return shapes_armature(root) if root is not None else None


def _target_root(context):
    """the COL_ root new shapes go into: the active object's, else the one on the armature"""
    root = col_root_of(context.object)
    if root is not None:
        return root
    arm = _armature_in(context)
    roots = [o for o in context.scene.objects if is_col_root(o) and shapes_armature(o) == arm]
    name = context.scene.albam.col_ui.target
    chosen = next((r for r in roots if r.name == name), None)
    return chosen or (roots[0] if len(roots) == 1 else None)


@blender_registry.register_blender_type
class ALBAM_OT_ColNew(bpy.types.Operator):
    """Start a new collision shape file (.col) on this armature, with one push group and no shapes yet: add them with
    Add Sphere / Add Capsule at selected bones, then edit like any objects"""
    bl_idname = "albam.col_new"
    bl_label = "New Collision Shapes"
    bl_options = {"REGISTER", "UNDO"}

    path: bpy.props.StringProperty(
        name="Game Path", description="Where the file goes in the game, with .col (e.g. Collision\\pl000_new.col); "
                                      "Patch adds it to the archive")

    @classmethod
    def poll(cls, context):
        return _armature_in(context) is not None

    def invoke(self, context, event):
        arm = _armature_in(context)
        stem = _stem(arm.albam_asset.relative_path) if arm.albam_asset.relative_path else arm.name.split(".")[0]
        self.path = f"Collision\\{stem}_new.col"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        path = self.path.strip().replace("/", "\\")
        if not path.lower().endswith(".col"):
            path += ".col"
        if any(is_col_root(o) and o.albam_asset.relative_path.lower() == path.lower() for o in bpy.data.objects):
            self.report({"ERROR"}, f"{path} is already in the scene")
            return {"CANCELLED"}
        arm = _armature_in(context)
        root = _new_root(context, _stem(path), "dmc4", path, b"", arm)
        root.matrix_parent_inverse = Matrix.Identity(4)
        _ensure_groups(root, 1)
        root[BUILT_PROP] = True
        apply_tips(root)
        context.scene.albam.col_ui.target = root.name
        self.report({"INFO"}, f"{root.name}: add shapes at selected bones (Add Sphere / Add Capsule)")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_ColAddShape(bpy.types.Operator):
    """Add a shape at the selected bones: a sphere on the active bone, or a capsule from the active bone to the other
    selected one (or to its child). It goes into the group of the selected shape, or group 0"""
    bl_idname = "albam.col_add_shape"
    bl_label = "Add Shape"
    bl_options = {"REGISTER", "UNDO"}

    kind: bpy.props.EnumProperty(items=(("sphere", "Sphere", "A sphere on the active bone"),
                                        ("capsule", "Capsule", "A capsule from the active bone to the other selected "
                                                               "bone (or its child)")))
    radius: bpy.props.FloatProperty(name="Radius (cm)", default=10.0, min=0.01,
                                    description="Radius in game centimetres")
    group: bpy.props.IntProperty(name="Group", default=-1, min=-1,
                                 description="Group to put the shape in (-1: the selected shape's, else 0)")

    @classmethod
    def poll(cls, context):
        arm = _armature_in(context)
        return arm is not None and _target_root(context) is not None and arm.data.bones.active is not None

    def execute(self, context):
        root = _target_root(context)
        arm = shapes_armature(root) or _armature_in(context)
        if shapes_armature(root) is None:
            root[ARMATURE_PROP] = arm
            root.parent = arm
        bone = arm.data.bones.active
        if bone.get(JOINT_PROP) is None:
            self.report({"ERROR"}, f"bone {bone.name} has no joint number (mtfw.anim_retarget)")
            return {"CANCELLED"}
        group = self.group
        if group < 0:
            sel = col_root_of(context.object) == root and context.object.get(GROUP_PROP)
            group = int(sel) if isinstance(sel, int) else 0
        _ensure_groups(root, group + 1)
        coll = root.users_collection[0] if root.users_collection else context.collection
        index = len(shape_records(root))
        name = f"{root.name}_{group}_n{index}"
        if self.kind == "sphere":
            a = _new_end(name, "sphere", arm, bone, (0.0, 0.0, 0.0), self.radius, coll, root)
        else:
            other = next((b for b in arm.data.bones if b.select and b != bone), None) or \
                next(iter(bone.children), None)
            if other is None or other.get(JOINT_PROP) is None:
                self.report({"ERROR"}, "select a second bone (with a joint number) for the capsule's other end")
                return {"CANCELLED"}
            a = _new_end(name + "_a", "a", arm, bone, (0.0, 0.0, 0.0), self.radius, coll, root)
            b = _new_end(name + "_b", "b", arm, other, (0.0, 0.0, 0.0), self.radius, coll, root)
            a[CAP_PROP] = b[CAP_PROP] = _new_capsule_key()
            apply_tips(a)
            apply_tips(b)
        _mark_shape(a, group)
        sync_tubes(root, context)
        self.report({"INFO"}, f"Added {self.kind} {a.name} to group {group}")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_ColAddGroup(bpy.types.Operator):
    """Add a group (kind 0, push) to the collision shapes; put shapes in it with their Group value"""
    bl_idname = "albam.col_add_group"
    bl_label = "Add Group"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return col_root_of(context.object) is not None

    def execute(self, context):
        root = col_root_of(context.object)
        _ensure_groups(root, len(root.albam_col.groups) + 1)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_PT_ColShapes(bpy.types.Panel):
    bl_label = "Collision Shapes"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return col_root_of(ob) is not None or (ob is not None and ob.type == "ARMATURE")

    def draw(self, context):
        layout = self.layout
        ob = context.object
        root = col_root_of(ob)
        if root is None:                        # an armature: its shape files, new file, add shapes
            roots = [o for o in context.scene.objects if is_col_root(o) and shapes_armature(o) == ob]
            if roots:
                layout.prop_search(context.scene.albam.col_ui, "target", context.scene, "objects", text="Shapes")
            layout.operator("albam.col_new", icon="ADD")
            row = layout.row(align=True)
            row.enabled = ob.mode == "POSE"
            row.operator("albam.col_add_shape", text="Add Sphere", icon="MESH_UVSPHERE").kind = "sphere"
            row.operator("albam.col_add_shape", text="Add Capsule", icon="MESH_CAPSULE").kind = "capsule"
            if ob.mode != "POSE":
                layout.label(text="Pose Mode: select bones to add shapes at", icon="INFO")
            return

        if root != ob:
            layout.label(text=f"Part of {root.name}", icon="OBJECT_DATA")
        arm = shapes_armature(root)
        row = layout.row()
        row.label(text=f"On {arm.name}" if arm else "Not on an armature", icon="ARMATURE_DATA" if arm else "ERROR")
        row.operator("albam.attach_to_armature", text="Attach", icon="LINKED")
        missing = list(root.get("col_missing_joints", []))
        if missing:
            layout.label(text=f"Shapes kept as they are (joints not on the armature): {missing}", icon="INFO")

        group_index = ob.get(GROUP_PROP) if root != ob else None
        if isinstance(group_index, int):
            box = layout.box()
            box.prop(ob, f'["{GROUP_PROP}"]', text="Group")
            if group_index < len(root.albam_col.groups):
                g = root.albam_col.groups[group_index]
                box.prop(g, "kind")
                grid = box.grid_flow(columns=3, align=True)
                for i, name in enumerate(FLAG_NAMES):
                    grid.prop(g, "flag_bits", index=i, text=name.capitalize(), toggle=True)
            else:
                box.label(text="A new group (kind 0, push) on export, or Add Group", icon="INFO")
            row = box.row()
            row.prop(ob, f'["{ID_PROP}"]', text="ID")
            row.prop(ob, f'["{SHRINK_PROP}"]', text="Shrink")
            box.label(text="Radius: the sphere's size (scale it); move / re-parent to place it", icon="INFO")

        layout.prop(root.albam_col, "follow_events")
        if root.albam_col.follow_events:
            groups = active_groups(root, context.scene.frame_current)
            layout.label(text="No LMT events on this armature's action: every group shown" if groups is None
                         else f"On at this frame: groups {sorted(groups)}", icon="TIME")
        records = shape_records(root)
        counts = {}
        for r in records:
            counts[r["group"]] = counts.get(r["group"], 0) + 1
        summary = {}
        for i, g in enumerate(root.albam_col.groups):
            row = summary.setdefault((g.kind, g.flags), [0, 0])
            row[0] += 1
            row[1] += counts.get(i, 0)
        col = layout.column(align=True)
        col.label(text=f"{len(root.albam_col.groups)} group(s), {len(records)} shape(s)", icon="MESH_CAPSULE")
        for (kind, flags), (n_groups, n_shapes) in sorted(summary.items(), key=lambda kv: -kv[1][0])[:8]:
            col.label(text=f"{n_groups} x kind {kind}, {flag_text(flags)}: {n_shapes} shape(s)")
        layout.operator("albam.col_add_group", icon="ADD")


