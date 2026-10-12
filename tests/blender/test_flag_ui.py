import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_editor
fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
try:
    opts = bpy.context.scene.albam.import_options_efl
    opts.sim_frames = 20; opts.load_textures = False
    path = None
    for base, _, names in os.walk(common.DATA + r"\arctool"):
        if "ec022_00v7.efl" in names: path = os.path.join(base, "ec022_00v7.efl"); break
    data = open(path, "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec022_00v7.efl", relative_path="effect\efl\com\ec022_00v7.efl", get_bytes=lambda: data), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    rec = next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == 10)
    state = bpy.context.scene.albam.efl_editor
    effect_editor.load_record(state, rec)
    item = next((i for i in state.fields if i.label == "CollFlag"), None)
    check(item is not None and item.kind == "flags", f"CollFlag on the More tab is checkboxes ({item.kind if item else None})")
    if item is not None:
        before = int(rec["efl_sub"]["move"]["CollParamOffset"]["CollFlag"])
        item.flags[1] = not item.flags[1]
        after = int(rec["efl_sub"]["move"]["CollParamOffset"]["CollFlag"])
        check(after == before ^ 2, f"ticking Stop Spin writes the collision data ({before} -> {after})")
    for name in ("MoveOptionFlag",):
        it = next((i for i in state.fields if i.label == name), None)
        check(it is not None and it.kind == "flags", f"{name} is checkboxes")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("FAILURES:", fails)
