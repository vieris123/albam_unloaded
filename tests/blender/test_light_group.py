import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, struct, traceback
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import mesh, model_settings

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


ROOT = common.DATA + r"\Dante Cyber porting\m20_100s"
common.skip_unless(ROOT)
REL = r"model\demo\pl000\pl000.mod"
DATA = open(os.path.join(ROOT, REL), "rb").read()
FILE_VALUE = struct.unpack_from("<I", DATA, 0x88)[0]


class F:
    app_id = "dmc4"
    display_name = "pl000.mod"
    relative_path = REL
    extension = "mod"
    def get_bytes(self):
        return DATA


def exported_value(root):
    vfiles = mesh.export_mod(root)
    mod = next(v for v in vfiles if v.relative_path.endswith(".mod"))
    return struct.unpack_from("<I", mod.data_bytes, 0x88)[0]


try:
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    item = next(i for i in scene.albam.rfs.file_list if i.name.lower().endswith("pl000::pl000.mod") and "demo" in i.name)
    mesh.build_blender_model(item, bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "mod")
    s = root.albam_mod
    print(f"   file light group {FILE_VALUE:#x}")
    check(s.loaded and model_settings.light_group_value(s) == FILE_VALUE, "import stores the file's light group")
    check(exported_value(root) == FILE_VALUE, "untouched export keeps it")
    s.light_group[5] = not s.light_group[5]
    want = FILE_VALUE ^ 0x20
    check(exported_value(root) == want, f"ticking group 5 exports {want:#x}")
    # a model imported before the setting existed: not loaded -> the file's value, and Load from File reads it
    s.loaded = False
    s.light_group = [False] * 32
    check(exported_value(root) == FILE_VALUE, "an older import (never loaded) exports the file's value")
    child = next(c for c in root.children_recursive if c.type == "MESH")
    check(model_settings.model_root(child) == root, "a mesh of the model finds its root")
    layout = Stub(); p = type("P", (), {})(); p.layout = layout
    ctx = type("C", (), {"object": child})()
    model_settings.ALBAM_PT_ModSettings.draw(p, ctx)
    check(any(n == "operator" and a[0] == "albam.mod_load_settings" for n, a, k in layout.calls),
          "panel offers Load from File for an older import")
    with bpy.context.temp_override(object=child):
        res = bpy.ops.albam.mod_load_settings()
    check(res == {"FINISHED"} and s.loaded and model_settings.light_group_value(s) == FILE_VALUE,
          "Load from File reads the value")
    layout = Stub(); p.layout = layout
    model_settings.ALBAM_PT_ModSettings.draw(p, ctx)
    toggles = [k for n, a, k in layout.calls if n == "prop" and a[1:2] == ("light_group",)]
    check(len(toggles) == 32, "panel draws 32 group toggles")
    check(model_settings.ALBAM_PT_ModSettings.poll(ctx), "panel shows for dmc4 models")
    rna = bpy.ops.albam.mod_load_settings.get_rna_type()
    check(bool(rna.description) and bool(model_settings.AlbamModSettings.bl_rna.properties["light_group"].description),
          "operator and property have tooltips")

    # -- level-of-detail distances (model_info 0x80 / 0x84) and the mesh LOD mask ------------------------------------
    def exported(root_):
        vfiles = mesh.export_mod(root_)
        return next(v for v in vfiles if v.relative_path.endswith(".mod")).data_bytes

    file_lod = struct.unpack_from("<ii", DATA, 0x80)
    check(s.lod_loaded and (s.middist, s.lowdist) == file_lod, f"import stores the LOD distances {file_lod}")
    s.middist, s.lowdist = 600, 2400
    check(struct.unpack_from("<ii", exported(root), 0x80) == (600, 2400), "edited LOD distances export")
    s.lod_loaded = False
    check(struct.unpack_from("<ii", exported(root), 0x80) == file_lod, "an older import exports the file's distances")
    with bpy.context.temp_override(object=child):
        bpy.ops.albam.mod_load_settings()
    check(s.lod_loaded and (s.middist, s.lowdist) == file_lod, "Load from File reads the distances")
    lod = child.data.albam_lod
    check(list(lod.levels) == [True, True, True], "a game mesh draws at every LOD")
    lod.levels = (True, True, False)
    props = child.data.albam_custom_properties.get_custom_properties_for_appid("dmc4")
    check(props.level_of_detail == 0xFB, f"Far off clears bit 2 only ({props.level_of_detail:#x})")
    bpy.context.scene.albam.export_settings.force_lod255 = False
    out = mesh.Mod153(mesh.KaitaiStream(mesh.BytesIO(bytes(exported(root)))))
    out._read()
    check(any(m.level_of_detail == 0xFB for m in out.meshes_data.meshes), "the exported mesh has the new LOD mask")
    layout = Stub(); p.layout = layout
    ctx_mesh = type("C", (), {"object": child})()
    model_settings.ALBAM_PT_ModSettings.draw(p, ctx_mesh)
    check(sum(1 for n, a, k in layout.calls if n == "prop" and a[1:2] == ("levels",)) == 3
          and any(n == "prop" and a[1:2] == ("middist",) for n, a, k in layout.calls),
          "panel draws the distances and the mesh's three LOD toggles")
    check(all(model_settings.AlbamModSettings.bl_rna.properties[k].description for k in ("middist", "lowdist"))
          and model_settings.AlbamMeshLod.bl_rna.properties["levels"].description, "LOD properties have tooltips")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
