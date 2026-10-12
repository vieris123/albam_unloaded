import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, traceback
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_editor, effect_export

PATH = common.MODS + r"\4Hook Mod Pack\DanteJDC\nativePC\effect\efl\com\ec002_00v0.efl"
common.skip_unless(PATH)
DATA = open(PATH, "rb").read()
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class F:
    app_id = "dmc4"
    display_name = "ec002_00v0.efl"
    relative_path = r"effect\efl\com\ec002_00v0"

    def get_bytes(self):
        return DATA


class Stub:
    def __init__(self):
        self.label_texts = []
    def __getattr__(self, name):
        def f(*a, **k):
            if name == "label":
                self.label_texts.append(k.get("text"))
            return self
        return f
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


try:
    scene = bpy.context.scene
    opts = scene.albam.import_options_efl
    opts.sim_frames = 30
    # 1. mod pack root only: no textures
    scene.albam.rfs.add_root_folder("dmc4", common.MODS + r"\4Hook Mod Pack\DanteJDC\nativePC")
    effect.load_efl(F(), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    missing = list(root.get("efl_missing_textures") or [])
    print("   missing:", missing)
    check(len(missing) >= 4, f"missing textures recorded ({len(missing)})")
    bpy.context.view_layer.objects.active = root
    layout = Stub(); p = type("P", (), {})(); p.layout = layout
    effect_editor.ALBAM_PT_EflEditor.draw(p, bpy.context)
    check(any(t and "texture(s) missing" in t for t in layout.label_texts), "Effect Editor shows the warning")
    # 2. add the base game root, rebuild: textures found, warning gone
    scene.albam.rfs.add_root_folder("dmc4", common.DATA + r"\arctool\uPlayerNero-vanilla")
    new_root, _, rebuilt = effect_export.apply_to_scene(bpy.context, root, rebuild=True)
    check(rebuilt and not list(new_root.get("efl_missing_textures") or []), "after adding the base game: none missing")
    bpy.context.view_layer.objects.active = new_root
    layout = Stub(); p.layout = layout
    effect_editor.ALBAM_PT_EflEditor.draw(p, bpy.context)
    check(not any(t and "texture(s) missing" in t for t in layout.label_texts), "warning gone")
    # 3. darkening strength: shared group, live update
    group = bpy.data.node_groups.get(effect.DARKEN_GROUP)
    revsub = [m for m in bpy.data.materials if "REVSUBTRACT" in str(m.get("efl_blend", "")) and "refraction" not in str(m.get("efl_blend", ""))]
    uses = all(any(n.bl_idname == "ShaderNodeGroup" and n.node_tree == group for n in m.node_tree.nodes) for m in revsub)
    check(group is not None and revsub and uses, f"{len(revsub)} darkening materials use {effect.DARKEN_GROUP}")
    opts.darken_strength = 2.0
    check(abs(group.nodes["Strength"].outputs[0].default_value - 2.0) < 1e-6, "slider updates the group")
    outs = [len([n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial"]) for m in revsub]
    check(all(o == 1 for o in outs), "single material output")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
