"""Headless test: editing LineType / ClothType / a FIX line's LineOfsNum rebuilds the block for its new layout."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import traceback
from types import SimpleNamespace

common.register()
import bpy  # noqa: E402
from albam.engines.mtfw import effect, effect_editor, effect_export  # noqa: E402
from albam.engines.mtfw.efl import EffectList, schema  # noqa: E402
from albam.engines.mtfw.efl.sim import simulate  # noqa: E402

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


def exported(index):
    """The record as export writes it now, read back from the bytes."""
    out = effect_export.build_efl_bytes(root)[0]
    return EffectList.from_bytes(out).records[index]


def run_jobs():
    effect_editor._live_apply()   # the queued reload (and the live apply when on)


def item(name):
    return state.fields.get(f"ptcl/{name}")


try:
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", common.NERO)
    scene.albam.import_options_efl.load_textures = False
    rel = r"effect\efl\com\ec000_00v0.efl"
    data = open(os.path.join(common.NERO, rel), "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec000_00v0.efl", relative_path=rel,
                                    get_bytes=lambda: data), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    records = {int(o["efl_record"]): o for o in effect_export.all_record_objects(root)}
    a, b = records[2], records[3]   # two FOLLOW Polylines
    state = scene.albam.efl_editor
    state.live = False
    state.tab = "ptcl"

    select(a)
    item("HeadSize").floats[0] = 33.0   # an edit the rebuild must keep
    size_before = len(exported(2).ptcl.data)

    # FOLLOW -> CHAIN
    item("LineType").enum_value = "3"
    run_jobs()
    p = exported(2).ptcl
    check(p.get("LineType") == 3 and p.struct.name == "EFL_PARTICLE_Polyline+CHAIN",
          f"LineType CHAIN rebuilds the block with the CHAIN extension ({p.struct.name})")
    check(len(p.data) >= p.struct.size > size_before, f"the block grew to hold it ({size_before:#x} -> {len(p.data):#x})")
    check(abs(p.get("HeadSize")[0] - 33.0) < 1e-6, "the shared fields edited before are kept (HeadSize)")
    check(item("Length") is not None, "the editor shows the new CHAIN fields")
    check("rebuilt" in state.edit_note, f"the panel says the block was rebuilt ({state.edit_note!r})")
    check(len(simulate(exported(2), seed=2, max_frames=30)) > 0, "the CHAIN record simulates")

    # CHAIN -> LENGTH
    item("LineType").enum_value = "4"
    run_jobs()
    p = exported(2).ptcl
    check(p.struct.name == "EFL_PARTICLE_Polyline+LENGTH" and p.has("LineLength"), f"CHAIN -> LENGTH ({p.struct.name})")

    # LENGTH -> FIX, then LineOfsNum up and down
    item("LineType").enum_value = "1"
    run_jobs()
    p = exported(2).ptcl
    n = p.get("LineOfsNum")
    check(p.struct.name.startswith("EFL_PARTICLE_Polyline+FIX") and all(p.has(f"FixPoint{i}") for i in range(n)),
          f"LENGTH -> FIX with its {n} stored points")
    first = [list(p.get(f"FixPoint{i}")) for i in range(n)]
    item("LineOfsNum").ints[0] = n + 3
    run_jobs()
    p = exported(2).ptcl
    check(p.get("LineOfsNum") == n + 3 and p.has(f"FixPoint{n + 2}"), f"LineOfsNum {n} -> {n + 3} adds stored points")
    check([list(p.get(f"FixPoint{i}")) for i in range(n)] == first, "... keeping the existing ones")
    if n >= 2:
        step = [b_ - a_ for a_, b_ in zip(first[-2], first[-1])]
        want = [c + s for c, s in zip(first[-1], step)]
        check(all(abs(x - y) < 1e-4 for x, y in zip(p.get(f"FixPoint{n}"), want)), "new points continue the line's step")
    item("LineOfsNum").ints[0] = 2
    run_jobs()
    p = exported(2).ptcl
    check(p.get("LineOfsNum") == 2 and p.has("FixPoint1") and not p.has("FixPoint2"), "LineOfsNum down drops points")
    check(len(simulate(exported(2), seed=2, max_frames=30)) > 0, "the FIX record simulates")

    # the packed word: LineType bits changed through LineFlags
    word = item("LineFlags")
    value = int(word.text, 0)
    word.text = hex((value & ~0xFF) | 3)   # LineType 3 CHAIN in bits 0-7
    run_jobs()
    p = exported(2).ptcl
    check(p.get("LineType") == 3 and p.struct.name == "EFL_PARTICLE_Polyline+CHAIN", "editing LineFlags' LineType bits rebuilds too")

    # FOLLOW -> FIX_END: no extension either way, an ordinary edit
    select(b)
    raw_before = b.get("efl_replaced")
    item("LineType").enum_value = "2"
    run_jobs()
    check(b.get("efl_replaced") is None and raw_before is None and int(b["efl_ptcl"]["LineType"]) == 2,
          "FOLLOW -> FIX_END stays an ordinary edit (no rebuild)")
    item("LineType").enum_value = "0"

    # bulk: two records switched at once
    a_type = int(a["efl_ptcl"]["LineType"])
    select(b, a)
    item("LineType").enum_value = "4"
    run_jobs()
    check(exported(2).ptcl.struct.name == "EFL_PARTICLE_Polyline+LENGTH" and
          exported(3).ptcl.struct.name == "EFL_PARTICLE_Polyline+LENGTH",
          f"several selected records switch together (was {a_type})")

    # the whole effect still writes and reads back
    out = effect_export.build_efl_bytes(root)[0]
    check(len(EffectList.from_bytes(out).records) == len(records), "the effect writes and reads back")

    # cloth: ClothType CHAIN / CURVE / ZIGZAG on the first cloth record under arctool
    import glob
    cloth = None
    for path in sorted(glob.glob(os.path.join(common.ARCTOOL, "**", "*.efl"), recursive=True)):
        try:
            efl = EffectList.from_bytes(open(path, "rb").read())
        except Exception:
            continue
        index = next((i for i, r in enumerate(efl.records) if r.ptcl is not None and r.ptcl.type in (12, 13)), None)
        if index is not None:
            cloth = (path, index, efl.records[index].ptcl.get("ClothType"))
            break
    if cloth is None:
        print("skip: no cloth record under arctool")
    else:
        path, index, kind = cloth
        cdata = open(path, "rb").read()
        effect.load_efl(SimpleNamespace(app_id="dmc4", display_name=os.path.basename(path),
                                        relative_path=os.path.relpath(path, common.ARCTOOL), get_bytes=lambda: cdata),
                        bpy.context)
        root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl" and o.name.endswith(
            os.path.splitext(os.path.basename(path))[0]))
        rec = next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == index)
        select(rec)
        target = (kind + 1) % 3
        item("ClothType").enum_value = str(target)
        run_jobs()
        p = exported(index).ptcl
        name = schema.EXTENSIONS[("cloth", target)][0]
        check(p.get("ClothType") == target and p.struct.name.endswith(name),
              f"ClothType {kind} -> {target} rebuilds with the {name} extension ({os.path.basename(path)} record {index})")
        check(len(simulate(exported(index), seed=index, max_frames=30)) > 0, "the cloth record simulates")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
