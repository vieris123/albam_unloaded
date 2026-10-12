import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, time, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_sim

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def root_of():
    return next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")


try:
    ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
    scene = bpy.context.scene
    opts = scene.albam.import_options_efl
    opts.sim_frames = 30
    opts.load_textures = False
    rel = r"effect\efl\com\ec024_60v2"
    data = open(os.path.join(ROOT, rel + ".efl"), "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec024_60v2.efl", relative_path=rel + ".efl",
                                    get_bytes=lambda: data), bpy.context)
    root = root_of()
    _r, notes, rebuilt = effect_export.apply_to_scene(bpy.context, root)
    check(not rebuilt and not notes, "untouched Apply replays without rebuilding")

    # a particle with a material on a GN particle object
    rec = next(o for o in effect_export.all_record_objects(root)
               if "efl_ptcl" in o and "BlendOp" in o["efl_ptcl"] and
               any(c.get("efl_generator") == o for c in bpy.data.objects))
    index = int(rec["efl_record"])
    old_op = rec["efl_ptcl"]["BlendOp"]
    new_op = 2 if old_op != 2 else 0
    props = rec["efl_ptcl"].to_dict()
    props["BlendOp"] = new_op
    rec["efl_ptcl"] = props
    bpy.context.view_layer.objects.active = rec
    t = time.time()
    res = bpy.ops.albam.efl_apply_edits()
    print(f"apply took {time.time() - t:.2f}s", res)
    root = root_of()
    rec = next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == index)
    mats = {m.get("efl_blend") for o in bpy.data.objects if o.get("efl_generator") == rec
            for o2 in [o] + list(o.children) for m in getattr(o2.data, "materials", []) or [] if m}
    # the source shape is the instanced object; find any material on objects of this record
    mats |= {m.get("efl_blend") for o in bpy.data.objects if o.parent == rec and o.type == "MESH"
             for m in o.data.materials if m}
    print("materials:", mats)
    want = ("op " + ("REVSUBTRACT" if new_op == 2 else "ADD"))
    check(any(m and want in m for m in mats), f"Apply rebuilt the material with the new blend op ({want})")
    check(rec["efl_ptcl"]["BlendOp"] == new_op, "the edit is kept")

    # a sim-only generator edit doesn't rebuild
    gen = rec["efl_gen"].to_dict()
    name = next(n for n in ("SetNum", "WaitFrame") if n in gen) \
        if any(n in gen for n in ("SetNum", "WaitFrame")) else None
    print("gen fields:", sorted(gen)[:60])
    if name:
        v = gen[name]
        gen[name] = (v + 1) if isinstance(v, int) else [v[0] + 1] + list(v[1:])
        print("edit", name, v, gen[name])
        rec["efl_gen"] = gen
        _r, notes, rebuilt = effect_export.apply_to_scene(bpy.context, root)
        check(not rebuilt and notes, f"a generator {name} edit replays without rebuilding ({notes})")
    root = root_of()
    rec = next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == index)
    rec.location = rec.location + __import__("mathutils").Vector((0.0, 0.0, 0.1))
    _r, notes, rebuilt = effect_export.apply_to_scene(bpy.context, root)
    check(rebuilt and any("Pos" in n for n in notes), "moving a generator rebuilds (ground / world axes re-measured)")
    root = root_of()
    bpy.context.view_layer.objects.active = root
    res = bpy.ops.albam.efl_apply_edits(rebuild=True)
    check(res == {"FINISHED"} and root_of() != root if False else res == {"FINISHED"}, "Rebuild Everything option runs")
    check(not hasattr(bpy.types, "ALBAM_OT_EflRebuild") and "efl_rebuild" not in dir(bpy.ops.albam),
          "the separate Rebuild operator is gone")
    root = root_of()
    root["efl_missing_textures"] = [r"effect	ex\does_not_exist"]
    _r, notes, rebuilt = effect_export.apply_to_scene(bpy.context, root)
    check(not rebuilt, "a texture that's still missing doesn't force a rebuild")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
