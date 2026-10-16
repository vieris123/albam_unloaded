"""Actions through lib/blender_compat on this Blender (4.2's flat F-curve lists or 5's slotted actions): LMT import
builds curves the armature plays, LMT export reads them back, the foot IK ghost plays the same action, and an SDL's
keyed tracks import, export byte-identical and follow an edit."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.engines.mtfw import animation, mesh, scheduler
from albam.blender_ui import foot_ik
from albam.lib import blender_compat as compat

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def item(root, rel):
    path = os.path.join(root, rel)
    data = open(path, "rb").read()
    return SimpleNamespace(app_id="dmc4", display_name=os.path.basename(path), relative_path=rel, absolute_path=path,
                           get_bytes=lambda d=data: d, extension=rel.rsplit(".", 1)[1]), data


LMT = r"motion\pl000\pl000_01.lmt"
SDL = r"scr\st405\data\blade01.sdl"
ST405 = os.path.join(common.ARCTOOL, "st405")
common.skip_unless(os.path.join(common.NERO, LMT))
common.skip_unless(os.path.join(ST405, SDL))

try:
    print("Blender", bpy.app.version_string, "legacy actions:", compat.LEGACY_ACTIONS)
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", common.NERO)
    model = next(i for i in scene.albam.rfs.file_list if i.name.lower().endswith("model::game::pl000::pl000.mod"))
    mesh.build_blender_model(model, bpy.context)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    if arm.name not in scene.collection.objects:
        scene.collection.objects.link(arm)

    # the user's own animation, playing when the LMT is imported: Euler rotations (as retargeted animations have),
    # a scale left on a bone the LMT doesn't scale
    own = compat.ensure_action(arm, "MyAnim")
    euler_bone = arm.pose.bones[3]
    euler_bone.rotation_mode = "XYZ"
    euler_bone.rotation_euler = (0.3, 0.2, 0.1)
    euler_bone.keyframe_insert("rotation_euler", frame=0)
    arm.pose.bones[1].keyframe_insert("location", frame=0)
    arm.pose.bones[1].scale = (1.5, 1.5, 1.5)
    arm.pose.bones[1].keyframe_insert("scale", frame=0)
    scene.frame_set(0)
    # a renamed bone: tracks go by joint number, whatever the bone is called (import used to write
    # pose.bones["<index>"])
    renamed = arm.data.bones[5]
    renamed.name = "renamed_spine"

    # -- LMT import: curves on every animation ------------------------------------------------------------
    scene.albam.import_options_lmt.armature = arm
    lmt_item, lmt_bytes = item(common.NERO, LMT)
    animation.load_lmt(lmt_item, bpy.context)
    lmt = scene.albam.lmt_groups.anim_group[scene.albam.lmt_groups.active_group_id]
    actions = [row.action for row in lmt.actions if row.action is not None]
    check(len(actions) > 1, f"{len(actions)} animations imported from {LMT}")
    check(arm.animation_data.action != own and own.use_fake_user and own.users >= 1,
          "the action the armature played before the import keeps a user (it would be dropped on save)")
    if not compat.LEGACY_ACTIONS:
        # slots named after the armature: picking the action in Blender's own Action editor finds its slot
        check(all(s.identifier == f"OB{arm.name}" for a in actions for s in a.slots),
              "imported actions' slots are named after the armature")
        arm.animation_data.action = actions[1]
        check(arm.animation_data.action_slot is not None, "a plain action assignment finds the slot")
    animated = {fc.data_path.split('"')[1] for fc in compat.action_fcurves(actions[0])}
    check("renamed_spine" in animated and "5" not in animated, "a renamed bone gets its tracks")
    check(euler_bone.rotation_mode == "QUATERNION", "a bone in Euler mode switches to quaternions for the LMT")
    check(tuple(arm.pose.bones[1].scale) == (1.0, 1.0, 1.0) or any(
        fc.data_path == f'pose.bones["{arm.pose.bones[1].name}"].scale' for fc in compat.action_fcurves(actions[0])),
        "channels the LMT doesn't key start from rest, not from the previous animation")
    # back to the user's animation the plain way (Action editor): the handler restores its rotation mode
    arm.animation_data.action = own
    bpy.context.view_layer.update()
    animation._follow_timer()       # timers don't run headless; the depsgraph handler queued it
    check(euler_bone.rotation_mode in animation.EULER_ORDERS, "switching back in Blender's UI restores Euler mode")
    scene.frame_set(0)
    check(abs(euler_bone.rotation_euler.x - 0.3) < 1e-6, "the user's animation plays its Euler keys again")
    empty = [a.name for a in actions if not compat.action_has_curves(a)]
    check(not empty, f"every animation has F-curves (without: {empty[:5]})")
    first = actions[0]
    curves = compat.action_fcurves(first)
    check(all(fc.data_path.startswith('pose.bones["') for fc in curves), "curves address pose bones")
    check(all(fc.group is not None for fc in curves), "curves are in channel groups")

    # -- selecting an animation plays it on the armature --------------------------------------------------
    lmt.active_id = 0
    ad = arm.animation_data
    check(ad is not None and ad.action == first, "selecting an animation assigns it to the armature")
    if not compat.LEGACY_ACTIONS:
        check(ad.action_slot is not None, "the armature plays a slot of the action")
    scene.frame_set(0)
    rest = {pb.name: pb.matrix_basis.copy() for pb in arm.pose.bones}
    moved = False
    for frame in range(1, 40):
        scene.frame_set(frame)
        if any((pb.matrix_basis - rest[pb.name]).to_translation().length > 1e-6
               or abs((pb.matrix_basis - rest[pb.name]).to_3x3().determinant()) > 1e-9
               or (pb.matrix_basis.to_quaternion() - rest[pb.name].to_quaternion()).magnitude > 1e-5
               for pb in arm.pose.bones):
            moved = True
            break
    check(moved, "the armature moves while the animation plays")
    # joint 0's location track is its position in model space, not an offset from the rest head (the whole body
    # used to stand bone 0's rest height too high)
    scene.frame_set(0)
    lowest = min(pb.head.z for pb in arm.pose.bones if pb.name != animation.ROOT_MOTION_BONE_NAME)
    rest_height = arm.data.bones["0"].head_local.z
    print(f"lowest bone at frame 0: {lowest:.3f} m (bone 0 rest height {rest_height:.3f})")
    check(-0.1 < lowest < 0.3, f"the feet are near the floor ({lowest:.3f} m)")

    # -- LMT export reads the curves back ----------------------------------------------------------------
    notes = []
    out = animation.export_lmt(lmt, notes)
    check(out[:8] == lmt_bytes[:8], "re-export keeps the header")
    src_lmt, out_lmt = animation.Lmt(animation.KaitaiStream(animation.io.BytesIO(lmt_bytes))), \
        animation.Lmt(animation.KaitaiStream(animation.io.BytesIO(bytes(out))))
    src_lmt._read()
    out_lmt._read()
    shape = lambda lmt_: [b.block_header.num_frames if b.offset else None for b in lmt_.block_offsets]  # noqa: E731
    check(shape(out_lmt) == shape(src_lmt), "re-export has the source's blocks and frame counts")
    # every source track comes back: tracks of joints pl000.mod doesn't have (155-165, Nero's other models) are kept
    # as they are and written back
    track_ids = lambda lmt_: [sorted((t.bone_index, t.usage) for t in b.block_header.tracks)  # noqa: E731
                              for b in lmt_.block_offsets if b.offset]
    check(track_ids(out_lmt) == track_ids(src_lmt), "re-export has every track of the source")
    joints = {int(b_['mtfw.anim_retarget']) for b_ in arm.data.bones if 'mtfw.anim_retarget' in b_} | {255}
    kept_same = [bytes(o.data) == bytes(s.data) for sb, ob in zip(src_lmt.block_offsets, out_lmt.block_offsets)
                 if sb.offset for s in sb.block_header.tracks if s.bone_index not in joints
                 for o in ob.block_header.tracks if (o.bone_index, o.usage) == (s.bone_index, s.usage)]
    check(kept_same and all(kept_same), f"kept tracks are written back byte-identical ({len(kept_same)})")
    # joint 0's location: one-key tracks used to be written with y / z swapped
    root_loc = [(s, o) for sb, ob in zip(src_lmt.block_offsets, out_lmt.block_offsets) if sb.offset
                for s in sb.block_header.tracks if (s.bone_index, s.usage) == (0, 1)
                for o in ob.block_header.tracks if (o.bone_index, o.usage) == (0, 1)]
    worst = max(max(abs(a - b) for a, b in zip(animation.decode_type_2(s.data)[0], animation.decode_type_2(o.data)[0]))
                for s, o in root_loc if s.buffer_type == o.buffer_type == 2)
    check(worst < 1e-5, f"joint 0's constant location round-trips ({worst:.2e} m)")
    # ref_data = the loop-start sample (the track's value at the loop frame) in looping animations, which the game
    # interpolates toward when it wraps: it used to be the first key, so a run whose loop frame isn't 0 snapped
    # back every loop. Rotations within compression precision, vectors within 0.1 cm (constant location tracks
    # store a stale ref the game doesn't read)
    bad_ref = []
    for bi, (sb, ob) in enumerate(zip(src_lmt.block_offsets, out_lmt.block_offsets)):
        if not sb.offset:
            continue
        exported = {(t.bone_index, t.usage): t for t in ob.block_header.tracks}
        for s in sb.block_header.tracks:
            o = exported.get((s.bone_index, s.usage))
            if o is None or s.buffer_type == 2:
                continue
            a = [getattr(s.ref_data, c) for c in "xyz"]
            b = [getattr(o.ref_data, c) for c in "xyz"]
            d = max(abs(p - q) for p, q in zip(a, b))
            if s.buffer_type in (4, 6):
                d = min(d, max(abs(p + q) for p, q in zip(a, b)))
            if d > (0.01 if s.buffer_type in (4, 6) else 0.1):
                bad_ref.append((bi, s.bone_index, s.usage, round(d, 3)))
    check(not bad_ref, f"every track's ref_data matches the source ({len(bad_ref)} off: {bad_ref[:4]})")
    # every (bone, property) with curves becomes a track, and the tracks import kept are written back
    tracks = animation._get_export_tracks(first, arm, [])
    written = len(out_lmt.block_offsets[0].block_header.tracks)
    kept = len(animation.get_kept_tracks(first))
    check(written == len(tracks) + kept and len(tracks) > 80, f"block 0 exports one track per animated bone "
          f"property plus the kept ones ({written} = {len(tracks)} + {kept}; source "
          f"{len(src_lmt.block_offsets[0].block_header.tracks)})")
    check(animation.game_length(first) > 0, f"game_length reads the curves ({animation.game_length(first)})")

    # -- foot IK ghost plays the same action --------------------------------------------------------------
    ground = bpy.data.objects.new("ground", bpy.data.meshes.new("ground"))
    ground.data.from_pydata([(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0)], [], [(0, 1, 2, 3)])
    scene.collection.objects.link(ground)
    errors = foot_ik.build_rig(arm, ground)
    ghost = next((o for o in bpy.data.objects if o.name == f"{arm.name}.fk_ghost"), None)
    check(ghost is not None, "foot IK builds the ghost")
    if ghost is not None:
        check(ghost.animation_data is not None and ghost.animation_data.action == arm.animation_data.action,
              "the ghost plays the armature's action")
        if not compat.LEGACY_ACTIONS:
            check(ghost.animation_data.action_slot is not None, "the ghost plays a slot of it")
    check(arm.animation_data.action == first, "the armature keeps its action after the rig build")
    foot_ik.remove_rig(arm)
    check(not any(o.name == f"{arm.name}.fk_ghost" for o in bpy.data.objects), "remove_rig removes the ghost")

    # -- SDL: keyed tracks round-trip and follow an edit --------------------------------------------------
    sdl_item, sdl_bytes = item(ST405, SDL)
    scene.albam.rfs.add_root_folder("dmc4", ST405)
    scheduler.load_sdl(sdl_item, bpy.context)
    root = next(o for o in bpy.data.objects if o.name.startswith("SDL_"))
    keyed = [o for o in bpy.data.objects if o.name != root.name and o.animation_data is not None
             and o.animation_data.action is not None and compat.action_has_curves(o.animation_data.action)]
    check(keyed, f"{len(keyed)} track Empties carry keyed properties")
    if not compat.LEGACY_ACTIONS:
        check(all(o.animation_data.action_slot is not None for o in keyed), "each keyed Empty plays its slot")
    files = scheduler.export_sdl(root)
    check(files[0].data_bytes == sdl_bytes, f"{os.path.basename(SDL)} exports byte-identical")
    ob = keyed[0]
    fc = compat.fcurves_of(ob.animation_data.action, ob)[0]
    fc.keyframe_points[0].co.y += 1.0
    fc.update()
    edited = scheduler.export_sdl(root)[0].data_bytes
    check(edited != sdl_bytes and len(edited) == len(sdl_bytes), "an edited key changes the export (same size)")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
