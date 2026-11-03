"""Match Game Skeleton (skeleton_match.py, 2026-11-02): a rig built the way MMD ones are (A-pose, smaller, its own bone
rolls, control bones in the spine, twist bones in the arms, constraints, auto numbers that land on Dante's joints) ends up
playing Dante's LMT like Dante:
- the plan changes nothing, and refusals leave the rig alone;
- every matched joint has the game model's parent and rest frame, the root is at the hips, the hips at the game's height;
- joint 13 moves to what the thighs hang from, a bone that isn't where its number belongs loses it, control bones are
  set aside, bones outside the match get numbers the game model doesn't use, constraints are muted;
- the mesh and shape keys are deformed exactly as the Armature modifier would, arms up in the game's T-pose;
- the same animation gives every joint the game model's rotation, and the hips its position;
- it exports with the game model's parents, and with every joint it has: the game reads some of them unchecked, so a
  missing one crashes it on the first frame (Dante's coat on 200 and 204, 2026-11-02), and export refuses such a model;
- running it again changes nothing."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import io, math, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
import numpy as np
from mathutils import Matrix, Vector
from albam.engines.mtfw import animation, col_shapes, joints, mesh, new_model, skeleton_match
from albam.exceptions import AlbamCheckFailure
from albam.lib import blender_compat as compat
from albam.registry import blender_registry

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


scene = bpy.context.scene
DANTE = os.path.join(common.ARCTOOL, "uPlayerDante-vanilla")
PATH = r"model\game\pl006\pl006.mod"
RIG_PATH = r"model\game\mine\mine.mod"
ARM_DOWN = math.radians(40)
SIZE = 0.7


def posed_rest(head, joint, shoulders):
    """where a joint of Dante's stands in the test rig: arms 40 degrees down, 0.7 times his size"""
    for side, first, last in (("r", 5, 8), ("l", 9, 12)):
        fingers = range(100, 116) if side == "r" else range(116, 132)
        if first < joint <= last or joint in fingers or joint == (150 if side == "r" else 151):
            pivot = shoulders[side]
            angle = -ARM_DOWN if side == "r" else ARM_DOWN
            head = pivot + Matrix.Rotation(angle, 3, "Y") @ (head - pivot)
    return head * SIZE


def make_rig(dante):
    source = {joints.joint_of(b): b for b in dante.data.bones}
    numbers = [j for j in source if skeleton_match._trusted(j) or j in (109, 125, 150, 151, 153)]
    shoulders = {"r": source[6].head_local.copy(), "l": source[10].head_local.copy()}
    place = {j: posed_rest(source[j].head_local.copy(), j, shoulders) for j in numbers}
    place[0] = Vector()         # MMD's root stands on the floor
    place[125] = (place[11] + place[12]) / 2    # the left palm's number on a twist dummy up the forearm

    ob = bpy.data.objects.new("rig", bpy.data.armatures.new("rig"))
    scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    edit = ob.data.edit_bones

    def bone(name, head, parent=None, roll=0.0):
        eb = edit.new(name)
        eb.head, eb.tail = head, head + Vector((0.0, 0.0, 0.08))
        eb.roll, eb.parent = roll, parent
        return eb

    hips_at = place[13]
    root = bone("all_parent", place[0])
    centre = bone("centre", hips_at, root)
    waist = bone("waist", hips_at, centre)
    lower = bone("lower", hips_at + Vector((0, 0, -0.02)), waist)      # what the thighs hang from: the real hips
    made = {0: root}
    for j in sorted(numbers, key=lambda n: skeleton_match._depth(n, {k: SimpleNamespace(
            parent=joints.joint_of(source[k].parent) if source[k].parent else None) for k in numbers})):
        if j in (0, 13):
            continue
        parent = joints.joint_of(source[j].parent) if source[j].parent else None
        up = made.get(parent)
        if parent == 13 or j in (14, 18):
            up = lower
        if j == 1:
            up = waist
        made[j] = bone(f"b{j}", place[j], up, roll=j * 0.37)
    # upper arm > twist > forearm, as MMD's
    twist = bone("twist_r", (place[6] + place[7]) / 2, made[6])
    made[7].parent = twist
    dummy = bone("dummy_leg", made[18].head + Vector((0, 0, 0.01)), made[18])
    breast = bone("breast_l", place[153] + Vector((0.08, -0.1, 0)), made[153])
    hair = bone("hair", place[4] + Vector((0, 0.1, 0)), made[4])
    ik = bone("ik_control", Vector((0.1, 0, 0)), root)
    names = {j: eb.name for j, eb in made.items()}
    bpy.ops.object.mode_set(mode="OBJECT")
    for j, name in names.items():
        ob.data.bones[name][joints.JOINT_PROP] = str(j)
        ob.data.bones[name][joints.ADDED_PROP] = 1
    # number_new_rig's kind of accidents
    for name, j in (("dummy_leg", 13), ("breast_l", 204)):
        ob.data.bones[name][joints.JOINT_PROP] = str(j)
        ob.data.bones[name][joints.ADDED_PROP] = 1
    con = ob.pose.bones["b14"].constraints.new("COPY_ROTATION")
    con.target, con.subtarget = ob, "ik_control"

    # three vertices per weighted bone, a little out from its head
    weighted = [n for n in names.values()] + ["twist_r", "breast_l", "hair", "lower"]
    verts, faces = [], []
    for n in weighted:
        head = ob.data.bones[n].head_local
        i = len(verts)
        verts += [head + Vector((0.02, 0, 0)), head + Vector((0, 0.02, 0)), head + Vector((0, 0, 0.02))]
        faces.append((i, i + 1, i + 2))
    me = bpy.data.meshes.new("body")
    me.from_pydata([tuple(v) for v in verts], [], faces)
    body = bpy.data.objects.new("body", me)
    scene.collection.objects.link(body)
    body.parent = ob
    body.modifiers.new("Armature", "ARMATURE").object = ob
    for i, n in enumerate(weighted):
        body.vertex_groups.new(name=n).add([i * 3, i * 3 + 1, i * 3 + 2], 1.0, "REPLACE")
    body.shape_key_add(name="Basis")
    key = body.shape_key_add(name="blink")
    key.value = 0.0       # 5.4 makes it 1
    for p in key.data:
        p.co.z += 0.01
    return ob, body


