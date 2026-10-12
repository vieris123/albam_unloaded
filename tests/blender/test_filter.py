import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, traceback
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_filter, effect_editor, effect_export, effect_sim

PATH = common.DATA + r"\arctool\uPlayerNero-vanilla\effect\efl\com\ec000_03v3.efl"
DATA = open(PATH, "rb").read()


class FakeFile:
    app_id = "dmc4"
    display_name = "ec000_03v3.efl"
    relative_path = r"effect\efl\com\ec000_03v3"

    def get_bytes(self):
        return DATA


class Stub:
    """Swallows any layout call."""
    def __init__(self, *a, **k):
        self.calls = []
        self.label_texts = []
    def __getattr__(self, name):
        def f(*a, **k):
            if name == "label":
                self.label_texts.append(k.get("text"))
            return self
        return f
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def visible_records(root):
    out = []
    for rec in effect_export.all_record_objects(root):
        deps = effect_filter._dependents(rec)
        shown = [d for d in deps if not d.hide_viewport]
        out.append((int(rec["efl_record"]), bool(rec.get("efl_filtered")), len(deps), len(shown)))
    return sorted(out)


try:
    scene = bpy.context.scene
    opts = scene.albam.import_options_efl
    opts.load_textures = False
    opts.sim_frames = 60
    # import options draw
    panel = Stub(); panel.layout = Stub()
    effect.draw_efl_options(panel, bpy.context)
    opts.group_all = False
    opts.group_bits[0] = True          # group 1
    opts.surface = "0x20"
    effect.draw_efl_options(panel, bpy.context)
    check(effect_filter.masks_from_options(opts) == (1, 0x20), "options -> masks (1, 0x20)")

    effect.load_efl(FakeFile(), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    check(effect_filter.get_masks(root) == (1, 0x20), "masks stored on root")
    vis = visible_records(root)
    passing = [r for r, filtered, _, _ in vis if not filtered]
    check(passing == [2, 3], f"group 1 + surface 0x20 passes records 2,3 (got {passing})")
    check(all(shown == 0 for r, f, deps, shown in vis if f), "filtered records' objects hidden")
    check(all(shown > 0 or deps == 0 for r, f, deps, shown in vis if not f), "passing records' objects visible")
    sims = effect_sim._sim_objects(scene)
    check(all(effect_export.record_object(o)["efl_record"] in (2, 3) for o in sims),
          f"handler only updates passing records ({len(sims)} sim objects)")

    # editor: load + change masks
    state = scene.albam.efl_editor
    rec0 = next(o for o in effect_export.all_record_objects(root) if o["efl_record"] == 0)
    bpy.context.view_layer.objects.active = rec0
    effect_editor.load_record(state, rec0)
    check(state.records_root == root and not state.group_all and state.group_bits[0] and state.surface == "0x20",
          "editor shows the effect's masks")
    state.group_all = True
    state.surface = "0x01"   # 0xf records
    check(effect_filter.get_masks(root) == (effect_filter.ALL, 1), "editor edit stores masks")
    passing = [r for r, f, _, _ in visible_records(root) if not f]
    check(passing == [0, 1, 6, 7, 12, 13], f"all groups + surface 1 -> 0xf records (got {passing})")
    check(int(root["efl_filter_shown"]) == 6, "shown count")
    state.surface = "ALL"
    check(all(not f for _, f, _, _ in visible_records(root)), "all/all shows every record")
    check(all(shown > 0 or deps == 0 for _, _, deps, shown in visible_records(root)), "unhidden again")
    # source shapes stay hidden (GN sources were hidden before the filter)
    srcs = [o for o in bpy.data.objects if o.hide_viewport and "efl_filter_hidden" not in o]
    print("   objects hidden by the importer itself:", len(srcs))

    # panel draw
    layout = Stub()
    p = type("P", (), {})(); p.layout = layout
    effect_editor.ALBAM_PT_EflEditor.draw(p, bpy.context)
    check(any(t and t.startswith("Records' groups") for t in layout.label_texts), "panel draws filter summary")
    print("  ", [t for t in layout.label_texts if t and ("Records'" in t or "Showing" in t)])

    # field tooltips
    for name in ("gen/GroupFlag", "gen/MaterialFlag", "gen/Scale", "gen/Pos"):
        item = state.fields.get(name)
        tip = effect_editor.ALBAM_OT_EflFieldInfo.description(bpy.context, type("Pr", (), {"field": name})())
        check(item is not None and len(tip) > 20, f"tooltip {name}")
        print("    " + tip.replace("\n", "\n    "))
    n_tips = sum(1 for it in state.fields if effect_editor.field_tooltip(it))
    check(n_tips == len(state.fields), f"every field has a tooltip ({n_tips})")

    # editing GroupFlag re-filters
    state.group_all = False
    for i in range(16):
        state.group_bits[i] = (i == 1)       # group 2
    item = state.fields.get("gen/GroupFlag")   # record 0 has group 1
    check(rec0.get("efl_filtered"), "record 0 filtered with group 2")
    item.text = "0x3"
    check(not rec0.get("efl_filtered"), "editing GroupFlag to 3 re-filters record 0 in")
    item.text = "0x1"

    # export unaffected
    data, notes, order = effect_export.build_efl_bytes(root)
    check(data == DATA, f"export byte-identical with filter on ({len(notes)} notes)")

    # rebuild keeps masks
    new_root, _, rebuilt = effect_export.apply_to_scene(bpy.context, root, rebuild=True)
    check(rebuilt and effect_filter.get_masks(new_root) == (2, effect_filter.ALL), "rebuild keeps masks")
    passing = [r for r, f, _, _ in visible_records(new_root) if not f]
    check(passing == [6, 7, 8, 9, 10, 11], f"rebuilt effect filtered by group 2 (got {passing})")

    # nothing passes
    state.group_all, state.surface = True, "0x80"
    check(int(new_root["efl_filter_shown"]) == 0, "surface 0x80 -> nothing shown")
    layout = Stub(); p.layout = layout
    effect_editor.ALBAM_PT_EflEditor.draw(p, bpy.context)
    check(any(t and "No record passes" in t for t in layout.label_texts), "panel warns when nothing passes")
    scene.frame_set(scene.frame_current + 5)   # handler with everything hidden
    check(True, "frame change with everything filtered")

    # help coverage over many record types
    import glob
    from albam.engines.mtfw.efl.field_help import lookup
    opts.build_geometry = False
    opts.simulate = False
    opts.group_all, opts.surface = True, "ALL"
    missing, seen_types, fields_seen = set(), set(), 0
    files = sorted(glob.glob(common.DATA + r"\arctool\uPlayerNero-vanilla\effect\efl\**\*.efl", recursive=True))
    for path in files:
        data = open(path, "rb").read()
        class F(FakeFile):
            display_name = path.split("\\")[-1]
            def get_bytes(self):
                return data
        before = set(bpy.data.objects)
        effect.load_efl(F(), bpy.context)
        for ob in set(bpy.data.objects) - before:
            if "efl_record" not in ob:
                continue
            seen_types.add((ob.get("efl_particle_type"), ob.get("efl_move_type")))
            effect_editor.load_record(state, ob)
            for it in state.fields:
                fields_seen += 1
                if not lookup(it.help_key):
                    missing.add(it.help_key)
                effect_editor.field_tooltip(it)
    check(not missing, f"help for every field over {len(files)} files, {len(seen_types)} type combos, "
                       f"{fields_seen} fields (missing: {sorted(missing)})")
except Exception:
    traceback.print_exc()
    failures.append("exception")

print("FAILURES:", failures)
