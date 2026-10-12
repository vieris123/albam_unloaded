import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, traceback, os
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
from mathutils import Vector
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_editor, effect_ean, effect_efs
from albam.engines.mtfw.efl import efs, ean, EffectList

ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
REL = r"effect\efl\com\ec000_00v2"
DATA = open(os.path.join(ROOT, REL + ".efl"), "rb").read()
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class F:
    app_id = "dmc4"
    display_name = "ec000_00v2.efl"
    relative_path = REL + ".efl"

    def get_bytes(self):
        return DATA


class Stub:
    def __init__(self):
        self.texts = []
    def __getattr__(self, name):
        def f(*a, **k):
            if "text" in k:
                self.texts.append(k["text"])
            if a and isinstance(a[0], str) and a[0].startswith("albam."):
                self.texts.append(a[0])
            return self
        return f
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


def root_now():
    return next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")


def record(root, index):
    return next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == index)


def activate(ob):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)


def exported():
    vfiles = effect_export.export_efl(root_now())
    return {os.path.basename(v.relative_path): v for v in vfiles}


try:
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    scene.albam.import_options_efl.sim_frames = 30
    effect.load_efl(F(), bpy.context)
    root = root_now()
    src = EffectList.from_bytes(DATA)
    ps = next(i for i, r in enumerate(src.records) if r.move and r.move.type == 3)
    bb = next(i for i, r in enumerate(src.records) if i != ps and r.ptcl and r.ptcl.has("AnimPath")
              and r.ptcl.get("BaseMapPath") and not (r.ptcl.type == 6 and r.ptcl.get("PrimModelType") in (0, 2, 4)))
    print("   types:", [(i, r.ptcl.type_name if r.ptcl else None) for i, r in enumerate(src.records)])
    print(f"   billboard record {bb}, PathStrip record {ps}")

    # panel shows the New buttons
    activate(record(root, bb))
    effect_editor.load_record(scene.albam.efl_editor, record(root, bb))
    layout = Stub(); p = type("P", (), {})(); p.layout = layout
    effect_editor.ALBAM_PT_EflEditor.draw(p, bpy.context)
    check("albam.efs_new" in layout.texts and "albam.ean_new" in layout.texts, "Linked files box offers New Strip / New Flipbook")

    # 1. New Flipbook for the billboard
    res = bpy.ops.albam.ean_new(path=r"effect\ean\com\my_sheet", columns=2, cells=4, cell_size=(64, 32))
    root = root_now()
    rec = record(root, bb)
    check(res == {"FINISHED"} and rec["efl_ptcl"]["AnimPath"] == r"effect\ean\com\my_sheet", "particle points at the new flipbook")
    linked = effect.linked_objects(root)
    ob = linked.get(r"ean:effect\ean\com\my_sheet")
    check(ob is not None and ob.parent == root, "new flipbook is a linked object of the effect (kept through the rebuild)")
    img = ob.data.materials[0].node_tree.nodes.active.image
    check(img is not None and img.get("efl_texture"), f"it shows the particle's texture ({img.name if img else None})")
    out = exported()
    check("my_sheet.ean" in out, f"export writes the new .ean ({sorted(out)})")
    a = ean.parse(out["my_sheet.ean"].data_bytes)
    check(a.version == ean.VERSION_DX9 and [tuple(p) for p in a.sequences[0].patterns] ==
          [(0, 0, 64, 32), (64, 0, 64, 32), (0, 32, 64, 32), (64, 32, 64, 32)], "new .ean holds the 2 x 2 grid")
    new_efl = EffectList.from_bytes(out["ec000_00v2.efl"].data_bytes)
    check(new_efl.records[bb].ptcl.get("AnimPath") == r"effect\ean\com\my_sheet", "exported .efl points at it")
    check(not effect_export.structure_changed(root), "after creation the preview is up to date")

    # 2. New Strip from a drawn curve as the billboard's spawn strip
    curve = bpy.data.curves.new("drawn", "CURVE")
    spline = curve.splines.new("POLY")
    spline.points.add(3)
    for i, co in enumerate(((0, 0, 0), (0.5, 0, 0.2), (1.0, 0.3, 0.4), (1.5, 0.3, 0.8))):
        spline.points[i].co = (*co, 1.0)
    cob = bpy.data.objects.new("drawn", curve)
    scene.collection.objects.link(cob)
    gen = record(root_now(), bb)
    activate(gen)
    res = bpy.ops.albam.efs_new(path=r"effect\efs\com\my_strip", use_for="RANGE", source="drawn")
    root = root_now()
    gen = record(root, bb)
    check(res == {"FINISHED"} and gen["efl_gen"]["RangeStripPath"] == r"effect\efs\com\my_strip", "generator points at the new strip")
    sob = effect.linked_objects(root).get(r"efs:effect\efs\com\my_strip")
    check(sob is not None and sob.parent == gen, "new strip parented to the generator")
    out = exported()
    strip = efs.parse(out["my_strip.efs"].data_bytes)
    want = gen.matrix_world.inverted() @ Vector((1.5, 0.3, 0.8))
    got = Vector(strip[0][-1]) * 0.01
    check(len(strip) == 1 and len(strip[0]) == 4 and (got - want).length < 1e-4,
          f"strip points = the curve in generator space ({tuple(round(c, 3) for c in got)})")
    sim = next((o for o in bpy.data.objects if o.get("efl_generator") == gen and o.get("efl_sim")), None)
    check(sim is not None and sim["efl_sim"].get("range_strip"), "preview spawns along it")

    # 3. a straight line as the PathStrip record's path
    activate(record(root, ps))
    res = bpy.ops.albam.efs_new(path=r"effect\efs\com\my_path", use_for="PATH", source="LINE", points=5, length=400.0)
    root = root_now()
    rec = record(root, ps)
    check(res == {"FINISHED"} and rec["efl_move"]["PathStripPath"] == r"effect\efs\com\my_path", "PathStrip move points at the new line")
    out = exported()
    line = efs.parse(out["my_path.efs"].data_bytes)[0]
    check(len(line) == 5 and abs(line[-1][1] - 400.0) < 1e-3, "line of 5 points, 400 cm along +Y")
    sim = next((o for o in bpy.data.objects if o.get("efl_generator") == rec and o.get("efl_sim")), None)
    strip_pts = list(sim["efl_sim"]["strip"]) if sim is not None else []
    check(len(strip_pts) == 15 and abs(strip_pts[-2] - 400.0) < 1e-3, "preview rides the new path")
    check(sorted(out) == sorted(["ec000_00v2.efl", "my_sheet.ean", "my_strip.efs", "my_path.efs"]),
          f"export writes the effect and its three new files ({sorted(out)})")

    # 4. refusing a duplicate path
    activate(record(root, ps))
    try:
        res = bpy.ops.albam.efs_new(path=r"effect\efs\com\my_path", use_for="PATH", source="LINE")
    except RuntimeError as err:
        res = str(err)
    check(res != {"FINISHED"}, "a second strip at the same path is refused")

    # 5. standalone flipbook for an image (Image Editor button), via a stub context
    image = bpy.data.images.new("standalone_tex", 256, 128)
    op_self = SimpleNamespace(path=r"effect\ean\com\solo", columns=4, cells=8, cell_size=(64, 64), source="GRID",
                              report=lambda *a: print("   report", a))
    op_self.make = lambda path, image: effect_ean._NewFlipbookProps.make(op_self, path, image)
    ctx = SimpleNamespace(space_data=SimpleNamespace(image=image), collection=scene.collection, scene=scene,
                          view_layer=bpy.context.view_layer)
    res = effect_ean.ALBAM_OT_EanNewForImage.execute(op_self, ctx)
    solo = bpy.data.objects.get("EAN_solo")
    check(res == {"FINISHED"} and solo is not None and any(i.bl_object == solo for i in scene.albam.exportable.file_list),
          "standalone flipbook made for an image and added to the Export list")
    a = ean.parse(effect_ean.build_ean_bytes(solo))
    check(len(a.sequences[0].patterns) == 8 and tuple(effect_ean.uv_size(solo)) == (256, 128), "it's an 8-frame grid over the 256 x 128 image")
    # tooltips
    missing = [op for op in ("efs_new", "ean_new", "ean_new_for_image")
               if not getattr(bpy.ops.albam, op).get_rna_type().description]
    for op in ("efs_new", "ean_new", "ean_new_for_image"):
        for prop in getattr(bpy.ops.albam, op).get_rna_type().properties:
            if prop.identifier != "rna_type" and not prop.description:
                missing.append(f"{op}.{prop.identifier}")
    check(not missing, f"every new control has a tooltip {missing}")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
