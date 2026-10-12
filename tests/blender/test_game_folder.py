"""Headless test: Save to Game Folder writes an export's files at their game paths."""
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
from albam.blender_ui import export_panel

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


OUT = common.out_dir("game_folder_out")
try:
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    scene = bpy.context.scene
    ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    scene.albam.import_options_efl.load_textures = False
    rel = r"effect\efl\com\ec000_00v2.efl"
    data = open(os.path.join(ROOT, rel), "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec000_00v2.efl", relative_path=rel,
                                    get_bytes=lambda: data), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    # edit the linked strip so the export carries it too
    from albam.engines.mtfw.effect import linked_objects
    strip = next(ob for key, ob in linked_objects(root).items() if key.startswith("efs:"))
    strip.data.vertices[0].co.x += 0.05
    items = scene.albam.exportable.file_list
    scene.albam.exportable.file_list_selected_index = next(i for i, it in enumerate(items) if it.bl_object == root)
    bpy.ops.albam.export()
    vfs = scene.albam.exported
    root_index = next(i for i, vf in enumerate(vfs.file_list) if vf.is_root)
    vfs.file_list_selected_index = root_index
    files = export_panel.export_files(vfs, vfs.file_list[root_index])
    print("export holds:", [r for r, _ in files])
    check(len(files) == 2, "the export holds the .efl and the edited .efs")

    check(not export_panel.game_folder(bpy.context), "no game folder set yet")
    try:
        bpy.ops.albam.save_to_game_folder()
        refused = False
    except RuntimeError as err:
        refused = "loose-file folder" in str(err)
    check(refused, "without a folder it refuses with a hint (the UI opens a folder picker instead)")
    bpy.ops.albam.save_to_game_folder(directory=OUT)
    check(scene.albam.export_settings.game_folder == OUT, "the folder is remembered")
    for relative, vf in files:
        path = os.path.join(OUT, *relative.replace("/", "\\").split("\\"))
        check(os.path.isfile(path) and open(path, "rb").read() == vf.get_bytes(), f"written at its game path: {relative}")
    efl_path = os.path.join(OUT, "effect", "efl", "com", "ec000_00v2.efl")
    check(open(efl_path, "rb").read() == data, "the untouched .efl is byte-identical to the game's")

    # a second save goes straight to the remembered folder and replaces the files
    open(efl_path, "wb").write(b"old")
    vfs.file_list_selected_index = len(vfs.file_list) - 1   # a leaf: the whole export is still saved
    bpy.ops.albam.save_to_game_folder()
    check(open(efl_path, "rb").read() == data, "saving again replaces the file (leaf selected)")

    # paths that would leave the folder are refused
    check(export_panel.target_path(OUT, "../evil.efl") is None, "'..' is refused")
    check(export_panel.target_path(OUT, "C:/evil.efl") is None, "absolute paths are refused")
    check(export_panel.target_path(OUT, "effect/efl/x.efl") == os.path.join(OUT, "effect", "efl", "x.efl"),
          "a game path maps under the folder")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
