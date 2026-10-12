"""Headless test: EFL keyframes as F-curves (effect_keys.py), timeline markers, scene-range simulation."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, glob, traceback, hashlib
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_editor, effect_sim, effect_keys
from albam.engines.mtfw.efl import EffectList
from albam.engines.mtfw.efl import keyframe as kfm
from albam.engines.mtfw.efl.edit import keyframe_props

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


ARC = common.DATA + r"\arctool"
NERO = os.path.join(ARC, "uPlayerNero-vanilla")
scene = bpy.context.scene
scene.render.fps = 60
scene.frame_end = 250
scene.albam.rfs.add_root_folder("dmc4", NERO)
opts = scene.albam.import_options_efl
opts.load_textures = False
state = scene.albam.efl_editor
state.live = False


def find_files():
    """One file per feature: generator Pos keys, f32 keys with a random part, colour keys, a loop, u32 keys."""
    want = {"genpos": None, "f32rand": None, "color": None, "loop": None, "u32": None, "inp1": None}
    seen = set()
    for path in sorted(glob.glob(ARC + r"\**\*.efl", recursive=True)):
        data = open(path, "rb").read()
        h = hashlib.md5(data).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        try:
            efl = EffectList.from_bytes(data)
        except Exception:
            continue
        if len(efl.records) > 40:
            continue
        feats = set()
        for rec in efl.records:
            for slot, block in rec.blocks():
                if block is None:
                    continue
                for sub in block.subblocks():
                    if sub.kind != "kf" or not sub.value_type:
                        continue
                    kf = kfm.read(sub)
                    if not kf.frames:
                        continue
                    if slot == "gen" and sub.field.name == "KeyframePosParamOffset":
                        feats.add("genpos")
                    if kf.vtype == "color":
                        feats.add("color")
                    if kf.vtype == "f32" and any(p[1] for p in kf.params) and len(kf.frames) > 1:
                        feats.add("f32rand")
                    if kf.loop:
                        feats.add("loop")
                    if kf.vtype == "u32":
                        feats.add("u32")
                    if kf.inp_type == 1:
                        feats.add("inp1")
        for f in feats:
            if want.get(f) is None:
                want[f] = path
        if all(want.values()):
            break
    return want


def load(path):
    data = open(path, "rb").read()
    rel = os.path.relpath(path, ARC)
    before = {o.name for o in bpy.data.objects}
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name=os.path.basename(path), relative_path=rel,
                                    get_bytes=lambda: data), bpy.context)
    root = next(o for o in bpy.data.objects if o.name not in before and o.albam_asset.extension == "efl")
    return root, data


def records(root):
    return {int(o["efl_record"]): o for o in effect_export.all_record_objects(root)}


def track_with(root, pred):
    for index, ob in sorted(records(root).items()):
        for slot, field, vtype in effect_keys.tracks(ob):
            prop = effect_keys.stored(ob, slot, field)
            if prop is not None and list(prop["frames"]) and pred(slot, field, vtype, prop):
                return ob, slot, field, vtype, prop.to_dict()
    return None


def exported_kf(root, ob, slot, field):
    out = effect_export.build_efl_bytes(root)[0]
    rec = EffectList.from_bytes(out).records[int(ob["efl_record"])]
    return keyframe_props(getattr(rec, slot)).get(field)


try:
    files = find_files()
    print("files:", files)

    # -- round trip of every imported file -------------------------------------------------------------
    for feat, path in files.items():
        if path is None:
            continue
        root, data = load(path)
        out = effect_export.build_efl_bytes(root)[0]
        check(out == data, f"{feat}: untouched export is byte-identical ({os.path.basename(path)})")
        stamped = [o for o in records(root).values() if effect_keys.VERSION_KEY in o]
        check(len(stamped) == len(records(root)), f"{feat}: every record Empty is stamped efl_keys")

    # -- f32 keys with a random part -------------------------------------------------------------------
    root, data = load(files["f32rand"])
    start, rate = effect_keys.timing(root)
    hit = track_with(root, lambda s, f, v, p: v == "f32" and any(p["params"][2 * i + 1] for i in range(len(p["frames"]))))
    ob, slot, field, vtype, prop = hit
    name = effect_keys.track_name(slot, field)
    check(name in ob, f"track property {name!r} exists")
    fcs = effect_keys._curves(ob, effect_keys._data_path(name))
    check(len(fcs) == 1 and len(fcs[0].keyframe_points) == len(prop["frames"]),
          f"one F-curve with {len(prop['frames'])} keys")
    frames = [kp.co.x for kp in fcs[0].keyframe_points]
    off = effect_keys.wanted_offset(ob, slot, field)
    check(frames == [start + (f + off) / rate for f in prop["frames"]], f"keys sit on start + wait + game frame ({frames}, wait {off})")
    rand_name = name + effect_keys.RAND
    check(rand_name in ob, "the random part property exists")
    # edit a key's value through the curve
    kp = fcs[0].keyframe_points[-1]
    kp.co.y = kp.co.y + 0.5
    fcs[0].update()
    new = exported_kf(root, ob, slot, field)
    old_params = list(prop["params"])
    check(abs(new["params"][-2] - (old_params[-2] + 0.5)) < 1e-5, f"a moved key value exports ({new['params'][-2]})")
    check(list(new["frames"]) == list(prop["frames"]), "frames unchanged")
    check(new["params"][-1] == old_params[-1], "the random part is kept")
    check(new["RefType"] == prop["RefType"] and new["InitOnlyFlag"] == prop["InitOnlyFlag"], "header flags kept")
    # move a key in time
    kp = fcs[0].keyframe_points[-1]   # update() invalidates the earlier reference
    kp.co.x += 5 / rate
    fcs[0].update()
    new = exported_kf(root, ob, slot, field)
    check(new["frames"][-1] == prop["frames"][-1] + 5, f"a moved key frame exports in game frames ({new['frames']})")
    # static random part applies to every key (without Rand curves)
    effect_keys._remove_curves(ob, effect_keys._data_path(rand_name))
    ob[rand_name] = 0.25
    new = exported_kf(root, ob, slot, field)
    check(all(abs(new["params"][2 * i + 1] - 0.25) < 1e-6 for i in range(len(new["frames"]))),
          "a static Rand property is every key's random part")
    # loop via the Keys tab
    effect_editor.load_record(state, ob)
    effect_editor._set_kf_field(state, effect_keys.track_id(slot, field))
    effect_editor.load_keyframe(state)
    check(state.kf_vtype == "f32", "the Keys tab shows the track")
    state.kf_loop = True
    check(any(m.type == "CYCLES" for m in fcs[0].modifiers), "Loop adds a Cycles modifier")
    new = exported_kf(root, ob, slot, field)
    check(new["LoopFlag"] == 1, "Loop exports as LoopFlag")
    state.kf_loop = False
    check(not any(m.type == "CYCLES" for m in fcs[0].modifiers), "Loop off removes it")
    state.kf_inp = "1"
    check(all(kp.interpolation == "BEZIER" for kp in fcs[0].keyframe_points), "hermite = Bezier keys")
    check(exported_kf(root, ob, slot, field)["InpType"] == 1, "exports InpType 1")
    state.kf_inp = "0"
    check(exported_kf(root, ob, slot, field)["InpType"] == 0, "linear keys export InpType 0")
    state.kf_ref = "1"
    state.kf_init_only = True
    new = exported_kf(root, ob, slot, field)
    check(new["RefType"] == 1 and new["InitOnlyFlag"] == 1, "timer / init-only export from the header")
    # clear keys
    bpy.context.view_layer.objects.active = ob
    bpy.ops.albam.efl_keys_clear(track=effect_keys.track_id(slot, field))
    check(name not in ob and not effect_keys._curves(ob, effect_keys._data_path(name)), "Clear removes curves and props")
    new = exported_kf(root, ob, slot, field)
    check(new is None, "cleared keys export as no keyframe")
    # revert brings them back
    bpy.ops.albam.efl_revert_record()
    check(effect_keys.key_count(ob, slot, field) == len(prop["frames"]), "Revert rebuilds the curves")
    check(effect_export.build_efl_bytes(root)[0] == data, "and the export is byte-identical again")

    # -- insert a key on an unkeyed field through the decorator operator -------------------------------
    ob2 = next(o for o in records(root).values() if o.get("efl_ptcl") is not None
               and ("ptcl", "Intensity") in effect_keys.field_tracks(o)
               and not effect_keys.has_keys(o, "ptcl", "KeyframeIntensityParamOffset"))
    effect_editor.load_record(state, ob2)
    item = state.fields.get("ptcl/Intensity")
    check(item is not None and item.track == "ptcl:KeyframeIntensityParamOffset", "the Intensity row knows its track")
    bpy.context.view_layer.objects.active = ob2
    off2 = effect_keys.wanted_offset(ob2, "ptcl", "KeyframeIntensityParamOffset")
    scene.frame_set(start + off2 + 12)
    bpy.ops.albam.efl_key_insert(track=item.track)
    scene.frame_set(start + off2 + 30)
    ob2["Particle Intensity"] = 3.0
    bpy.ops.albam.efl_key_insert(track=item.track)
    new = exported_kf(root, ob2, "ptcl", "KeyframeIntensityParamOffset")
    base = list(ob2["efl_ptcl"]["Intensity"])
    check(new is not None and list(new["frames"]) == [12, 30], f"two inserted keys export at game frames 12, 30 ({new and new['frames']})")
    check(new is not None and abs(new["params"][0] - base[0]) < 1e-6 and abs(new["params"][1] - base[1]) < 1e-6,
          "the first key took the field's value and random part")
    check(new is not None and abs(new["params"][2] - 3.0) < 1e-6, "the second key took the edited property value")

    # -- colour keys -------------------------------------------------------------------------------------
    root_c, data_c = load(files["color"])
    ob, slot, field, vtype, prop = track_with(root_c, lambda s, f, v, p: v == "color")
    name = effect_keys.track_name(slot, field)
    fcs = effect_keys._curves(ob, effect_keys._data_path(name))
    check(len(fcs) == 4, "a colour track has 4 curves")
    b, g, r, a = prop["params"][:4]
    check(abs(fcs[0].keyframe_points[0].co.y - r / 255) < 1e-6, "red channel = R / 255")
    fcs[3].keyframe_points[0].co.y = 0.5
    fcs[3].update()
    new = exported_kf(root_c, ob, slot, field)
    check(new["params"][3] == 128, f"an edited alpha exports as a byte ({new['params'][3]})")

    # -- generator position keys ---------------------------------------------------------------------------
    root_g, data_g = load(files["genpos"])
    start_g, rate_g = effect_keys.timing(root_g)
    ob, slot, field, vtype, prop = track_with(root_g, lambda s, f, v, p: f == "KeyframePosParamOffset")
    fcs = effect_keys._curves(ob, "location")
    check(len(fcs) == 3 and len(fcs[0].keyframe_points) == len(prop["frames"]), "Pos keys are location keys")
    check(abs(fcs[0].keyframe_points[0].co.y - prop["params"][0] * 0.01) < 1e-7, "in metres")
    check(effect_export.build_efl_bytes(root_g)[0] == data_g, "untouched generator keys export byte-identical")
    fcs[1].keyframe_points[-1].co.y += 0.1
    fcs[1].update()
    new = exported_kf(root_g, ob, slot, field)
    check(abs(new["params"][-4] - (prop["params"][-4] + 10.0)) < 1e-3, f"a moved location key exports in cm ({new['params'][-4]})")
    # the generator's base Pos isn't overwritten while location is animated
    ob.location.x += 1.0
    out = effect_export.build_efl_bytes(root_g)[0]
    rec = EffectList.from_bytes(out).records[int(ob["efl_record"])]
    check(list(rec.gen.get("Pos")) == list(EffectList.from_bytes(data_g).records[int(ob["efl_record"])].gen.get("Pos")),
          "the animated generator's base Pos is left alone")
    ob.location.x -= 1.0
    fcs[1].keyframe_points[-1].co.y -= 0.1
    fcs[1].update()

    # -- timeline markers ------------------------------------------------------------------------------------
    marker = scene.timeline_markers.get(root_g[effect_sim.START_MARKER])
    check(marker is not None and marker.frame == start_g, "the effect has a start marker at its start frame")
    marker.frame += 10
    effect_sim.sync_markers(scene)
    check(int(root_g["efl_start_frame"]) == start_g + 10, "dragging the start marker moves the start frame")
    off_g = effect_keys.applied_offset(ob, slot, field)
    check(abs(fcs[0].keyframe_points[0].co.x - (start_g + 10 + (prop["frames"][0] + off_g) / rate_g)) < 1e-4, f"and the keys (offset {off_g})")
    check(effect_export.build_efl_bytes(root_g)[0] == data_g, "the export is unchanged by the move")
    effect_editor.sync_records(state, root_g)
    check(not state.end_at, "End Effect is off without an end marker")
    state.end_at = True
    end_marker = scene.timeline_markers.get(root_g.get(effect_sim.END_MARKER, ""))
    check(end_marker is not None and end_marker.frame == scene.frame_current, "End Effect makes an end marker at the current frame")
    state.end_frame = start_g + 40
    check(end_marker.frame == start_g + 40 and state.end_frame == start_g + 40, "At Frame moves the marker")
    check(effect_sim.end_game_frame(root_g, scene) == 30, f"end game frame = marker - start ({effect_sim.end_game_frame(root_g, scene)})")
    end_marker.frame = start_g + 50
    check(state.end_frame == start_g + 50, "the panel reads a dragged end marker")
    marker.frame -= 10
    effect_sim.sync_markers(scene)
    check(end_marker.frame == start_g + 40, "the end marker follows the start marker")
    state.end_at = False
    check(scene.timeline_markers.get(f"{root_g.name} end") is None, "End Effect off removes the marker")

    # -- simulated length follows the scene range ----------------------------------------------------------
    sim_ob = next((o for o in bpy.data.objects if o.get("efl_root") == root_g and effect_sim.SIM_KEY in o
                   and o[effect_sim.SIM_KEY]["kind"] in (0, 2, 6)), None)
    if sim_ob is not None:
        scene.frame_end = start_g + 100
        check(effect_sim.sim_length(sim_ob, scene) == 101, f"length = frames to the scene end ({effect_sim.sim_length(sim_ob, scene)})")
        n1 = len(effect_sim._particles(sim_ob))
        scene.frame_end = start_g + 400
        n2 = len(effect_sim._particles(sim_ob))
        check(n2 >= n1, f"a longer scene range re-simulates ({n1} -> {n2} particles)")
    else:
        print("skip: no instanced particle system in the genpos file")

    # -- live apply on key edits (depsgraph) --------------------------------------------------------------
    state.live = True
    effect_editor._pending.clear()
    action = ob.animation_data.action
    effect_editor._on_depsgraph(scene, SimpleNamespace(updates=[SimpleNamespace(id=action, is_updated_geometry=False)]))
    check(root_g.name in effect_editor._pending, "an edited action queues a live apply of its effect")
    effect_editor._pending.clear()
    state.live = False

    # -- legacy objects (no efl_keys stamp) export from efl_kf -----------------------------------------------
    ob_legacy, slot, field, vtype, prop = track_with(root_c, lambda s, f, v, p: v == "color")
    del ob_legacy[effect_keys.VERSION_KEY]
    stored = effect_keys.keyframe_props_of(ob_legacy)[slot][field]
    check(list(stored["frames"]) == list(prop["frames"]), "a legacy record exports its stored keyframes")
    ob_legacy[effect_keys.VERSION_KEY] = 1

    # -- the panel draws ----------------------------------------------------------------------------------------
    class Stub:
        def __getattr__(self, name):
            def f(*a, **k):
                return Stub()
            return f
        enabled = True

    effect_editor.load_record(state, ob)
    bpy.context.view_layer.objects.active = ob
    state.tab = "keys"
    class Panel(effect_editor._EflEditorDraw):
        layout = Stub()
    panel = Panel()
    panel.draw(bpy.context)
    state.tab = "ptcl"
    panel.draw(bpy.context)
    check(True, "the panel draws the Keys and Particle tabs")

    # -- every Nero effect imports and exports byte-identical ------------------------------------------------
    bad = []
    nero = sorted(glob.glob(os.path.join(NERO, r"effect\efl\**\*.efl"), recursive=True))
    for path in nero:
        root_n, data_n = load(path)
        if effect_export.build_efl_bytes(root_n)[0] != data_n:
            bad.append(os.path.basename(path))
    check(not bad, f"{len(nero)} Nero effects export byte-identical after import (bad: {bad[:5]})")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
