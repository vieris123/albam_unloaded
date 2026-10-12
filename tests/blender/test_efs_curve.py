"""Headless test: a linked .efs strip converted to a curve still exports and drives the preview."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_efs, effect_editor
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
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec000_00v2.efl", relative_path=rel,
                                    get_bytes=lambda: data), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    strip = next(ob for key, ob in linked_objects(root).items() if key.startswith("efs:"))
    original = bytes(strip.albam_asset.original_bytes)
    src = efs.parse_strip(original)

    # convert the strip to a curve, as Object > Convert > Curve does
    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    strip.hide_set(False)
    strip.select_set(True)
    bpy.context.view_layer.objects.active = strip
    bpy.ops.object.convert(target="CURVE")
    strip = bpy.data.objects[strip.name]
    check(strip.type == "CURVE" and "efl_linked" in strip, f"the strip is now a curve and still linked ({strip.type})")

    out = effect_efs.build_efs_bytes(strip)
    got = efs.parse_strip(out)
    check([len(p.vertices) for p in got.parts] == [len(p.vertices) for p in src.parts],
          f"same point count per part ({[len(p.vertices) for p in got.parts]})")
    check(out == original, "an unmoved converted strip exports byte-identical")
    print("  first points:", got.parts[0].vertices[0].pos, src.parts[0].vertices[0].pos)

    # make it a smooth Bezier and move a point: the drawn curve is exported
    spline = strip.data.splines[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.curve.select_all(action="SELECT")
    bpy.ops.curve.spline_type_set(type="BEZIER")
    bpy.ops.object.mode_set(mode="OBJECT")
    strip.data.resolution_u = 4
    spline = strip.data.splines[0]
    print("  spline type after spline_type_set:", spline.type, len(spline.bezier_points), len(spline.points))
    if spline.type != "BEZIER":   # the operator needs a 3D View; build the Bezier spline directly
        pts = [p.co.xyz.copy() for p in spline.points]
        strip.data.splines.remove(spline)
        spline = strip.data.splines.new("BEZIER")
        spline.bezier_points.add(len(pts) - 1)
        for bp, co in zip(spline.bezier_points, pts):
            bp.co = co
            bp.handle_left_type = bp.handle_right_type = "AUTO"
    for bp in spline.bezier_points:   # smooth handles (the conversion leaves straight "vector" ones)
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    spline.bezier_points[1].co.z += 0.1
    got = efs.parse_strip(effect_efs.build_efs_bytes(strip))
    n_ctrl = len(spline.bezier_points)
    check(len(got.parts[0].vertices) == (n_ctrl - 1) * 4 + 1,
          f"a Bezier part exports its drawn points ({len(got.parts[0].vertices)} for {n_ctrl} control points, resolution 4)")
    check(all(abs(sum(c * c for c in v.norm) - 1) < 1e-5 for v in got.parts[0].vertices), "every point has a unit normal")
    check(got.parts[0].vertices[0].norm == src.parts[0].vertices[0].norm, "normals come from the nearest source point")

    # the live apply that crashed: structure_changed -> linked_changes -> build_efs_bytes
    state = scene.albam.efl_editor
    state.live = True
    effect_editor.schedule_live_apply(root)
    effect_editor._live_apply()
    check(not state.live_error, f"the effect applies with the curve ({state.live_error!r})")
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    files = effect_export.export_efl(root)
    check(any(f.relative_path.endswith(".efs") for f in files), "exporting the effect writes the edited strip")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
