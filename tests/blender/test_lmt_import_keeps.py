"""LMT import leaves an armature that already plays an action alone (its action, pose, rotation modes and the scene's
frame rate); an armature without one plays the first imported animation at 60 fps, as before."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

common.register()
import bpy  # noqa: E402
from albam.engines.mtfw import animation, mesh  # noqa: E402
from albam.lib import blender_compat as compat  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


DANTE = os.path.join(common.ARCTOOL, "uPlayerDante-vanilla")
common.skip_unless(DANTE)
context = bpy.context
scene = context.scene
scene.albam.rfs.add_root_folder("dmc4", DANTE)
mesh.build_blender_model(scene.albam.rfs.get_vfile("dmc4", r"model\game\pl006\pl006.mod"), context)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
item = next(i for i in scene.albam.rfs.file_list if i.name.lower().endswith("pl006_01.lmt"))
scene.albam.import_options_lmt.armature = arm

# an armature with no action: the first animation plays, at 60 fps
scene.render.fps = 30
animation.load_lmt(item, context)
check(arm.animation_data.action is not None and arm.animation_data.action.name.endswith(".0000"), "no action: the first one plays")
check(scene.render.fps == 60, "and the scene goes to 60 fps")

# an armature playing the user's own (Euler, 30 fps) animation keeps it
scene.render.fps = 30
mine = bpy.data.actions.new("my_euler_anim")
bone = arm.data.bones[5].name
for p in arm.pose.bones:
    p.matrix_basis.identity()
arm.pose.bones[bone].rotation_mode = "XYZ"
for i in range(3):
    fc = compat.fcurve_new(mine, f'pose.bones["{bone}"].rotation_euler', i, bone, owner=arm)
    fc.keyframe_points.insert(0, 0.0)
    fc.keyframe_points.insert(30, 0.5)
compat.assign_action(arm, mine)
scene.frame_set(15)
pose_before = [p.matrix.copy() for p in arm.pose.bones]
groups_before = len(scene.albam.lmt_groups.anim_group)
animation.load_lmt(item, context)
check(arm.animation_data.action == mine, "an armature playing an action keeps it")
check(arm.pose.bones[bone].rotation_mode == "XYZ", "and its rotation modes")
check(scene.render.fps == 30, "and the scene keeps its frame rate")
scene.frame_set(15)
check(max(max(abs(a - b) for ra, rb in zip(m, p.matrix) for a, b in zip(ra, rb)) for m, p in zip(pose_before, arm.pose.bones)) < 1e-5,
      "and its pose")
check(len(scene.albam.lmt_groups.anim_group) == groups_before + 1 and len(scene.albam.lmt_groups.anim_group[-1].actions) > 0,
      "the LMT is still imported, as a new group")
lmt = scene.albam.lmt_groups.anim_group[-1]
lmt.active_id = 1
check(arm.animation_data.action == lmt.actions[1].action, "picking a row in the LMT list still plays it")
print("FAILURES:", failures)
sys.exit(1 if failures else 0)
