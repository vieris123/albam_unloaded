"""DMC4 material display from the XfMaterialStandard pixel shaders (2026-10-17): LIGHTING_NONE materials are unlit,
THIN ones translucent (albedo x additional.r x lightmap_factor), LIGHTMAP_SHADOW masks the specular with the shadow
map's red, POWMAP has no environment cube. Imports one game model per feature, checks the node setup, that export
keeps every material's functions and the texture behind each slot, and renders (Cycles, CPU) that an unlit material
ignores lights while a lit one doesn't, and that Translucency lets a light behind the surface through."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import io, tempfile, traceback
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.engines.mtfw import material, mesh

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


CASES = [
    ("unlit", os.path.join(common.ARCTOOL, "em010 (frost)"), r"effect\mod\ene\ee010\ee010_01.mod"),
    ("thin", os.path.join(common.ARCTOOL, "em009"), r"model\game\em009\em009_00.mod"),
    ("shadow", os.path.join(common.ARCTOOL, r"New texture\tex 4\st000"), r"scr\st000\stage\st000-m00-base.mod"),
    ("powmap", os.path.join(common.ARCTOOL, "em030 - sanctus"), r"model\game\pl023\pl023_02.mod"),
]
common.skip_unless(*(os.path.join(root, rel) for _, root, rel in CASES))
FUNCS = ("attr", "vtype", "func_skin", "func_lighting", "func_normalmap", "func_specular", "func_lightmap",
         "func_multitexture")
SLOTS = ("basemap", "normalmap", "maskmap", "lightmap", "shadowmap", "additionalmap", "envmap", "heightmap")
scene = bpy.context.scene


def parse(data):
    m = mesh.Mod153(mesh.KaitaiStream(io.BytesIO(bytes(data))))
    m._read()
    return m


def slots(mod, record):
    textures = list(mod.materials_data.textures)
    return {s: (textures[getattr(record, s) - 1] if getattr(record, s) else None) for s in SLOTS}


def render_mean(setup):
    """mean red of a 16 x 16 Cycles render of a plane facing the camera (+Z) with the MT Framework group"""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bpy.ops.mesh.primitive_plane_add(size=2)
    plane = bpy.context.object
    mat = bpy.data.materials.new("m")
    mat.use_nodes = True
    nt = mat.node_tree
    for nd in [n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"]:
        nt.nodes.remove(nd)
    g = nt.nodes.new("ShaderNodeGroup")
    g.node_tree = bpy.data.node_groups[material.MTFW_SHADER_NODEGROUP_NAME]
    g.inputs["Diffuse BM"].default_value = (0.5, 0.2, 0.1, 1)
    nt.links.new(g.outputs[0], next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL").inputs[0])
    plane.data.materials.append(mat)
    cam = bpy.data.objects.new("C", bpy.data.cameras.new("C"))
    cam.location = (0, 0, 3)
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.world = scene.world or bpy.data.worlds.new("W")
    scene.world.use_nodes = False
    scene.world.color = (0, 0, 0)
    setup(g)
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 8
    scene.cycles.device = "CPU"
    scene.render.resolution_x = scene.render.resolution_y = 16
    path = os.path.join(tempfile.gettempdir(), "albam_material_display.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    px = list(img.pixels)
    bpy.data.images.remove(img)
    return sum(px[0::4]) / (len(px) // 4)


def light(z, power):
    ob = bpy.data.objects.new("L", bpy.data.lights.new("L", "POINT"))
    ob.data.energy = power
    ob.location = (0, 0, z)
    scene.collection.objects.link(ob)


try:
    for tag, root, rel in CASES:
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
        scene.albam.rfs.add_root_folder("dmc4", root)
        item = next(i for i in scene.albam.rfs.file_list if i.name.lower().endswith(rel.lower().replace("\\", "::")))
        before = set(bpy.data.objects)
        mesh.build_blender_model(item, bpy.context)
        new = set(bpy.data.objects) - before
        src = parse(open(os.path.join(root, rel), "rb").read())
        recs = src.materials_data.materials
        groups = [n for ob in new if ob.type == "MESH" for s in ob.material_slots if s.material
                  for n in s.material.node_tree.nodes if n.name == "MTFrameworkGroup"]
        if tag == "unlit":
            check(any(g.inputs["Unlit"].default_value == 1 for g in groups), f"{rel}: LIGHTING_NONE is unlit")
            check(any(g.inputs["Unlit"].default_value == 0 for g in groups) or all(r.func_lighting == 0 for r in recs),
                  f"{rel}: lit materials stay lit")
        elif tag == "thin":
            check(any(g.inputs["Translucency"].links for g in groups), f"{rel}: THIN materials are translucent")
        elif tag == "shadow":
            check(any(g.inputs["Specular MM"].links and g.inputs["Specular MM"].links[0].from_node.label ==
                      "Specular x Shadow" for g in groups), f"{rel}: the shadow map masks the specular")
        elif tag == "powmap":
            pow_groups = [g for g in groups if g.id_data.name in {s.material.node_tree.name for ob in new
                                                                   if ob.type == "MESH" for s in ob.material_slots
                                                                   if s.material}]
            check(not any(n.type == "GROUP" and n.node_tree and n.node_tree.name == material.CUBE_UV_GROUP
                          for g in pow_groups for n in g.id_data.nodes), f"{rel}: POWMAP has no environment cube")
        holder = next((o for o in new if o.type == "ARMATURE"), None) or \
            next(o for o in new if o.albam_asset.extension == "mod")
        out = parse(next(v for v in mesh.export_mod(holder) if v.relative_path.lower().endswith(".mod")).data_bytes)
        same = len(recs) == len(out.materials_data.materials) and all(
            [getattr(a, f) for f in FUNCS] == [getattr(b, f) for f in FUNCS] and slots(src, a) == slots(out, b)
            for a, b in zip(recs, out.materials_data.materials))
        check(same, f"{rel}: export keeps every material's functions and the texture in each slot")

    unlit_dark = render_mean(lambda g: setattr(g.inputs["Unlit"], "default_value", 1))
    unlit_lit = render_mean(lambda g: (setattr(g.inputs["Unlit"], "default_value", 1), light(2, 2000)))
    lit_dark = render_mean(lambda g: None)
    lit_lit = render_mean(lambda g: light(2, 2000))
    print(f"   unlit {unlit_dark:.3f} / {unlit_lit:.3f}, lit {lit_dark:.3f} / {lit_lit:.3f}")
    check(abs(unlit_dark - unlit_lit) < 0.02 and unlit_dark > 0.2, "an unlit material ignores the light")
    check(lit_lit > lit_dark + 0.1, "a lit material responds to it")
    behind_plain = render_mean(lambda g: light(-2, 2000))
    behind_thin = render_mean(lambda g: (setattr(g.inputs["Translucency"], "default_value", (0.5, 0.2, 0.1, 1)),
                                         light(-2, 2000)))
    print(f"   light behind: plain {behind_plain:.3f}, translucent {behind_thin:.3f}")
    check(behind_thin > behind_plain + 0.05, "Translucency lets a light behind the surface through")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
