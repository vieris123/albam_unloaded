"""Match Game Skeleton: make a rig from another game or tool play the game's own LMTs (2026-11-02).

The right joint numbers aren't enough. An LMT track is a joint's local transform in its parent's frame and replaces the
rest value (`animation.rest_in_parent`), so a rig plays a game model's animations only if it agrees with that model on
- the parents: a thigh under an unanimated MMD `下半身` doesn't follow the hips track;
- each joint's rest orientation: the same quaternion means something else in another frame;
- the rest pose: the mesh has to stand as the game's model does (T-pose), or an A-pose arm stays 40 degrees off;
- the size: the root track is an absolute position, so a smaller model's hips are lifted to the game model's height.

`build_plan` works all of that out from the reference model's skeleton and changes nothing; `apply_plan` does it:
- every joint the reference has gets the reference's parent and rest orientation. Its position stays the rig's,
  so the proportions stay too; the root goes to the hips, where the game's root sits (joints 1 and 13 are at offset 0);
- the rest pose: walking down the old hierarchy each joint turns the shortest way so the mean of its children lines up
  with the reference's (`_deltas`), the hands also about that axis, so the palms match. Feet and toes keep their
  pitch: a heeled shoe stays heeled. The meshes and every shape key are deformed by the result with Blender's own
  weighting (normalised linear skinning; `_skin`), so shape keys are no obstacle, and the rig's rest moves with them;
- the size: uniform, so the hips stand as high as the reference's and the feet reach the floor;
- a rig already matched keeps its pose (`_already_matched`): only its size and missing joints are looked at, because
  its children's mean now includes joints added at the game model's offsets, and turning it again leans the body;
- numbers: only the body and fingers (`_trusted`) are taken on trust. `number_new_rig` hands out low numbers
  blindly, so a breast bone can hold 204 (Dante's left shoulder deform): any other joint whose place doesn't fit the
  reference joint of that number loses it. Joints the reference has are animated by its LMTs, so bones outside the match get
  numbers it doesn't use. Unweighted bones outside the match (IK, `_dummy_`, `_shadow_` controls) become Not a Game
  Joint: there aren't enough free numbers for them, and the game doesn't need them. Joint 13 goes to the thighs'
  common parent;
- joints the reference has and the rig doesn't are added as unweighted bones, at the reference's offset from their
  parent: the game reads some without checking they exist (`joints.NEEDED_JOINTS`: Dante's coat pins to 200 and 204),
  and hangs things on others (152, the sword on his back), so the joint table has to hold all of them;
- pose bone constraints are muted (the game has none, and MMD's would fight the LMT curves in the preview).

Editing a bone's rest doesn't move a mesh, which is why frames can simply be set. Actions imported before this are
stale (`rest_in_parent` changed): LMTs have to be imported again.
"""
import math
from pathlib import PureWindowsPath
from types import SimpleNamespace

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from . import joints
from .model_settings import model_root
from .new_model import WARNING, _report_notes

ROOT, SPINE, HIPS = 0, 1, 13
THIGHS = (14, 18)
FINGERS = range(100, 132)
PALMS = (109, 125)                        # in the finger range, but rigs rarely have them: an MMD twist dummy gets picked
ADDED_PREFIX = "game_"                    # joints added here: placed by the reference's offsets, so they say nothing
SAME_FRAME = 0.01                         # degrees
SHORT_OFFSET = 0.02                       # m: below this a joint's direction from its parent means nothing
KEEP_PITCH = {16, 17, 20, 21}             # feet, toes
PALM_AXES = {8: (103, 113), 12: (119, 129)}   # hand: index and little finger bases
SAME_PLACE = 0.01                         # m: joints this close are one point (the root, spine and hips in the game)
MIN_SPREAD = 0.3                          # a joint's children balance out when their mean is shorter than this share
MIN_LENGTH = 1e-4
MISPLACED = 0.1                           # share of the reference's height: a joint this far from where it should be
OFF_CENTRE = 0.03                         # m
TWIST_NOTE = 30.0                         # degrees: palms turned this much may need their wrist weights looked at
CHAIN_COLLECTION = "Chain "               # cns_chain's bone collections
_skeletons = {}


