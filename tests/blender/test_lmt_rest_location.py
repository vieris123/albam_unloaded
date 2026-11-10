"""LMT export leaves out location tracks that never move: the rest offsets Blender's I key keys along with rotation, or
another skeleton's proportions a retarget baked in (Gerb / Wall Run). Such a track replaces the joint's offset, so a
model with other proportions took the animated rig's bone lengths (Nero rig animations on Ellen, own size: arms and
legs bent out and stretched). The root, the joints the game's LMTs move and locations that do move keep theirs."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

common.register()
import bpy  # noqa: E402
from albam.engines.mtfw import animation, joints  # noqa: E402
from albam.lib import blender_compat as compat  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


context = bpy.context
arm = bpy.data.objects.new("rig", bpy.data.armatures.new("rig"))
context.scene.collection.objects.link(arm)
context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
bones = (("root", 0, None), ("spine", 1, "root"), ("upperarm", 6, "spine"), ("forearm", 7, "upperarm"),
         ("prop_r", 150, "forearm"))
for i, (name, _, parent) in enumerate(bones):
    eb = arm.data.edit_bones.new(name)
    eb.head, eb.tail = (0, 0, i * 0.2), (0, 0, i * 0.2 + 0.1)
    if parent:
        eb.parent = arm.data.edit_bones[parent]
bpy.ops.object.mode_set(mode="OBJECT")
for name, joint, _ in bones:
    arm.data.bones[name][joints.JOINT_PROP] = str(joint)

action = bpy.data.actions.new("keyed_with_i")
for name, *_ in bones:
    for i in range(4):
        fc = compat.fcurve_new(action, f'pose.bones["{name}"].rotation_quaternion', i, name, owner=arm)
        for f in (0, 10):
            fc.keyframe_points.insert(f, 1.0 if i == 0 else 0.0)
    for i in range(3):
        fc = compat.fcurve_new(action, f'pose.bones["{name}"].location', i, name, owner=arm)
        for f in (0, 10):
            moving = 0.05 if name == "forearm" and i == 1 and f == 10 else 0.0
            fc.keyframe_points.insert(f, 0.03 if name == "upperarm" and i == 1 else moving)   # upperarm: longer, still

# as LMT import leaves them: linear keys whose handles were never set (at 0, off the curve)
for i in range(3):
    fc = compat.fcurve_find(action, 'pose.bones["upperarm"].location', i, arm)
    for k in fc.keyframe_points:
        k.interpolation = "LINEAR"
        k.handle_left_type = k.handle_right_type = "FREE"
        k.handle_left, k.handle_right = (k.co[0] - 1, 0.0), (k.co[0] + 1, 0.0)

# and a looping import's Cycles modifier repeats a still curve: still
for i in range(3):
    compat.fcurve_find(action, 'pose.bones["spine"].location', i, arm).modifiers.new("CYCLES")

notes = []
tracks = animation._get_export_tracks(action, arm, notes)
located = {name for name, prop, _ in tracks if prop == "location"}
rotated = {name for name, prop, _ in tracks if prop in animation.ROTATION_PROPS}
check(rotated == {name for name, *_ in bones}, "every rotation track stays")
check("spine" not in located and "upperarm" not in located, f"locations at rest or held at another length are left out ({sorted(located)})")
check("root" in located, "the root keeps its location (its position)")
check("prop_r" in located, "a joint the game's LMTs move keeps it (a missing track would hold the last motion's)")
check("forearm" in located, "a location that moves is kept")
check(any("2 bones" in n and "never moves" in n for n in notes), f"the export says so ({notes})")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
