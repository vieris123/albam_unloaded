import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, traceback, os
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_editor
from albam.engines.mtfw.efl import EffectList
ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
REL = r"effect\efl\com\ec000_04v1"
DATA = open(os.path.join(ROOT, REL + ".efl"), "rb").read()
failures = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: failures.append(m)
class F:
    app_id = "dmc4"; display_name = "ec000_04v1.efl"; relative_path = REL + ".efl"
    def get_bytes(self): return DATA
class Stub:
    def __init__(self): self.texts = []
    def __getattr__(self, n):
        def f(*a, **k):
            if "text" in k: self.texts.append(k["text"])
            return self
        return f
    def __setattr__(self, n, v): object.__setattr__(self, n, v)
try:
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    scene.albam.import_options_efl.simulate = False
    effect.load_efl(F(), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    src = EffectList.from_bytes(DATA)
    idx = next(i for i, r in enumerate(src.records) if r.ptcl and r.ptcl.has("ColorFlag") and r.ptcl.get("ColorFlag") == 0x1F)
    rec = next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == idx)
    bpy.context.view_layer.objects.active = rec
    state = scene.albam.efl_editor
    effect_editor.load_record(state, rec)
    tm, cf = state.fields.get("ptcl/TransMode"), state.fields.get("ptcl/ColorFlag")
    check(tm.kind == "flags" and cf.kind == "flags", "TransMode and ColorFlag load as checkboxes")
    check(tm.flags[0] and not tm.flags[1] and all(cf.flags[i] for i in range(5)), "checkboxes show the stored bits (TransMode 1, ColorFlag 0x1F)")
    tm.flags[1] = True     # also draw in reflections
    cf.flags[4] = False    # shared random
    check(int(rec["efl_ptcl"]["TransMode"]) == 3 and int(rec["efl_ptcl"]["ColorFlag"]) == 0xF, "ticking writes the values (3, 0xF)")
    rec["efl_ptcl"]["ColorFlag"] = 0x4F   # an unnamed bit (0x40) must survive a checkbox edit
    effect_editor.load_record(state, rec)
    cf = state.fields.get("ptcl/ColorFlag")
    cf.flags[0] = False
    check(int(rec["efl_ptcl"]["ColorFlag"]) == 0x4E, "unnamed bits are kept (0x4F -> 0x4E)")
    layout = Stub(); p = type("P", (), {})(); p.layout = layout
    state.tab = "ptcl"; state.show_unverified = True
    state.ptcl_open = [True] * len(state.ptcl_open)   # TransMode is in the Drawing section, collapsed by default
    effect_editor.ALBAM_PT_EflEditor.draw(p, bpy.context)
    check("World (main view)" in layout.texts and "Each Channel Random" in layout.texts and any(t and "other bits 0x40 kept" in t for t in layout.texts),
          "panel draws labelled checkboxes and notes kept bits")
    data, notes, _ = effect_export.build_efl_bytes(root)
    out = EffectList.from_bytes(data).records[idx].ptcl
    check(out.get("TransMode") == 3 and out.get("ColorFlag") == 0x4E, "export writes them")
    tip = effect_editor.field_tooltip(state.fields.get("ptcl/ColorFlag"))
    check("Color1" in tip and "Tick the flags" in tip, "tooltip explains the flags")
except Exception:
    traceback.print_exc(); failures.append("exception")
print("FAILURES:", failures)
