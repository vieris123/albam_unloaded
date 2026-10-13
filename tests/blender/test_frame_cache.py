"""Headless test: the per-frame cache (effect_sim._frames). Replayed, scrubbed and freshly recomputed frames draw
exactly the same meshes; moving the camera redraws camera-facing systems and moving it back reuses the cache."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import hashlib  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
from types import SimpleNamespace  # noqa: E402

common.register()
import bpy  # noqa: E402
from albam.engines.mtfw import effect, effect_sim  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


EM009 = os.path.join(common.ARCTOOL, "em009")
common.skip_unless(EM009)
CASES = ((common.NERO, r"effect\efl\com\ec024_60v2.efl"),   # 109 systems, 72 ribbons
         (EM009, r"effect\efl\ene\ee008_40v0.efl"),          # chains, world-space moves
         (EM009, r"effect\efl\ene\ee099_90v0.efl"))          # every drawn kind


def digest(obs):
    """A hash of every particle mesh: positions and point attributes (empty layers are ignored: an idle system may
    keep its old, now empty, layers or have none, which draw the same)."""
    h = hashlib.md5()
    for ob in sorted(obs, key=lambda o: o.name):
        if ob.type != "MESH":
            continue
        me = ob.data
        co = [0.0] * (len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        h.update(repr([round(c, 5) for c in co]).encode())
        for attr in sorted(me.attributes, key=lambda a: a.name):
            if attr.domain != "POINT" or attr.name.startswith(".") or attr.name == "position" or not len(attr.data):
                continue
            width = {"FLOAT_VECTOR": 3, "FLOAT_COLOR": 4, "FLOAT2": 2}.get(attr.data_type, 1)
            values = [0] * (len(attr.data) * width) if attr.data_type == "INT" else [0.0] * (len(attr.data) * width)
            key = "vector" if attr.data_type in ("FLOAT_VECTOR", "FLOAT2") else "color" if attr.data_type == "FLOAT_COLOR" else "value"
            attr.data.foreach_get(key, values)
            h.update(attr.name.encode() + repr([round(v, 5) for v in values]).encode())
    return h.hexdigest()


try:
    scene = bpy.context.scene
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    scene.render.fps = 60
    scene.frame_start, scene.frame_end, scene.frame_current = 1, 240, 1
    scene.albam.import_options_efl.load_textures = False
    for root_dir, rel in CASES:
        scene.albam.rfs.add_root_folder("dmc4", root_dir)
        data = open(os.path.join(root_dir, rel), "rb").read()
        effect.load_efl(SimpleNamespace(app_id="dmc4", display_name=os.path.basename(rel), relative_path=rel,
                                        get_bytes=lambda: data), bpy.context)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (0.0, -4.0, 1.0)
    cam.rotation_euler = (1.4, 0.0, 0.0)
    bpy.context.view_layer.update()   # a camera made by script has no world matrix until the scene updates
    obs = effect_sim._sim_objects(scene)

    frames = list(range(2, 92))
    first = {}
    t = time.perf_counter()
    for f in frames:
        scene.frame_set(f)
        first[f] = digest(obs)
    t_first = time.perf_counter() - t
    t = time.perf_counter()
    for f in frames:
        scene.frame_set(f)
    t_replay = time.perf_counter() - t
    print(f"first pass {t_first / len(frames) * 1000:.1f} ms/frame (with digests), replay "
          f"{t_replay / len(frames) * 1000:.1f} ms/frame")

    differs = [f for f in frames[::7] if (scene.frame_set(f), digest(obs))[1] != first[f]]
    check(not differs, f"replayed frames draw what the first pass drew ({differs[:3]})")
    differs = [f for f in (70, 20, 55, 9, 88) if (scene.frame_set(f), digest(obs))[1] != first[f]]
    check(not differs, f"scrubbing backwards and jumping draw the same ({differs[:3]})")
    differs = []
    for f in (20, 60, 85):
        effect_sim._frames.clear()   # computed from scratch
        scene.frame_set(f)
        if digest(obs) != first[f]:
            differs.append(f)
    check(not differs, f"fresh computation equals the cached frames ({differs[:3]})")

    scene.frame_set(60)
    before = digest(obs)
    cam.location = (2.0, -4.0, 1.0)   # ribbons face the eye in their node group (not in the cached points), so
    cam.rotation_euler = (1.4, 0.0, 0.4)   # turn the camera too: billboards and the culling fade follow it
    bpy.context.view_layer.update()
    scene.frame_set(60)
    moved = digest(obs)
    cam.location = (0.0, -4.0, 1.0)
    cam.rotation_euler = (1.4, 0.0, 0.0)
    bpy.context.view_layer.update()
    scene.frame_set(60)
    check(moved != before, "moving the camera redraws the camera-facing systems")
    check(digest(obs) == before, "moving it back draws the cached frame")

    # an edit drops the cache: a different simulation is drawn
    effect_sim.invalidate()
    check(not effect_sim._frames, "invalidate() empties the frame cache")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
