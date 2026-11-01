"""Nero's taunts for his Devil Trigger stand: a constraint rig that drives the stand body (pl020) and the Devil Bringer arm
model (wp024) from Nero's armature, Nero's bank-0 taunt animations baked through it and exported as LMTs with Nero's
block indices, for dmc4_hook's GuardianDevil (its taunt mimic plays the registry's word for Nero's motion id from the two
files). The saved .blend keeps the rig: load it, import another LMT onto Nero's armature, pick an action, and Pose >
Animation > Bake Action (visual keying) on the stand and the arm gives the retargeted actions; set their slots in the LMT
panel and export.

    "C:\\Program Files\\Blender Foundation\\Blender 4.2\\blender.exe" -b --factory-startup --python scripts/stand_taunt_retarget.py

or open it in Blender's Text Editor and Run Script (the add-on enabled or not). Use a new, empty file: the
script imports the models into the current scene.

Reads the extracted uPlayerNero arc through tests/common.py (ALBAM_DMC4_DATA) and writes motion\\pl020\\pl020_taunt.lmt,
motion\\wp024\\wp024_taunt.lmt and stand_taunt_retarget.blend under ALBAM_STAND_TAUNT_OUT (default
E:\\DMC mod stuffs\\guardian_taunt); copy the two LMTs under the game's nativePC.

The rig: every mapped stand bone has a Copy Rotation from its Nero counterpart in Local space (the rest-relative delta,
what the game's tracks mean on a differently built rig), the root and hips a Transformation constraint that also copies
the location scaled by the rigs' height ratio; the arm's elbow, wrist and fingers take Nero's right-arm rotations the same
way, and the arm's root a Copy Transforms (World) from the helper bone ARM_ATTACH on the stand, a child of the stand's
joint 6 (the right shoulder stub) whose rest transform is the offset the vanilla mimic blocks use. That offset is
measured, not guessed: the arm's joint 0 is a root (its track is a model-space transform, and the arm's model space is
the stand's, its sync copies the stand's position and rotation), so in a vanilla mimic pair (block k of pl020_04 on the
stand, block k of wp024_04 on the arm) at frame 1, stand_bone6.matrix^-1 @ arm_bone0.matrix is that offset: on the
joint (4 mm spread over 8 blocks), turned 90 degrees about the game's forward axis.

Joint numbering (game axes: +x is the character's left): Nero 0-4 root / hips / spine / neck / head, 5-8 right arm
(clavicle, shoulder, elbow, wrist) with fingers 100-115, 9-12 left arm with fingers 116-131, 13 leg root, 14-17 right leg,
18-21 left leg. Stand body: 0-4 the same, 5-6 the right clavicle / shoulder, 7-10 the left arm with fingers 100-108, 11
leg root, 12 / 13 the thighs. Arm model: 0 shoulder (at the model origin in its rest pose), 1 elbow, 2 wrist, fingers
3-5 / 6-8 / 9-11 / 12-15 / 16-18. Edit STAND_MAP / ARM_MAP / TAUNTS to change what follows what, or which blocks are made.
"""
import importlib.util, os, sys, traceback
import bpy


