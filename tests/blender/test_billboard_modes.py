import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, traceback, math
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
from mathutils import Euler, Vector, Matrix
import albam
albam.register()
from albam.engines.mtfw import effect, effect_sim
failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)
try:
    # _view_basis: modes 2/3/4 keep the world axis and are proper rotations
    view = effect_sim.BLENDER_TO_GAME @ Euler((1.1, 0.2, 0.7)).to_matrix()
    for mode, axis in ((2, 0), (3, 1), (4, 2)):
        b = effect_sim._view_basis(mode, view)[0]   # (basis, mirrored axis)
        e = Vector([1.0 if i == axis else 0.0 for i in range(3)])
        check(abs(b.determinant() - 1) < 1e-6 and (b @ e - e).length < 1e-6, f"mode {mode}: rotation that keeps world axis {axis}")
    check(effect_sim._view_basis(1, view)[0] == view, "mode 1: the camera's rotation")

    path = common.MODS + r"\4Hook Mod Pack\DanteJDC\nativePC\effect\efl\com\ec002_00v0.efl"
    common.skip_unless(path)
    data = open(path, "rb").read()
    scene = bpy.context.scene
    scene.albam.import_options_efl.sim_frames = 120
    scene.albam.import_options_efl.load_textures = False
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec002_00v0.efl", relative_path=r"effect\efl\com\ec002_00v0.efl",
                                    get_bytes=lambda: data), bpy.context)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (2.0, -3.0, 2.0)
    cam.rotation_euler = Euler((1.0, 0.0, 0.55))
    bpy.context.view_layer.update()
    view = (cam.matrix_world.to_quaternion() @ Vector((0, 0, 1))).normalized()
    sims = {o["efl_sim"]["record"]: o for o in bpy.data.objects if o.get("efl_sim")}
    for rec in (5, 6, 7, 8):
        ob = sims.get(rec)
        check(ob is not None and ob["efl_sim"]["orient"]["billboard"] == 1, f"record {rec}: billboard mode 1 carried")
    worst, count = 0.0, 0
    for frame in range(scene.frame_start, scene.frame_start + 60, 3):
        scene.frame_set(frame)
        dg = bpy.context.evaluated_depsgraph_get()
        for rec in (5, 6, 7, 8):
            ev = sims[rec].evaluated_get(dg)
            me = ev.to_mesh()
            for poly in me.polygons:
                n = (ev.matrix_world.to_3x3() @ poly.normal).normalized()
                worst = max(worst, min((n - view).length, (n + view).length)); count += 1
            ev.to_mesh_clear()
    print(f"   {count} polygon faces, worst deviation from facing the camera {worst:.2e}")
    check(count >= 4 and worst < 1e-3, "records 5-8 (PolygonBillBoardType 1) face the camera")
except Exception:
    traceback.print_exc(); failures.append("exception")
print("FAILURES:", failures)
