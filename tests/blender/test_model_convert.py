"""Turning an existing model into a DMC4 one (new_model.update_model, texture_convert.py, lib/dxt.py, 2026-11-01):
- in a fresh file New DMC4 Model is offered without picking an app, on the armature of an Empty > armature > mesh model
  too, and the Game Joint panel shows on a rig that has no joint numbers yet;
- a rig over the bone limit is refused before anything changes;
- PNG textures become DDS: base (alpha test from its alpha, DXT5, right way up), normal (DXT5nm, green inverted, X in
  alpha), mask (1 - roughness from a packed channel), with the game's .tex revision, mips, power-of-two size and range;
- a mesh with two materials is split, a colour-only material gets a flat texture, a static mesh's second UV is its
  first (the game's files have it so, its shader samples normal maps there);
- a PNG put in a slot later is converted by the export, and a repainted source is re-encoded (only then)."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import io, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
import numpy as np
from albam.exceptions import AlbamCheckFailure
from albam.engines.mtfw import joints, mesh, new_model, texture_convert
from albam.engines.mtfw.structs.tex_112 import Tex112
from albam.blender_ui.export_panel import ALBAM_OT_Export
from albam.lib.blender import is_blimage_dds
from albam.registry import blender_registry

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


scene = bpy.context.scene
OUT = common.out_dir("model_convert")


def png(name, size, fill):
    """a PNG on disk, read back by Blender like any texture; fill(x, y) in 0-1, y up from the bottom -> rgba"""
    w, h = size
    im = bpy.data.images.new(name + "_src", w, h, alpha=True)
    y, x = np.mgrid[0:h, 0:w]
    px = np.stack(fill((x + 0.5) / w, (y + 0.5) / h), axis=2).astype(np.float32)
    im.pixels.foreach_set(px.ravel())
    path = os.path.join(OUT, name + ".png")
    im.filepath_raw = path
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)
    return bpy.data.images.load(path)


def material(name, base=None, alpha=False, normal=None, packed=None, colour=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    if colour:
        bsdf.inputs["Base Color"].default_value = colour
    if base is not None:
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = base
        nt.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
        if alpha:
            nt.links.new(node.outputs["Alpha"], bsdf.inputs["Alpha"])
    if normal is not None:
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = normal
        node.image.colorspace_settings.name = "Non-Color"
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(node.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs[0], bsdf.inputs["Normal"])
    if packed is not None:     # glTF style: roughness in green
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = packed
        node.image.colorspace_settings.name = "Non-Color"
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(node.outputs["Color"], sep.inputs[0])
        nt.links.new(sep.outputs[1], bsdf.inputs["Roughness"])
    return mat


def grid(name, materials):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=4, size=2)
    ob = bpy.context.object
    ob.name = name
    for mat in materials:
        ob.data.materials.append(mat)
    for i, p in enumerate(ob.data.polygons):
        p.material_index = i % len(materials)
    return ob


def rig(name, bones=3, parent=None):
    arm = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    scene.collection.objects.link(arm)
    arm.parent = parent
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    last = None
    for i in range(bones):
        b = arm.data.edit_bones.new(f"b{i}")
        b.head, b.tail, b.parent = (0, 0, i * 0.1), (0, 0, (i + 1) * 0.1), last
        last = b
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def weigh(ob, arm):
    ob.parent = arm
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    group = ob.vertex_groups.new(name="b0")
    group.add(list(range(len(ob.data.vertices))), 1.0, "REPLACE")


def texture_of(mat, socket):
    group = mat.node_tree.nodes["MTFrameworkGroup"]
    return new_model._upstream_image(group.inputs[socket])


def tex(files, image):
    path = image.albam_asset.relative_path.lower()
    t = Tex112.from_bytes(next(f for f in files if f.relative_path.lower() == path).data_bytes)
    t._read()
    return t


def export(root):
    """through the registry, as the Export button does"""
    return blender_registry.export_registry[("dmc4", "mod")](root)


def parse(files, root):
    path = root.albam_asset.relative_path.lower()
    m = mesh.Mod153(mesh.KaitaiStream(io.BytesIO(bytes(next(f for f in files if f.relative_path.lower() == path).data_bytes))))
    m._read()
    return m


try:
    check(scene.albam.apps.app_selected == "dmc4", "a fresh file starts on DMC4")

    # Empty > armature > meshes, as model importers leave it; a stand-in for "an existing model"
    base = png("skin", (64, 64), lambda x, y: (x, y, 0.5 + 0 * x, (x < 0.5) * 1.0))    # opaque left, cut out right
    normal = png("skin_n", (64, 64), lambda x, y: (x, y, 1.0 + 0 * x, 1.0 + 0 * x))
    packed = png("skin_orm", (32, 32), lambda x, y: (x, 0.25 + 0 * x, y, 1.0 + 0 * x))
    skin = material("skin", base, alpha=True, normal=normal, packed=packed)
    cloth = material("cloth", colour=(0.2, 0.4, 0.8, 1.0))

    holder = bpy.data.objects.new("model_import", None)
    scene.collection.objects.link(holder)
    arm = rig("armature", parent=holder)
    body = grid("body", [skin, cloth])
    weigh(body, arm)

    bpy.context.view_layer.objects.active = holder
    ctx = SimpleNamespace(object=holder, scene=scene)
    check(new_model.ALBAM_PT_NewModel.poll(ctx), "the DMC4 Model panel shows in a file where no app was picked")
    check(new_model.root_candidate(holder) == arm and new_model.root_candidate(body) == arm,
          "the rig is the root of an Empty > armature > mesh model")
    ctx = SimpleNamespace(object=arm, bone=arm.data.bones[0], edit_bone=None)
    check(not joints.is_game_armature(arm) and joints.ALBAM_PT_GameJoint.poll(ctx),
          "the Game Joint panel shows on a rig with no joint numbers (Mark Selected, before New DMC4 Model)")

    huge = rig("huge", bones=260)
    big = grid("big", [material("big")])
    weigh(big, huge)
    try:
        new_model.setup_new_model(bpy.context, huge, r"model\game\huge\huge.mod")
        check(False, "a rig over the limit is refused")
    except AlbamCheckFailure as e:
        check("Mark Selected" in e.solution, "a rig over the limit is refused, pointing at Mark Selected")
    check(not huge.albam_asset.relative_path and joints.joint_of(huge.data.bones[0]) is None and
          not big.material_slots[0].material.node_tree.nodes.get("MTFrameworkGroup"),
          "the refusal changed nothing")

    root, notes = new_model.setup_new_model(bpy.context, holder, r"model\game\mine\mine.mod")
    print("\n".join(notes))
    check(root == arm, "the armature became the model")
    meshes = [c for c in arm.children_recursive if c.type == "MESH"]
    check(len(meshes) == 2 and all(len(m.material_slots) == 1 for m in meshes) and
          all(len({p.material_index for p in m.data.polygons}) == 1 for m in meshes),
          f"the two-material mesh was split ({[m.name for m in meshes]})")
    check(all(m.vertex_groups.get("b0") and m.modifiers.get("Armature") and m.parent == arm for m in meshes),
          "both halves keep their weights, modifier and parent")
    check(sum(len(m.data.polygons) for m in meshes) == 16, "no faces lost")

    props = skin.albam_custom_properties.get_custom_properties_for_appid("dmc4")
    check((props.func_skin, props.func_lighting, props.func_normalmap, props.func_specular) == ("0x3", "0x2", "0x1", "0x1"),
          "skin: SKIN_4WT, SH4SPOT, normal map, specular (the commonest skinned material in the game's files)")
    check(props.attr == "0x8", f"skin's half cut-out alpha is an alpha test ({props.attr})")

    base_dds = texture_of(skin, "Diffuse BM").image
    normal_dds = texture_of(skin, "Normal NM").image
    mask_dds = texture_of(skin, "Specular MM").image
    check(all(is_blimage_dds(i) for i in (base_dds, normal_dds, mask_dds)), "every texture is DDS")
    check(base_dds.albam_asset.relative_path == r"model\game\mine\skin_BM.tex" and
          normal_dds.albam_asset.relative_path == r"model\game\mine\skin_n_NM.tex",
          f"game paths next to the model ({base_dds.albam_asset.relative_path})")
    check(not any(n.type in ("BSDF_PRINCIPLED", "NORMAL_MAP", "SEPARATE_COLOR") for n in skin.node_tree.nodes),
          "the old shader nodes are gone")

    # what Blender decodes from the DDS is what was asked for, the right way up
    def read(im):
        im.reload()
        return texture_convert.read_pixels(im).astype(np.float32)

    src = read(base)
    got = read(base_dds)
    check(got.shape == src.shape and np.abs(got[..., :3] - src[..., :3]).mean() < 6.0,
          f"base survives DXT, right way up ({np.abs(got[..., :3] - src[..., :3]).mean():.2f} of 255)")
    check(got[32, 8, 3] > 240 and got[32, 56, 3] < 16, "base keeps its alpha")

    src = read(normal)
    got = read(normal_dds)
    check(got[..., 0].min() > 240 and got[..., 2].min() > 240, "normal map: red and blue stay at 255 as in the game's")
    check(np.abs(got[..., 3] - src[..., 0]).mean() < 4.0, "normal map: X is in alpha")
    check(np.abs(got[..., 1] - (255 - src[..., 1])).mean() < 6.0, "normal map: green is inverted (OpenGL to the game's)")
    group = skin.node_tree.nodes["MTFrameworkGroup"]
    check(group.inputs["Alpha NM"].is_linked and group.inputs["Flip Normal Green"].default_value == 1,
          "the display reads X from alpha and flips green back")

    got = read(mask_dds)
    check(abs(got[..., :3].mean() - 191) < 4, f"the mask is 1 - roughness of the packed green channel ({got.mean():.0f})")

    check(texture_of(cloth, "Diffuse BM") is not None, "a colour-only material gets a flat texture")
    flat = read(texture_of(cloth, "Diffuse BM").image)
    srgb = np.array([0.2, 0.4, 0.8])
    srgb = 255 * (1.055 * srgb ** (1 / 2.4) - 0.055)
    check(np.abs(flat[0, 0, :3] - srgb).max() < 6, f"in its colour ({flat[0, 0, :3]}, {srgb})")

    check(blender_registry.export_registry[("dmc4", "mod")] is mesh.export_mod and
          blender_registry.export_registry[("re5", "mod")] is mesh.export_mod,
          "the registered .mod export is export_mod itself")
    entry = next(e for e in scene.albam.exportable.file_list if e.bl_object == root)
    before = len(scene.albam.exported.file_list)
    ALBAM_OT_Export._execute(bpy.context, entry)
    check(len(scene.albam.exported.file_list) > before, "the Export button's route fills the exported list")

    files = export(root)
    t = tex(files, base_dds)
    check((t.revision, t.compression_format, t.num_mipmaps_per_image, t.width) == (0x22, "DXT5", 7, 64),
          f"base: revision 0x22, DXT5, full mips ({hex(t.revision)}, {t.compression_format}, {t.num_mipmaps_per_image})")
    check((t.red, t.green, t.blue, t.alpha) == (1.0, 1.0, 1.0, 1.0), "colour range 1: the game doesn't darken it")
    t = tex(files, normal_dds)
    check((t.revision, t.compression_format) == (0x32, "DXT5"), f"normal: revision 0x32, DXT5 ({hex(t.revision)})")
    t = tex(files, mask_dds)
    check((t.revision, t.compression_format) == (0x2, "DXT1"), f"mask: revision 2, DXT1 ({hex(t.revision)})")
    model = parse(files, root)
    check(model.materials_data.materials[0].normalmap != 0 and model.materials_data.materials[0].maskmap != 0 or
          model.materials_data.materials[1].normalmap != 0, "the .mod's material points at the normal and mask maps")
    check(len(model.meshes_data.meshes) == 2, "two meshes exported")

    # non-power-of-two, an image with an alpha channel the material doesn't use
    odd = png("odd", (300, 120), lambda x, y: (x, y, x, 0 * x))
    prop_mat = material("prop", odd)
    static = grid("static", [prop_mat])
    bpy.context.view_layer.objects.active = static
    static_root, notes = new_model.setup_new_model(bpy.context, static, r"model\game\mine\prop.mod")
    odd_dds = texture_of(prop_mat, "Diffuse BM").image
    t = tex(export(static_root), odd_dds)
    check((t.width, t.height, t.compression_format) == (256, 128, "DXT1"),
          f"sizes go to the nearest power of two, an unused alpha gives DXT1 ({t.width} x {t.height}, {t.compression_format})")
    props = prop_mat.albam_custom_properties.get_custom_properties_for_appid("dmc4")
    check((props.vtype, props.func_skin, props.attr) == ("0x2", "0x0", "0x10"), "static opaque functions")
    v = parse(export(static_root), static_root).meshes_data.meshes[0].vertices[0]
    check(bytes(v.uv.u) + bytes(v.uv.v) == bytes(v.uv2.u) + bytes(v.uv2.v) and bytes(v.uv2.u) != b"\xff\xff",
          "a static mesh's second UV is a copy of its first, not filler")

    # later edits: no button needed
    node = texture_of(prop_mat, "Diffuse BM")
    late = png("late", (16, 16), lambda x, y: (y, y, x, 1.0 + 0 * x))
    node.image = late
    files = export(static_root)
    check(is_blimage_dds(node.image) and node.image != late, "a PNG put in a slot later is converted by the export")
    check(tex(files, node.image).compression_format == "DXT1", "and exported")
    second = node.image
    export(static_root)
    check(node.image == second, "a second export changes nothing")

    px = np.empty(16 * 16 * 4, np.float32)
    late.pixels.foreach_get(px)
    px[0::4] = 1.0
    late.pixels.foreach_set(px)
    name = second.name
    export(static_root)
    check(node.image.name == name and np.abs(read(node.image)[..., 0] - 255).max() < 6,
          "repainting the source re-encodes it, under the same name")
    check(node.image.albam_asset.relative_path, "it keeps its game path")
except Exception:
    traceback.print_exc()
    failures.append("exception")

print("FAILURES:", failures)
