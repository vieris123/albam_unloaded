"""Bones named after their joints (joints.py `name_bones`, 2026-10-31): importing Nero's / Dante's body names the bones
thumb_1_r, thigh_l ... (joints the table has no name for: joint_<n>; Nero's 153 hangs off the Devil Bringer, so it
isn't Dante's chest), vertex groups follow, the coat (its own 0-38) keeps index names, the .mod exports the same bytes
as an unnamed import, and Name Bones by Joint on an old rig keeps its LMT (every action, not only the one playing) and
its vertex groups working."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.engines.mtfw import animation, joints, mesh
from albam.lib import blender_compat as compat

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


DANTE = os.path.join(common.ARCTOOL, "uPlayerDante-vanilla")
BODY, COAT, DBODY = r"model\game\pl000\pl000.mod", r"model\game\pl000\pl000_03.mod", r"model\game\pl006\pl006.mod"
LMT = r"motion\pl000\pl000_01.lmt"
common.skip_unless(*(os.path.join(common.NERO, p) for p in (BODY, COAT, LMT)), os.path.join(DANTE, DBODY))
scene = bpy.context.scene
scene.albam.rfs.add_root_folder("dmc4", common.NERO)
scene.albam.rfs.add_root_folder("dmc4", DANTE)


def import_model(rel, named=True):
    item = next(i for i in scene.albam.rfs.file_list if i.name.lower().endswith(rel.lower().replace("\\", "::")))
    before = set(bpy.data.objects)
    keep = joints.name_bones
    if not named:
        joints.name_bones = lambda ob: {}   # the import before 2026-10-31: bones named by their table index
    try:
        mesh.build_blender_model(item, bpy.context)
    finally:
        joints.name_bones = keep
    arm = next(o for o in set(bpy.data.objects) - before if o.type == "ARMATURE")
    if arm.name not in scene.collection.objects:
        scene.collection.objects.link(arm)
    return arm


def by_joint(arm):
    return {joints.joint_of(b): b.name for b in arm.data.bones if joints.joint_of(b) is not None}


def export(arm):
    return next(v for v in mesh.export_mod(arm) if v.relative_path.lower().endswith(".mod")).data_bytes


def groups_match(arm):
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.parent == arm]
    names = {b.name for b in arm.data.bones}
    return bool(meshes) and all(vg.name in names for o in meshes for vg in o.vertex_groups)


try:
    nero = import_model(BODY)
    j = by_joint(nero)
    check(j[100] == "thumb_1_r" and j[14] == "thigh_r" and j[21] == "toe_l" and j[0] == "root" and
          j[109] == "palm_r" and j[131] == "pinky_3_l", f"Nero's bones are named after their joints ({j[100]}, {j[14]})")
    check(j[153] == "joint_153" and j[154] == "joint_154",
          f"Nero's Devil Bringer joints don't take Dante's names ({j[153]}, {j[154]})")
    check(groups_match(nero), "Nero's vertex groups follow the bone names")
    check(joints.joint_label(nero, 100) == "100 thumb_1_r" and joints.joint_label(nero, 153) == "153",
          "joint labels")

    dante = import_model(DBODY)
    j = by_joint(dante)
    check(j[153] == "chest" and j[154] == "collar_r" and j[155] == "collar_l" and j[152] == "weapon_back",
          f"Dante's chest / collars ({j[153]}, {j[154]}, {j[155]})")
    check(groups_match(dante), "Dante's vertex groups follow the bone names")

    coat = import_model(COAT)
    check(all(b.name.isdigit() for b in coat.data.bones) and not joints.game_joint_names(coat),
          "the coat (its own joints 0-38) isn't a player skeleton: index names kept")

    named_bytes = export(nero)
    old = import_model(BODY, named=False)
    check(all(b.name.isdigit() for b in old.data.bones), "an old import has index names")
    check(export(old) == named_bytes, "the named rig exports the same .mod as an unnamed one")

    # an old rig with an LMT: Name Bones by Joint renames the curves of every action of the LMT
    scene.albam.import_options_lmt.armature = old
    item_path = os.path.join(common.NERO, LMT)
    data = open(item_path, "rb").read()
    lmt_item = SimpleNamespace(app_id="dmc4", display_name="pl000_01.lmt", relative_path=LMT,
                               absolute_path=item_path, get_bytes=lambda: data, extension="lmt")
    animation.load_lmt(lmt_item, bpy.context)
    lmt = scene.albam.lmt_groups.anim_group[scene.albam.lmt_groups.active_group_id]
    before = animation.export_lmt(lmt)
    bpy.context.view_layer.objects.active = old
    with bpy.context.temp_override(object=old, active_object=old):
        result = bpy.ops.albam.name_bones_by_joint()
    check(result == {"FINISHED"} and by_joint(old)[100] == "thumb_1_r", "Name Bones by Joint renames an old rig")
    check(groups_match(old), "its vertex groups follow")
    playing = old.animation_data.action if old.animation_data else None
    stale = [fc.data_path for item in lmt.actions if item.action and item.action != playing
             for fc in compat.action_fcurves(item.action)
             if fc.data_path.startswith('pose.bones["') and fc.data_path[12:].split('"')[0] not in old.data.bones]
    check(not stale, f"the LMT's other actions address the new names ({stale[:3]})")
    check(animation.export_lmt(lmt) == before, "the LMT exports the same bytes after the rename")
    check(export(old) == named_bytes, "the renamed rig exports the same .mod")
    with bpy.context.temp_override(object=old, active_object=old):
        again = bpy.ops.albam.name_bones_by_joint()
    check(again == {"CANCELLED"}, "nothing left to rename the second time")

    # a new bone: the joint picker lists the player skeleton by name, gives a free number, refuses a used one
    check(joints.player_joint_hint(14) == "thigh_r, under 13 hips" and joints.player_joint_hint(0) == "root" and
          joints.player_joint_hint(60) is None, "player joint hints")
    bpy.context.view_layer.objects.active = nero
    bpy.ops.object.mode_set(mode="EDIT")
    eb = nero.data.edit_bones.new("extra")
    eb.head, eb.tail, eb.parent = (0, 0, 1), (0, 0, 1.1), nero.data.edit_bones[by_joint(nero)[2]]
    bpy.ops.object.mode_set(mode="POSE")
    choices = joints.joint_choices(nero)
    labels = {j: label for j, label, _ in choices}
    check(labels.get(100) == "100 thumb_1_r, under 8 hand_r" and dict((j, u) for j, _, u in choices)[100] == "thumb_1_r",
          f"the picker lists joints by name with their bone ({labels.get(100)})")
    free = next((j for j, _, user in choices if user is None), None)
    with bpy.context.temp_override(object=nero, active_object=nero):
        result = bpy.ops.albam.pick_joint_number("EXEC_DEFAULT", armature=nero.name, bone="extra", joint=str(free))
        try:
            bpy.ops.albam.pick_joint_number("EXEC_DEFAULT", armature=nero.name, bone="extra", joint="14")
            refused = False
        except RuntimeError as e:   # an ERROR report raises from bpy.ops
            refused = "game file" in str(e)
    check(free is not None and result == {"FINISHED"} and joints.joint_of(nero.data.bones["extra"]) == free,
          f"picking a free joint ({free}) numbers the bone")
    check(refused and joints.joint_of(nero.data.bones["extra"]) == free, "a game file bone's joint is refused")

    # a number another added bone has moves over: that bone goes to -1, and export numbers it again
    bpy.ops.object.mode_set(mode="EDIT")
    eb = nero.data.edit_bones.new("extra2")
    eb.head, eb.tail, eb.parent = (0, 0, 1), (0, 0, 1.1), nero.data.edit_bones["extra"]
    bpy.ops.object.mode_set(mode="POSE")
    with bpy.context.temp_override(object=nero, active_object=nero):
        result = bpy.ops.albam.pick_joint_number("EXEC_DEFAULT", armature=nero.name, bone="extra2", joint=str(free))
    extra, extra2 = nero.data.bones["extra"], nero.data.bones["extra2"]
    check(result == {"FINISHED"} and joints.joint_of(extra2) == free and joints.joint_of(extra) is None and
          nero.pose.bones["extra"].albam_joint.number == -1, "the picker replaces another added bone, which goes to -1")
    nero.pose.bones["extra"].albam_joint.number = free
    check(joints.joint_of(extra) == free and nero.pose.bones["extra2"].albam_joint.number == -1,
          "so does typing the number")
    game_bone = nero.data.bones[by_joint(nero)[14]]
    nero.pose.bones["extra"].albam_joint.number = 14
    check(joints.joint_of(extra) == free and joints.joint_of(game_bone) == 14, "typing a game file bone's number is refused")
    numbered = dict(joints.ensure_joint_numbers(nero))
    check(numbered.get("extra2") not in (None, free), f"the replaced bone gets a free number on export ({numbered})")
    bpy.ops.object.mode_set(mode="EDIT")
    nero.data.edit_bones.remove(nero.data.edit_bones["extra2"])
    bpy.ops.object.mode_set(mode="POSE")

    class Stub:
        def __init__(self):
            self.lines = []
        def __getattr__(self, name):
            def call(*args, **kw):
                self.lines.append((name, args[0] if args else None, kw.get("text")))
                return self if name in ("row", "column", "box") else SimpleNamespace()
            return call
    layout = Stub()
    ctx = SimpleNamespace(object=nero, bone=nero.data.bones["extra"], edit_bone=None, mode="POSE")
    joints.ALBAM_PT_GameJoint.draw(SimpleNamespace(layout=layout), ctx)
    texts = [t for name, _, t in layout.lines if name == "label"]
    hint = joints.player_joint_hint(free)
    check(("operator", "albam.pick_joint_number", "") in layout.lines and
          (f"Player skeleton: {hint}" if hint else "Not a player skeleton joint") in texts,
          f"the Game Joint panel shows the picker and what the number is ({texts})")

    # Mark Selected: the selected new bones become Not a Game Joint, the game model's bones are skipped
    bpy.ops.object.mode_set(mode="EDIT")
    eb = nero.data.edit_bones.new("extra2")
    eb.head, eb.tail, eb.parent = (0, 0, 1.2), (0, 0, 1.3), nero.data.edit_bones["extra"]
    bpy.ops.object.mode_set(mode="POSE")
    picked = {"extra", "extra2", "thigh_r"}
    for b in nero.data.bones:
        pb = nero.pose.bones[b.name]
        if compat.POSE_BONE_SELECT:
            pb.select = b.name in picked
        else:
            b.select = b.name in picked
    with bpy.context.temp_override(object=nero, active_object=nero):
        marked = bpy.ops.albam.set_not_joint(value=True)
    helpers = {b.name for b in nero.data.bones if joints.is_helper(b)}
    check(marked == {"FINISHED"} and {"extra", "extra2"} <= helpers and "thigh_r" not in helpers,
          f"Mark Selected marks the new bones, not the game model's ({sorted(helpers)})")
    nero.pose.bones["thigh_r"].albam_joint.not_joint = True
    check(not joints.is_helper(nero.data.bones["thigh_r"]), "the checkbox refuses a game model bone")
    check(export(nero) == named_bytes, "the marked bones aren't exported")
    with bpy.context.temp_override(object=nero, active_object=nero):
        unmarked = bpy.ops.albam.set_not_joint(value=False)
    check(unmarked == {"FINISHED"} and not any(joints.is_helper(nero.data.bones[n]) for n in ("extra", "extra2")),
          "Unmark Selected makes them joints again")
except Exception:
    traceback.print_exc()
    failures.append("exception")

print("FAILURES:", failures)
