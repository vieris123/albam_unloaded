"""Add Existing Animation (anim_tools.ALBAM_OT_LmtAddExistingAnim): only actions on the LMT's armature are offered, the
dialog says what an action gives (joints, bones it lacks, object motion), and the frame rate, looping and slot are set;
an action from an LMT brings its own settings. Add Animation makes a new action."""
import io
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

common.register()
import bpy  # noqa: E402
from albam.blender_ui import anim_tools  # noqa: E402
from albam.engines.mtfw import animation, joints  # noqa: E402
from albam.lib import blender_compat as compat  # noqa: E402
from mathutils import Vector  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


context = bpy.context
scene = context.scene
scene.render.fps = 30
arm = bpy.data.objects.new("rig", bpy.data.armatures.new("rig"))
scene.collection.objects.link(arm)
context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
for i, name in enumerate(("hips", "spine", "head", "helper")):
    eb = arm.data.edit_bones.new(name)
    eb.head, eb.tail = (0, 0, i * 0.2), (0, 0, i * 0.2 + 0.1)
bpy.ops.object.mode_set(mode="OBJECT")
for i, name in enumerate(("hips", "spine", "head")):
    arm.data.bones[name][joints.JOINT_PROP] = str(i)


def action(name, bones, frames, object_motion=False):
    a = bpy.data.actions.new(name)
    for b in bones:
        for i in range(4):
            fc = compat.fcurve_new(a, f'pose.bones["{b}"].rotation_quaternion', i, b, owner=arm)
            for f in frames:
                fc.keyframe_points.insert(f, 1.0 if i == 0 else 0.0)
    if object_motion:
        fc = compat.fcurve_new(a, "location", 0, owner=arm)
        for f in frames:
            fc.keyframe_points.insert(f, f * 0.01)
    return a


walk = action("walk", ("hips", "spine"), (0, 30))
other = action("other_rig", ("bone001", "bone002"), (0, 10))
mixed = action("mixed", ("head", "missing_bone", "helper"), (0, 15), object_motion=True)
groups = scene.albam.lmt_groups
lmt = groups.add("test.lmt")
lmt.armature = arm
groups.active_group_id = 0

names = anim_tools.compatible_actions(lmt)
check(names == ["mixed", "walk"], f"only actions on the armature's joints are offered ({names})")
summary = anim_tools.action_summary(mixed, arm)
check(any("doesn't have" in line and line.startswith("!") for line in summary), "bones the armature lacks are flagged")
check(any("armature object" in line for line in summary), "object motion is flagged")
check(any("1 joints animated" in line for line in summary), f"joints are counted ({summary[0]})")

result = bpy.ops.albam.add_existing_anim("EXEC_DEFAULT", action="walk", source_fps=30.0, loops=True, loop_start=20, slot=3)
props = animation.get_lmt_props(walk)
check(result == {"FINISHED"} and props.lmt_id == 3 and lmt.num_slots == 4, "it goes in the chosen slot")
check(abs(props.source_fps - 30.0) < 1e-6 and props.num_frames == 61,
      f"30 fps, keys 0-30 -> keys on game frames 0-60, 61 frames as the game counts them ({props.num_frames})")
check(props.loop_frames == 20, "looping from the chosen frame")
check(walk.use_fake_user and lmt.actions[lmt.active_id].action == walk, "kept, and selected")
check("walk" not in anim_tools.compatible_actions(lmt), "an action in the LMT isn't offered again")

# an action set up by an LMT brings its own settings into the dialog
mprops = animation.get_lmt_props(mixed)
mprops.num_frames, mprops.source_fps, mprops.loop_frames = 40, 60.0, 5
op = SimpleNamespace(action="mixed", source_fps=30.0, loops=False, loop_start=0)
anim_tools._on_existing_action(op, context)
check(op.source_fps == 60.0 and op.loops and op.loop_start == 5, "an LMT action brings its frame rate and loop")
result = bpy.ops.albam.add_existing_anim("EXEC_DEFAULT", action="mixed", source_fps=60.0, loops=False, slot=3)
check(result == {"FINISHED"} and mprops.loop_frames == -1 and mprops.lmt_id == 3, "a taken slot is allowed (and flagged)")
check(lmt.slot_counts().get(3) == 2, "the panel sees the clash")


class Stub:
    def __init__(self):
        self.labels = []

    def __getattr__(self, name):
        if name == "label":
            return lambda text="", icon="NONE", **kw: self.labels.append((text, icon))
        return lambda *a, **kw: Stub() if name in ("row", "column") else None