def _addon_folder():
    """The albam package folder: from this file when run with --python, else (Blender's Text Editor, where __file__ is
    only the text block's name) from the enabled add-on, else the usual install."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if os.path.isfile(__file__) else ""
    if here and os.path.isfile(os.path.join(here, "tests", "common.py")):
        return here
    loaded = sys.modules.get("albam")
    if loaded is not None and getattr(loaded, "__file__", None):
        return os.path.dirname(loaded.__file__)
    return r"E:\DMC mod stuffs\blender_addon\addons\albam"


# tests/common.py loaded by path under its own name: Blender (or another add-on) may already have a module called common
_spec = importlib.util.spec_from_file_location("albam_tests_common", os.path.join(_addon_folder(), "tests", "common.py"))
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)
if hasattr(bpy.types.Scene, "albam"):      # the add-on is already enabled in this Blender
    import albam
else:
    albam = common.register()
from mathutils import Matrix, Vector
from albam.engines.mtfw import animation, mesh, joints
from albam.lib import blender_compat as compat

OUT = os.environ.get("ALBAM_STAND_TAUNT_OUT", r"E:\DMC mod stuffs\guardian_taunt")
TAUNTS = [0x96, 0x97, 0x98, 0x99, 0x9A, 0x9B, 0x9C, 0x9D, 0x9E, 0xA5, 0xA6]   # uPlayerNero::setProvokeMtn's three tables
# stand joint <- Nero joint (rotation deltas; 0 / 1 also location, scaled)
STAND_MAP = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 9, 8: 10, 9: 11, 10: 12,
             100: 116, 101: 117, 102: 118, 103: 119, 104: 120, 105: 121, 106: 122, 107: 123, 108: 124,
             11: 13, 12: 14, 13: 18, 200: 200, 201: 204, 202: 205, 203: 206, 204: 207, 205: 208, 206: 209, 207: 212, 208: 213}
LOCATION_JOINTS = (0, 1)       # stand joints whose location follows too (scaled)
# arm joint <- Nero joint (rotation deltas); joint 0 follows the stand's ARM_ATTACH helper instead
ARM_MAP = {1: 7, 2: 8, 3: 100, 4: 101, 5: 102, 6: 103, 7: 104, 8: 105, 9: 106, 10: 107, 11: 108,
           12: 109, 13: 110, 14: 111, 15: 112, 16: 113, 17: 114, 18: 115}
ARM_SHOULDER_JOINT = 6         # the stand body joint the arm's root hangs from
ATTACH_BONE = "ARM_ATTACH"     # the helper bone on the stand (Not a Game Joint: never exported)
HEIGHT_SCALE = 172.3 / 138.9   # stand spine height / Nero's: the hips' location deltas
INCLUDE_ROOT_MOTION = True     # the stand walks with Nero's taunt (Albam's import makes Nero's hips follow his root_motion
                               # bone, and the constraints read that; False mutes it, so only the hips' own keys count)
STAND_MIMICS = "motion::pl020::pl020_04-stand moveset.lmt"      # the vanilla mimic files, as the extraction names them
ARM_MIMICS = "motion::wp024::wp024_04-stand arm moveset.lmt"
CON_PREFIX = "RETARGET_"

scene = bpy.context.scene
rfs = scene.albam.rfs
rfs.add_root_folder("dmc4", common.NERO)


def rfs_item(suffix):
    return next(i for i in rfs.file_list if i.name.lower().endswith(suffix.lower()))


def import_model(suffix):
    before = set(bpy.data.objects)
    mesh.build_blender_model(rfs_item(suffix), bpy.context)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE" and o not in before)
    if arm.name not in scene.collection.objects:
        scene.collection.objects.link(arm)
    return arm


def import_lmt(armature, suffix):
    scene.albam.import_options_lmt.armature = armature
    animation.load_lmt(rfs_item(suffix), bpy.context)
    return scene.albam.lmt_groups.anim_group[scene.albam.lmt_groups.active_group_id]


def joint_bones(armature):
    out = {}
    for b in armature.data.bones:
        j = b.get("mtfw.anim_retarget")
        if j is not None and not joints.is_helper(b):
            out[int(j)] = armature.pose.bones[b.name]
    return out


def by_slot(group):
    return {animation.get_lmt_props(r.action).lmt_id: r.action for r in group.actions if r.action}


def play(armature, action):
    compat.assign_action(armature, action)
    for pb in armature.pose.bones:
        pb.rotation_mode = "QUATERNION"


def reset_pose(armature):
    for pb in armature.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)


def copy_rotation(owner_pb, target_ob, target_pb):
    con = owner_pb.constraints.new("COPY_ROTATION")
    con.name = CON_PREFIX + "rotation"
    con.target = target_ob
    con.subtarget = target_pb.name
    con.target_space = "LOCAL"
    con.owner_space = "LOCAL"
    con.mix_mode = "REPLACE"
    return con


def scaled_location(owner_pb, target_ob, target_pb, scale):
    con = owner_pb.constraints.new("TRANSFORM")
    con.name = CON_PREFIX + "location"
    con.target = target_ob
    con.subtarget = target_pb.name
    con.target_space = "LOCAL"
    con.owner_space = "LOCAL"
    con.map_from = "LOCATION"
    con.map_to = "LOCATION"
    con.use_motion_extrapolate = True
    con.mix_mode = "REPLACE"
    for axis in "xyz":
        setattr(con, "from_min_" + axis, -1.0)
        setattr(con, "from_max_" + axis, 1.0)
        setattr(con, "to_min_" + axis, -scale)
        setattr(con, "to_max_" + axis, scale)
    return con


def add_attach_bone(armature, parent_pb, rest_offset):
    """A helper bone under `parent_pb` whose rest transform is parent_rest @ rest_offset (so in pose it sits at
    parent.matrix @ rest_offset); Not a Game Joint, so Albam never exports it."""
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    eb = armature.data.edit_bones.new(ATTACH_BONE)
    eb.parent = armature.data.edit_bones[parent_pb.name]
    eb.length = 0.05
    eb.matrix = armature.data.bones[parent_pb.name].matrix_local @ rest_offset
    bpy.ops.object.mode_set(mode="OBJECT")
    bone = armature.data.bones[ATTACH_BONE]
    bone[joints.NOT_JOINT_PROP] = True
    return armature.pose.bones[ATTACH_BONE]


def visual_bake(armature, action, frames):
    """Key the constrained result into `action` (what Bake Action with visual keying does), for the bones the rig
    drives only: rotation for every constrained bone, location where a location / attach constraint sets it. Bones the
    rig leaves alone get no track (the game keeps their rest pose), and helper bones aren't game joints."""
    compat.assign_action(armature, action)
    bones = armature.data.bones
    driven = {}
    for pb in armature.pose.bones:
        names = [c.name for c in pb.constraints if c.name.startswith(CON_PREFIX)]
        if names and not joints.is_helper(bones[pb.name]):
            driven[pb.name] = any(n.endswith(("location", "attach")) for n in names)
    for f in range(frames):
        scene.frame_set(f)
        bpy.context.view_layer.update()
        final = {pb.name: pb.matrix.copy() for pb in armature.pose.bones}
        for pb in armature.pose.bones:
            if pb.name not in driven:
                continue
            rest = bones[pb.name].matrix_local
            if pb.parent:
                base = final[pb.parent.name] @ bones[pb.parent.name].matrix_local.inverted() @ rest
            else:
                base = rest
            pb.matrix_basis = base.inverted() @ final[pb.name]
            pb.keyframe_insert("rotation_quaternion", frame=f)
            if driven[pb.name]:
                pb.keyframe_insert("location", frame=f)


