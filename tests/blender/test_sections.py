import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, traceback, os, glob, collections, random
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_editor, effect_sim
from albam.engines.mtfw.efl import EffectList, schema, sim, ean

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Stub:
    def __init__(self):
        self.calls = []
    def __getattr__(self, name):
        def f(*a, **k):
            self.calls.append((name, a, k))
            return self
        return f


try:
    # 1. every particle field / bit of every type and extension gets a section; list what falls in "other"
    structs = [s for s in schema.all_structs() if "PARTICLE" in s.name]
    bases = list(structs)
    for key in schema.EXTENSIONS:
        for s in bases:
            try:
                structs.append(schema.extended_struct(s, key))
            except Exception:
                pass
    other = collections.Counter()
    for st in structs:
        for f in st.fields:
            if f.sub:
                continue
            ext = f.offset >= st.base_size
            if effect_editor.ptcl_section(f.name, extension=ext) == "other":
                other[f.name] += 1
            for b in st.bits:
                if b.field == f.name and effect_editor.ptcl_section(b.name, f.name, ext) == "other":
                    other["bit " + b.name] += 1
    print("   in Other:", sorted(other))
    check(all(n.startswith("member_") or n == "PrimFlags2" for n in other),
          "only fields the DX9 game doesn't read (member_*, PrimFlags2) fall in Other")

    # 2. import an effect, load a few records of different types, draw the Particle tab
    ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
    REL = r"effect\efl\com\ec000_00v2"
    DATA = open(os.path.join(ROOT, REL + ".efl"), "rb").read()

    class F:
        app_id = "dmc4"
        display_name = "ec000_00v2.efl"
        relative_path = REL + ".efl"
        def get_bytes(self):
            return DATA

    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    scene.albam.import_options_efl.sim_frames = 30
    effect.load_efl(F(), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    state = scene.albam.efl_editor
    seen_types = set()
    for ob in effect_export.all_record_objects(root):
        props = ob.get("efl_ptcl")
        if props is None or props["type_name"] in seen_types:
            continue
        seen_types.add(props["type_name"])
        bpy.context.view_layer.objects.active = ob
        effect_editor.load_record(state, ob)
        state.tab = "ptcl"
        items = [i for i in state.fields if i.slot == "ptcl"]
        unsorted = [i.label for i in items if not i.section]
        layout = Stub(); p = type("P", (), {})(); p.layout = layout
        effect_editor.ALBAM_PT_EflEditor.draw(p, bpy.context)
        headers = [k["text"] for n, a, k in layout.calls if n == "prop" and a[1:2] == ("ptcl_open",)]
        drawn = sum(1 for n, a, k in layout.calls if n == "operator" and a and a[0] == "albam.efl_field_info")
        print(f"   {props['type_name']}: {len(items)} fields -> {headers}; {drawn} drawn")
        check(not unsorted and headers, f"{props['type_name']}: every field has a section and headers are drawn")
        # search opens every section
        state.search = "a"
        layout = Stub(); p.layout = layout
        effect_editor.ALBAM_PT_EflEditor.draw(p, bpy.context)
        drawn_search = sum(1 for n, a, k in layout.calls if n == "operator" and a and a[0] == "albam.efl_field_info")
        want = sum(1 for i in items if "a" in i.label.lower() and (state.show_unverified or i.tier in effect_editor.VERIFIED_TIERS))
        check(drawn_search == want, f"{props['type_name']}: searching shows all {want} matches in collapsed sections too")
        state.search = ""
        if "AnimFlag" in [i.label for i in items]:
            item = next(i for i in items if i.label == "AnimFlag")
            check(item.kind == "flags", "AnimFlag is checkboxes")
    check(list(state.ptcl_open) == [k in ("tex", "color", "size") for k, *_ in effect_editor.PTCL_SECTIONS],
          "Texture, Colour and Size open by default")

    # 3. ModelAnimFlag checkboxes on a Model record
    model_file = None
    for path in glob.glob(common.DATA + r"\arctool\**\*.efl", recursive=True):
        try:
            e = EffectList.from_bytes(open(path, "rb").read())
        except Exception:
            continue
        if any(r.ptcl and r.ptcl.type == 5 and r.ptcl.get("ModelAnimFlag") & 0x10 for r in e.records):
            model_file = path
            break
    print("   model file", model_file)
    if model_file:
        st = next(s for s in structs if s.name == "EFL_PARTICLE_Model")
        f = st.by_name["ModelAnimFlag"]
        state.fields.clear()
        item = effect_editor._add_field(state, "ptcl", f, 0x10010)
        check(item.kind == "flags" and item.flags[4] and item.flags[16] and not item.flags[0],
              "ModelAnimFlag is checkboxes showing UV Scroll + Use ModelZofs")

    # 4. random flips: AnimFlag 0xC00 -> each particle flips U and V with probability 1/2
    rng = random.Random(1)
    rolls = collections.Counter(sim._random_flips(0xC00, rng) for _ in range(4000))
    check(set(rolls) == {0, 0x100, 0x200, 0x300} and all(800 < n < 1200 for n in rolls.values()),
          f"0xC00 gives the four flip combinations about equally ({dict(rolls)})")
    check(all(sim._random_flips(0xD00, rng) & 0x100 == 0 for _ in range(100)),
          "a flip the record sets itself isn't flipped again")
    check(sim._random_flips(0x3, rng) == 0, "no _RAND bits, no flips (and no random draw)")
    # effect_sim row flip = uv_affine with the flag
    pattern = (16, 32, 64, 48)
    for rot in (0, 0x1000):
        rows = [[*ean.uv_affine(pattern, 256, 128, rot)[0], *ean.uv_affine(pattern, 256, 128, rot)[1], 64, 48]]
        state_ = type("S", (), {"sequence": 0, "pattern": 0, "flip": 0x300})()
        got = effect_sim._frame_row(rows, [0], [1], state_)
        want = ean.uv_affine(pattern, 256, 128, rot | 0x300)
        check(all(abs(a - b) < 1e-9 for a, b in zip(got[:6], [*want[0], *want[1]])) and got[6:] == [64, 48],
              f"per-particle flip row matches uv_affine with 0x300 (rotate={bool(rot)})")
    # a simulated 0xC00 record has a mix of flips
    for path in glob.glob(common.DATA + r"\arctool\uPlayerNero-vanilla\effect\efl\**\*.efl", recursive=True):
        e = EffectList.from_bytes(open(path, "rb").read())
        found = None
        for idx, r in enumerate(e.records):
            if r.ptcl and r.ptcl.has("AnimFlag") and r.ptcl.get("AnimFlag") & 0xC00 == 0xC00 and r.ptcl.type == 0:
                parts = sim.simulate(r, 0, 120, [8])
                if len(parts) >= 20:
                    found = idx
                    break
        if found is not None:
            break
    flips = collections.Counter(p.flip for p in parts)
    check(len(flips) == 4, f"{os.path.basename(path)} record {found}: particles get all four flips ({dict(flips)})")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