stub = Stub()
draw_op = SimpleNamespace(layout=stub, action="mixed", source_fps=60.0, loops=False, loop_start=0, slot=3)
anim_tools.ALBAM_OT_LmtAddExistingAnim.draw(draw_op, context)
check(any("taken by" in t for t, _ in stub.labels), "the dialog flags the taken slot")
check(any(icon == "ERROR" and "armature object" in t for t, icon in stub.labels), "and the object motion")

result = bpy.ops.albam.add_anim("EXEC_DEFAULT", name="fresh", slot=5)
fresh = bpy.data.actions.get("fresh")
check(result == {"FINISHED"} and fresh is not None and animation.get_lmt_props(fresh).lmt_id == 5, "Add Animation makes a new one")

# root motion: the hips travel 1 m and rise 20 cm; the travel goes to root_motion, the height stays
travel = bpy.data.actions.new("travel")
hips_rest = arm.data.bones["hips"].matrix_local.to_3x3()
end = hips_rest.inverted() @ Vector((0.3, -1.0, 0.2))       # in the hips' own location space
for i in range(3):
    fc = compat.fcurve_new(travel, 'pose.bones["hips"].location', i, "hips", owner=arm)
    for f, v in ((0, 0.0), (30, end[i])):
        fc.keyframe_points.insert(f, v).interpolation = "LINEAR"
check(abs(animation.hips_travel(arm, travel) - Vector((0.3, -1.0)).length) < 1e-4, "the dialog's travel estimate")
op = SimpleNamespace(action="travel", source_fps=30.0, loops=False, loop_start=0, root_motion=False)
anim_tools._on_existing_action(op, context)
check(op.root_motion, "root motion is offered for hips that travel")


def hips_world(frames):
    compat.assign_action(arm, travel)
    out = []
    for f in frames:
        scene.frame_set(f)
        out.append(arm.pose.bones["hips"].matrix.translation.copy())
    return out


before = hips_world((0, 15, 30))
result = bpy.ops.albam.add_existing_anim("EXEC_DEFAULT", action="travel", source_fps=30.0, slot=6, root_motion=True)
check(result == {"FINISHED"} and "root_motion" in arm.data.bones, "root motion is split off on add")
after = hips_world((0, 15, 30))
check(max((a - b).length for a, b in zip(before, after)) < 1e-5, "the preview looks the same")
scene.frame_set(30)
root = arm.pose.bones["root_motion"].head
check((root.xy - Vector((0.3, -1.0))).length < 1e-5 and abs(root.z) < 1e-6, f"root_motion carries the travel ({tuple(root)})")
check(arm.location.length > 1e-4, "(the armature object stands off the origin, left there by the 'mixed' action)")
own = Vector(fc.evaluate(30) for fc in (compat.fcurve_find(travel, 'pose.bones["hips"].location', i, arm) for i in range(3)))
check(((hips_rest @ own) - Vector((0.0, 0.0, 0.2))).length < 1e-5, "the hips keep only their height")
try:
    animation.extract_root_motion(context, arm, travel)
    again = "done twice"
except Exception as err:  # noqa: BLE001
    again = getattr(err, "message", str(err))
check("already has root motion" in again, f"a second split is refused ({again[:60]})")
while len(lmt.actions) > 2:     # keep walk and travel (no clashing slots, no missing bones) for the export
    i = next(k for k, item in enumerate(lmt.actions) if item.action not in (travel, walk))
    lmt.actions.remove(i)
