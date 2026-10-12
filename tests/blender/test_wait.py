"""Headless test: generator-timer keyframe tracks sit after the generator's WaitFrame."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_editor, effect_keys
from albam.engines.mtfw.efl import EffectList
from albam.engines.mtfw.efl.edit import keyframe_props

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


try:
    scene = bpy.context.scene
    scene.render.fps = 60
    scene.frame_end = 250
    scene.albam.import_options_efl.load_textures = False
    state = scene.albam.efl_editor
    state.live = False
    path = common.DATA + r"\arctool\Anima\uPlayerDante\xffect\efl\com\ec021_07v0.efl"
    data = open(path, "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec021_07v0.efl", relative_path="ec021_07v0.efl",
                                    get_bytes=lambda: data), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    start, rate = effect_keys.timing(root)
    ob = next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == 0)
    track = ("gen", "KeyframeSetNumParamOffset")
    prop = effect_keys.stored(ob, *track).to_dict()
    name = effect_keys.track_name(*track)

    def frames_now():
        return [kp.co.x for kp in effect_keys._curves(ob, effect_keys._data_path(name))[0].keyframe_points]

    def exported():
        return EffectList.from_bytes(effect_export.build_efl_bytes(root)[0]).records[0].gen

    wait = int(list(ob["efl_gen"]["WaitFrame"])[0])
    frames = frames_now()
    check(wait == 20 and prop["RefType"] == 1, f"record 0: SetNum on the generator timer, WaitFrame {wait}")
    check(frames == [start + (f + wait) / rate for f in prop["frames"]],
          f"its curve starts after the wait ({frames[:3]} for game keys {list(prop['frames'])[:3]})")
    check(effect_export.build_efl_bytes(root)[0] == data, "the untouched effect exports byte-identical")

    effect_editor.load_record(state, ob)
    item = state.fields.get("gen/WaitFrame")
    item.ints[0] = 25
    moved = frames_now()
    check(all(abs(b - a - 5 / rate) < 1e-4 for a, b in zip(frames, moved)), "editing WaitFrame moves the curve")
    gen = exported()
    check(list(keyframe_props(gen)["KeyframeSetNumParamOffset"]["frames"]) == list(prop["frames"])
          and gen.get("WaitFrame")[0] == 25, "the keys keep their game frames; WaitFrame 25 exports")

    effect_editor._set_kf_field(state, "gen:KeyframeSetNumParamOffset")
    effect_editor.load_keyframe(state)
    state.kf_ref = "2"   # the effect timer: no wait
    check(abs(frames_now()[0] - (start + prop["frames"][0] / rate)) < 1e-4, "an effect-timer track starts at the marker")
    new = keyframe_props(exported())["KeyframeSetNumParamOffset"]
    check(list(new["frames"]) == list(prop["frames"]) and new["RefType"] == 2, "same game frames, RefType 2")

    # particle-age tracks are drawn for the first particle, born when the wait ends (record 51: wait 72, Scale)
    ob51 = next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == 51)
    p = effect_keys.stored(ob51, "ptcl", "KeyframeScaleParamOffset").to_dict()
    first = effect_keys._curves(ob51, effect_keys._data_path("Particle Scale"))[0].keyframe_points[0].co.x
    check(int(p["RefType"]) == 0 and abs(first - (start + (72 + p["frames"][0]) / rate)) < 1e-4,
          f"a particle-age track starts after the wait ({first})")
    # a key inserted before the wait goes to the first playable frame
    effect_editor.load_record(state, ob51)
    bpy.context.view_layer.objects.active = ob51
    scene.frame_set(start + 5)
    bpy.ops.albam.efl_key_insert(track="ptcl:KeyframeIntensityParamOffset")
    new = keyframe_props(EffectList.from_bytes(effect_export.build_efl_bytes(root)[0]).records[51].ptcl)
    check(list(new["KeyframeIntensityParamOffset"]["frames"]) == [0],
          f"a key inserted before the wait exports at frame 0 ({list(new['KeyframeIntensityParamOffset']['frames'])})")

    # a key inserted on a new generator-timer track lands where it plays
    effect_editor.load_record(state, ob)
    effect_editor._set_kf_field(state, "gen:KeyframeSetNumParamOffset")
    effect_editor.load_keyframe(state)
    state.kf_ref = "1"
    bpy.ops.albam.efl_keys_clear(track="gen:KeyframeSetNumParamOffset")
    bpy.context.view_layer.objects.active = ob
    scene.frame_set(start + 40)
    bpy.ops.albam.efl_key_insert(track="gen:KeyframeSetNumParamOffset")
    new = keyframe_props(exported())["KeyframeSetNumParamOffset"]
    check(list(new["frames"]) == [15], f"a key inserted 40 frames in exports at generator frame 40 - 25 ({list(new['frames'])})")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