def reference_skeleton(context, path):
    """{joint: SimpleNamespace(parent=joint or None, matrix=matrix_local)} of a .mod in the Game Files. Built by the
    import's own function on a scratch armature, so the frames are the imported ones to the bit."""
    from . import mesh
    try:
        item = context.scene.albam.rfs.get_vfile("dmc4", path)
    except (KeyError, ValueError):
        raise AlbamCheckFailure(f"{path} isn't in the Game Files", details=path,
                                solution="Add the game's extracted folder in Game Files, or pick another model")
    data = item.get_bytes()
    cached = _skeletons.get((path, len(data)))
    if cached is not None:
        return cached
    Mod = mesh.MOD_CLASS_MAPPER.get(data[4])
    if Mod is None:
        raise AlbamCheckFailure(f"{path} isn't a model this can read", details=f"version {data[4]}",
                                solution="Pick a DX9 character model")
    mod = Mod.from_bytes(data)
    mod._read()
    if not mod.header.num_bones:
        raise AlbamCheckFailure(f"{path} has no bones", details=path, solution="Pick a character's model")
    active, selected = context.view_layer.objects.active, list(context.selected_objects)
    ob = mesh.build_blender_armature(mod, "albam_match_reference", mesh._create_bbox_data(mod))
    out = {}
    for b in ob.data.bones:
        j = joints.joint_of(b)
        if j is not None and j < 254:
            out[j] = SimpleNamespace(parent=joints.joint_of(b.parent) if b.parent else None, matrix=b.matrix_local.copy())
    data_block = ob.data
    bpy.data.objects.remove(ob)
    bpy.data.armatures.remove(data_block)
    context.view_layer.objects.active = active
    for o in selected:
        o.select_set(True)
    _skeletons[(path, len(data))] = out
    return out


def _deformed_meshes(ob):
    return [o for o in bpy.data.objects if o.type == "MESH" and
            any(m.type == "ARMATURE" and m.object == ob for m in o.modifiers)]


def _weighted(meshes):
    names = set()
    for o in meshes:
        groups = {g.group for v in o.data.vertices for g in v.groups if g.weight > 0}
        names |= {vg.name for vg in o.vertex_groups if vg.index in groups}
    return names


def _in_chain(bone):
    return any(c.name.startswith(CHAIN_COLLECTION) for c in getattr(bone, "collections", ()))


def _ancestors(bone):
    return [p.name for p in bone.parent_recursive]


def _common_parent(ob, a, b):
    others = set(_ancestors(b))
    return next((ob.data.bones[n] for n in _ancestors(a) if n in others), None)


def _trusted(j):
    return j < 22 or (j in FINGERS and j not in PALMS)


def _ref_parent(j, ref, kept):
    """the nearest joint above j in the reference that the rig has"""
    p = ref[j].parent
    while p is not None and p not in kept:
        p = ref[p].parent if p in ref else None
    return p


def _depth(j, ref):
    n = 0
    while ref[j].parent is not None and ref[j].parent in ref:
        j, n = ref[j].parent, n + 1
    return n


def _head(ref, j):
    return ref[j].matrix.to_translation()


def _about(point, rotation):
    return Matrix.Translation(point) @ rotation.to_matrix().to_4x4() @ Matrix.Translation(-point)


def _palm_turn(axis, have, want):
    """the rotation about axis taking have onto want, both seen across the axis"""
    a, b = have - have.project(axis), want - want.project(axis)
    if a.length < MIN_LENGTH or b.length < MIN_LENGTH:
        return Quaternion()
    angle = a.angle(b)
    return Quaternion(axis, -angle if axis.dot(a.cross(b)) < 0 else angle)


