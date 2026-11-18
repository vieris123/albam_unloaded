"""Bake Occlusion (engines/mtfw/occlusion.py, 2026-11-15): ambient occlusion into the per-vertex occlusion the .mod
stores in tangent.w (`mtfw_tangent_w`):
- a floor grid with a box standing on it: the floor darkens next to the box, stays open far from it; nothing goes
  below Darkest;
- baked in the rest pose: posing the armature changes nothing;
- another model's mesh casts shadows while visible, not when hidden;
- the export writes it into tangent.w (no longer 254 everywhere); Clear Occlusion gives 254 back."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import io, math, traceback
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
import numpy as np
from albam.engines.mtfw import mesh, new_model, occlusion
from albam.registry import blender_registry

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def values(ob):
    attribute = ob.data.attributes.get(mesh.TANGENT_W_ATTR)
    out = np.empty(len(ob.data.vertices), np.float32)
    attribute.data.foreach_get("value", out)
    return out


def near_box(ob, radius):
    co = np.array([v.co[:] for v in ob.data.vertices])
    return np.linalg.norm(co[:, :2], axis=1) < radius


try:
    ctx = bpy.context
    bpy.ops.object.armature_add(location=(0, 0, 0))
    arm = ctx.object
    arm.name = "occ_rig"
    bpy.ops.object.mode_set(mode="EDIT")
    lifter = arm.data.edit_bones.new("box_bone")
    lifter.head, lifter.tail = (0, 0, 0), (0, 0.5, 0)
    bpy.ops.object.mode_set(mode="OBJECT")
    floor_bone = arm.data.bones[0].name
    bone_name = "box_bone"
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=24, y_subdivisions=24, size=2)
    floor = ctx.object
    floor.name = "occ_floor"
    bpy.ops.mesh.primitive_cube_add(size=0.3, location=(0, 0, 0.15))
    box = ctx.object
    box.name = "occ_box"
    for ob in (floor, box):
        ob.data.materials.append(bpy.data.materials.new(ob.name + "_mat"))
        group = ob.vertex_groups.new(name=bone_name if ob is box else floor_bone)
        group.add(range(len(ob.data.vertices)), 1.0, "REPLACE")
        mod = ob.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
    ctx.view_layer.objects.active = arm
    root, _notes = new_model.setup_new_model(ctx, arm, r"model\game\occ\occ.mod", pbr=False)
    floor = bpy.data.objects["occ_floor"]

    # another model: a wall next to the floor, x = 0.6
    bpy.ops.mesh.primitive_cube_add(size=0.4, location=(0.6, 0, 0.2))
    wall = ctx.object
    wall.name = "occ_wall"
    wall.data.materials.append(bpy.data.materials.new("wall_mat"))
    ctx.view_layer.objects.active = wall
    wall_root, _notes = new_model.setup_new_model(ctx, wall, r"model\game\occ\wall.mod", pbr=False)

    wall.hide_set(True)
    notes = occlusion.bake_occlusion(ctx, root, distance=0.2, samples=32, darkest=0.35)
    print(notes)
    v = values(floor)
    close, far = near_box(floor, 0.25), ~near_box(floor, 0.5)
    check(v[close].mean() < v[far].mean() - 0.1, f"the floor darkens next to the box ({v[close].mean():.2f} vs "
                                                 f"{v[far].mean():.2f} far away)")
    check(abs(v[far].min() - 1.0) < 1e-6 or v[far].min() > 0.95, f"open floor stays lit ({v[far].min():.3f})")
    check(v.min() >= 0.35 - 1e-6, f"nothing below Darkest ({v.min():.3f})")
    hidden_wall = v.copy()

    # posing doesn't matter: the rest pose is baked
    ctx.view_layer.objects.active = arm
    arm.pose.bones[bone_name].location = (0, 0, 1.0)   # bone along +Y, roll 0: local Z is up; lifts the box 1 m
    ctx.view_layer.update()
    posed = box.evaluated_get(ctx.evaluated_depsgraph_get()).to_mesh()
    low = min((box.matrix_world @ p.co).z for p in posed.vertices)
    box.evaluated_get(ctx.evaluated_depsgraph_get()).to_mesh_clear()
    check(low > 0.9, f"(the pose lifts the box off the floor: its bottom at {low:.2f} m)")
    occlusion.bake_occlusion(ctx, root, distance=0.2, samples=32, darkest=0.35)
    check(np.allclose(values(floor), hidden_wall, atol=1e-6) and arm.data.pose_position == "POSE",
          "with the box posed away the floor still gets the rest pose's occlusion, and the pose comes back")
    arm.pose.bones[bone_name].location = (0, 0, 0)

    wall.hide_set(False)
    occlusion.bake_occlusion(ctx, root, distance=0.2, samples=32, darkest=0.35)
    v = values(floor)
    co = np.array([p.co[:] for p in floor.data.vertices])
    by_wall = (co[:, 0] > 0.32) & (co[:, 0] < 0.4) & (np.abs(co[:, 1]) < 0.15)
    check(v[by_wall].mean() < hidden_wall[by_wall].mean() - 0.1,
          f"a visible model shades it ({v[by_wall].mean():.2f}), a hidden one doesn't ({hidden_wall[by_wall].mean():.2f})")

    # an alpha-tested card over the floor: it blocks light where its texture is opaque, not where it's a hole
    bpy.ops.mesh.primitive_plane_add(size=0.3, location=(-0.5, 0, 0.08))
    card = ctx.object
    card.name = "occ_card"
    card.data.materials.append(bpy.data.materials.new("card_mat"))
    ctx.view_layer.objects.active = card
    new_model.setup_new_model(ctx, card, r"model\game\occ\card.mod", pbr=False)
    card_mat = card.material_slots[0].material
    card_props = card_mat.albam_custom_properties.get_custom_properties_for_appid("dmc4")
    card_props.attr, card_props.alpha_ref = "0x8", 128
    sheet = bpy.data.images.new("card_alpha", 8, 8, alpha=True)
    new_model._upstream_image(card_mat.node_tree.nodes["MTFrameworkGroup"].inputs["Diffuse BM"]).image = sheet
    under = (np.abs(co[:, 0] + 0.5) < 0.1) & (np.abs(co[:, 1]) < 0.1)
    sheet.pixels.foreach_set(np.zeros(8 * 8 * 4, np.float32))   # alpha 0 everywhere: a hole
    occlusion.bake_occlusion(ctx, root, distance=0.2, samples=32, darkest=0.35)
    through = values(floor)[under].mean()
    sheet.pixels.foreach_set(np.ones(8 * 8 * 4, np.float32))
    occlusion.bake_occlusion(ctx, root, distance=0.2, samples=32, darkest=0.35)
    blocked = values(floor)[under].mean()
    check(through > 0.97 and blocked < through - 0.2,
          f"an alpha-tested card shades only where its texture is opaque (hole {through:.2f}, opaque {blocked:.2f})")
    card.hide_set(True)

    files = blender_registry.export_registry[("dmc4", "mod")](root)
    data = next(f for f in files if f.relative_path.lower().endswith("occ.mod")).data_bytes
    m = mesh.Mod153(mesh.KaitaiStream(io.BytesIO(bytes(data))))
    m._read()
    ws = [vx.tangent.w for part in m.meshes_data.meshes for vx in part.vertices]
    check(len(set(ws)) > 5 and min(ws) >= round(0.35 * 255) - 1 and max(ws) == 255,
          f"exported into tangent.w ({min(ws)}..{max(ws)}, {len(set(ws))} values)")

    occlusion.clear_occlusion(root)
    files = blender_registry.export_registry[("dmc4", "mod")](root)
    data = next(f for f in files if f.relative_path.lower().endswith("occ.mod")).data_bytes
    m = mesh.Mod153(mesh.KaitaiStream(io.BytesIO(bytes(data))))
    m._read()
    ws = {vx.tangent.w for part in m.meshes_data.meshes for vx in part.vertices}
    check(ws == {254}, f"Clear Occlusion: 254 everywhere again ({sorted(ws)[:5]})")

except Exception:
    traceback.print_exc()
    failures.append("exception")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
