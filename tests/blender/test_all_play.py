import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, glob, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.engines.mtfw import effect
ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
scene = bpy.context.scene
scene.albam.rfs.add_root_folder("dmc4", ROOT)
scene.albam.import_options_efl.sim_frames = 60
scene.albam.import_options_efl.load_textures = False
bad = []
files = sorted(glob.glob(os.path.join(ROOT, "effect", "efl", "**", "*.efl"), recursive=True))
for path in files:
    rel = os.path.relpath(path, ROOT)
    data = open(path, "rb").read()
    f = SimpleNamespace(app_id="dmc4", display_name=os.path.basename(path), relative_path=rel, get_bytes=lambda d=data: d)
    try:
        effect.load_efl(f, bpy.context)
    except Exception as err:
        bad.append((rel, repr(err)))
errors = []
import builtins
real_print = builtins.print
def capture(*a, **k):
    msg = " ".join(str(x) for x in a)
    if "failed" in msg or "Error" in msg:
        errors.append(msg)
    real_print(*a, **k)
builtins.print = capture
try:
    for frame in range(scene.frame_start, scene.frame_start + 40, 4):
        scene.frame_set(frame)
except Exception:
    traceback.print_exc(); errors.append("frame_set exception")
builtins.print = real_print
print("FILES", len(files), "IMPORT FAILURES", bad[:5], "PLAY ERRORS", errors[:5])
models = [ob for ob in scene.objects if ob.get("efl_sim", {}).get("kind") == 5]
print("model particle objects", len(models), [ob.modifiers[0].node_group.name for ob in models[:1]])
mats = {m.name for c in bpy.data.collections if c.name.startswith("EFL_model_") and "_" in c.name[10:] for o in c.objects for m in [s.material for s in o.material_slots] if m}
print("variant mats", sorted(mats)[:5])
from albam.engines.mtfw import effect_sim
effect_sim._view["on"] = True
import mathutils
effect_sim._view["matrix"] = mathutils.Matrix.Translation((0, -5, 1))
n = 0
for ob in effect_sim._sim_objects(scene):
    if effect_sim._camera_dependent(ob):
        effect_sim.update_object(ob, scene); n += 1
print("viewport-updated", n)
print("FAILURES:", [f"import {b}" for b in bad] + [f"play {e}" for e in errors])