def _deltas(ob, kept, ref):
    """{bone name: matrix taking its rest to the new pose, in armature space}, and the palm turns in degrees"""
    joint_by_name = {b.name: j for j, b in kept.items()}
    children = {}
    for j in kept:
        p = _ref_parent(j, ref, kept)
        if p is not None:
            children.setdefault(p, []).append(j)
    out, palms = {}, {}
    stack = [(b, Matrix.Identity(4)) for b in ob.data.bones if b.parent is None]
    while stack:
        bone, delta = stack.pop()
        j = joint_by_name.get(bone.name)
        if j is not None and j != ROOT and j not in KEEP_PITCH:
            head = delta @ bone.head_local
            own = bone.name
            kids = [c for c in children.get(j, ()) if own in _ancestors(kept[c]) and
                    not kept[c].name.startswith(ADDED_PREFIX) and (_head(ref, c) - _head(ref, j)).length > SAME_PLACE]
            if kids:
                offsets = [delta @ kept[c].head_local - head for c in kids]
                have = sum(offsets, Vector()) / len(kids)
                want = sum((_head(ref, c) - _head(ref, j) for c in kids), Vector()) / len(kids)
                spread = sum(o.length for o in offsets) / len(kids)
                if have.length > MIN_SPREAD * spread and want.length > MIN_LENGTH:
                    turn = have.rotation_difference(want)
                    delta = _about(head, turn) @ delta
                    if j in PALM_AXES and all(c in kept for c in PALM_AXES[j]):
                        first, last = PALM_AXES[j]
                        turn = _palm_turn(want.normalized(), delta @ kept[first].head_local - delta @ kept[last].head_local,
                                          _head(ref, first) - _head(ref, last))
                        palms[j] = math.degrees(turn.angle)
                        delta = _about(head, turn) @ delta
        out[bone.name] = delta
        stack.extend((c, delta) for c in bone.children)
    return out, palms


def _already_matched(kept, ref):
    """every joint is in the reference's frame: this rig has been through here"""
    return all(math.degrees((ref[j].matrix.to_3x3().inverted() @ b.matrix_local.to_3x3()).to_quaternion().angle) < SAME_FRAME
               for j, b in kept.items())


def _misplaced(kept, ref, deltas, scale, tolerance):
    """joints outside the trusted set that don't sit where the reference has that joint: under the joint above it, the
    same way from it, at that joint's distance. A breast bone near the shoulder is under the chest, not the upper arm,
    and a twist dummy up the forearm is behind the wrist, not in the palm."""
    wrong, keep = [], dict(kept)
    for j in sorted(kept, key=lambda n: _depth(n, ref)):
        if _trusted(j):
            continue
        p = _ref_parent(j, ref, keep)
        if p is None:
            continue
        place = lambda n: scale * (deltas[kept[n].name] @ kept[n].head_local)   # noqa: E731
        offset, want = place(j) - place(p), _head(ref, j) - _head(ref, p)
        if kept[p].name not in _ancestors(kept[j]) or (offset - want).length > tolerance or \
                (want.length > SHORT_OFFSET and offset.dot(want) <= 0):
            wrong.append(j)
            del keep[j]
    return wrong


def _refuse(message, details, solution):
    raise AlbamCheckFailure(message, details=details, solution=solution)


def _pick_hips(ob, numbers, notes):
    """joint 13 belongs on what the thighs hang from, unless that's another body joint: an automatic number from
    New DMC4 Model is no reason to leave it. Returns the bone."""
    pelvis = _common_parent(ob, numbers[THIGHS[0]], numbers[THIGHS[1]])
    held = joints.joint_of(pelvis) if pelvis is not None else None
    if pelvis is None or held == HIPS or (held is not None and _trusted(held)):
        return numbers.get(HIPS)
    old = numbers.get(HIPS)
    notes.append(f"joint {HIPS} (hips) moved to {pelvis.name}, what the thighs hang from" +
                 (f", from {old.name}" if old is not None else ""))
    return pelvis


