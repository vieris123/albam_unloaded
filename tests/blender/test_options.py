import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, traceback, os, glob
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_editor
from albam.engines.mtfw.efl import EffectList, sim, edit

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)

try:
    # refraction over the DX9 files: ParticleOptionFlag 0x10 unless the u8 CullingFlag has 0x2 OCCLUSION (before
    # 2026-10-08 the check used 0x200 of the old u16 CullingFlag, i.e. a VolumeBlendRate bit, and 324 of 1,304
    # refracting particles were missed). The folder holds duplicates and mod packs, so compare rules, not a count.
    n = total = old_rule = 0
    for path in glob.glob(common.DATA + r"\arctool\**\*.efl", recursive=True):
        try:
            e = EffectList.from_bytes(open(path, "rb").read())
        except Exception:
            continue
        for r in e.records:
            p = r.ptcl
            if p is None or not p.has("ParticleOptionFlag") or not p.has("CullingFlag"):
                continue
            total += 1
            expected = bool(p.get("ParticleOptionFlag") & 0x10) and not (p.get("CullingFlag") & 0x2)
            check(sim.refracts(p) == expected, f"{os.path.basename(path)} record {e.records.index(r)}: refracts "
                  f"{sim.refracts(p)}, expected {expected}") if sim.refracts(p) != expected else None
            n += expected
            volume = p.get("VolumeBlendRate") if p.has("VolumeBlendRate") else 0
            old_rule += bool(p.get("ParticleOptionFlag") & 0x10) and not ((p.get("CullingFlag") | (volume << 8)) & 0x200)
    print(f"{n} of {total} particles refract ({old_rule} under the old u16 rule)")
    check(n > old_rule > 0, "the u8 OCCLUSION rule keeps more refracting particles than the old u16 one")

    ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
    REL = r"effect\efl\com\ec000_00v2"
    DATA = open(os.path.join(ROOT, REL + ".efl"), "rb").read()
    class F:
        app_id = "dmc4"; display_name = "ec000_00v2.efl"; relative_path = REL + ".efl"
        def get_bytes(self): return DATA
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    scene.albam.import_options_efl.sim_frames = 10
    effect.load_efl(F(), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    src = EffectList.from_bytes(DATA)
    idx = next(i for i, r in enumerate(src.records) if r.ptcl and r.ptcl.get("CullingFlag") >> 8 if False) if False else \
        next(i for i, r in enumerate(src.records) if r.ptcl and r.ptcl.has("VolumeBlendRate") and r.ptcl.get("VolumeBlendRate"))
    rec = next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == idx)
    vol = src.records[idx].ptcl.get("VolumeBlendRate"); cf = src.records[idx].ptcl.get("CullingFlag")
    pof = src.records[idx].ptcl.get("ParticleOptionFlag")
    print(f"   record {idx}: CullingFlag {cf:#x}, VolumeBlendRate {vol}, ParticleOptionFlag {pof:#x}")
    state = scene.albam.efl_editor
    bpy.context.view_layer.objects.active = rec
    effect_editor.load_record(state, rec)
    items = {i.label: i for i in state.fields if i.slot == "ptcl"}
    check(items["ParticleOptionFlag"].kind == "flags" and items["CullingFlag"].kind == "flags"
          and items["VolumeBlendRate"].kind == "ints", "option and culling flags are checkboxes, VolumeBlendRate a number")
    check(items["VolumeBlendRate"].section == "draw" and items["OtDepthBias"].section == "draw",
          "the new fields sit in Drawing & Blending")
    # tick the sign bit (Sort Bias Toward Camera) and Keep Behind Camera
    items["ParticleOptionFlag"].flags[31] = True
    items["ParticleOptionFlag"].flags[6] = True
    want = pof | 0x80000040
    out = effect_export.build_efl_bytes(root)[0]
    got = EffectList.from_bytes(out).records[idx].ptcl.get("ParticleOptionFlag")
    check(got == want, f"ticking writes the sign bit too ({got:#x} == {want:#x})")
    items["ParticleOptionFlag"].flags[31] = bool(pof >> 31 & 1)
    items["ParticleOptionFlag"].flags[6] = bool(pof >> 6 & 1)
    check(effect_export.build_efl_bytes(root)[0] == DATA, "unticking restores byte-identical export")
    # props stored by an older import: CullingFlag u16 with the volume byte on top, uknDraw_0x14
    props = rec["efl_ptcl"].to_dict()
    props["CullingFlag"] = cf | vol << 8
    props.pop("VolumeBlendRate"); props["uknDraw_0x14"] = 0; props.pop("OtDepthBias")
    rec["efl_ptcl"] = props
    check(effect_export.build_efl_bytes(root)[0] == DATA, "an older import's props still export byte-identical")
    effect_editor.load_record(state, rec)
    stored = rec["efl_ptcl"]
    check(stored["CullingFlag"] == cf and stored["VolumeBlendRate"] == vol and "uknDraw_0x14" not in stored
          and "OtDepthBias" in stored, "loading it in the editor upgrades the stored fields")
    check(effect_export.build_efl_bytes(root)[0] == DATA, "and it still exports byte-identical")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
