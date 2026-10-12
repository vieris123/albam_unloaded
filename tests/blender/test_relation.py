import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, math, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
from mathutils import Euler, Matrix, Quaternion, Vector
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, mesh
from albam.engines.mtfw.efl import EffectList

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def close_m(a, b, eps=1e-4):
    return all(abs(a[i][j] - b[i][j]) < eps for i in range(3) for j in range(3))


try:
    ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    item = next(i for i in scene.albam.rfs.file_list if i.name.lower().endswith("model::game::pl000::pl000.mod"))
    mesh.build_blender_model(item, bpy.context)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    if arm.name not in scene.collection.objects:
        scene.collection.objects.link(arm)
    opts = scene.albam.import_options_efl
    opts.armature = arm
    opts.sim_frames = 30
    opts.load_textures = False
    rel = r"effect\efl\com\ec024_60v2"
    data = open(os.path.join(ROOT, rel + ".efl"), "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec024_60v2.efl", relative_path=rel + ".efl",
                                    get_bytes=lambda: data), bpy.context)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    src = EffectList.from_bytes(data)
    rec = next(o for o in effect_export.all_record_objects(root) if int(o["efl_record"]) == 98)
    handle = effect_export.rotation_handle(rec)
    check(handle is not None and rec.parent_type == "BONE", "RelationType 2 joint generator gets a rotation companion")
    bpy.context.view_layer.update()
    g = src.records[98].gen
    x, y, z, w = g.get("Quat")
    want_rot = root.matrix_world.to_3x3().normalized() @ Quaternion((w, x, y, z)).to_matrix()
    check(close_m(rec.matrix_world.to_3x3().normalized(), want_rot), "generator rotation = its Quat in world (root) axes")
    bone = arm.pose.bones[rec.parent_bone]
    want_pos = (arm.matrix_world @ bone.matrix @ (Vector(g.get("Pos")) * 0.01))
    check((rec.matrix_world.translation - want_pos).length < 1e-4, "position = Pos in the joint frame (turned by the joint)")
    # turn the bone: position follows, rotation doesn't
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = (0.6, -0.3, 1.0)
    bpy.context.view_layer.update()
    want_pos = (arm.matrix_world @ bone.matrix @ (Vector(g.get("Pos")) * 0.01))
    check((rec.matrix_world.translation - want_pos).length < 1e-4 and
          close_m(rec.matrix_world.to_3x3().normalized(), want_rot), "turning the joint moves it but doesn't turn it")
    out = effect_export.build_efl_bytes(root)[0]
    check(out == data, "export with a posed bone is byte-identical (Pos / Quat unchanged)")
    # rotate the companion, move the generator
    turn = Euler((0.0, 0.0, 0.5)).to_quaternion()
    handle.rotation_quaternion = turn @ handle.rotation_quaternion
    rec.location = rec.location + Vector((0.0, 0.05, 0.0))
    bpy.context.view_layer.update()
    gen2 = EffectList.from_bytes(effect_export.build_efl_bytes(root)[0]).records[98].gen
    x2, y2, z2, w2 = gen2.get("Quat")
    expect = turn @ Quaternion((w, x, y, z))
    check(abs(abs(Quaternion((w2, x2, y2, z2)).dot(expect)) - 1) < 1e-5, "rotating the companion exports Quat in world axes")
    check(abs(gen2.get("Pos")[1] - (g.get("Pos")[1] + 5.0)) < 1e-3, "moving the generator exports Pos in the joint frame")
    # duplicate / remove
    bpy.context.view_layer.objects.active = rec
    try:
        parent = rec.parent if rec.parent is not None and rec.parent.type == "ARMATURE" else None
        dup = effect_export._copy_record_object(bpy.context, rec, root, parent)
        effect_export.apply_to_scene(bpy.context, root)
    except Exception:
        traceback.print_exc()
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    records = effect_export.all_record_objects(root)
    last = max(records, key=lambda o: int(o["efl_record"]))
    orig = next(o for o in records if int(o["efl_record"]) == 98)
    check(len(records) == len(src.records) + 1 and effect_export.rotation_handle(last) is not None
          and effect_export.rotation_handle(last) != effect_export.rotation_handle(orig),
          "the duplicate (rebuilt as a new record) has its own companion")
    handles = [o for o in bpy.data.objects if o.get(effect_export.ROT_HANDLE_OF) is not None]
    check(all(effect_export.rotation_handle(o[effect_export.ROT_HANDLE_OF]) == o for o in handles),
          f"no orphan companions after the rebuild ({len(handles)})")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