def build_plan(ob, ref, match_size=True):
    """what apply_plan will do; changes nothing"""
    notes, numbers = [], {}
    for b in joints.joint_bones(ob):
        j = joints.joint_of(b)
        if j is not None:
            numbers.setdefault(j, b)
    game_bones = [b.name for b in numbers.values() if joints.from_game_file(b)]
    if game_bones:
        _refuse("This rig has bones of a game model", details=", ".join(game_bones[:8]),
                solution="They're fixed. Match Game Skeleton is for rigs made elsewhere (New DMC4 Model)")
    missing = [j for j in (ROOT, SPINE) + THIGHS if j not in numbers or j not in ref]
    if missing:
        names = ", ".join(joints.joint_label(ob, j) if j in numbers else str(j) for j in missing)
        _refuse("The rig needs the main joints first", details=f"missing: {names}",
                solution="Give its root, spine and thighs their numbers (Bone Properties > Game Joint)")
    width = numbers[18].head_local.x - numbers[14].head_local.x
    if width * (_head(ref, 18).x - _head(ref, 14).x) <= 0:
        _refuse("The rig is turned the other way round to the game model, or its legs are swapped",
                details=f"{numbers[14].name} and {numbers[18].name}",
                solution="Rotate the model 180 degrees about Z and apply it, or swap the legs' numbers")
    hips = _pick_hips(ob, numbers, notes)
    if hips is None:
        _refuse("The rig has no hips", details="joint 13", solution="Give the bone the thighs hang from number 13")
    if numbers.get(HIPS) != hips:
        numbers.pop(joints.joint_of(hips), None)
        numbers[HIPS] = hips
    kept = {j: b for j, b in numbers.items() if j in ref}
    scale = 1.0
    if match_size and hips.head_local.z > MIN_LENGTH and _head(ref, HIPS).z > MIN_LENGTH:
        scale = _head(ref, HIPS).z / hips.head_local.z
    trusted = {j: b for j, b in kept.items() if _trusted(j)}
    deltas, _ = _deltas(ob, trusted, ref)
    height = max(m.matrix.to_translation().z for m in ref.values())
    for j in _misplaced(kept, ref, deltas, scale, MISPLACED * height):
        notes.append(f"{kept.pop(j).name} loses joint {j}: it isn't where the game model has that joint")
    deltas, palms = _deltas(ob, kept, ref)
    if _already_matched(kept, ref):
        deltas, palms = {b.name: Matrix.Identity(4) for b in ob.data.bones}, {}
    for j in sorted(kept):
        if abs(_head(ref, j).x) < SAME_PLACE and abs(kept[j].head_local.x) > OFF_CENTRE:
            notes.append(f"{WARNING}{kept[j].name} (joint {j}) is off the centre line: is it the right bone?")
    for j, angle in palms.items():
        if angle > TWIST_NOTE:
            notes.append(f"{WARNING}{kept[j].name}: palm turned {angle:.0f} degrees, check the wrist")

    meshes = _deformed_meshes(ob)
    weighted = _weighted(meshes)
    matched = {b.name for b in kept.values()}
    helpers = [b.name for b in joints.joint_bones(ob)
               if b.name not in matched and b.name not in weighted and not _in_chain(b) and not b.get(SIZE_PROP)]
    others = [b for b in joints.joint_bones(ob) if b.name not in matched and b.name not in helpers]
    keep_numbers = {joints.joint_of(b) for b in others if joints.joint_of(b) not in ref} - {None}
    needs = [b.name for b in others if joints.joint_of(b) is None or joints.joint_of(b) in ref]
    free = [j for j in range(253, -1, -1) if j not in ref and j not in keep_numbers]
    if len(free) < len(needs):
        _refuse("Not enough joint numbers left", f"{len(needs)} bones need one, {len(free)} are free of the game model's",
                "Remove bones, or merge weights of small bones into their parents")
    added = sorted((j for j in ref if j not in kept), key=lambda n: _depth(n, ref))
    if len(kept) + len(others) + len(added) > joints.MAX_BONES:
        _refuse("Too many bones", f"{len(kept) + len(others) + len(added)} joints, a model holds {joints.MAX_BONES}",
                "Remove bones, or merge weights of small bones into their parents")
    root_place = scale * (deltas[hips.name] @ hips.head_local) \
        if (_head(ref, ROOT) - _head(ref, HIPS)).length < SAME_PLACE else None
    return SimpleNamespace(kept=kept, deltas=deltas, scale=scale, helpers=helpers, meshes=meshes, root_place=root_place,
                           renumber=dict(zip(needs, free)), added=added, notes=notes)