data = animation.export_lmt(lmt)
parsed = animation.Lmt(animation.KaitaiStream(io.BytesIO(data)))
parsed._read()
block = parsed.block_offsets[6].block_header
tracks = {(t.bone_index, t.usage) for t in block.tracks}
check((255, 4) in tracks and (0, 1) in tracks, f"the LMT has root motion (joint 255, usage 4) and the hips' height ({sorted(tracks)})")
# the root-motion end, as the game's files have it (Albam wrote a zero rotation until 2026-11-03: she zipped around)
end_q = (block.end_quat.x, block.end_quat.y, block.end_quat.z, block.end_quat.w)
end_p = Vector((block.end_pos.x, block.end_pos.y, block.end_pos.z))
want = arm.data.bones["root_motion"].matrix_local.to_3x3().inverted() @ Vector((0.3, -1.0, 0.0)) * 100
check(end_q == (0.0, 0.0, 0.0, 1.0), f"end rotation is the identity ({end_q})")
check((end_p - want).length < 0.5, f"end position is the root motion at the last frame ({tuple(end_p)} vs {tuple(want)})")
tprops = animation.get_lmt_props(travel)
tprops.loop_frames = 30          # loops from game frame 30 of 60: one loop travels half of it
data = animation.export_lmt(lmt)
parsed = animation.Lmt(animation.KaitaiStream(io.BytesIO(data)))
parsed._read()
b = parsed.block_offsets[6].block_header
loop_p = Vector((b.end_pos.x, b.end_pos.y, b.end_pos.z))
check(abs(loop_p.length - want.length * (30 + 1) / 60) < 0.1, f"a later loop frame gives one loop's travel ({loop_p.length:.1f} cm)")
tprops.end_quat = (0.0, 0.0, 0.0, 1.0)
tprops.end_pos = (1.0, 2.0, 3.0)
data = animation.export_lmt(lmt)
parsed = animation.Lmt(animation.KaitaiStream(io.BytesIO(data)))
parsed._read()
b = parsed.block_offsets[6].block_header
check((b.end_pos.x, b.end_pos.y, b.end_pos.z) == (1.0, 2.0, 3.0), "values set by hand are kept")
# a set End Rotation with a zero End Position (an action copied from an imported one): a motion that doesn't loop gets
# its travel (the game snaps the character back otherwise), a looping one keeps the zero (39 DX9 loops have it)
tprops.end_pos = (0.0, 0.0, 0.0)
data = animation.export_lmt(lmt)
parsed = animation.Lmt(animation.KaitaiStream(io.BytesIO(data)))
parsed._read()
b = parsed.block_offsets[6].block_header
check((b.end_pos.x, b.end_pos.y, b.end_pos.z) == (0.0, 0.0, 0.0), "a looping motion keeps a zero end position")
tprops.loop_frames = -1
data = animation.export_lmt(lmt)
parsed = animation.Lmt(animation.KaitaiStream(io.BytesIO(data)))
parsed._read()
b = parsed.block_offsets[6].block_header
zero_p = Vector((b.end_pos.x, b.end_pos.y, b.end_pos.z))
check((zero_p - want).length < 0.5, f"a zero end position on a motion that doesn't loop gets its travel ({tuple(zero_p)})")

# the game interpolates keys linearly: an eased curve (Bezier, Blender's default for keys set by hand) gets a key on
# every game frame between its keys, a straight one keeps its two (a hand-keyed root motion ran at full speed and
# stopped dead in the game)
shapes = bpy.data.actions.new("shapes")
animation.get_lmt_props(shapes).source_fps = 60.0
curves = {}
for name, interpolation in (("eased", "BEZIER"), ("straight", "LINEAR")):
    fc = compat.fcurve_new(shapes, f'pose.bones["{name}"].location', 0, name, owner=arm)
    for f, v in ((0, 0.0), (30, 1.0)):
        fc.keyframe_points.insert(f, v).interpolation = interpolation
    curves[name] = fc
timing = animation.ExportTiming(shapes)
eased_keys = animation._track_keys({0: curves["eased"]}, (0.0,), timing)
check([f for f, _ in eased_keys] == [float(f) for f in range(31)], f"an eased curve gets every frame ({len(eased_keys)} keys)")
check(max(abs(v[0] - curves["eased"].evaluate(f)) for f, v in eased_keys) < 1e-6, "on the curve")
straight_keys = animation._track_keys({0: curves["straight"]}, (0.0,), timing)
check([f for f, _ in straight_keys] == [0.0, 30.0], f"a straight one keeps its keys ({[f for f, _ in straight_keys]})")
quats = {}
for i, (a, b) in enumerate(zip((1.0, 0.0, 0.0, 0.0), (0.7071, 0.7071, 0.0, 0.0))):
    fc = compat.fcurve_new(shapes, 'pose.bones["eased"].rotation_quaternion', i, "eased", owner=arm)
    fc.keyframe_points.insert(0, a)
    fc.keyframe_points.insert(30, b)
    quats[i] = fc
rot = dict(animation._quaternion_keys(quats, timing))
shown = Vector([quats[i].evaluate(5) for i in range(4)]).normalized()
check(len(rot) == 31 and (Vector(rot[5.0]) - shown).length < 1e-5,
      "an eased rotation follows Blender's curve between its keys (not a linear slerp)")
print("FAILURES:", failures)
sys.exit(1 if failures else 0)
