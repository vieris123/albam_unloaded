import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, glob, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.engines.mtfw import effect, effect_export, mesh
ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
scene = bpy.context.scene
scene.albam.rfs.add_root_folder("dmc4", ROOT)
scene.albam.import_options_efl.sim_frames = 60
item = next(i for i in scene.albam.rfs.file_list if i.name.lower().endswith("model::game::pl000::pl000.mod"))
mesh.build_blender_model(item, bpy.context)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
if arm.name not in scene.collection.objects:
    scene.collection.objects.link(arm)
scene.albam.import_options_efl.armature = arm
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
print("HANDLES", sum(1 for o in bpy.data.objects if o.get(effect_export.ROT_HANDLE_OF) is not None))
print("FILES", len(files), "IMPORT FAILURES", bad[:5], "PLAY ERRORS", errors[:5])
print("FAILURES:", [f"import {b}" for b in bad] + [f"play {e}" for e in errors])