def summary(plan):
    return [f"{len(plan.kept)} joints match the game model", f"{len(plan.added)} joints it has are added", f"scale {plan.scale:.3f}",
            f"{len(plan.renumber)} other bones get numbers it doesn't animate",
            f"{len(plan.helpers)} unweighted bones become Not a Game Joint"]


def _skin(mesh_ob, ob, moves, fallback):
    """deform a mesh and its shape keys as the Armature modifier would: weights normalised, a vertex with none only
    takes `fallback`. In armature space, so the mesh object's own transform is respected."""
    to_arm = ob.matrix_world.inverted() @ mesh_ob.matrix_world
    back = to_arm.inverted()
    stack = np.empty((len(mesh_ob.vertex_groups) + 1, 3, 4))
    known = np.zeros(len(mesh_ob.vertex_groups), bool)
    for vg in mesh_ob.vertex_groups:
        move = moves.get(vg.name)
        if move is not None and ob.data.bones[vg.name].use_deform:
            stack[vg.index] = np.array(back @ move @ to_arm)[:3]
            known[vg.index] = True
    stack[-1] = np.array(back @ fallback @ to_arm)[:3]
    me = mesh_ob.data
    rows = [(v.index, g.group, g.weight) for v in me.vertices for g in v.groups
            if g.weight > 0 and g.group < len(known) and known[g.group]]
    count = len(me.vertices)
    total, summed = np.zeros(count), np.zeros((count, 3, 4))
    if rows:
        verts, groups = np.array([r[0] for r in rows]), np.array([r[1] for r in rows])
        weights = np.array([r[2] for r in rows])
        np.add.at(total, verts, weights)
        np.add.at(summed, verts, stack[groups] * weights[:, None, None])
    bare = total == 0
    summed[bare] = stack[-1]
    total[bare] = 1.0
    summed /= total[:, None, None]

    def move_points(points):
        co = np.empty(count * 3, np.float32)
        points.foreach_get("co", co)
        co = co.reshape(-1, 3).astype(np.float64)
        moved = (summed[:, :, :3] * co[:, None, :]).sum(2) + summed[:, :, 3]
        points.foreach_set("co", moved.astype(np.float32).ravel())

    move_points(me.vertices)
    for key in me.shape_keys.key_blocks if me.shape_keys else ():
        move_points(key.data)
    me.update()


def _new_rest(bone, delta, scale, target=None):
    """(rest matrix without scale, length): `target` is the rotation to end on, else the bone's turned by delta"""
    rotation = target if target is not None else (delta.to_3x3() @ bone.matrix_local.to_3x3())
    rest = rotation.normalized().to_4x4()
    rest.translation = scale * (delta @ bone.head_local)
    return rest, max(bone.length * scale, 0.01)


