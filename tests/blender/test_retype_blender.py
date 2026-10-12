import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, traceback
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_editor, effect_export, effect_retype
from albam.engines.mtfw.efl import EffectList

PATH = common.DATA + r"\arctool\uPlayerNero-vanilla\effect\efl\com\ec000_03v3.efl"
DATA = open(PATH, "rb").read()
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class FakeFile:
    app_id = "dmc4"
    display_name = "ec000_03v3.efl"
    relative_path = r"effect\efl\com\ec000_03v3"

    def get_bytes(self):
        return DATA


class Stub:
    def __init__(self):
        self.label_texts = []
        self.ops = []
    def __getattr__(self, name):
        def f(*a, **k):
            if name == "label":
                self.label_texts.append(k.get("text"))
            if name == "operator":
                self.ops.append(a[0] if a else k.get("operator"))
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


try:
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", common.DATA + r"\arctool\uPlayerNero-vanilla")
    opts = scene.albam.import_options_efl
    opts.load_textures = False
    opts.sim_frames = 60
    effect.load_efl(FakeFile(), bpy.context)
    root = root_now()
    src = EffectList.from_bytes(DATA)
    n_records = len(src.records)
    rec0 = record(root, 0)
    old_ptcl = dict(rec0["efl_ptcl"])
    print("   record 0:", rec0["efl_particle_type"], rec0["efl_move_type"], "kf:", list((rec0.get("efl_kf") or {}).keys()))
    activate(rec0)

    # panel shows the button
    layout = Stub(); p = type("P", (), {})(); p.layout = layout
    state = scene.albam.efl_editor
    effect_editor.load_record(state, rec0)
    state.tab = "ptcl"
    effect_editor.ALBAM_PT_EflEditor.draw(p, bpy.context)
    check("albam.efl_change_type" in layout.ops, "Particle tab shows Change Type")

    # 1. Billboard -> Polygon
    edited_color = [10, 20, 30, 255]
    rec0["efl_ptcl"]["Color0"] = edited_color      # an unapplied edit must survive the change
    res = bpy.ops.albam.efl_change_type(slot="ptcl", new_type="2")
    check(res == {"FINISHED"}, f"change ptcl to Polygon ({res})")
    root = root_now()
    rec0 = record(root, 0)
    check(rec0["efl_particle_type"] == "Polygon" and int(rec0["efl_ptcl"]["type"]) == 2, "record 0 is a Polygon")
    check(list(rec0["efl_ptcl"]["Color0"]) == edited_color, "unapplied Color0 edit kept")
    check(rec0["efl_ptcl"]["BaseMapPath"] == old_ptcl["BaseMapPath"], "texture path kept")
    check(len(effect_export.all_record_objects(root)) == n_records, "record count unchanged")
    data, notes, order = effect_export.build_efl_bytes(root)
    new = EffectList.from_bytes(data)
    check(new.records[0].ptcl.type == 2, "exported record 0 ptcl type 2 (same position)")
    same = all(bytes(a.ptcl.data) == bytes(b.ptcl.data) and bytes(a.move.data) == bytes(b.move.data)
               for a, b in zip(src.records[1:], new.records[1:]))
    check(same, "other records' blocks byte-identical")
    check(not rec0.get("efl_replaced"), "rebuilt: no pending replacement left")
    check(any(o.get("efl_generator") == rec0 for o in bpy.data.objects), "Polygon preview object built")

    # 2. move -> Add, keyframes kept
    activate(rec0)
    old_move = rec0["efl_move_type"]
    res = bpy.ops.albam.efl_change_type(slot="move", new_type="1")
    root = root_now(); rec0 = record(root, 0)
    check(res == {"FINISHED"} and rec0["efl_move_type"] == "Add", f"move {old_move} -> Add")

    # 3. Polyline CHAIN from a game example
    activate(rec0)
    res = bpy.ops.albam.efl_change_type(slot="ptcl", new_type="1", variant="3")
    root = root_now(); rec0 = record(root, 0)
    check(res == {"FINISHED"} and rec0["efl_ptcl"]["LineType"] == 3 and "+CHAIN" in rec0["efl_ptcl"]["struct"],
          f"Polyline CHAIN ({rec0['efl_ptcl'].get('struct')})")

    # 4. cloth ZIGZAG (template or defaults)
    activate(rec0)
    res = bpy.ops.albam.efl_change_type(slot="ptcl", new_type="12", variant="2")
    root = root_now(); rec0 = record(root, 0)
    check(res == {"FINISHED"} and "+ClothZIGZAG" in rec0["efl_ptcl"]["struct"], f"ClothPolyline ZIGZAG ({rec0['efl_ptcl'].get('struct')})")
    scene.frame_set(scene.frame_current + 10)

    # 5. Hit with no example anywhere -> refused cleanly (if no template exists)
    activate(rec0)
    tpl, _ = effect_retype.find_template(bpy.context, "ptcl", 11, None)
    try:
        res = bpy.ops.albam.efl_change_type(slot="ptcl", new_type="11")
    except RuntimeError as err:
        res = str(err)
    print("   Hit:", "template found" if tpl else "no template", res)
    check((tpl is None and res != {"FINISHED"}) or (tpl is not None and res == {"FINISHED"}), "Hit handled")

    # 6. duplicate + revert + export after changes
    root = root_now(); rec0 = record(root, 0); activate(rec0)
    check(bpy.ops.albam.efl_duplicate_record() == {"FINISHED"}, "duplicate a changed record")
    root = root_now()
    data, notes, order = effect_export.build_efl_bytes(root)
    again = EffectList.from_bytes(data)
    check(len(again.records) == n_records + 1 and again.records[-1].ptcl.type == again.records[0].ptcl.type,
          "duplicate has the changed type")
    rec0 = record(root, 0); activate(rec0)
    effect_editor.load_record(state, rec0)
    check(bpy.ops.albam.efl_revert_record() == {"FINISHED"}, "revert fields after change")
    # pending replacement (no rebuild) also exports
    rec1 = record(root, 1)
    blk = effect_retype.current_block(rec1, "ptcl")
    from albam.engines.mtfw.efl.retype import retype
    new_blk, _ = retype(blk, 0, None, None)
    effect_retype.store_block(rec1, new_blk)
    check(effect_export.structure_changed(root), "pending replacement counts as a structure change")
    data, notes, order = effect_export.build_efl_bytes(root)
    check(EffectList.from_bytes(data).records[1].ptcl.type == 0, "pending replacement exported in place")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
