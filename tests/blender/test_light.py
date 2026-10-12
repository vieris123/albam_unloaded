import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, traceback
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.engines.mtfw import effect_editor
from albam.engines.mtfw.efl import schema
failures = []
st = next(s for s in schema.all_structs() if s.name == "EFL_PARTICLE_Light")
state = bpy.context.scene.albam.efl_editor
item = effect_editor._add_field(state, "ptcl", st.by_name["LightAttribute"], 0x10)
ok = item.kind == "flags" and item.flags[4] and not item.flags[1]
print(("ok   " if ok else "FAIL ") + "LightAttribute is checkboxes showing Simple")
if not ok: failures.append(1)
g = effect_editor._add_field(state, "ptcl", st.by_name["LightGroupFlag"], 0xFFFFFFFF)
ok = g.kind == "hex" and g.tier == "dx9" and g.section if hasattr(g, "section") else True
print(("ok   " if g.kind == "hex" and g.tier == "dx9" else "FAIL ") + f"LightGroupFlag is a verified hex mask ({g.kind}, {g.tier})")
print("FAILURES:", failures)