def apply_plan(context, ob, plan, ref):
    """make the plan so; ob must be the active object in Object Mode"""
    bones = ob.data.bones
    kept = {j: b.name for j, b in plan.kept.items()}
    size = Matrix.Scale(plan.scale, 4)
    moves = {b.name: size @ plan.deltas[b.name] for b in bones}
    joint_by_name = {name: j for j, name in kept.items()}
    rests = {}
    for b in bones:
        j = joint_by_name.get(b.name)
        rests[b.name] = _new_rest(b, plan.deltas[b.name], plan.scale, ref[j].matrix.to_3x3() if j is not None else None)
    root_name = kept[ROOT]
    if plan.root_place is not None:
        rests[root_name][0].translation = plan.root_place
    children = [(c, c.parent_bone, c.matrix_world.copy()) for c in ob.children if c not in plan.meshes]

    for name in plan.helpers:
        bones[name].pop(joints.JOINT_PROP, None)
        bones[name].pop(joints.ADDED_PROP, None)
    joints.set_not_joint([bones[n] for n in plan.helpers], True)
    for j, name in kept.items():
        bones[name][joints.JOINT_PROP] = str(j)
        bones[name][joints.ADDED_PROP] = 1
    for name, j in plan.renumber.items():
        bones[name][joints.JOINT_PROP] = str(j)
        bones[name][joints.ADDED_PROP] = 1

    for mesh_ob in {o.data: o for o in plan.meshes}.values():   # linked copies share their vertices
        _skin(mesh_ob, ob, moves, size)

    mirror, ob.data.use_mirror_x = ob.data.use_mirror_x, False
    bpy.ops.object.mode_set(mode="EDIT")
    edit = ob.data.edit_bones
    for eb in edit:
        eb.use_connect = False
    for eb in edit:
        rest, length = rests[eb.name]
        eb.length = length
        eb.matrix = rest
    every = dict(kept)
    place = {j: rests[name][0].translation for j, name in kept.items()}
    for j in plan.added:    # parents first
        p = ref[j].parent if ref[j].parent in place else ROOT
        place[j] = place[p] + (_head(ref, j) - _head(ref, p))
        eb = edit.new(f"{ADDED_PREFIX}{joints.PLAYER_JOINTS.get(j, (j,))[0]}")
        eb.tail = (0.0, 0.0, 0.05)
        rest = ref[j].matrix.to_3x3().normalized().to_4x4()
        rest.translation = place[j]
        eb.matrix = rest
        eb.use_deform = False
        every[j] = eb.name
    for j, name in every.items():
        p = ref[j].parent if ref[j].parent in every else (None if j == ROOT else ROOT)
        edit[name].parent = edit[every[p]] if p is not None else None
    bpy.ops.object.mode_set(mode="OBJECT")
    ob.data.use_mirror_x = mirror
    for j in plan.added:
        bones[every[j]][joints.JOINT_PROP] = str(j)
        bones[every[j]][joints.ADDED_PROP] = 1

    muted = 0
    for pb in ob.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
        for con in pb.constraints:
            muted += not con.mute
            con.mute = True
    for name in kept.values():
        bone = ob.data.bones[name]
        bone.use_inherit_rotation, bone.inherit_scale, bone.use_local_location = True, "FULL", True
    context.view_layer.update()
    to_arm = ob.matrix_world.inverted()
    for child, bone, world in children:
        child.matrix_world = ob.matrix_world @ moves.get(bone, size) @ to_arm @ world

    notes = list(plan.notes)
    if muted:
        notes.append(f"muted {muted} bone constraints: the game has none, and they'd fight the animations here")
    if any(g.armature == ob and g.actions for g in context.scene.albam.lmt_groups.anim_group):
        notes.append(f"{WARNING}LMTs imported on this rig are out of date: import them again")
    return notes


def match_skeleton(context, ob, path, match_size=True, own_size=True):
    ref = reference_skeleton(context, path)
    plan = build_plan(ob, ref, match_size)
    notes = apply_plan(context, ob, plan, ref)
    if not match_size and own_size:
        notes += keep_own_size(context, ob, ref)
    else:
        notes += remove_own_size(context, ob)
    return notes, plan


