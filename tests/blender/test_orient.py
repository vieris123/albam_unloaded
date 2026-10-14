import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, math, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
from mathutils import Euler, Matrix, Vector
import albam
albam.register()
from albam.engines.mtfw import effect, effect_sim
from albam.engines.mtfw.efl import EffectList

effect_sim._model_rotation_full = lambda *a, **k: effect_sim._model_rotation(*a, **k)[0]
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def close(a, b, eps=1e-4):
    return all(abs(x - y) < eps for x, y in zip(a, b))


try:
    scene = bpy.context.scene
    # 1. node group: scale after rotation
    me = bpy.data.meshes.new("pts")
    me.vertices.add(1)
    pts = bpy.data.objects.new("pts", me)
    scene.collection.objects.link(pts)
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    cube = bpy.context.active_object
    cube.hide_set(True)
    effect_sim._wrapped_modifier(pts, "GN", effect_sim._node_group(), instance_from=("OBJECT", cube))
    for name, value in (("rot", (0.0, 0.0, math.pi / 2)), ("scale3", (1.0, 1.0, 1.0)), ("scale_after", (2.0, 1.0, 1.0)),
                        ("p_center", (0.0, 0.0, 0.0)), ("uv_u", (1, 0, 0)), ("uv_v", (0, 1, 0)), ("tint", (1, 1, 1))):
        a = me.attributes.new(name, "FLOAT_VECTOR", "POINT")
        a.data[0].vector = value
    for name, value in (("alpha", 1.0), ("shape_on", 0.0), ("shape_w", 0.0)):
        a = me.attributes.new(name, "FLOAT", "POINT")
        a.data[0].value = value
    me.attributes.new("shape", "FLOAT_VECTOR", "POINT")
    dg = bpy.context.evaluated_depsgraph_get()
    ev = pts.evaluated_get(dg).to_mesh()
    xs = [v.co.x for v in ev.vertices]; ys = [v.co.y for v in ev.vertices]
    ext = (max(xs) - min(xs), max(ys) - min(ys))
    pts.evaluated_get(dg).to_mesh_clear()
    check(close(ext, (4.0, 2.0)), f"scale after a 90 degree turn stretches the world X ({ext[0]:.2f} x {ext[1]:.2f})")
    me.attributes["scale_after"].data[0].vector = (1, 1, 1)
    me.attributes["scale3"].data[0].vector = (2, 1, 1)
    me.update()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = pts.evaluated_get(dg).to_mesh()
    xs = [v.co.x for v in ev.vertices]; ys = [v.co.y for v in ev.vertices]
    ext = (max(xs) - min(xs), max(ys) - min(ys))
    pts.evaluated_get(dg).to_mesh_clear()
    check(close(ext, (2.0, 4.0)), f"scale before the turn stretches the world Y ({ext[0]:.2f} x {ext[1]:.2f})")

    # 2. rotation rules
    G2B, B2G = effect_sim.GAME_TO_BLENDER, effect_sim.BLENDER_TO_GAME
    gen_now = Matrix.Translation((1, 2, 3)) @ Euler((0.3, -0.2, 1.1)).to_matrix().to_4x4()
    p = SimpleNamespace(birth=0, dir=(0.0, 1.0, 0.0), path=None)
    s = SimpleNamespace(rot=(0.0, 0.0, 0.0), pos=(0.0, 0.0, 0.0), anchor=None)
    ob = SimpleNamespace(name="none")
    base = dict(local=False, init=False, after=False, axis=None)
    r = effect_sim._model_rotation_full(ob, scene, p, s, 5, "XYZ", base, gen_now, gen_now, "follow")
    check(close([c for row in r for c in row], [c for row in gen_now.to_3x3() for c in row]),
          "default: the generator's current rotation")
    r = effect_sim._model_rotation_full(ob, scene, p, s, 5, "XYZ", dict(base, local=True), gen_now, gen_now, "follow")
    check(close([c for row in r for c in row], [c for row in G2B for c in row]), "ROT_LOCAL: world (game) axes")
    r = effect_sim._model_rotation_full(ob, scene, p, s, 5, "XYZ", dict(base, axis=(0, 0, 1)), gen_now, gen_now, "follow")
    want = (gen_now.to_3x3() @ Vector(p.dir)).normalized()
    got = r @ Vector((0, 0, 1))   # r maps game-local vectors to Blender world
    check(close(got, want), "DirAxisType +Z: the particle's Z axis points along the move direction")
    gen_birth = Euler((0.0, 0.0, 0.7)).to_matrix().to_4x4()
    effect_sim._history["init"] = {}
    r = effect_sim._model_rotation_full(SimpleNamespace(name="init"), scene, p, s, 5, "XYZ", dict(base, local=True, init=True),
                                   gen_birth, gen_birth, "follow")
    check(close([c for row in r for c in row], [c for row in G2B @ (B2G @ gen_birth.to_3x3()) for c in row]),
          "ROT_INIT: keeps the spawn-time generator rotation (as Euler angles added to Rot)")

    # 3. real effects with these flags
    ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    scene.albam.import_options_efl.sim_frames = 40
    DANTE = common.DATA + r"\arctool\Anima\uPlayerDante"
    for root_dir, rel, index, flag in ((DANTE, r"effect\efl\com\ec005_60v7", 19, "after"),
                                       (ROOT, r"effect\efl\com\ec024_60v0", 7, "init")):
        data = open(os.path.join(root_dir, rel + ".efl"), "rb").read()
        f = SimpleNamespace(app_id="dmc4", display_name=os.path.basename(rel) + ".efl", relative_path=rel + ".efl",
                            get_bytes=lambda d=data: d)
        effect.load_efl(f, bpy.context)
        sims = [o for o in bpy.data.objects if o.get("efl_sim") and o["efl_sim"].get("record") == index
                and o["efl_sim"].get("orient") and o["efl_sim"]["orient"][flag]]
        check(bool(sims), f"{rel} record {index}: the sim object carries orient {flag}")
        if not sims:
            continue
        ob = sims[0]
        counts, sa = [], []
        for frame in range(scene.frame_start, scene.frame_start + 30, 1):
            scene.frame_set(frame)
            counts.append(len(ob.data.vertices))
            if len(ob.data.vertices):
                sa = [tuple(round(c, 4) for c in v.vector) for v in ob.data.attributes["scale_after"].data]
        check(max(counts) > 0, f"{rel}: particles play ({max(counts)} at most)")
        if flag == "after":
            check(sa and any(v != (1.0, 1.0, 1.0) for v in sa), f"{rel}: scale_after carries ModelScale ({sa[:1]})")
        check(effect_sim.node_group_of(ob).name == effect_sim.NODE_GROUP, f"{rel}: uses {effect_sim.NODE_GROUP}")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
