"""Changing the scene frame rate after an effect was imported (and keyed) rescales its keys and end marker about the
start marker, so every key keeps its game frame: the preview and the export convert with the current rate."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import traceback  # noqa: E402
from types import SimpleNamespace  # noqa: E402

common.register()
import bpy  # noqa: E402
from albam.engines.mtfw import effect, effect_editor, effect_export, effect_keys, effect_sim  # noqa: E402
from albam.engines.mtfw.efl import EffectList  # noqa: E402
from albam.engines.mtfw.efl import keyframe as kfm  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


REL = r"effect\efl\com\ec000_03v0.efl"   # record 1: move Rot / Ofs handle keys; generator-timer tracks too
common.skip_unless(os.path.join(common.NERO, REL))
scene = bpy.context.scene
scene.render.fps, scene.render.fps_base = 24, 1.0   # the import sets 60 (the game's rate)
scene.frame_end = 300
scene.frame_current = 1
scene.albam.import_options_efl.load_textures = False
scene.albam.efl_editor.live = False


def all_keys(root):
    """{object name: {data path: sorted key frames}} of every object of the effect."""
    out = {}
    for ob in bpy.data.objects:
        if ob.get("efl_root") == root and ob.animation_data and ob.animation_data.action:
            from albam.lib import blender_compat as compat
            for fc in compat.fcurves_of(ob.animation_data.action, ob):
                out.setdefault(ob.name, {}).setdefault(fc.data_path, set()).update(round(kp.co.x, 4) for kp in fc.keyframe_points)
    return out


def file_kf(data, index, slot, field):
    rec = EffectList.from_bytes(data).records[index]
    for s, block in rec.blocks():
        if s == slot and block is not None:
            for sub in block.subblocks():
                if sub.kind == "kf" and sub.field.name == field:
                    return kfm.read(sub)
    return None


try:
    scene.albam.rfs.add_root_folder("dmc4", common.NERO)
    data = open(os.path.join(common.NERO, REL), "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name=os.path.basename(REL), relative_path=REL,
                                    get_bytes=lambda: data), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    start = int(root["efl_start_frame"])
    check(scene.render.fps == 60 and scene.render.fps_base == 1.0, "importing an effect sets the scene to 60 fps")
    check(abs(float(root[effect_sim.KEY_FPS]) - 60.0) < 1e-6, "the effect remembers the frame rate its keys are laid out for")
    rec = next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == 1)
    rot = effect_keys.handle_of(rec, "move", "KeyframeRotParamOffset")
    # a user key at 60 fps, 30 game frames after the start
    rot.rotation_euler = (0.3, 0.0, 0.0)
    rot.keyframe_insert("rotation_euler", frame=start + 30)
    effect_sim.set_end(root, scene, start + 200)
    before = all_keys(root)
    exported_60, _, _ = effect_export.build_efl_bytes(root)
    kf_60 = file_kf(exported_60, 1, "move", "KeyframeRotParamOffset")
    check(30 in kf_60.frames, f"the key exports at game frame 30 at 60 fps ({kf_60.frames})")

    # -- 60 -> 30 fps: everything halves about the start marker -------------------------------------------
    scene.render.fps = 30
    check(effect_editor._fps_changed(scene), "the depsgraph handler notices the rate change")
    effect_editor._run_job(("fps", scene), scene.albam.efl_editor)
    after = all_keys(root)
    halved = all(abs(start + (f - start) * 0.5 - g) < 1e-3 for name in before for path in before[name]
                 for f, g in zip(sorted(before[name][path]), sorted(after[name][path])))
    check(halved and before.keys() == after.keys(), f"every key of {len(after)} objects sits at half its distance from the start")
    check(effect_sim.end_frame_of(root, scene) == start + 100, "the end marker moved with them")
    check(abs(float(root[effect_sim.KEY_FPS]) - 30.0) < 1e-6, "the remembered rate is updated")
    exported_30, _, _ = effect_export.build_efl_bytes(root)
    check(exported_30 == exported_60, "the export is unchanged: the keys kept their game frames")
    scene.frame_set(start + 15)
    check(effect_sim._game_frame(rot, scene) == 30, "the preview reads game frame 30 where the key now sits")
    check(not effect_sim.sync_fps(root, scene), "a second sync at the same rate does nothing")

    # -- back to 60 (through the frame-change path) -------------------------------------------------------
    scene.render.fps = 60
    effect_sim.sync_markers(scene)
    restored = all_keys(root)
    check(restored == before, "going back to 60 fps restores the original key frames")
    check(effect_sim.end_frame_of(root, scene) == start + 200, "and the end marker")

    # -- an older effect without a remembered rate takes the current one --------------------------------
    del root[effect_sim.KEY_FPS]
    scene.render.fps = 24
    check(not effect_sim.sync_fps(root, scene) and abs(float(root[effect_sim.KEY_FPS]) - 24.0) < 1e-6,
          "an effect without a remembered rate adopts the current one without moving its keys")
    scene.render.fps = 60
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