# ---- own size: Nero's / Dante's animations at the model's height --------------------------------------------------
# The root track is an absolute position, so a model smaller than the game's would have its feet in the air. A new
# root joint above joint 0 scaled by s (ModelExtension <offset>, dmc4_hook) scales that position, and an offset of
# 1 / s on joint 0 takes the scale off again for everything below: joint 0's world is P . T . R . S^-1 = the track's
# rotation at s times its position (uniform scale commutes with rotation). Chains keep their lengths, which come from
# the rest pose (Vibed/RE/chain_cnschain.md 3.2c). Root motion (joint 255) isn't scaled: the feet slide by 1 - s.

SIZE_ROOT = "game_size_root"
SIZE_PROP = "albam_size_root"
SAME_SIZE = 0.01


def size_root(ob):
    return next((b for b in ob.data.bones if b.get(SIZE_PROP)), None)


def _free_root_number(context, ob, ref):
    """a number no LMT of the character animates and no model of the scene has"""
    used = set(ref) | set(joints.PLAYER_JOINTS) | set(joints.PLAYER_FACE_TRACKS) | set(joints.RESERVED)
    used |= joints._reserved_by_lmts(ob)
    for arm in (o for o in context.scene.objects if o.type == "ARMATURE"):
        used |= {joints.joint_of(b) for b in arm.data.bones if b.get(SIZE_PROP) is None} - {None}
    free = [j for j in range(253, -1, -1) if j not in used]
    if not free:
        _refuse("No joint number left for the size root", "every number is used or animated",
                "Turn Match Size on, or free a number")
    return free[0]


def keep_own_size(context, ob, ref):
    """the size root under joint 0 at the game's model frame, and the list offsets; returns notes"""
    from . import model_ext
    by = {joints.joint_of(b): b.name for b in joints.joint_bones(ob) if joints.joint_of(b) is not None}
    hips_z = (ob.matrix_world @ ob.data.bones[by[HIPS]].head_local).z
    s = hips_z / _head(ref, HIPS).z
    if abs(s - 1.0) < SAME_SIZE:
        return remove_own_size(context, ob) + ["the model is the game model's size: no size root needed"]
    existing = size_root(ob)
    number = joints.joint_of(existing) if existing is not None else _free_root_number(context, ob, ref)
    context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    edit = ob.data.edit_bones
    eb = edit.get(existing.name) if existing is not None else edit.new(SIZE_ROOT)
    eb.parent = None
    eb.head, eb.tail, eb.roll = (0.0, 0.0, 0.0), (0.0, 0.0, 0.1), 0.0     # rest = the game's model frame
    eb.use_deform = False
    hips_root = edit[by[ROOT]]
    hips_root.parent, hips_root.use_connect = eb, False
    name = eb.name
    bpy.ops.object.mode_set(mode="OBJECT")
    bone = ob.data.bones[name]
    bone[SIZE_PROP] = 1
    bone[joints.JOINT_PROP] = str(number)
    bone[joints.ADDED_PROP] = 1
    lst = model_ext.set_size_offsets(context, ob.albam_asset.relative_path, number, s)
    return [f"own size {s:.3f} of the game model's: joint {number} ({name}) scales the animations, joint 0 undoes it "
            f"below ({lst.albam_asset.relative_path}, needs dmc4_hook)",
            f"{WARNING}moves carry her the game model's distances: the feet slide a little"]


def remove_own_size(context, ob):
    from . import model_ext
    bone = size_root(ob)
    if bone is None:
        return []
    number, name = joints.joint_of(bone), bone.name
    context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    edit = ob.data.edit_bones
    for child in edit[name].children:
        child.parent = None
    edit.remove(edit[name])
    bpy.ops.object.mode_set(mode="OBJECT")
    model_ext.clear_size_offsets(context, ob.albam_asset.relative_path, number)
    return [f"the size root (joint {number}) and its offsets are gone"]


def _model_paths(context):
    return [str(f.relative_path_windows) for f in context.scene.albam.rfs.file_list if f.name.lower().endswith(".mod")]


