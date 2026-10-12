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
from albam.engines.mtfw import effect, effect_sim
failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)
try:
    ROOT = common.DATA + r"\arctool\Anima\uPlayerDante\xffect\.."
    path = common.DATA + r"\arctool\Anima\uPlayerDante\xffect\efl\com\ec021_02v0.efl"
    data = open(path, "rb").read()
    scene = bpy.context.scene
    scene.albam.import_options_efl.sim_frames = 60
    scene.albam.import_options_efl.load_textures = False
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec021_02v0.efl", relative_path=r"effect\efl\com\ec021_02v0.efl",
                                    get_bytes=lambda: data), bpy.context)
    print("   sims:", sorted((o["efl_sim"].get("record"), o["efl_sim"].get("kind")) for o in bpy.data.objects if o.get("efl_sim")))
    ob = next(o for o in bpy.data.objects if o.get("efl_sim") and o["efl_sim"].get("record") == 5)
    info = ob["efl_sim"]
    check(info.get("orient") and list(info["orient"]["axis"]) == [0, 1, 0] and not info["orient"]["after"],
          "Polygon record carries orient (DirAxisType 2 = +Y, no scale-after)")
    checked = 0
    for frame in range(scene.frame_start + 1, scene.frame_start + 40):
        scene.frame_set(frame)
        if not len(ob.data.vertices):
            continue
        gf = effect_sim._game_frame(ob, scene)
        alive = effect_sim._alive_states(ob, gf)
        rot = [tuple(v.vector) for v in ob.data.attributes["rot"].data]
        for (p, s), r in zip(alive, rot):
            d = effect_sim._move_direction(ob, scene, p, s, gf, ob["efl_generator"].matrix_world,
                                           effect_sim._birth_matrix(ob, scene, p.birth, ob["efl_generator"].matrix_world),
                                           info.get("space"))
            if d is None or s.rot != (0.0, 0.0, 0.0) and any(s.rot):
                continue
            # points object space -> world, then the particle's +Y (game axis) must point along d
            world_rot = ob.matrix_world.to_quaternion().to_matrix() @ Euler(r, "XYZ").to_matrix()
            y = (world_rot @ Vector((0, 1, 0))).normalized()   # rotations map game-local vectors
            if (y - d).length > 1e-3 and checked < 3:
                print("   mismatch", tuple(round(c, 3) for c in y), tuple(round(c, 3) for c in d))
            checked += (y - d).length < 1e-3
        if checked > 5:
            break
    check(checked > 5, f"rendered +Y axis points along the travel direction ({checked} particles checked)")
except Exception:
    traceback.print_exc(); failures.append("exception")
print("FAILURES:", failures)