try:
    print("Blender", bpy.app.version_string)
    nero = import_model("model::game::pl000::pl000.mod")
    stand = import_model("model::game::pl020::pl020.mod")
    arm = import_model("model::game::wp024::wp024.mod")
    for ob in (nero, stand, arm):
        ob.matrix_world = Matrix.Identity(4)
    NB, SB, AB = joint_bones(nero), joint_bones(stand), joint_bones(arm)
    print("bones: nero", len(NB), "stand", len(SB), "arm", len(AB))
    missing = [j for j in STAND_MAP if j not in SB] + [j for j in STAND_MAP.values() if j not in NB]
    missing += [j for j in ARM_MAP if j not in AB] + [j for j in ARM_MAP.values() if j not in NB]
    assert not missing, f"joints missing on a rig: {missing}"

    # -- the arm root's offset from the stand's shoulder, read from the vanilla mimic pairs -----------------------
    stand_mimics = by_slot(import_lmt(stand, STAND_MIMICS))
    arm_mimics = by_slot(import_lmt(arm, ARM_MIMICS))
    common_slots = sorted(set(stand_mimics) & set(arm_mimics))
    assert common_slots, "no mimic block in both files"
    offsets = []
    for slot in common_slots[:8]:
        play(stand, stand_mimics[slot]); play(arm, arm_mimics[slot])
        scene.frame_set(1)
        bpy.context.view_layer.update()
        offsets.append(SB[ARM_SHOULDER_JOINT].matrix.inverted() @ AB[0].matrix)
    loc = sum((m.to_translation() for m in offsets), Vector()) / len(offsets)
    quat = offsets[0].to_quaternion()
    for m in offsets[1:]:
        quat = quat.slerp(m.to_quaternion(), 0.5)
    OFFSET = Matrix.Translation(loc) @ quat.to_matrix().to_4x4()
    spread = max((m.to_translation() - loc).length for m in offsets)
    rot_spread = max(m.to_quaternion().rotation_difference(quat).angle for m in offsets)
    print(f"arm root offset from stand joint {ARM_SHOULDER_JOINT}: translation {tuple(round(v, 3) for v in loc)} m, "
          f"rotation {tuple(round(v, 3) for v in quat)}, spread over {len(offsets)} mimics {spread:.3f} m / {rot_spread:.4f} rad")
    compat.assign_action(stand, None); compat.assign_action(arm, None)
    reset_pose(stand); reset_pose(arm)

    # -- the constraint rig ------------------------------------------------------------------------------------------
    attach = add_attach_bone(stand, SB[ARM_SHOULDER_JOINT], OFFSET)
    SB, AB = joint_bones(stand), joint_bones(arm)          # pose bones are rebuilt by the mode switch
    for sj, nj in STAND_MAP.items():
        copy_rotation(SB[sj], nero, NB[nj])
        if sj in LOCATION_JOINTS:
            scaled_location(SB[sj], nero, NB[nj], HEIGHT_SCALE)
    for aj, nj in ARM_MAP.items():
        copy_rotation(AB[aj], nero, NB[nj])
    root = AB[0].constraints.new("COPY_TRANSFORMS")
    root.name = CON_PREFIX + "attach"
    root.target = stand
    root.subtarget = ATTACH_BONE
    root.target_space = "WORLD"
    root.owner_space = "WORLD"
    for pb in list(stand.pose.bones) + list(arm.pose.bones):
        pb.rotation_mode = "QUATERNION"
    print("constraints:", sum(len(pb.constraints) for pb in stand.pose.bones), "on the stand,",
          sum(len(pb.constraints) for pb in arm.pose.bones), "on the arm")

    # -- Nero's taunts through the rig -----------------------------------------------------------------------------
    nero_lmt = import_lmt(nero, "motion::pl000::pl000_01.lmt")
    nero_actions = by_slot(nero_lmt)
    if not INCLUDE_ROOT_MOTION:
        for pb in nero.pose.bones:
            for con in pb.constraints:
                if getattr(con, "subtarget", "") == animation.ROOT_MOTION_BONE_NAME:
                    con.mute = True
    groups = scene.albam.lmt_groups
    stand_group = groups.add("pl020_taunt.lmt"); stand_group.armature = stand; stand_group.num_slots = nero_lmt.num_slots
    arm_group = groups.add("wp024_taunt.lmt"); arm_group.armature = arm; arm_group.num_slots = nero_lmt.num_slots
    for slot in TAUNTS:
        src = nero_actions.get(slot)
        if src is None:
            print(f"slot {slot:#x}: no animation in pl000_01"); continue
        sp = animation.get_lmt_props(src)
        frames = sp.num_frames
        play(nero, src)
        s_act = bpy.data.actions.new(f"stand_taunt_{slot:02X}")
        a_act = bpy.data.actions.new(f"arm_taunt_{slot:02X}")
        visual_bake(stand, s_act, frames)
        visual_bake(arm, a_act, frames)
        for act in (s_act, a_act):
            p = animation.get_lmt_props(act)
            p.lmt_id = slot; p.num_frames = frames; p.loop_frames = sp.loop_frames; p.source_fps = 60.0
        stand_group.add(s_act); arm_group.add(a_act)
        print(f"slot {slot:#x}: {frames} frames baked")

    for group, rel in ((stand_group, r"motion\pl020\pl020_taunt.lmt"), (arm_group, r"motion\wp024\wp024_taunt.lmt")):
        notes = []
        data = animation.export_lmt(group, notes)
        path = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(bytes(data))
        print(f"wrote {path} ({len(data)} bytes); notes: {notes[:8]}")
    blend = os.path.join(OUT, "stand_taunt_retarget.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, copy=True)   # copy: an open Blender keeps its own file
    print(f"saved {blend} (the constraint rig is in it)")
    print("DONE")
except Exception:
    traceback.print_exc()
    if not bpy.app.background:
        raise                              # the Text Editor shows the error; exiting would close Blender
    sys.exit(1)
