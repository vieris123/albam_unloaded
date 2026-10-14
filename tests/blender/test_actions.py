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

    # -- LMT import: curves on every animation ------------------------------------------------------------
    scene.albam.import_options_lmt.armature = arm
    lmt_item, lmt_bytes = item(common.NERO, LMT)
    animation.load_lmt(lmt_item, bpy.context)
    lmt = scene.albam.lmt_groups.anim_group[scene.albam.lmt_groups.active_group_id]
    actions = [row.action for row in lmt.actions if row.action is not None]
    check(len(actions) > 1, f"{len(actions)} animations imported from {LMT}")
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
    # every (bone, property) with curves becomes a track (the source has a few more: 4 per block of pl000_01
    # don't come back through import, on every Blender)
    tracks = animation._get_export_tracks(first, arm, [])
    written = len(out_lmt.block_offsets[0].block_header.tracks)
    check(written == len(tracks) > 80, f"block 0 exports one track per animated bone property ({written} of "
          f"{len(tracks)}; source {len(src_lmt.block_offsets[0].block_header.tracks)})")
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
