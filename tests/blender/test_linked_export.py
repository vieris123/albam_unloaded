"""Headless test: an effect's linked .efs / .ean are in the Export list and export on their own."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, shutil, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export
from albam.engines.mtfw.effect import linked_objects
from albam.blender_ui import export_panel

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
OUT = common.out_dir("linked_out")
scene = bpy.context.scene


def load(rel):
    data = open(os.path.join(ROOT, rel), "rb").read()
    before = {o.name for o in bpy.data.objects}
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name=os.path.basename(rel), relative_path=rel,
                                    get_bytes=lambda: data), bpy.context)
    return next(o for o in bpy.data.objects if o.name not in before and o.albam_asset.extension == "efl")


def listed():
    return [item.bl_object for item in scene.albam.exportable.file_list]


def export(ob):
    items = scene.albam.exportable.file_list
    scene.albam.exportable.file_list_selected_index = next(i for i, it in enumerate(items) if it.bl_object == ob)
    count = len(scene.albam.exported.file_list)
    bpy.ops.albam.export()
    vfs = scene.albam.exported
    root_index = next(i for i in range(count, len(vfs.file_list)) if vfs.file_list[i].is_root)
    vfs.file_list_selected_index = root_index
    return export_panel.export_files(vfs, vfs.file_list[root_index])


try:
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    scene.albam.import_options_efl.load_textures = True
    root = load(r"effect\efl\com\ec000_00v2.efl")
    linked = linked_objects(root)
    print("linked:", sorted(linked))
    check(any(k.startswith("efs:") for k in linked), "ec000_00v2 links a strip")
    for key, ob in linked.items():
        check(ob in listed(), f"{ob.name} is in the Export list")
    check(listed().index(root) < min(listed().index(ob) for ob in linked.values()), "the effect comes first")

    strip = next(ob for key, ob in linked.items() if key.startswith("efs:"))
    files = export(strip)
    check([r for r, _ in files] == ["effect/efs/com/ec000_00v2.efs"], f"the strip exports alone ({[r for r, _ in files]})")
    original = open(os.path.join(ROOT, r"effect\efs\com\ec000_00v2.efs"), "rb").read()
    check(files[0][1].get_bytes() == original, "untouched, byte-identical to the game's")
    bpy.ops.albam.save_to_game_folder(directory=OUT)
    check(os.path.isfile(os.path.join(OUT, "effect", "efs", "com", "ec000_00v2.efs")), "Save to Game Folder writes it")

    # a rebuild keeps one row per linked object
    n = len(listed())
    effect_export.apply_to_scene(bpy.context, root, rebuild=True)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl" and "ec000_00v2" in o.name)
    alive = [ob for ob in listed() if ob is not None and ob.name in bpy.data.objects]
    check(len(alive) == len(set(alive)) and strip in alive, f"no duplicate rows after a rebuild ({len(alive)} rows)")

    # a flipbook
    root2 = load(r"effect\efl\com\ec000_04v1.efl")
    eans = [ob for key, ob in linked_objects(root2).items() if key.startswith("ean:")]
    print("flipbooks:", [ob.name for ob in eans])
    if eans:
        check(all(ob in listed() for ob in eans), "its flipbooks are in the Export list")
        files = export(eans[0])
        check(len(files) == 1 and files[0][0].endswith(".ean"), f"a flipbook exports alone ({files[0][0]})")
        src = os.path.join(ROOT, *files[0][0].split("/"))
        check(files[0][1].get_bytes() == open(src, "rb").read(), "byte-identical to the game's")
    else:
        print("skip: no flipbook found under the root")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
