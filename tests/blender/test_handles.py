"""Vector keyframe tracks (particle / move rotations, path offset, model scale) are keyed on handle Empties parented
to the record: import builds them from the file's keys, keying the handle changes the exported keyframe, a track
without keys gets a handle from Insert Key, clearing a track removes it, deleting it removes the keys, a duplicated
record gets handles of its own, and a rebuild brings them back."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import math, traceback  # noqa: E402
from types import SimpleNamespace  # noqa: E402

common.register()
import bpy  # noqa: E402
from albam.engines.mtfw import effect, effect_export, effect_keys  # noqa: E402
from albam.engines.mtfw.efl import EffectList  # noqa: E402
from albam.engines.mtfw.efl import keyframe as kfm  # noqa: E402
from albam.engines.mtfw.efl.sim import ROT_ORDERS  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def close(a, b, eps=1e-4):
    return len(a) == len(b) and all(abs(x - y) < eps for x, y in zip(a, b))


NERO, DANTE = common.NERO, os.path.join(common.ARCTOOL, "uPlayerDante-vanilla")
MOVE = r"effect\efl\com\ec000_03v0.efl"      # record 1: move Rot and Ofs keys (4 each)
MODEL = r"effect\efl\com\ec024_60v1.efl"     # record 0: ModelScale keys
POLY = r"effect\efl\com\ec005_56v0.efl"      # Dante, record 0: Polygon Rot keys
common.skip_unless(os.path.join(NERO, MOVE))
common.skip_unless(os.path.join(DANTE, POLY))

scene = bpy.context.scene
scene.render.fps = 60
scene.frame_end = 250
scene.albam.import_options_efl.load_textures = False
scene.albam.efl_editor.live = False


def load(root_dir, rel):
    data = open(os.path.join(root_dir, rel), "rb").read()
    before = {o.name for o in bpy.data.objects}
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name=os.path.basename(rel), relative_path=rel,
                                    get_bytes=lambda: data), bpy.context)
    root = next(o for o in bpy.data.objects if o.name not in before and o.albam_asset.extension == "efl")
    return root, data


def record(root, index):
    return next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == index)


def file_kf(data, index, slot, field):
    rec = EffectList.from_bytes(data).records[index]
    for s, block in rec.blocks():
        if s != slot or block is None:
            continue
        for sub in block.subblocks():
            if sub.kind == "kf" and sub.field.name == field:
                return kfm.read(sub)
    return None


def curve_keys(ob, channel):
    """{frame: (x, y, z)} from an object's channel curves."""
    out = {}
    curves = effect_keys._curves(ob, channel)
    for i, fc in curves.items():
        for kp in fc.keyframe_points:
            out.setdefault(round(kp.co.x, 3), [0.0, 0.0, 0.0])[i] = kp.co.y
    return {f: tuple(v) for f, v in out.items()}


