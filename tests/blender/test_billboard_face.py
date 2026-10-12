import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
from mathutils import Euler, Vector
import albam
albam.register()
from albam.engines.mtfw import effect
failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)
try:
    ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
    import glob
    from albam.engines.mtfw.efl import EffectList
    for path in sorted(glob.glob(os.path.join(ROOT, "effect", "efl", "com", "*.efl"))):
        e = EffectList.from_bytes(open(path, "rb").read())
        if sum(1 for r in e.records if r.ptcl and r.ptcl.type == 0 and r.ptcl.get("TransMode") & 1) >= 3:
            break
    rel = os.path.splitext(os.path.relpath(path, ROOT))[0]
    print("   effect", rel)
    data = open(path, "rb").read()
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    scene.albam.import_options_efl.sim_frames = 200
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="x.efl", relative_path=rel + ".efl", get_bytes=lambda: data), bpy.context)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (3.0, -4.0, 2.5)
    cam.rotation_euler = Euler((1.2, 0.0, 0.65))
    bpy.context.view_layer.update()
    view = (cam.matrix_world.to_quaternion() @ Vector((0, 0, 1))).normalized()
    sims = [o for o in bpy.data.objects if o.get("efl_sim") and o["efl_sim"].get("kind") == 0]
    print("   sims", len(sims), sorted({o["efl_sim"].get("kind") for o in bpy.data.objects if o.get("efl_sim")}))
    worst, count = 0.0, 0
    for frame in range(scene.frame_start, scene.frame_start + 150, 3):
        scene.frame_set(frame)
        dg = bpy.context.evaluated_depsgraph_get()
        for ob in sims:
            ev = ob.evaluated_get(dg)
            me = ev.to_mesh()
            if False:
                print("   dbg", ob.name, len(ob.data.vertices), len(me.polygons), [m.type for m in ob.modifiers])
            for poly in me.polygons:
                n = (ev.matrix_world.to_3x3() @ poly.normal).normalized()
                worst = max(worst, min((n - view).length, (n + view).length)); count += 1
            ev.to_mesh_clear()
    print(f"   {count} billboard quads, worst normal deviation from the view axis {worst:.2e}")
    check(count >= 5 and worst < 1e-3, "every billboard lies in the screen plane")
except Exception:
    traceback.print_exc(); failures.append("exception")
print("FAILURES:", failures)
