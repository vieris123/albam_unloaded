import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_editor
from albam.engines.mtfw.efl import retype
failures = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: failures.append(m)
try:
    ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
    opts = bpy.context.scene.albam.import_options_efl
    opts.sim_frames = 30; opts.load_textures = False
    rel = r"effect\efl\com\ec024_60v2"
    data = open(os.path.join(ROOT, rel + ".efl"), "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="x.efl", relative_path=rel + ".efl", get_bytes=lambda: data), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    rec = next(o for o in effect_export.all_record_objects(root) if o.get("efl_life") is not None)
    state = bpy.context.scene.albam.efl_editor
    effect_editor.load_record(state, rec)
    kf = [f"{s}:{f}" for s, f, v in effect_editor.keyframe_fields(rec)]
    check("life:KeyframeKeepFrameParamOffset" in kf, "the Keys tab lists the life KeepFrame keyframe")
    check(state.fields.get("life/KeyframeKeepFrameParamOffset") is None, "it's no longer an editable field in the Life tab")
    # add a key through the editor and export
    bpy.context.view_layer.objects.active = rec
    state.live = False
    bpy.ops.albam.efl_key_insert(track="life:KeyframeKeepFrameParamOffset")
    rec["Life KeepFrame"] = 25
    bpy.ops.albam.efl_key_insert(track="life:KeyframeKeepFrameParamOffset")
    out = effect_export.build_efl_bytes(root)[0]
    from albam.engines.mtfw.efl import EffectList
    from albam.engines.mtfw.efl.edit import keyframe_props
    life = EffectList.from_bytes(out).records[int(rec["efl_record"])].life
    p = keyframe_props(life).get("KeyframeKeepFrameParamOffset")
    check(p is not None and list(p["params"])[0] == 25, f"the key exports ({p})")
    check(life.get("HoldUntilEffectEnds") == rec["efl_life"]["HoldUntilEffectEnds"], "the hold flag is kept")
    offered = [t for t, _ in retype.offered_types("ptcl")]
    check(16 not in offered and 17 not in offered, "Change Type doesn't offer LiteBillboard / SizeBillboard")
except Exception:
    traceback.print_exc(); failures.append("exception")
print("FAILURES:", failures)
