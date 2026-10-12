import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, math, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
from mathutils import Vector
import albam
albam.register()
from albam.engines.mtfw import effect, effect_sim
from albam.engines.mtfw.efl import sim, EffectList

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


try:
    # 1. the formula (calc_culling_fade 0x963BD0)
    dist = {"flags": 0x1, "option": 0x2000, "dir": [0, 0, 1], "near": [100.0, 200.0], "far": [1000.0, 2000.0],
            "angle": [0.0, 0.0], "rate": 0.0}
    f = lambda c, d, v=(0, 0, 1): sim.culling_fade(c, tuple(x * d for x in v), (0, 0, 1))
    check(f(dist, 50) == 0.0 and f(dist, 150) == 0.5 and f(dist, 500) == 1.0 and abs(f(dist, 1500) - 0.5) < 1e-9
          and f(dist, 2500) == 0.0, "distance: hidden / fade in / full / fade out / hidden")
    check(f(dict(dist, option=0x6000), 150) == 0.0 and f(dict(dist, option=0xA000), 1500) == 0.0,
          "NEAR_CLIP / FAR_CLIP cut instead of fading")
    ang = dict(dist, flags=0x81, option=0x0, angle=[0.0, math.pi / 2])
    side = (1.0, 0.0, 0.0)   # 90 degrees from the direction
    diag = (math.sqrt(0.5), 0.0, math.sqrt(0.5))   # 45 degrees
    check(f(ang, 300) == 1.0 and abs(f(ang, 300, diag) - 0.5) < 1e-6 and f(ang, 300, side) == 0.0,
          "angle: 1 - angle / AngleEnd")
    rng = dict(ang, option=0x800, angle=[math.pi / 8, math.pi / 2], rate=math.pi / 4)
    check(f(rng, 300) == 1.0 and abs(f(rng, 300, diag) - 0.5) < 1e-6, "angle range: full to AngleStart, then by Rate")
    back = (0.0, 0.0, -1.0)
    check(f(ang, 300, back) == 0.0 and f(dict(ang, option=0x1), 300, back) == 1.0,
          "BOTH_DIR also accepts the opposite direction (max)")
    check(f(dict(ang, option=0x1001), 300, back) == 0.0, "with ANGLE_OVERLAP the two combine by min")

    # 2. a real near-fade record
    ROOT = common.DATA + r"\arctool\em_dante"
    rel = r"effect\efl\com\ec005_20v1"
    data = open(os.path.join(ROOT, rel + ".efl"), "rb").read()
    rec = EffectList.from_bytes(data).records[0]
    params = sim.culling_params(rec.ptcl)
    check(params is not None and params["near"] == [100.0, 200.0], f"culling block read ({params and params['near']})")
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    scene.albam.import_options_efl.sim_frames = 60
    scene.albam.import_options_efl.load_textures = False
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec005_20v1.efl", relative_path=rel + ".efl",
                                    get_bytes=lambda: data), bpy.context)
    ob = next(o for o in bpy.data.objects if o.get("efl_sim") and o["efl_sim"].get("record") == 0)
    gen = ob["efl_generator"]
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    bpy.context.view_layer.update()
    frame = next(f for f in range(scene.frame_start, scene.frame_start + 60)
                 if (scene.frame_set(f) or True) and len(ob.data.vertices))
    results = []
    for metres, want in ((0.5, 0.0), (1.5, 0.5), (5.0, 1.0)):
        cam.location = gen.matrix_world.translation + Vector((0.0, -metres, 0.0))
        bpy.context.view_layer.update()
        scene.frame_set(frame)
        alphas = [d.value for d in ob.data.attributes["alpha"].data]
        base = alphas
        results.append((metres, round(max(alphas), 3)))
    print("   camera distance -> max alpha:", results)
    a_far = results[2][1]
    check(results[0][1] == 0.0 and a_far > 0 and abs(results[1][1] - a_far * 0.5) < 0.02 * max(a_far, 1e-6),
          "closer than 100 cm hidden, 150 cm at half, 500 cm full")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
