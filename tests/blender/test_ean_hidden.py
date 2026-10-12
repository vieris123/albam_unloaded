import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_editor
failures = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: failures.append(m)
try:
    ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    opts = scene.albam.import_options_efl
    opts.sim_frames = 30; opts.load_textures = True
    rel = r"effect\efl\com\ec000_04v1"
    data = open(os.path.join(ROOT, rel + ".efl"), "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="x.efl", relative_path=rel + ".efl", get_bytes=lambda: data), bpy.context)
    root = lambda: next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    eans = lambda: [o for o in effect.linked_objects(root()).values() if o.albam_asset.extension == "ean"]
    check(eans() and all(o.hide_get() for o in eans()), f"flipbook meshes start hidden ({len(eans())})")
    shown = eans()[0]; shown_name = shown.name
    shown.hide_set(False)
    state = scene.albam.efl_editor
    rec = next(o for o in effect_export.all_record_objects(root()) if int(o["efl_record"]) == 0)
    bpy.context.view_layer.objects.active = rec
    effect_editor.load_record(state, rec)
    state.live = True
    rec["efl_ptcl"]["BlendSrc"] = 2   # a particle field edit: the effect is rebuilt
    effect_editor.schedule_live_apply(root())
    effect_editor._live_apply()
    check(not state.live_error, "the particle edit rebuilt the effect")
    others = [o for o in eans() if o.name != shown_name]
    check(others and all(o.hide_get() for o in others), "hidden flipbooks stay hidden after the rebuild")
    check(not bpy.data.objects[shown_name].hide_get(), "a flipbook you unhid stays visible")
except Exception:
    traceback.print_exc(); failures.append("exception")
print("FAILURES:", failures)
