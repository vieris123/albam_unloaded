"""Headless check: joining an ordinary edge mesh into a linked .efs strip (Ctrl+J) and exporting it."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy, bmesh
import albam
albam.register()
from albam.engines.mtfw import effect, effect_efs
from albam.engines.mtfw.effect import linked_objects
from albam.engines.mtfw.efl import efs

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
try:
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    scene.albam.import_options_efl.load_textures = False
    rel = r"effect\efl\com\ec000_00v2.efl"
    data = open(os.path.join(ROOT, rel), "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="x.efl", relative_path=rel, get_bytes=lambda: data),
                    bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    strip = next(ob for key, ob in linked_objects(root).items() if key.startswith("efs:"))
    strip.hide_set(False)

    # an ordinary mesh: a circle's edge loop opened into a chain, somewhere in the world
    bpy.ops.mesh.primitive_circle_add(vertices=12, radius=0.5, location=(1.0, 0.0, 1.0))
    circle = bpy.context.active_object
    bm = bmesh.new()
    bm.from_mesh(circle.data)
    bm.edges.ensure_lookup_table()
    bm.edges.remove(bm.edges[0])   # open the loop
    bm.to_mesh(circle.data)
    bm.free()
    world_first = circle.matrix_world @ circle.data.vertices[0].co

    # Ctrl+J with the strip active, then delete the strip's own points
    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    circle.select_set(True)
    strip.select_set(True)
    bpy.context.view_layer.objects.active = strip
    old_count = len(strip.data.vertices)
    bpy.ops.object.join()
    check(len(strip.data.vertices) == old_count + 12 and "efl_linked" in strip, "the mesh joined into the strip")
    bm = bmesh.new()
    bm.from_mesh(strip.data)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.verts[i] for i in range(old_count)], context="VERTS")
    bm.to_mesh(strip.data)
    bm.free()

    got = efs.parse_strip(effect_efs.build_efs_bytes(strip))
    check(len(got.parts) == 1 and len(got.parts[0].vertices) == 12, f"one part of 12 points ({[len(p.vertices) for p in got.parts]})")
    check(all(abs(sum(c * c for c in v.norm) - 1) < 1e-5 for v in got.parts[0].vertices), "unit normals")
    print("  normals:", got.parts[0].vertices[0].norm)
    # the point sits where the mesh was in the world: strip points are in the generator's space
    gen_space = strip.matrix_world.inverted() @ world_first
    check(any(all(abs(a - b * 100) < 1e-3 for a, b in zip(v.pos, gen_space)) for v in got.parts[0].vertices),
          "the points stay where the mesh was (converted into the generator's space)")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