def _search_models(self, context, edit_text):
    text = edit_text.lower()
    return [p for p in _model_paths(context) if text in p.lower()]


def default_reference(context, ob):
    """the model the rig replaces, else the first player model found"""
    paths = {p.lower(): p for p in _model_paths(context)}
    own = ob.albam_asset.relative_path
    for path in (own, r"model\game\pl006\pl006.mod", r"model\game\pl000\pl000.mod"):
        if path.lower() in paths:
            return paths[path.lower()]
    return own


def other_character(ob, path):
    """a warning when the rig matches one model and goes into the game as another, else None. Each character has its
    own joints (Dante's 153-155 are chest and collars, Nero's hang off the Devil Bringer), and the game looks up the
    ones of the model that loads, so the two have to be the same."""
    own, used = (PureWindowsPath(p).stem.lower() for p in (ob.albam_asset.relative_path, path))
    if own == used or own not in joints.NEEDED_JOINTS or used not in joints.NEEDED_JOINTS:
        return None
    return (f"{WARNING}This model exports as {own} but would match {used}. Pick {own}'s .mod "
            "(add that character's folder in Game Files)")


_preview = []


@blender_registry.register_blender_type
class ALBAM_OT_MatchSkeleton(bpy.types.Operator):
    """Make this rig play the game's animations: its joints take a game model's parents and rest orientations, the
    mesh is posed and scaled to match (shape keys too), control bones are set aside and constraints muted. Run it
    once the main bones have their joint numbers, and import LMTs afterwards"""
    bl_idname = "albam.match_skeleton"
    bl_label = "Match Game Skeleton"
    bl_options = {"REGISTER", "UNDO"}

    reference: bpy.props.StringProperty(
        name="Game Model", search=_search_models,
        description="The model whose animations this rig should play, from the Game Files: use the .mod the rig "
                    "replaces. Dante's and Nero's joints differ, and the game looks up the joints of the model it loads")
    match_size: bpy.props.BoolProperty(
        name="Match Size", default=True,
        description="Scale the model so its hips stand as high as the game model's. Off: it keeps its own size")
    own_size: bpy.props.BoolProperty(
        name="Animations at Own Size", default=True,
        description="With Match Size off: add a root joint above the hips and a ModelExtension list that scale the "
                    "game's animations to this model's height, so its feet stay on the floor (needs dmc4_hook). "
                    "Off: the animations lift the hips to the game model's height")

    @classmethod
    def poll(cls, context):
        ob = context.object
        root = model_root(ob) if ob is not None else None
        return root is not None and root.type == "ARMATURE" and joints.is_game_armature(root) and \
            root.albam_asset.app_id == "dmc4"

    def invoke(self, context, event):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        ob = model_root(context.object)
        self.reference = default_reference(context, ob)
        _preview.clear()
        try:
            plan = build_plan(ob, reference_skeleton(context, self.reference), self.match_size)
            _preview.extend(summary(plan) + plan.notes)
        except AlbamCheckFailure as e:
            _preview.extend((f"{WARNING}{e.message}", f"{WARNING}{e.solution}"))
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "reference")
        layout.prop(self, "match_size")
        if not self.match_size:
            layout.prop(self, "own_size")
        warning = other_character(model_root(context.object), self.reference)
        for line in _preview + ([warning] if warning else []):
            warn = line.startswith(WARNING)
            layout.label(text=line[len(WARNING):] if warn else line, icon="ERROR" if warn else "INFO")

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        root = model_root(context.object)
        context.view_layer.objects.active = root
        try:
            notes, plan = match_skeleton(context, root, self.reference, self.match_size, self.own_size)
        except AlbamCheckFailure:
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
            return {"CANCELLED"}
        warning = other_character(root, self.reference)
        _report_notes(self, root, summary(plan) + notes + ([warning] if warning else []),
                      f"{root.name} matches {self.reference}")
        return {"FINISHED"}
