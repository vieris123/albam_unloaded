import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, traceback, os
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_editor, effect_efs, effect_ean
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
            return self
        return f
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


def root_now():
    return next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")


try:
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    scene.albam.import_options_efl.sim_frames = 60
    effect.load_efl(F(), bpy.context)
    root = root_now()
    linked = effect.linked_objects(root)
    print("   linked:", sorted(linked))
    efs_ob = next((o for k, o in linked.items() if k.startswith("efs:")), None)
    ean_obs = [o for k, o in linked.items() if k.startswith("ean:")]
    check(efs_ob is not None and len(ean_obs) >= 1, f"import linked 1 strip and {len(ean_obs)} flipbooks")
    check(efs_ob.parent is not None and "efl_record" in efs_ob.parent, f"strip parented to its generator ({efs_ob.parent.name})")
    check(all(o.parent == root for o in ean_obs), "flipbooks under the effect root")
    check(efs_ob.name in root.users_collection[0].objects, "linked objects in the effect's collection")
    vfiles = effect_export.export_efl(root)
    check(len(vfiles) == 1 and vfiles[0].data_bytes == DATA, "untouched export: just the .efl, byte-identical")
    check(not effect_export.structure_changed(root), "untouched: no rebuild needed")

    # edit the strip: the preview must use it after Apply
    sim_ob = next(o for o in bpy.data.objects if o.get("efl_sim") and o["efl_sim"].get("strip"))
    before = list(sim_ob["efl_sim"]["strip"])[:3]
    efs_ob.data.vertices[0].co.x += 0.5   # game-space metres: +50 cm game X
    check(effect_export.structure_changed(root), "strip edit asks for a rebuild")
    bpy.context.view_layer.objects.active = root
    res = bpy.ops.albam.efl_apply_edits()
    root = root_now()
    linked2 = effect.linked_objects(root)
    efs2 = next(o for k, o in linked2.items() if k.startswith("efs:"))
    check(res == {"FINISHED"} and efs2 == efs_ob and efs2.name in bpy.data.objects, "Apply rebuilt and kept the strip object")
    check(abs(efs2.data.vertices[0].co.x - efs_ob.data.vertices[0].co.x) < 1e-6, "strip edit survived the rebuild")
    sim_ob = next(o for o in bpy.data.objects if o.get("efl_sim") and o["efl_sim"].get("strip"))
    after = list(sim_ob["efl_sim"]["strip"])[:3]
    check(abs(after[0] - (before[0] + 50)) < 1e-2, f"preview uses the edited strip ({before[0]:.2f} -> {after[0]:.2f})")
    check(efs2.parent is not None and "efl_record" in efs2.parent, "strip re-parented to the new generator")
    check(not effect_export.structure_changed(root), "after Apply: up to date")

    # edit a flipbook frame (move frame 0 of sequence 0 one pixel wider via its UVs)
    ean_ob = next(o for k, o in effect.linked_objects(root).items() if k.startswith("ean:"))
    state = scene.albam.ean_editor
    W, H = effect_ean.uv_size(ean_ob)
    first = min((p for p in ean_ob.data.polygons), key=lambda p: p.index)
    rect = list(effect_ean.ean_from_object(ean_ob).sequences[0].patterns[0])
    uv = ean_ob.data.uv_layers[effect_ean.UV_LAYER]
    us = [uv.data[i].uv[0] for i in first.loop_indices]
    for i in first.loop_indices:
        if uv.data[i].uv[0] == max(us):
            uv.data[i].uv[0] += 1.0 / W
    vfiles = effect_export.export_efl(root)
    names = sorted(os.path.basename(v.relative_path) for v in vfiles)
    print("   exported:", names)
    check(len(vfiles) == 3, "export writes the .efl plus the edited .efs and .ean")
    efs_v = next(v for v in vfiles if v.relative_path.lower().endswith(".efs"))
    strip = efs.parse(efs_v.data_bytes)
    src = efs.parse(open(os.path.join(ROOT, r"effect\efs\com\ec000_00v2.efs"), "rb").read())
    check(abs(strip[0][0][0] - (src[0][0][0] + 50)) < 1e-2, "exported .efs has the moved point")
    ean_v = next(v for v in vfiles if v.relative_path.lower().endswith(".ean"))
    check(ean.parse(ean_v.data_bytes).sequences[0].patterns[0][2] == rect[2] + 1, "exported .ean has the edited frame")
    efl_v = next(v for v in vfiles if v.relative_path.lower().endswith(".efl"))
    check(efl_v.data_bytes == DATA, "the .efl itself is unchanged")

    # panel: linked box + select operator
    bpy.context.view_layer.objects.active = root
    layout = Stub(); p = type("P", (), {})(); p.layout = layout
    effect_editor.ALBAM_PT_EflEditor.draw(p, bpy.context)
    check(any(t and "Linked files" in t for t in layout.texts), "Effect Editor lists linked files")
    check(any(t and "edited" in t for t in layout.texts), "edited files are marked")
    res = bpy.ops.albam.efl_select_linked(name=ean_ob.name)
    check(res == {"FINISHED"} and bpy.context.view_layer.objects.active == ean_ob ,
          "select operator opens the flipbook")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
