"""PBR materials for dmc4_hook's PbrMaterials (engines/mtfw/pbr.py, 2026-11-15):
- New DMC4 Model converts Principled BSDFs to PBR (specular RIM, envmap_bias 5, fresnel = (roughness, metal, F0, 1)):
  plain values go into the record with no mask; roughness / metal images and the glTF Material Output's Occlusion are
  packed into one ORM mask (DXT1, R occlusion, G roughness, B metal, x = y = 1); Specular IOR Level -> F0 = level x
  0.08; Subsurface Weight -> lighting THIN with the scatter colour weight x Radius / max x 0.5, a weight image ->
  the additional map's G (R 255);
- the export writes those records (keys in pbr.PBR_KEYS) and the ORM / additional textures;
- the Blender preview: the group's PBR inputs follow the values;
- the material's PBR fields, Make Classic / Make PBR round trip;
- a RIM key dmc4_hook doesn't replace is refused at export; a model with PBR Materials off converts classic."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import io, traceback
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
import numpy as np
from albam.engines.mtfw import mesh, new_model, pbr, texture_convert
from albam.engines.mtfw.structs.tex_112 import Tex112
from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


OUT = common.out_dir("pbr_material")


def png(name, rgba, size=8):
    im = bpy.data.images.new(name + "_src", size, size, alpha=True)
    im.pixels.foreach_set(np.tile(np.array(rgba, np.float32), size * size))
    path = os.path.join(OUT, name + ".png")
    im.filepath_raw = path
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)
    image = bpy.data.images.load(path)
    image.colorspace_settings.name = "Non-Color"
    return image


def material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    return mat, mat.node_tree, next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def image_into(nt, image, socket, channel=None):
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    if channel is None:
        nt.links.new(tex.outputs["Color"], socket)
        return
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(tex.outputs["Color"], sep.inputs[0])
    nt.links.new(sep.outputs[channel], socket)


def part(name, mat, root, x):
    bpy.ops.mesh.primitive_uv_sphere_add(location=(x, 0, 0))
    ob = bpy.context.object
    ob.name = name
    ob.data.materials.append(mat)
    ob.parent = root
    return ob


def group_of(mat):
    return mat.node_tree.nodes["MTFrameworkGroup"]


def linked_image(mat, socket):
    links = group_of(mat).inputs[socket].links
    return links[0].from_node.image if links and links[0].from_node.type == "TEX_IMAGE" else None


def near(a, b, tol=1e-4):
    return np.allclose(np.array(a, np.float64), np.array(b, np.float64), atol=tol)


try:
    root = bpy.data.objects.new("pbr_root", None)
    bpy.context.scene.collection.objects.link(root)

    consts, nt, bsdf = material("a_consts")
    bsdf.inputs["Roughness"].default_value = 0.3
    bsdf.inputs["Metallic"].default_value = 0.8
    bsdf.inputs["Specular IOR Level"].default_value = 0.35
    part("p_consts", consts, root, 0)

    maps, nt, bsdf = material("b_maps")
    packed = png("rough_metal", (0.2, 0.6, 0.9, 1.0))
    occlusion = png("ao", (0.5, 0.5, 0.5, 1.0))
    image_into(nt, packed, bsdf.inputs["Roughness"], 1)
    image_into(nt, packed, bsdf.inputs["Metallic"], 2)
    gltf = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
    gltf.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    holder = nt.nodes.new("ShaderNodeGroup")
    holder.node_tree = gltf
    image_into(nt, occlusion, holder.inputs["Occlusion"], 0)
    part("p_maps", maps, root, 3)

    skin, nt, bsdf = material("c_skin")
    bsdf.inputs["Subsurface Weight"].default_value = 1.0
    bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.4, 0.24)
    part("p_skin", skin, root, 6)

    sssmap, nt, bsdf = material("d_sssmap")
    image_into(nt, png("sss_weight", (0.7, 0.7, 0.7, 1.0)), bsdf.inputs["Subsurface Weight"])
    bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.2, 0.1)
    part("p_sssmap", sssmap, root, 9)

    bpy.context.view_layer.objects.active = root
    root, notes = new_model.setup_new_model(bpy.context, root, r"model\game\pbrtest\pbrtest.mod")
    print("\n".join(notes))
    check(root.albam_mod.pbr, "new models have PBR Materials on by default")

    p = pbr.props_of(consts)
    check((p.func_specular, p.envmap_bias, p.func_lighting) == ("0x4", 5, "0x2"), "plain values: RIM, bias 5, SH4SPOT")
    check(near(p.fresnel_factor, (0.3, 0.8, 0.028, 1.0)),
          f"fresnel = (roughness, metal, 0.35 x 0.08, 1) ({tuple(round(v, 4) for v in p.fresnel_factor)})")
    check(linked_image(consts, "Specular MM") is None, "no mask texture for plain values")
    g = group_of(consts)
    check(g.inputs["PBR"].default_value == 1 and abs(g.inputs["PBR Roughness"].default_value - 0.3) < 1e-4 and
          abs(g.inputs["PBR Metal"].default_value - 0.8) < 1e-4 and
          abs(g.inputs["PBR Specular"].default_value - 0.35) < 1e-4 and
          near(g.inputs["Specular MM"].default_value, (1, 1, 1, 1)),
          "the preview follows the values (no mask = white ORM)")

    p = pbr.props_of(maps)
    orm = linked_image(maps, "Specular MM")
    check(near(p.fresnel_factor, (1.0, 1.0, 0.04, 1.0)), f"images: scales 1, F0 0.04 ({tuple(p.fresnel_factor)})")
    check(orm is not None and orm.get(texture_convert.RECIPE_PROP) and orm.name.endswith("_MM.dds"),
          f"roughness / metal / occlusion packed into one mask ({orm.name if orm else None})")
    px = texture_convert.read_pixels(orm) if orm else None
    check(px is not None and np.abs(px[..., :3].reshape(-1, 3).mean(0) - (128, 153, 230)).max() < 8,
          f"ORM: R occlusion, G roughness, B metal ({px[..., :3].reshape(-1, 3).mean(0) if px is not None else None})")

    p = pbr.props_of(skin)
    check(p.func_lighting == "0x4" and near(p.lightmap_factor[:3], (0.5, 0.2, 0.12)),
          f"Subsurface: THIN, scatter = Radius / max x 0.5 ({tuple(round(v, 4) for v in p.lightmap_factor)})")
    check(linked_image(skin, "Alpha Mask AM") is None, "no additional map: scatters everywhere")
    g = group_of(skin)
    check(abs(g.inputs["Subsurface DMC4"].default_value - 1.0) < 1e-4 and
          near(g.inputs["Subsurface Radius DMC4"].default_value, (1.0, 0.4, 0.24)), "the preview shows the subsurface")

    p = pbr.props_of(sssmap)
    extra = linked_image(sssmap, "Alpha Mask AM")
    check(p.func_lighting == "0x4" and near(p.lightmap_factor[:3], (0.5, 0.1, 0.05)),
          f"a weight image: THIN, scatter from the radius ({tuple(round(v, 4) for v in p.lightmap_factor)})")
    px = texture_convert.read_pixels(extra) if extra else None
    check(px is not None and abs(px[..., 0].mean() - 255) < 4 and abs(px[..., 1].mean() - 178) < 8,
          f"the weight image in the additional map's G, R thick ({px[..., :3].reshape(-1, 3).mean(0) if px is not None else None})")

    files = blender_registry.export_registry[("dmc4", "mod")](root)
    by_path = {f.relative_path.lower(): f for f in files}
    m = mesh.Mod153(mesh.KaitaiStream(io.BytesIO(bytes(by_path[root.albam_asset.relative_path.lower()].data_bytes))))
    m._read()
    recs = m.materials_data.materials
    keys = [r.pipeline for r in recs]
    check(len(recs) == 4 and all(r.func_specular == 4 and r.envmap_bias == 5 for r in recs) and
          all(k in pbr.PBR_KEYS for k in keys), f"exported: four RIM records, keys dmc4_hook replaces ({keys})")
    check(near(recs[0].fresnel_factor, (0.3, 0.8, 0.028, 1.0)) and recs[0].maskmap == 0, "plain values in the record")
    check(recs[1].maskmap != 0 and near(recs[1].fresnel_factor, (1, 1, 0.04, 1)), "the ORM mask is the record's mask")
    check(recs[2].func_lighting == 4 and near(recs[2].lightmap_factor[:3], (0.5, 0.2, 0.12)), "SSS record")
    check(recs[3].additionalmap != 0, "the weight map is the additional map")
    tex = by_path.get(orm.albam_asset.relative_path.lower())
    t = Tex112.from_bytes(bytes(tex.data_bytes)) if tex else None
    if t is not None:
        t._read()
    check(t is not None and (t.revision, t.compression_format) == (0x2, "DXT1"),
          f"the ORM .tex is a DXT1 mask ({(hex(t.revision), t.compression_format) if t else None})")

    # the DMC4 PBR panel draws (classic and PBR, with and without subsurface)
    class Layout:
        def __init__(self):
            self.texts = []
        def label(self, text="", icon="NONE"):
            self.texts.append(text)
        def operator(self, idname, **_):
            self.texts.append(idname)
        def prop(self, data, name, **kw):
            self.texts.append(kw.get("text", name))
        def column(self, **_):
            return self
        row = box = column
    for mat in (consts, maps, skin):
        layout = Layout()
        ctx = type("C", (), {"material": mat})()
        check(pbr.ALBAM_PT_PbrMaterial.poll(ctx), f"the DMC4 PBR panel shows on {mat.name}")
        pbr.ALBAM_PT_PbrMaterial.draw(type("P", (), {"layout": layout})(), ctx)
        print("   ", layout.texts)
    check("scatter" in layout.texts and any("thickness" in t.lower() for t in layout.texts),
          "the panel shows the scatter colour on a subsurface material")

    # the material's fields, Make Classic / Make PBR
    values = consts.albam_pbr
    values.roughness = 0.45
    values.specular = 0.5
    values.subsurface = True
    p = pbr.props_of(consts)
    check(near(p.fresnel_factor[:3], (0.45, 0.8, 0.04)) and p.func_lighting == "0x4" and
          near(p.lightmap_factor[:3], (0.5, 0.2, 0.12)), "the PBR fields write the record's values")
    check(abs(group_of(consts).inputs["PBR Roughness"].default_value - 0.45) < 1e-4, "and the preview")
    values.subsurface = False
    pbr.make_classic(consts)
    p = pbr.props_of(consts)
    check((p.func_specular, p.envmap_bias, p.func_lighting) == ("0x0", 0, "0x2") and
          abs(p.fresnel_factor[2] - pbr.power_from_roughness(0.45)) < 1e-3 and group_of(consts).inputs["PBR"].default_value == 0,
          f"Make Classic: no specular map, SpecularPow from the roughness ({p.fresnel_factor[2]:.2f})")
    pbr.make_classic(maps)
    check(linked_image(maps, "Specular MM") is None, "Make Classic drops the ORM mask")
    pbr.props_of(consts).func_specular = "0x1"
    pbr.make_pbr(consts)
    p = pbr.props_of(consts)
    check(p.func_specular == "0x4" and abs(p.fresnel_factor[0] - 0.45) < 1e-3 and p.fresnel_factor[1] == 0,
          f"Make PBR: roughness back from SpecularPow, metal 0 ({tuple(round(v, 3) for v in p.fresnel_factor)})")
    pbr.make_pbr(maps)

    # a RIM key dmc4_hook doesn't replace is refused
    pbr.props_of(skin).func_multitexture = "0x1"
    try:
        blender_registry.export_registry[("dmc4", "mod")](root)
        check(False, "a PBR material with multitexture ALPHA is refused at export")
    except AlbamCheckFailure as err:
        check("PBR" in str(err.details), f"a PBR material with multitexture ALPHA is refused at export ({err.details})")
    pbr.props_of(skin).func_multitexture = "0x0"
    pbr.props_of(maps).func_lighting = "0x0"
    pbr.props_of(maps).func_specular = "0x0"
    try:
        pbr.make_pbr(maps)
        check(False, "Make PBR refuses an unlit material")
    except AlbamCheckFailure:
        check(True, "Make PBR refuses an unlit material")

    # PBR Materials off: a new material converts classic
    root.albam_mod.pbr = False
    late, nt, bsdf = material("e_late")
    bsdf.inputs["Roughness"].default_value = 0.3
    part("p_late", late, root, 12)
    new_model.update_model(root)
    check(pbr.props_of(late).func_specular != "0x4", "PBR Materials off: converted classic")

except Exception:
    traceback.print_exc()
    failures.append("exception")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
