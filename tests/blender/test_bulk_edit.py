"""Headless test: bulk editing records (All Selected, Copy Draw Common / section / tab to Selected)."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import traceback
from types import SimpleNamespace

common.register()
import bpy  # noqa: E402
from albam.engines.mtfw import effect, effect_editor, effect_export, effect_keys, effect_sim  # noqa: E402
from albam.engines.mtfw.efl import EffectList  # noqa: E402
from albam.engines.mtfw.efl.edit import keyframe_props  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def select(active, *others):
    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    for ob in (active,) + others:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = active
    effect_editor.load_record(state, active)


def exported():
    return EffectList.from_bytes(effect_export.build_efl_bytes(root)[0]).records


try:
    scene = bpy.context.scene
    scene.render.fps = 60
    scene.albam.rfs.add_root_folder("dmc4", common.NERO)
    scene.albam.import_options_efl.load_textures = False
    rel = r"effect\efl\com\ec000_00v2.efl"
    data = open(os.path.join(common.NERO, rel), "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec000_00v2.efl", relative_path=rel,
                                    get_bytes=lambda: data), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    records = {int(o["efl_record"]): o for o in effect_export.all_record_objects(root)}
    kinds = {i: o["efl_particle_type"] for i, o in records.items()}
    print("types:", kinds)
    poly = [i for i, k in kinds.items() if k == "Polygon"]
    prim = [i for i, k in kinds.items() if k == "PrimModel"]
    line = [i for i, k in kinds.items() if k == "Line"]
    a, b, c = records[poly[0]], records[poly[1]], records[prim[0]]
    state = scene.albam.efl_editor
    state.live = False

    # -- edits go to every selected record ------------------------------------------------------------
    select(a, b, c)
    check(set(effect_editor.selected_records(bpy.context, a)) == {b, c}, "the other selected records are found")
    state.fields["ptcl/Intensity"].floats[0] = 3.5
    check(all(abs(list(o["efl_ptcl"]["Intensity"])[0] - 3.5) < 1e-6 for o in (a, b, c)),
          "an Intensity edit goes to every selected record (Polygon, Polygon, PrimModel)")
    state.fields["ptcl/BlendSrc"].enum_value = "1"   # a dropdown
    check(all(int(o["efl_ptcl"]["BlendSrc"]) == 1 and (int(o["efl_ptcl"]["PrimMaterialFlags"]) & 0xF) == 1
              for o in (a, b, c)), "a bit-field edit updates each record's word too")
    state.fields["ptcl/Width"].floats[0] = 77.0
    check(abs(list(b["efl_ptcl"]["Width"])[0] - 77.0) < 1e-6 and "Width" not in c["efl_ptcl"],
          "a Polygon-only field reaches the other Polygon and skips the PrimModel")
    check("1 without it" in state.multi_report, f"the panel says so ({state.multi_report!r})")
    select(a)
    state.fields["ptcl/Intensity"].floats[0] = 1.25
    check(abs(list(b["efl_ptcl"]["Intensity"])[0] - 3.5) < 1e-6, "with one record selected only it changes")

    # -- the records list: Outliner-like clicks and selection buttons ---------------------------------------
    effect_editor.sync_records(state, root, a)
    row = {item.ob: i for i, item in enumerate(state.records)}
    bpy.ops.albam.efl_pick_record(index=row[b], mode="EXTEND")   # Shift+click
    check(a.select_get() and b.select_get() and bpy.context.view_layer.objects.active == b and state.target == b,
          "Shift+click adds the record, shows it and keeps the others selected")
    check(set(effect_editor.selected_records(bpy.context, b)) == {a}, "... so edits reach both")
    bpy.ops.albam.efl_pick_record(index=row[c], mode="TOGGLE")   # Ctrl+click: add
    check(c.select_get() and a.select_get() and b.select_get(), "Ctrl+click adds an unselected record")
    bpy.ops.albam.efl_pick_record(index=row[c], mode="TOGGLE")   # Ctrl+click: remove
    check(not c.select_get() and a.select_get() and b.select_get() and state.target in (a, b),
          "Ctrl+click again removes it, another selected record is shown")
    bpy.ops.albam.efl_pick_record(index=row[c], mode="SET")   # plain click
    check(c.select_get() and not a.select_get() and not b.select_get() and state.target == c,
          "a plain click selects the record alone")
    check(next(item for item in state.records if item.ob == c).selected and
          not next(item for item in state.records if item.ob == a).selected, "the rows mirror the selection")
    select(a)
    effect_editor.sync_records(state, root, a)
    bpy.ops.albam.efl_select_records(mode="TYPE")
    polys = {records[i] for i in poly}
    check({o for o in records.values() if o.select_get()} == polys, f"Same Type selects the {len(polys)} Polygons")
    bpy.ops.albam.efl_select_records(mode="ALL")
    check(all(o.select_get() for o in records.values()), "All selects every record")
    bpy.ops.albam.efl_select_records(mode="NONE")
    check([o for o in records.values() if o.select_get()] == [a], "None keeps only the record shown")

    # -- the selection survives a rebuild (a blending edit rebuilds the effect) ----------------------------
    # what the user clicks in the viewport: the particles objects, not the Empties
    def particles_of(record):
        return next(o for o in bpy.data.objects if o.get("efl_generator") == record and effect_sim.SIM_KEY in o)
    pa, pb = particles_of(a), particles_of(b)
    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    pa.select_set(True)
    pb.select_set(True)
    c.select_set(True)
    bpy.context.view_layer.objects.active = pa
    effect_editor.load_record(state, a)
    state.live = True
    state.fields["ptcl/BlendOp"].enum_value = "1"
    effect_editor._live_apply()
    check(not state.live_error, f"the live rebuild ran ({state.live_error!r})")
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    records = {int(o["efl_record"]): o for o in effect_export.all_record_objects(root)}
    a, b, c = records[poly[0]], records[poly[1]], records[prim[0]]
    pa, pb = particles_of(a), particles_of(b)
    check(pa.select_get() and pb.select_get() and c.select_get(),
          "after the rebuild the same particles objects and Empty are selected")
    check(bpy.context.view_layer.objects.active == pa, "... and the clicked particles object is active again")
    check(sum(o.select_get() for o in bpy.context.view_layer.objects) == 3, "... and nothing else")
    state.live = False

    # -- Copy Draw Common ----------------------------------------------------------------------------
    select(a)
    state.fields["ptcl/Color0"].color_a = (1.0, 0.0, 0.5, 1.0)
    start, rate = effect_keys.timing(root)
    off = effect_keys.wanted_offset(a, "ptcl", "KeyframeIntensityParamOffset")
    scene.frame_set(start + off + 0)
    bpy.ops.albam.efl_key_insert(track="ptcl:KeyframeIntensityParamOffset")
    scene.frame_set(start + off + 20)
    a["Particle Intensity"] = 6.0
    bpy.ops.albam.efl_key_insert(track="ptcl:KeyframeIntensityParamOffset")
    targets = (b, c) + tuple(records[i] for i in line[:1])
    select(a, *targets)
    result = bpy.ops.albam.efl_copy_to_selected(group="draw_common")
    check(result == {"FINISHED"}, "Copy Draw Common to Selected runs")
    out = exported()
    src = out[poly[0]].ptcl
    for o in targets:
        t = out[int(o["efl_record"])].ptcl
        same = all(t.get(n) == src.get(n) for n in ("Intensity", "Scale", "ScaleAdd", "ColorFlag", "Color0", "Color1"))
        check(same, f"record {int(o['efl_record'])} ({o['efl_particle_type']}) has the draw common values")
        kf = keyframe_props(t).get("KeyframeIntensityParamOffset")
        check(kf is not None and list(kf["frames"]) == [0, 20] and abs(kf["params"][2] - 6.0) < 1e-6,
              f"... and the Intensity keys ({kf and list(kf['frames'])})")
    check(abs(list(c["efl_ptcl"]["Width"] if "Width" in c["efl_ptcl"] else [0])[0]) < 1e-9 or "Width" not in c["efl_ptcl"],
          "fields outside the block are left alone")

    # -- a section and a tab ---------------------------------------------------------------------------
    select(a)
    state.fields["ptcl/BlendDst"].enum_value = "1"
    select(a, b)
    bpy.ops.albam.efl_copy_to_selected(group="draw", keys=False)
    check(int(b["efl_ptcl"]["BlendDst"]) == 1, "Copy section (Drawing & Blending) carries the blending")
    life_before = list(c["efl_life"]["KeepFrame"])
    state.tab = "life"
    select(a)
    state.fields["life/KeepFrame"].ints[0] = 42
    select(a, c)
    bpy.ops.albam.efl_copy_to_selected(group="tab:life")
    check(list(c["efl_life"]["KeepFrame"])[0] == 42 and life_before[0] != 42 or list(c["efl_life"]["KeepFrame"])[0] == 42,
          "Copy Tab (Life) to a record of another type")
    out = exported()
    check(out[int(c["efl_record"])].life.get("KeepFrame")[0] == 42, "and it exports")

    # -- Generator Common: spawn settings yes, placement no
    state.tab = "gen"
    select(a)
    pos_b, scale_b = tuple(b.location), tuple(b.scale)
    state.fields["gen/WaitFrame"].ints[0] = 9
    state.fields["gen/SetNum"].ints[0] = 4
    a.scale = (2.0, 2.0, 2.0)
    select(a, b)
    bpy.ops.albam.efl_copy_to_selected(group="gen_common")
    check(list(b["efl_gen"]["WaitFrame"])[0] == 9 and list(b["efl_gen"]["SetNum"])[0] == 4,
          "Generator Common copies the spawn settings")
    check(tuple(b.location) == pos_b and tuple(b.scale) == scale_b, "... but not the placement (Pos, Scale)")
    out = exported()
    check(out[int(b["efl_record"])].gen.get("WaitFrame")[0] == 9, "and it exports")

    # -- one field at a time
    state.tab = "ptcl"
    select(a)
    a_int, b_color = list(a["efl_ptcl"]["Intensity"]), list(b["efl_ptcl"]["Color0"])
    state.fields["ptcl/Intensity"].floats[0] = 9.0
    b_int_before = list(b["efl_ptcl"]["Intensity"])
    check(abs(b_int_before[0] - 9.0) > 1e-6, "(one record selected: the edit stayed on it)")
    select(a, b, c)
    bpy.ops.albam.efl_copy_field_to_selected(field="ptcl/Intensity", track="ptcl:KeyframeIntensityParamOffset",
                                             keys=False)
    check(all(abs(list(o["efl_ptcl"]["Intensity"])[0] - 9.0) < 1e-6 for o in (b, c)),
          "Copy Field: Intensity reaches both other records")
    check(list(b["efl_ptcl"]["Color0"]) == b_color, "... and nothing else changes (Color0 kept)")
    select(a)
    state.fields["ptcl/Color1"].color_a = (0.0, 1.0, 0.0, 1.0)
    select(a, b, c)
    bpy.ops.albam.efl_copy_field_to_selected(field="ptcl/Color1")
    check(list(b["efl_ptcl"]["Color1"]) == list(a["efl_ptcl"]["Color1"]) and list(b["efl_ptcl"]["Color0"]) == b_color,
          "Copy Field: Color1 alone")
    # a keyframe track alone (Keys tab row): clear the target's Intensity keys, copy the track back
    select(b)   # the Keys tab acts on the record shown
    bpy.ops.albam.efl_keys_clear(track="ptcl:KeyframeIntensityParamOffset")
    check(effect_keys.key_count(b, "ptcl", "KeyframeIntensityParamOffset") == 0, "(the target's keys are cleared)")
    select(a, b)
    bpy.ops.albam.efl_copy_field_to_selected(field="", track="ptcl:KeyframeIntensityParamOffset")
    check(effect_keys.key_count(b, "ptcl", "KeyframeIntensityParamOffset") == 2, "Copy track alone brings the keys back")

    # -- the panel draws the bulk box -----------------------------------------------------------------
    class Stub:
        def __getattr__(self, name):
            return lambda *a, **k: Stub()
        enabled = True

    class Panel(effect_editor._EflEditorDraw):
        layout = Stub()

    state.tab = "ptcl"
    Panel().draw(bpy.context)
    check(True, "the panel draws with several records selected")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
