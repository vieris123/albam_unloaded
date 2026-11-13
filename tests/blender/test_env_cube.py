"""Environment cubes from ordinary images (texture_convert CUBE, 2026-11-09), and the edge-glow material recipe
(docs/edge_glow.md):
- a flat PNG in a material's Environment CM slot is converted by the export into a DDS cube: six square faces, full
  mips, revision 0x13 as the game's _CM files, every face the PNG's colour, shown in Blender as a vertical strip;
- a vertical strip of six faces keeps each face's own pixels;
- the glow material's settings (additive blend, no z write, no fog, the edge fresnel) land in the .mod's record."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import io, traceback
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
import numpy as np
from albam.engines.mtfw import mesh, new_model, texture_convert
from albam.engines.mtfw.structs.tex_112 import Tex112
from albam.lib.blender import is_blimage_dds
from albam.registry import blender_registry

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


scene = bpy.context.scene
OUT = common.out_dir("env_cube")
GLOW = (0.35, 0.6, 1.0)


def png(name, w, h, rgba_rows):
    """a PNG on disk; rgba_rows(y) -> rgba for row y counted from the top"""
    im = bpy.data.images.new(name + "_src", w, h, alpha=True)
    px = np.array([rgba_rows(h - 1 - y) for y in range(h) for _x in range(w)], np.float32)
    im.pixels.foreach_set(px.ravel())
    path = os.path.join(OUT, name + ".png")
    im.filepath_raw = path
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)
    return bpy.data.images.load(path)


def stored(c):
    """the bytes a PNG made from these pixel values holds"""
    return np.rint(np.array(c, np.float32) * 255.0)


try:
    # a static model with one material, made a DMC4 one
    mat = bpy.data.materials.new("glow")
    mat.use_nodes = True
    bpy.ops.mesh.primitive_uv_sphere_add()
    ob = bpy.context.object
    ob.name = "glow_mesh"
    ob.data.materials.append(mat)
    bpy.context.view_layer.objects.active = ob
    root, _notes = new_model.setup_new_model(bpy.context, ob, r"model\game\glow\glow.mod", pbr=False)

    # the recipe: black albedo, white mask, the glow colour as the environment, the edge fresnel
    flat = png("glow_colour", 8, 8, lambda y: (*GLOW, 1.0))
    black = png("black", 8, 8, lambda y: (0.0, 0.0, 0.0, 1.0))
    white = png("white", 8, 8, lambda y: (1.0, 1.0, 1.0, 1.0))
    nt = mat.node_tree
    group = nt.nodes["MTFrameworkGroup"]
    for socket, image in (("Diffuse BM", black), ("Specular MM", white), ("Environment CM", flat)):
        for link in list(group.inputs[socket].links):
            nt.links.remove(link)
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = image
        nt.links.new(node.outputs["Color"], group.inputs[socket])
    props = mat.albam_custom_properties.get_custom_properties_for_appid("dmc4")
    reach = 0.35
    f = 1.0 / ((1.0 + reach) ** 5 - 1.0)
    props.attr = "0x40"
    props.blend_state = 0x02A20225
    props.alpha_ref = 0
    props.zwrite = False
    props.fog_enable = False
    props.func_specular = "0x1"
    props.fresnel_factor = (f, -f, 200.0, 1.0)

    files = blender_registry.export_registry[("dmc4", "mod")](root)
    env = next(n for n in nt.nodes if n.type == "TEX_IMAGE" and n.outputs["Color"].links and
               n.outputs["Color"].links[0].to_socket.name == "Environment CM").image
    check(is_blimage_dds(env) and env.get(texture_convert.RECIPE_PROP) and env.name.endswith("_CM.dds"),
          f"the PNG in Environment CM became a DDS cube image ({env.name})")
    check(tuple(env.size) == (8, 48), f"shown as a vertical strip of six faces ({tuple(env.size)})")
    by_path = {f.relative_path.lower(): f for f in files}
    data = by_path.get(env.albam_asset.relative_path.lower())
    check(data is not None, f"the cube is exported ({env.albam_asset.relative_path})")
    t = Tex112.from_bytes(bytes(data.data_bytes))
    t._read()
    check((t.revision, t.num_images, t.width, t.height, t.num_mipmaps_per_image, t.compression_format) ==
          (0x13, 6, 8, 8, 4, "DXT1"), f"a cube like the game's _CM files "
          f"({hex(t.revision)}, {t.num_images}, {t.width} x {t.height}, {t.num_mipmaps_per_image} mips, {t.compression_format})")
    px = texture_convert.read_pixels(env)
    want = stored(GLOW)
    check(px is not None and np.abs(px[..., :3].reshape(-1, 3) - want).max() < 8,
          f"every face holds the glow colour ({px[0, 0, :3] if px is not None else None}, {want})")

    # a strip of six faces keeps them apart
    faces = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (0, 1, 1), (1, 0, 1)]
    strip = png("strip", 4, 24, lambda y: (*faces[y // 4], 1.0))
    cube, _use = texture_convert.convert(texture_convert.CUBE, [strip])
    got = texture_convert.read_pixels(cube)
    check(got is not None and got.shape[:2] == (24, 4) and
          all(np.abs(got[i * 4:(i + 1) * 4, :, :3].reshape(-1, 3) - stored(faces[i])).max() < 8 for i in range(6)),
          "a six-face strip keeps each face")

    m = mesh.Mod153(mesh.KaitaiStream(io.BytesIO(bytes(by_path[root.albam_asset.relative_path.lower()].data_bytes))))
    m._read()
    rec = m.materials_data.materials[0]
    check((rec.attr, rec.blend_state, rec.zwrite, rec.fog_enable, rec.alpha_ref & 0xFF, rec.func_specular) ==
          (0x40, 0x02A20225, 0, 0, 0, 1), "the glow settings are in the material record")
    check(np.allclose(list(rec.fresnel_factor), [f, -f, 200.0, 1.0], atol=1e-5), f"and its fresnel ({list(rec.fresnel_factor)})")
    paths = m.materials_data.textures
    check(rec.envmap and paths[rec.envmap - 1].lower() == env.albam_asset.relative_path.lower()[:-4],
          f"the cube is the material's environment map ({paths})")

except Exception:
    traceback.print_exc()
    failures.append("exception")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