def evaluated(ob):
    bpy.context.view_layer.update()
    eval_ob = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = eval_ob.to_mesh()
    out = [v.co.copy() for v in me.vertices]
    eval_ob.to_mesh_clear()
    return out


def rest_state(ob):
    return {b.name: (b.matrix_local.copy(), b.get(joints.JOINT_PROP)) for b in ob.data.bones}


try:
    common.skip_unless(DANTE)
    scene.albam.rfs.add_root_folder("dmc4", DANTE)
    item = scene.albam.rfs.get_vfile("dmc4", PATH)
    mesh.build_blender_model(item, bpy.context)
    dante = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    before_objects = set(bpy.data.objects)
    ref = skeleton_match.reference_skeleton(bpy.context, PATH)
    check(set(bpy.data.objects) == before_objects and len(ref) > 60, "the reference is read without leaving anything behind")
    worst = max(abs(a - b) for b in dante.data.bones if joints.joint_of(b) in ref
                for ra, rb in zip(ref[joints.joint_of(b)].matrix, b.matrix_local) for a, b in zip(ra, rb))
    check(worst < 1e-5, f"its frames are the imported model's ({worst:.2e})")

    rig, body = make_rig(dante)

    # the skinning reproduces the Armature modifier, weights and all
    rig.pose.bones["b6"].rotation_quaternion = (0.8, 0.2, 0.5, 0.26)
    rig.pose.bones["b14"].rotation_quaternion = (0.9, 0.3, 0.3, 0.0)
    rig.pose.bones["b14"].constraints[0].mute = True
    want = evaluated(body)
    body.vertex_groups["b7"].add([0], 0.5, "ADD")   # a shared vertex, normalised
    want = evaluated(body)
    bpy.context.view_layer.update()
    moves = {pb.name: pb.matrix @ pb.bone.matrix_local.inverted() for pb in rig.pose.bones}
    shadow = body.copy()
    shadow.data = body.data.copy()
    scene.collection.objects.link(shadow)
    shadow.modifiers.clear()
    skeleton_match._skin(shadow, rig, moves, Matrix.Identity(4))
    shape = shadow.data.shape_keys
    bpy.context.view_layer.update()
    have = [p.co.copy() for p in shape.key_blocks["Basis"].data]
    worst = max((a - b).length for a, b in zip(have, want))
    check(worst < 1e-4, f"_skin moves vertices as the Armature modifier does ({worst:.2e} m)")
    moved_key = shape.key_blocks["blink"].data[3].co - shape.key_blocks["Basis"].data[3].co
    check(abs(moved_key.length - 0.01) < 1e-5, "and shape keys with them")
    bpy.data.objects.remove(shadow)
    body.vertex_groups["b7"].remove([0])
    for pb in rig.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    rig.pose.bones["b14"].constraints[0].mute = False

    bpy.context.view_layer.objects.active = rig
    root, notes = new_model.setup_new_model(bpy.context, rig, RIG_PATH)
    check(root == rig, "New DMC4 Model takes the rig")
    bpy.context.view_layer.objects.active = rig
    check(skeleton_match.ALBAM_OT_MatchSkeleton.poll(SimpleNamespace(object=rig)), "Match Game Skeleton is offered")
    check(skeleton_match.default_reference(bpy.context, rig) == PATH, "a player model is the default reference")
    state = rest_state(rig)
    co = [v.co.copy() for v in body.data.vertices]
    plan = skeleton_match.build_plan(rig, ref)
    check(rest_state(rig) == state and [v.co for v in body.data.vertices] == co, "the plan changes nothing")
    check(joints.joint_of(rig.data.bones["dummy_leg"]) == 13 and plan.kept[13].name == "lower",
          "joint 13 is planned for what the thighs hang from")
    check("breast_l" in plan.renumber and 204 not in plan.kept, f"a misplaced number is taken away ({plan.notes})")
    check("ik_control" in plan.helpers and "dummy_leg" in plan.helpers and "lower" not in plan.helpers,
          "unweighted control bones are set aside")

    # matched to one character, exported as another: the dialog says so
    own_path = rig.albam_asset.relative_path
    rig.albam_asset.relative_path = PATH
    check(skeleton_match.other_character(rig, r"model\game\pl000\pl000.mod") is not None and
          skeleton_match.other_character(rig, PATH) is None, "matching another character than the export is warned about")
    rig.albam_asset.relative_path = own_path

    # refused, unchanged
    try:
        skeleton_match.build_plan(dante, ref)
        refused = False
    except AlbamCheckFailure:
        refused = True
    check(refused, "a game model's own bones are refused")
    flipped = {j: SimpleNamespace(parent=r.parent, matrix=Matrix.Rotation(math.pi, 4, "Z") @ r.matrix) for j, r in ref.items()}
    try:
        skeleton_match.build_plan(rig, flipped)
        refused = False
    except AlbamCheckFailure as e:
        refused = "round" in e.message
    check(refused and rest_state(rig) == state, "a rig facing the other way is refused")

    class Stub:
        def __init__(self):
            self.lines = []
        def __getattr__(self, name):
            return lambda *args, **kw: self.lines.append((name, args[0] if args else None, kw.get("text")))
    skeleton_match._preview[:] = skeleton_match.summary(plan) + plan.notes
    layout = Stub()
    skeleton_match.ALBAM_OT_MatchSkeleton.draw(SimpleNamespace(layout=layout, reference=PATH), bpy.context)
    texts = [t for name, _, t in layout.lines if name == "label"]
    check(any("joints match" in t for t in texts) and any("hips" in t for t in texts),
          f"the dialog says what will happen ({len(texts)} lines)")
    model_layout = Stub()
    model_layout.row = model_layout.column = lambda *a, **k: model_layout
    new_model.ALBAM_PT_NewModel.draw(SimpleNamespace(layout=model_layout), SimpleNamespace(object=rig))
    check(("operator", "albam.match_skeleton", None) in model_layout.lines, "the DMC4 Model panel has the button")

    scale = ref[13].matrix.to_translation().z / rig.data.bones["lower"].head_local.z
    result = bpy.ops.albam.match_skeleton("EXEC_DEFAULT", reference=PATH)
    check(result == {"FINISHED"}, "the operator runs")

    by = {joints.joint_of(b): b for b in joints.joint_bones(rig) if joints.joint_of(b) is not None}
    matched = list(ref)
    wrong = [j for j in matched if (joints.joint_of(by[j].parent) if by[j].parent else None) != ref[j].parent]
    check(not wrong, f"every joint has the game model's parent ({wrong})")
    check(not set(ref) - set(by), f"every joint of the game model exists ({sorted(set(ref) - set(by))})")
    check(not any(by[j].use_deform for j in plan.added), "the added ones don't deform")
    check(125 in plan.added and joints.joint_of(rig.data.bones["b125"]) != 125 and by[125].name.startswith("game_"),
          "a palm number on a bone behind the wrist goes to a new bone")
    check(joints.joint_of(by[126].parent) == 125, "and the fingers hang from that")
    angle = lambda m: math.degrees(m.to_quaternion().angle)   # noqa: E731
    worst = max(angle(ref[j].matrix.to_3x3().inverted() @ by[j].matrix_local.to_3x3()) for j in matched)
    check(worst < 0.01, f"and its rest frame ({worst:.5f} deg)")
    check((by[0].head_local - by[13].head_local).length < 1e-5, "the root is at the hips, as in the game")
    check(abs(by[13].head_local.z - ref[13].matrix.to_translation().z) < 1e-4, "the hips are at the game's height")
    check(joints.is_helper(rig.data.bones["ik_control"]) and joints.is_helper(rig.data.bones["dummy_leg"]) and
          joints.joint_of(rig.data.bones["dummy_leg"]) is None, "control bones are Not a Game Joint")
    breast_number = joints.joint_of(rig.data.bones["breast_l"])
    check(breast_number is not None and breast_number not in ref, f"the breast bone got a free number ({breast_number})")
    check(joints.joint_of(rig.data.bones["hair"]) not in ref, "so did the unnumbered hair")
    check(all(c.mute for pb in rig.pose.bones for c in pb.constraints), "constraints are muted")

    arms = [(6, 7), (7, 8), (10, 11), (11, 12), (14, 15)]
    worst = max(math.degrees((by[b].head_local - by[a].head_local).angle(
        ref[b].matrix.to_translation() - ref[a].matrix.to_translation())) for a, b in arms)
    check(worst < 0.01, f"limbs point the game model's way ({worst:.4f} deg)")
    rest = evaluated(body)
    base = body.data.shape_keys.key_blocks["Basis"].data
    check(max((a - base[i].co).length for i, a in enumerate(rest)) < 1e-4, "at rest the mesh stands as baked")
    parts = skeleton_match._deformed_meshes(rig)    # New DMC4 Model split it
    first = next(v for o in parts for v in o.data.vertices for g in v.groups if o.vertex_groups[g.group].name == by[8].name)
    check((first.co - by[8].head_local).length < 0.05 * scale, "the mesh went up with the arm")
    keys = body.data.shape_keys.key_blocks
    check(abs((keys["blink"].data[0].co - keys["Basis"].data[0].co).length - 0.01 * scale) < 1e-4, "shape keys followed, scaled")

    # again: nothing to do
    state, co = rest_state(rig), [[v.co.copy() for v in o.data.vertices] for o in skeleton_match._deformed_meshes(rig)]
    again = skeleton_match.build_plan(rig, ref)
    check(abs(again.scale - 1.0) < 1e-5 and not again.added and not again.renumber, "a matched rig needs nothing more")
    bpy.ops.albam.match_skeleton("EXEC_DEFAULT", reference=PATH)
    worst = max((a[0].to_translation() - b[0].to_translation()).length for a, b in
                ((state[n], (bone.matrix_local, 0)) for n, bone in rig.data.bones.items()))
    moved = max((v.co - c).length for o, cs in zip(skeleton_match._deformed_meshes(rig), co) for v, c in zip(o.data.vertices, cs))
    check(worst < 1e-5 and moved < 1e-5 and {n: s[1] for n, s in state.items()} == {n: s[1] for n, s in rest_state(rig).items()},
          f"and running it twice changes nothing: no lean ({worst:.2e}, {moved:.2e} m)")
    by = {joints.joint_of(b): b for b in joints.joint_bones(rig) if joints.joint_of(b) is not None}

    # new bones keep off the numbers the player's LMTs animate, imported or not (face tracks 155-165)
    bpy.ops.object.mode_set(mode="EDIT")
    for i in range(100):
        rig.data.edit_bones.new(f"extra_{i}").tail = (0.0, 0.0, 0.1)
    bpy.ops.object.mode_set(mode="OBJECT")
    given = {j for _, j in joints.ensure_joint_numbers(rig)}
    check(len(given) == 100 and not given & set(range(155, 166)) and not given & set(joints.PLAYER_JOINTS),
          "new bones stay off the numbers the player's LMTs animate")
    bpy.ops.object.mode_set(mode="EDIT")
    for i in range(100):
        rig.data.edit_bones.remove(rig.data.edit_bones[f"extra_{i}"])
    bpy.ops.object.mode_set(mode="OBJECT")
    by = {joints.joint_of(b): b for b in joints.joint_bones(rig) if joints.joint_of(b) is not None}

    # the same animation on both
    lmt_item = scene.albam.rfs.get_vfile("dmc4", r"motion\pl006\pl006_01.lmt")
    for target in (rig, dante):
        scene.albam.import_options_lmt.armature = target
        animation.load_lmt(lmt_item, bpy.context)
    group_of = lambda arm: next(g for g in scene.albam.lmt_groups.anim_group if g.armature == arm)   # noqa: E731
    rows = zip(group_of(rig).actions, group_of(dante).actions)
    action_r, action_d = next((a.action, b.action) for a, b in rows if a.action and b.action and a.action.frame_range[1] > 30)
    compat.assign_action(rig, action_r)
    compat.assign_action(dante, action_d)
    dby = {joints.joint_of(b): b.name for b in dante.data.bones if joints.joint_of(b) is not None}
    by = {joints.joint_of(b): b.name for b in joints.joint_bones(rig) if joints.joint_of(b) is not None}
    worst_turn = worst_hip = 0.0
    for frame in (0, 12, 30):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for j in matched:
            a, d = rig.pose.bones[by[j]].matrix.to_3x3(), dante.pose.bones[dby[j]].matrix.to_3x3()
            worst_turn = max(worst_turn, angle(d.inverted() @ a))
        worst_hip = max(worst_hip, (rig.pose.bones[by[13]].head - dante.pose.bones[dby[13]].head).length)
    check(worst_turn < 0.1, f"Dante's LMT turns every joint as it turns Dante's ({worst_turn:.4f} deg)")
    check(worst_hip < 1e-3, f"and puts the hips where his are ({worst_hip:.5f} m)")
    scene.frame_set(0)
    for pb in rig.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)

    # a capsule on the rig: its wire tube is a mesh under the armature, not a part of the model
    root_col = col_shapes._new_root(bpy.context, "shapes", "dmc4", r"chains\shapes.col", b"", rig)
    col_shapes._ensure_groups(root_col, 1)
    bones_now = {joints.joint_of(b): b for b in joints.joint_bones(rig)}
    coll_col = root_col.users_collection[0]
    a_end = col_shapes._new_end("cap_a", "a", rig, bones_now[14], (0.0, 0.0, 0.0), 10.0, coll_col, root_col)
    b_end = col_shapes._new_end("cap_b", "b", rig, bones_now[15], (0.0, 0.0, 0.0), 10.0, coll_col, root_col)
    a_end[col_shapes.CAP_PROP] = b_end[col_shapes.CAP_PROP] = col_shapes._new_capsule_key()
    col_shapes._mark_shape(a_end, 0)
    col_shapes.sync_tubes(root_col, bpy.context)
    tubes = [o for o in rig.children_recursive if o.type == "MESH" and "col_root" in o]
    check(tubes and not set(tubes) & set(joints.model_meshes(rig)), "a capsule's tube isn't one of the model's meshes")

    bpy.context.view_layer.objects.active = rig
    files = blender_registry.export_registry[("dmc4", "mod")](rig)
    data = next(f for f in files if f.relative_path.lower() == RIG_PATH.lower()).data_bytes
    parsed = mesh.Mod153(mesh.KaitaiStream(io.BytesIO(bytes(data))))
    parsed._read()
    table = parsed.bones_data.bones_hierarchy
    number = [b.idx_anim_map for b in table]
    parents = {b.idx_anim_map: (number[b.idx_parent] if b.idx_parent < 255 else None) for b in table}
    wrong = [j for j in matched if parents.get(j) != ref[j].parent]
    check(not wrong, f"the exported .mod has the game model's parents ({wrong})")
    check(all(j not in ref or j in matched for j in parents), "and no bone of it on a joint the rig didn't match")
    check(len(table) == len(joints.joint_bones(rig)) and "ik_control" not in [b.name for b in joints.joint_bones(rig)],
          "control bones aren't exported")
    check(all(number.count(j) == 1 for j in ref), "the .mod has every joint of the game model")

    # what crashed the game: a player model without the joints its parts pin to
    rig.albam_asset.relative_path = r"model\game\pl006x\pl006.mod"
    bpy.ops.object.mode_set(mode="EDIT")
    rig.data.edit_bones.remove(rig.data.edit_bones[by[200]])
    bpy.ops.object.mode_set(mode="OBJECT")
    try:
        blender_registry.export_registry[("dmc4", "mod")](rig)
        refused = ""
    except AlbamCheckFailure as e:
        refused = e.details
    check("200" in refused, f"export refuses a pl006 without joint 200 ({refused})")

    # no crash, but the sword on the back falls to the root (the Red Queen's joint table is 152, 150, 151)
    rig.albam_asset.relative_path = r"model\game\pl000x\pl000.mod"
    bpy.ops.object.mode_set(mode="EDIT")
    rig.data.edit_bones.remove(rig.data.edit_bones[by[152]])
    bpy.ops.object.mode_set(mode="OBJECT")
    try:
        blender_registry.export_registry[("dmc4", "mod")](rig)
        refused = ""
    except AlbamCheckFailure as e:
        refused = e.details
    check("152" in refused, f"export refuses a pl000 without the weapon joints ({refused})")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
