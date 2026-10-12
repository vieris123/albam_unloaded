"""Headless test: meshes into flipbooks (Ctrl+J repair, New Flipbook frames from a mesh)."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_ean, effect_editor, effect_export
from albam.engines.mtfw.effect import linked_objects
from albam.engines.mtfw.efl import ean

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def depsgraph(ob):
    effect_editor._on_depsgraph(bpy.context.scene, SimpleNamespace(updates=[
        SimpleNamespace(id=ob, is_updated_geometry=True)]))
    effect_editor._live_apply()


def plane(location, uv_rect=None):
    bpy.ops.mesh.primitive_plane_add(size=1, location=location)
    ob = bpy.context.active_object
    if uv_rect is not None:   # (u0, v0, u1, v1)
        u0, v0, u1, v1 = uv_rect
        layer = ob.data.uv_layers.active
        for poly in ob.data.polygons:
            for i in poly.loop_indices:
                u, v = layer.data[i].uv
                layer.data[i].uv = (u0 + u * (u1 - u0), v0 + v * (v1 - v0))
    return ob


def join(source, target):
    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    source.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.join()


ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
try:
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    state = scene.albam.efl_editor
    state.live = True

    # 1. Ctrl+J into a standalone flipbook
    path = os.path.join(ROOT, r"effect\ean\com\ec032_06.ean")
    data = open(path, "rb").read()
    effect_ean.load_ean(SimpleNamespace(app_id="dmc4", display_name="ec032_06.ean",
                                        relative_path="effect/ean/com/ec032_06.ean", get_bytes=lambda: data), bpy.context)
    fb = bpy.context.active_object
    before = ean.parse(effect_ean.build_ean_bytes(fb))
    W, H = effect_ean.uv_size(fb)
    p = plane((3, 0, 0), (0.0, 0.5, 0.25, 0.75))   # a quarter-width, quarter-height cell
    join(p, fb)
    depsgraph(fb)
    after = ean.parse(effect_ean.build_ean_bytes(fb))
    n0 = len(before.sequences[0].patterns)
    check(len(after.sequences[0].patterns) == n0 + 1, f"the joined face is a new frame of sequence 0 ({n0} -> "
                                                       f"{len(after.sequences[0].patterns)})")
    check(after.sequences[0].patterns[:n0] == before.sequences[0].patterns, "the old frames are unchanged")
    check(after.sequences[0].patterns[-1] == (0, H // 4, W // 4, H // 4),
          f"it comes last, with its own UV rectangle ({after.sequences[0].patterns[-1]}, sheet {W} x {H})")
    check(all(s1.patterns == s0.patterns for s0, s1 in zip(before.sequences[1:], after.sequences[1:])),
          "other sequences unchanged")
    depsgraph(fb)
    check(ean.parse(effect_ean.build_ean_bytes(fb)).sequences[0].patterns == after.sequences[0].patterns,
          "a second update changes nothing")

    # 2. Ctrl+J into an effect's linked flipbook applies the effect
    rel = r"effect\efl\com\ec000_00v2.efl"
    edata = open(os.path.join(ROOT, rel), "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec000_00v2.efl", relative_path=rel,
                                    get_bytes=lambda: edata), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    linked = next(ob for key, ob in linked_objects(root).items() if key.startswith("ean:"))
    linked.hide_set(False)
    n_before = sum(len(s.patterns) for s in effect_ean.ean_from_object(linked).sequences)
    join(plane((5, 0, 0), (0.5, 0.5, 1.0, 1.0)), linked)
    depsgraph(linked)
    linked = next(ob for key, ob in linked_objects(next(o for o in bpy.data.objects
                                                         if o.albam_asset.extension == "efl")).items()
                  if key.startswith("ean:") and ob.name == linked.name)
    n_after = sum(len(s.patterns) for s in effect_ean.ean_from_object(linked).sequences)
    check(n_after == n_before + 1 and not state.live_error, f"a linked flipbook gains the frame and the effect applies "
                                                            f"({n_before} -> {n_after}, {state.live_error!r})")

    # 3. New Flipbook with frames from a mesh: a 2 x 2 grid of faces over the sheet
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=2, y_subdivisions=2, size=1, location=(0, 4, 0))
    grid = bpy.context.active_object
    grid.name = "FrameSource"
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    record = next(o for o in effect_export.all_record_objects(root) if (o.get("efl_ptcl") or {}).get("AnimPath"))
    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    bpy.context.view_layer.objects.active = record
    image = effect_ean.ALBAM_OT_EanNew._image(None, record)
    size = effect_ean._sheet_size(image)
    rects = effect_ean.rects_from_mesh(grid, size)
    check(len(rects) == 4 and all(r[2] > 0 and r[3] > 0 for r in rects), f"4 frames from a 2 x 2 grid ({rects})")
    try:
        result = bpy.ops.albam.ean_new(path="effect\\ean\\com\\from_mesh", source="FrameSource")
    except Exception as err:
        result = err
    print("  ean_new:", result)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    print("  linked:", sorted(linked_objects(root)))
    new = linked_objects(root).get("ean:effect\\ean\\com\\from_mesh")
    check(new is not None, "the new flipbook is linked to the effect")
    if new is not None:
        anim = ean.parse(effect_ean.build_ean_bytes(new))
        check(anim.sequences[0].patterns == rects, "its frames are the faces' UV rectangles, in face order")

    # 4. a mesh without UV area per face is refused with the face numbers
    bad = plane((0, 8, 0), (0.2, 0.2, 0.2, 0.2))
    try:
        effect_ean.rects_from_mesh(bad, (256, 256))
        check(False, "a face without UV area is refused")
    except Exception as err:
        check("no area" in str(getattr(err, "message", err)), f"a face without UV area is refused ({err})")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
