"""Bones added in Blender export to the .mod (joints.py, mesh._serialize_joint_layout): game models keep their bone
tables bit for bit; new bones on Nero's coat get free joint numbers, go after the model's own bones (parents first,
whatever Blender's order), invert their chain, sit where Blender has them, are in the palettes and weight bounds, and
come back on re-import with the same weights; LMT export, new chains and .col shapes accept them; Shift+D copies
get their own number; deleting a model bone and helper bones are handled."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import io, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from mathutils import Matrix, Vector
from albam.exceptions import AlbamCheckFailure
from albam.engines.mtfw import animation, cns_chain, joints, mesh

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


BODY, COAT = r"model\game\pl000\pl000.mod", r"model\game\pl000\pl000_03.mod"
common.skip_unless(os.path.join(common.NERO, BODY), os.path.join(common.NERO, COAT))
scene = bpy.context.scene
scene.albam.rfs.add_root_folder("dmc4", common.NERO)


def parse(data):
    m = mesh.Mod153(mesh.KaitaiStream(io.BytesIO(bytes(data))))
    m._read()
    return m


def rows(mx):
    return [(r.x, r.y, r.z, r.w) for r in (mx.row_1, mx.row_2, mx.row_3, mx.row_4)]


def import_model(rel):
    item = next(i for i in scene.albam.rfs.file_list if i.name.lower().endswith(rel.lower().replace("\\", "::")))
    before = set(bpy.data.objects)
    mesh.build_blender_model(item, bpy.context)
    arm = next(o for o in set(bpy.data.objects) - before if o.type == "ARMATURE")
    if arm.name not in scene.collection.objects:
        scene.collection.objects.link(arm)
    return arm, open(os.path.join(common.NERO, rel), "rb").read()


def export(arm):
    return next(v for v in mesh.export_mod(arm) if v.relative_path.lower().endswith(".mod")).data_bytes


def joint(arm, name):
    return int(arm.data.bones[name][joints.JOINT_PROP])


try:
    # -- game models keep their bone tables ---------------------------------------------------------------------------
    for rel in (BODY, COAT):
        arm, src = import_model(rel)
        s, o = parse(src).bones_data, parse(export(arm)).bones_data
        fields = lambda b: (b.idx_anim_map, b.idx_parent, b.idx_mirror, b.idx_mapping, b.length,  # noqa: E731
                            b.parent_distance, b.location.x, b.location.y, b.location.z)
        check([fields(b) for b in s.bones_hierarchy] == [fields(b) for b in o.bones_hierarchy]
              and bytes(s.bone_map) == bytes(o.bone_map), f"{rel}: bone table unchanged")
        check(all(rows(a) == rows(b) for a, b in zip(s.parent_space_matrices, o.parent_space_matrices))
              and all(rows(a) == rows(b) for a, b in zip(s.inverse_bind_matrices, o.inverse_bind_matrices)),
              f"{rel}: matrices bit for bit")
        check(joints.ensure_joint_numbers(arm) == [], f"{rel}: every bone has its joint number")
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)

    # -- new bones on the coat ----------------------------------------------------------------------------------------
    arm, src = import_model(COAT)
    n_src = parse(src).header.num_bones
    meshes = [c for c in arm.children_recursive if c.type == "MESH"]
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    a = eb.new("tail_a")
    a.head = eb["7"].head + Vector((0, 0, -0.10)); a.tail = a.head + Vector((0, 0, -0.05)); a.parent = eb["7"]
    b = eb.new("tail_b")
    b.head = a.head + Vector((0, 0, -0.10)); b.tail = b.head + Vector((0, 0, -0.05)); b.parent = a
    mid = eb.new("mid_under_1")
    mid.head = eb["1"].head + Vector((0, 0.03, 0)); mid.tail = mid.head + Vector((0, 0, 0.05)); mid.parent = eb["1"]
    helper = eb.new("root_motion")
    helper.tail = (0, 0, 0.01)
    bpy.ops.object.mode_set(mode="OBJECT")
    names = [bn.name for bn in arm.data.bones]
    check(names.index("mid_under_1") < names.index("8"), "Blender orders the new bone mid-list")
    target = max(meshes, key=lambda o: len(o.data.vertices))
    for k, name in enumerate(("tail_a", "tail_b", "mid_under_1")):
        target.vertex_groups.new(name=name).add(list(range(k * 10, k * 10 + 10)), 0.5, "ADD")

    data = export(arm)
    out = parse(data)
    bd = out.bones_data
    check(out.header.num_bones == n_src + 3, f"{out.header.num_bones} bones exported ({n_src} + 3, helper left out)")
    check("mtfw.anim_retarget" not in arm.data.bones["root_motion"], "the helper bone gets no joint number")
    by_joint = {bh.idx_anim_map: i for i, bh in enumerate(bd.bones_hierarchy)}
    ia, ib, im = (by_joint.get(joint(arm, n)) for n in ("tail_a", "tail_b", "mid_under_1"))
    check(min(ia, ib, im) >= n_src and all(j < 254 for j in (joint(arm, "tail_a"), joint(arm, "tail_b"))),
          f"new bones go after the model's own with free joint numbers ({ia}, {ib}, {im})")
    check(bd.bones_hierarchy[ia].idx_parent == 7 and bd.bones_hierarchy[ib].idx_parent == ia
          and bd.bones_hierarchy[im].idx_parent == 1, "their parents are right")
    check(all(bd.bone_map[bh.idx_anim_map] == i for i, bh in enumerate(bd.bones_hierarchy)), "joint table matches")
    world = {}
    for j, bh in enumerate(bd.bones_hierarchy):
        local = Matrix(rows(bd.parent_space_matrices[j]))
        world[j] = local if bh.idx_parent == 255 else local @ world[bh.idx_parent]
    worst = max(abs(v - w) for j in world for rr, ss in zip(Matrix(rows(bd.inverse_bind_matrices[j])) @ world[j],
                                                            Matrix.Identity(4)) for v, w in zip(rr, ss))
    check(worst < 1e-3, f"inverse binds invert the chain ({worst:.1e})")
    head = arm.data.bones["tail_a"].head_local
    check((Vector(world[ia][3][:3]) - Vector((head.x, head.z, -head.y)) * 100).length < 0.01,
          "tail_a sits where Blender has it")
    loc = bd.bones_hierarchy[ia].location
    check(abs(bd.bones_hierarchy[ia].parent_distance - Vector((loc.x, loc.y, loc.z)).length) < 1e-4,
          "mLength = |offset|")
    palette = {j for p in bd.bone_palettes for j in list(p.indices)[:p.unk_01]}
    check({ia, ib, im} <= palette, "the palettes hold the new bones")

    # re-import: rest positions and weights
    before_w = {}
    for o in meshes:
        groups = {g.index: g.name for g in o.vertex_groups}
        jmap = {bn.name: bn.get(joints.JOINT_PROP) for bn in arm.data.bones}
        before_w[o.name] = sorted((v.index, jmap.get(groups[g.group])) for v in o.data.vertices for g in v.groups
                                  if g.weight > 0.01)
    item = SimpleNamespace(app_id="dmc4", display_name="pl000_03.mod", relative_path=COAT, absolute_path="",
                           get_bytes=lambda: bytes(data), extension="mod",
                           relative_path_windows_no_ext=COAT[:-4])
    seen = set(bpy.data.objects)
    mesh.build_blender_model(item, bpy.context)
    arm2 = next(o for o in set(bpy.data.objects) - seen if o.type == "ARMATURE")
    j2 = {bn.get(joints.JOINT_PROP): bn for bn in arm2.data.bones}
    worst = max((j2[arm.data.bones[n][joints.JOINT_PROP]].head_local - arm.data.bones[n].head_local).length
                for n in ("tail_a", "tail_b", "mid_under_1"))
    check(worst < 1e-4, f"re-import puts the new bones back ({worst:.1e} m)")
    matched = 0
    new_meshes = [o for o in set(bpy.data.objects) - seen if o.type == "MESH"]
    for o in new_meshes:
        groups = {g.index: g.name for g in o.vertex_groups}
        jmap = {bn.name: bn.get(joints.JOINT_PROP) for bn in arm2.data.bones}
        w = sorted((v.index, jmap.get(groups[g.group])) for v in o.data.vertices for g in v.groups if g.weight > 0.01)
        matched += any(len(v) == len(w) and sum(x == y for x, y in zip(v, w)) > 0.98 * len(w)
                       for v in before_w.values())
    check(matched == len(new_meshes), f"re-imported weights land on the same joints ({matched}/{len(new_meshes)})")
    for ob in [arm2] + new_meshes:
        bpy.data.objects.remove(ob)

    # -- LMT export: a new bone without a number gets one and a track ------------------------------------------------
    bpy.context.view_layer.objects.active = arm     # the re-import made its own armature active
    bpy.ops.object.mode_set(mode="EDIT")
    c = arm.data.edit_bones.new("tail_c")
    c.head = arm.data.edit_bones["tail_b"].tail; c.tail = c.head + Vector((0, 0, -0.05))
    c.parent = arm.data.edit_bones["tail_b"]
    bpy.ops.object.mode_set(mode="OBJECT")
    action = bpy.data.actions.new("new_bone_anim")
    arm.animation_data_create()
    animation.compat.assign_action(arm, action)
    pb = arm.pose.bones["tail_c"]
    pb.rotation_mode = "QUATERNION"
    for f, q in ((0, (1, 0, 0, 0)), (10, (0.92, 0.39, 0, 0))):
        pb.rotation_quaternion = q
        pb.keyframe_insert("rotation_quaternion", frame=f)
    group = scene.albam.lmt_groups.add("new_bones.lmt")
    group.armature = arm
    group.num_slots = 1
    props = animation.get_lmt_props(action)
    props.lmt_id, props.num_frames, props.loop_frames, props.source_fps = 0, 11, -1, 60
    action.albam_asset.app_id = "dmc4"
    group.add(action)
    lmt = animation.Lmt(animation.KaitaiStream(animation.io.BytesIO(bytes(animation.export_lmt(group)))))
    lmt._read()
    check("mtfw.anim_retarget" in arm.data.bones["tail_c"], "LMT export gives the new bone a joint number")
    check(any(t.bone_index == joint(arm, "tail_c") for t in lmt.block_offsets[0].block_header.tracks),
          "and writes its track")

    # -- chain on new bones -------------------------------------------------------------------------------------------
    chain = cns_chain.new_chain(bpy.context, arm, [arm.data.bones[n] for n in ("tail_a", "tail_b", "tail_c")],
                                r"model\game\pl000\pl000_03_90.phs")
    slots = [int(j) for j in chain["phs_joints"]]
    check(slots == [joint(arm, n) for n in ("tail_a", "tail_b", "tail_c")], f"a chain over the new bones ({slots})")
    # New Chain from Selected Bones reads the selection through blender_compat (Blender 5 keeps it on pose bones;
    # reading Bone.select there raised and greyed the button out)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    for pb in arm.pose.bones:
        if animation.compat.POSE_BONE_SELECT:
            pb.select = pb.name in ("tail_a", "tail_b")
        else:
            pb.bone.select = pb.name in ("tail_a", "tail_b")
    check(bpy.ops.albam.phs_new.poll() and [b.name for b in animation.compat.selected_bones(arm)] ==
          ["tail_a", "tail_b"], "New Chain from Selected Bones sees the selected bones")
    bpy.ops.object.mode_set(mode="OBJECT")

    # -- Shift+D in Edit Mode: the copy gets its own number ----------------------------------------------------------
    bpy.ops.object.mode_set(mode="EDIT")
    for e in arm.data.edit_bones:
        e.select = e.select_head = e.select_tail = e.name == "tail_b"
    arm.data.edit_bones.active = arm.data.edit_bones["tail_b"]
    bpy.ops.armature.duplicate()
    bpy.ops.object.mode_set(mode="OBJECT")
    copy = next(bn for bn in arm.data.bones if bn.name.startswith("tail_b."))
    check(copy.get(joints.JOINT_PROP) == arm.data.bones["tail_b"][joints.JOINT_PROP], "Shift+D copies the number")
    original = joint(arm, "tail_b")
    joints.ensure_joint_numbers(arm)
    check(joint(arm, "tail_b") == original and joint(arm, copy.name) != original,
          "the copy gets a new number, the original keeps its")

    # -- Game Joint panel properties ------------------------------------------------------------------------------------
    settings = arm.pose.bones["tail_a"].albam_joint
    taken = joint(arm, "tail_b")
    before = settings.number
    settings.number = taken
    check(settings.number == before, "the panel refuses another bone's joint number")
    used = {joint(arm, bn.name) for bn in arm.data.bones if joints.JOINT_PROP in bn}
    free = next(n for n in range(200, 254) if n not in used)
    settings.number = free
    check(settings.number == free, f"the panel sets a free joint number ({free})")
    settings.mirror = "mid_under_1"
    check(arm.data.bones["tail_a"][joints.MIRROR_PROP] == "mid_under_1", "the mirror pick is stored on the bone")
    out = parse(export(arm))
    by_joint = {bh.idx_anim_map: (i, bh) for i, bh in enumerate(out.bones_data.bones_hierarchy)}
    check(by_joint[joint(arm, "tail_a")][1].idx_mirror == by_joint[joint(arm, "mid_under_1")][0],
          "export writes the picked mirror")
    settings.not_joint = True
    out = parse(export(arm))
    check(out.header.num_bones == n_src + 4, "a bone marked Not a Game Joint isn't exported")  # tail_b, c, copy, mid
    settings.not_joint = False

    # -- deleting a model bone is refused ------------------------------------------------------------------------------
    bpy.ops.object.mode_set(mode="EDIT")
    arm.data.edit_bones.remove(arm.data.edit_bones["20"])
    bpy.ops.object.mode_set(mode="OBJECT")
    try:
        export(arm)
        check(False, "deleting a model bone is refused")
    except AlbamCheckFailure as err:
        check("deleted" in err.message and "index 20" in err.details,
              f"deleting a model bone is refused ({err.message}: {err.details})")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