try:
    scene.albam.rfs.add_root_folder("dmc4", NERO)
    scene.albam.rfs.add_root_folder("dmc4", DANTE)

    # -- import: handles carry the file's keys ---------------------------------------------------------
    root, DATA = load(NERO, MOVE)
    rec = record(root, 1)
    rot = effect_keys.handle_of(rec, "move", "KeyframeRotParamOffset")
    ofs = effect_keys.handle_of(rec, "move", "KeyframeOfsParamOffset")
    check(rot is not None and ofs is not None, "move Rot and Ofs tracks have handle Empties")
    check(rot.parent == rec and ofs.parent == rec and rot.matrix_parent_inverse == rot.matrix_parent_inverse.Identity(4),
          "handles are children of the record with an identity parent inverse")
    check(rot.get(effect_keys.HANDLE_OF) == rec and rot[effect_keys.HANDLE_TRACK] == "move:KeyframeRotParamOffset",
          "a handle points back at its record and track")
    check(rot.empty_display_type == "ARROWS" and ofs.empty_display_type == "PLAIN_AXES" and rot.hide_render,
          "rotation handles are arrows, position handles axes, both hidden from render")
    order = effect_keys._order_of(rec, "move", "RotOrder")
    check(rot.rotation_mode == ROT_ORDERS[order], f"the rotation handle's mode is the track's order ({rot.rotation_mode})")
    kf_rot = file_kf(DATA, 1, "move", "KeyframeRotParamOffset")
    kf_ofs = file_kf(DATA, 1, "move", "KeyframeOfsParamOffset")
    rot_keys, ofs_keys = curve_keys(rot, "rotation_euler"), curve_keys(ofs, "location")
    check(len(rot_keys) == len(kf_rot.frames) == 4, f"the rotation handle has the file's {len(kf_rot.frames)} keys")
    check(all(close(v, tuple(p[0::2])) for v, p in zip([rot_keys[f] for f in sorted(rot_keys)], kf_rot.params)),
          "rotation keys are the game's angles (radians, no axis change)")
    check(all(close(v, tuple(c * 0.01 for c in p[0::2])) for v, p in zip([ofs_keys[f] for f in sorted(ofs_keys)], kf_ofs.params)),
          "position keys are the game's offsets in metres")
    rand = rec.get(effect_keys.rand_name("move", "KeyframeRotParamOffset", "vec3"))
    check(rand is not None and close(tuple(rand), tuple(kf_rot.params[0][1::2])), "the random part stays on the record")
    out, notes, _ = effect_export.build_efl_bytes(root)
    check(out == DATA, "untouched export is byte-identical")

    # -- keying the handle edits the keyframe ------------------------------------------------------------
    frames = sorted(rot_keys)
    f2 = frames[2]
    rot.rotation_euler = (0.25, -0.5, 1.0)
    rot.keyframe_insert("rotation_euler", frame=f2)
    ofs.location = (0.5, 0.25, -0.1)
    ofs.keyframe_insert("location", frame=frames[1])
    out, notes, _ = effect_export.build_efl_bytes(root)
    new_rot = file_kf(out, 1, "move", "KeyframeRotParamOffset")
    new_ofs = file_kf(out, 1, "move", "KeyframeOfsParamOffset")
    check(close(tuple(new_rot.params[2][0::2]), (0.25, -0.5, 1.0)) and new_rot.frames == kf_rot.frames,
          f"rotating the handle at a key frame changes that key ({[round(p, 3) for p in new_rot.params[2][0::2]]})")
    check(close(tuple(new_rot.params[2][1::2]), tuple(kf_rot.params[2][1::2])), "its random part is kept")
    check(close(tuple(new_ofs.params[1][0::2]), (50.0, 25.0, -10.0), 1e-3), "moving the position handle writes centimetres")
    check(close(tuple(new_rot.params[0][0::2]), tuple(kf_rot.params[0][0::2])), "the other keys are untouched")

    # -- a track without keys: Insert Key makes the handle from the field's value -------------------------
    fresh = next((o, s, f, v) for o in effect_export.all_record_objects(root) for s, f, v in effect_keys.tracks(o)
                 if (s, f) in effect_keys.HANDLES and not effect_keys.has_keys(o, s, f))
    o, s, f, v = fresh
    check(effect_keys.handle_of(o, s, f) is None, f"{o.name} {effect_keys.track_name(s, f)}: no handle before its first key")
    frame = effect_keys.insert_key(o, s, f, v, scene.frame_current + 10)
    handle = effect_keys.handle_of(o, s, f)
    field_value, _ = effect_keys.field_key_values(o, s, f, v, from_field=True)
    channel, unit, _ = effect_keys.HANDLES[(s, f)]
    check(handle is not None and effect_keys.key_count(o, s, f) == 1, "Insert Key creates the handle with one key")
    check(close(tuple(getattr(handle, channel)), tuple(c * unit for c in field_value)), "the handle starts at the field's value")
    out, notes, _ = effect_export.build_efl_bytes(root)
    new = file_kf(out, int(o["efl_record"]), s, f)
    check(new is not None and len(new.frames) == 1 and close(tuple(new.params[0][0::2]), tuple(field_value)),
          "the new key exports with the field's value")
    handle_name = handle.name
    effect_keys.remove_track(o, s, f, v)
    check(effect_keys.handle_of(o, s, f) is None and handle_name not in bpy.data.objects, "Clear Keys removes the handle")
    out, notes, _ = effect_export.build_efl_bytes(root)
    cleared = file_kf(out, int(o["efl_record"]), s, f)
    check(cleared is None or not cleared.frames, "no handle, no keys")

    # -- deleting the handle drops the keys ---------------------------------------------------------------
    bpy.data.objects.remove(ofs)
    check(effect_keys.handle_of(rec, "move", "KeyframeOfsParamOffset") is None and
          effect_keys.key_count(rec, "move", "KeyframeOfsParamOffset") == 0, "a deleted handle counts as no keys")
    out, notes, _ = effect_export.build_efl_bytes(root)
    gone = file_kf(out, 1, "move", "KeyframeOfsParamOffset")
    check(gone is None or not gone.frames, "its keys are removed on export")
    frame = effect_keys.insert_key(rec, "move", "KeyframeOfsParamOffset", "vec3", scene.frame_current + 5)
    ofs = effect_keys.handle_of(rec, "move", "KeyframeOfsParamOffset")
    check(ofs is not None and effect_keys.key_count(rec, "move", "KeyframeOfsParamOffset") == 1,
          "Insert Key makes a new handle after the old one was deleted")

    # -- a duplicated record gets its own handles ------------------------------------------------------------
    copy = rec.copy()
    for collection in rec.users_collection:
        collection.objects.link(copy)
    effect_export.adopt_duplicate(copy, rec)
    copy_rot = effect_keys.handle_of(copy, "move", "KeyframeRotParamOffset")
    check(copy_rot is not None and copy_rot != rot and copy_rot.parent == copy, "the copy has a handle of its own")
    check(effect_keys.key_count(copy, "move", "KeyframeRotParamOffset") == 4 and
          close(curve_keys(copy_rot, "rotation_euler")[f2], (0.25, -0.5, 1.0)), "carrying the source's current keys")
    check(effect_keys.handle_of(rec, "move", "KeyframeRotParamOffset") == rot, "the source keeps its handle")

    # -- a keyed handle triggers the live preview, a picked record selects its handles ---------------------
    from albam.engines.mtfw import effect_editor
    check(root.name in effect_editor._action_roots(rot.animation_data.action), "a handle's action maps to its effect root")
    state = scene.albam.efl_editor
    effect_editor.load_record(state, rec)
    effect_editor.sync_records(state, root, rec)
    index = next(i for i, item in enumerate(state.records) if item.ob == rec)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.ops.albam.efl_pick_record(index=index, mode="SET")
    check(rec.select_get() and all(h.select_get() for h in effect_keys.handles_of(rec)) and len(effect_keys.handles_of(rec)) >= 2,
          "picking a record in the list selects its handles too (their keys show in the Graph Editor)")

    # -- a vector track keyed as a custom property (before handles) migrates to a handle --------------------
    legacy = next(o for o in effect_export.all_record_objects(root) if o != rec and o != copy
                  and any((s, f) == ("move", "KeyframeRotParamOffset") for s, f, v in effect_keys.tracks(o)))
    name = effect_keys.track_name("move", "KeyframeRotParamOffset")
    effect_keys.remove_track(legacy, "move", "KeyframeRotParamOffset", "vec3")
    legacy[name] = [0.0, 0.0, 0.0]
    for frame, value in ((scene.frame_current + 2, (0.1, 0.2, 0.3)), (scene.frame_current + 12, (0.4, 0.5, 0.6))):
        legacy[name] = list(value)
        legacy.keyframe_insert(f'["{name}"]', frame=frame)
    check(effect_keys.handle_of(legacy, "move", "KeyframeRotParamOffset") is None, "legacy curves: no handle yet")
    check(effect_keys.key_count(legacy, "move", "KeyframeRotParamOffset") == 2, "the legacy keys count (migrated on first use)")
    migrated = effect_keys.handle_of(legacy, "move", "KeyframeRotParamOffset")
    keys = curve_keys(migrated, "rotation_euler") if migrated is not None else {}
    check(migrated is not None and close(keys.get(scene.frame_current + 12, ()), (0.4, 0.5, 0.6)) and name not in legacy,
          "the legacy property's keys moved onto the handle and the property is gone")

    # -- a rebuild brings the handles back ----------------------------------------------------------------
    bpy.context.view_layer.objects.active = rec
    new_root, notes, rebuilt = effect_export.apply_to_scene(bpy.context, root, rebuild=True)
    check(rebuilt, "rebuilt")
    rec2 = record(new_root, 1)
    rot2 = effect_keys.handle_of(rec2, "move", "KeyframeRotParamOffset")
    check(rot2 is not None and rot2.name in bpy.data.objects and effect_keys.key_count(rec2, "move", "KeyframeRotParamOffset") == 4,
          "the rebuilt record has its rotation handle and keys")
    check(close(curve_keys(rot2, "rotation_euler")[f2], (0.25, -0.5, 1.0)), "with the edited key")
    check(bpy.context.view_layer.objects.active == rec2, "the record stays active")

    # -- other handle kinds ----------------------------------------------------------------------------------
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    root, DATA = load(NERO, MODEL)
    rec = record(root, 0)
    scale = effect_keys.handle_of(rec, "ptcl", "KeyframeModelScaleParamOffset")
    kf = file_kf(DATA, 0, "ptcl", "KeyframeModelScaleParamOffset")
    check(scale is not None and scale.empty_display_type == "CUBE", "ModelScale keys sit on a cube handle")
    keys = curve_keys(scale, "scale")
    check(close(keys[min(keys)], tuple(kf.params[0][0::2])), "its scale keys are the game's values (no unit)")
    out, notes, _ = effect_export.build_efl_bytes(root)
    check(out == DATA, f"{os.path.basename(MODEL)} exports byte-identical")

    root, DATA = load(DANTE, POLY)
    rec = record(root, 0)
    prot = effect_keys.handle_of(rec, "ptcl", "KeyframeRotParamOffset")
    order = effect_keys._order_of(rec, "ptcl", "RotOrder")
    kf = file_kf(DATA, 0, "ptcl", "KeyframeRotParamOffset")
    check(prot is not None and prot.rotation_mode == ROT_ORDERS[order], f"a Polygon Rot handle uses the particle's RotOrder ({prot.rotation_mode})")
    keys = curve_keys(prot, "rotation_euler")
    check(close(keys[min(keys)], tuple(kf.params[0][0::2])), "with the game's angles")
    # editing the order field turns the handle's mode without touching its angles
    props = rec["efl_ptcl"]
    old = int(props["RotOrder"])
    props["RotOrder"] = (old + 1) % 6
    effect_keys.sync_handles(rec)
    check(prot.rotation_mode == ROT_ORDERS[(old + 1) % 6] and close(tuple(prot.rotation_euler), keys[min(keys)] if abs(scene.frame_current - min(keys)) < 0.5 else tuple(prot.rotation_euler)),
          "sync_handles follows a RotOrder edit")
    props["RotOrder"] = old
    effect_keys.sync_handles(rec)
    out, notes, _ = effect_export.build_efl_bytes(root)
    check(out == DATA, f"{os.path.basename(POLY)} exports byte-identical after the order round trip")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
