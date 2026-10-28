"""New DMC4 Model (new_model.py, mesh_prep.py, mesh._serialize_groups): a .mod made from objects built in Blender.
- the blank source parses as an empty v153 model with the game's header defaults;
- a static cube (quads, flat shading, UV seams, moved off the origin, a Principled material with a DDS image) gets
  an Empty root, a converted material and an export entry; it exports 24 vertices / 12 triangles where Blender
  shows it, one part record on its centre, its texture; the user's mesh is untouched and no temporary is left;
- a rig made in Blender (3 bones, a mesh deformed through its Armature modifier) gets joints 0-2, exports its bone
  table (joint map, parents, inverse binds = inverse of the chain) and comes back on re-import with its bones and
  weights where they were;
- refusals: a mesh without a material, a model with no meshes;
- imported game models: every mesh passes through mesh preparation unchanged and the part records are the file's."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import io, struct, traceback
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from mathutils import Matrix, Vector
from albam.exceptions import AlbamCheckFailure
from albam.engines.mtfw import joints, mesh, mesh_prep, new_model

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


scene = bpy.context.scene
scene.albam.apps.app_selected = "dmc4"
OUT = common.out_dir("new_model")


def parse(data):
    m = mesh.Mod153(mesh.KaitaiStream(io.BytesIO(bytes(data))))
    m._read()
    return m


def export(root):
    files = mesh.export_mod(root)
    return next(v for v in files if v.relative_path.lower().endswith(".mod")).data_bytes, files


def dds_bytes(size=8):
    """an uncompressed A8R8G8B8 DDS, one mip"""
    header = struct.pack("<4s7I44sII4s5I5I", b"DDS ", 124, 0x100F, size, size, size * 4, 0, 1, bytes(44),
                         32, 0x41, b"\0\0\0\0", 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000, 0x1000, 0, 0, 0, 0)
    assert len(header) == 128
    return header + bytes([40, 80, 200, 255]) * (size * size)


def dds_image(name):
    data = dds_bytes()
    path = os.path.join(OUT, name + ".dds")
    with open(path, "wb") as f:
        f.write(data)
    im = bpy.data.images.load(path)
    im.pack()
    return im


def principled_material(name, image):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def reimport(data, rel):
    """write the exported file under a Game Files root and import it"""
    path = os.path.join(OUT, "game", rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes(data))
    if not any(r.name.endswith("game") for r in scene.albam.rfs.file_list if r.tree_node.depth == 0):
        scene.albam.rfs.add_root_folder("dmc4", os.path.join(OUT, "game"))
    else:
        bpy.ops.albam.refresh_real_folders()
    item = next(i for i in scene.albam.rfs.file_list if i.name.lower().endswith(rel.lower().replace("\\", "::")))
    before = set(bpy.data.objects)
    root = mesh.build_blender_model(item, bpy.context)
    return root, [o for o in set(bpy.data.objects) - before if o.type == "MESH" and o.parent == root]


try:
    # -- the blank source ---------------------------------------------------------------------------------------------
    blank = new_model.blank_mod153()
    m = parse(blank)
    check(len(blank) == 0x90 and m.header.version == 153 and m.header.num_bones == 0 and m.header.num_meshes == 0
          and m.header.num_groups == 0, "the blank source is an empty v153 model (0x90 bytes)")
    check((m.model_info.middist, m.model_info.lowdist, m.model_info.light_group, m.reserved_01, m.reserved_02)
          == (1000, 3000, 3, 0, 0), "it has the game's header defaults (LOD 1000 / 3000, light group 3)")

    # -- a static cube ------------------------------------------------------------------------------------------------
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.0, 2.0, 3.0))
    cube = bpy.context.object
    cube.name = "Crate"
    image = dds_image("crate_bm")
    cube.data.materials.append(principled_material("CrateMat", image))
    check(bpy.ops.albam.mod_new.poll(), "New DMC4 Model is offered on a plain mesh")
    n_objects = len(bpy.data.objects)
    res = bpy.ops.albam.mod_new("EXEC_DEFAULT", path=r"model\game\crate\crate.mod")
    root = cube.parent
    check(res == {"FINISHED"} and root is not None and root.type == "EMPTY" and root.name == "crate",
          f"it puts the cube under a new Empty root ({root and root.name})")
    check(root.albam_asset.relative_path == r"model\game\crate\crate.mod" and
          bytes(root.albam_asset.original_bytes) == blank and
          any(e.bl_object == root for e in scene.albam.exportable.file_list),
          "the root is a dmc4 .mod asset with the blank source, on the Export list")
    check((cube.matrix_world.translation - Vector((1, 2, 3))).length < 1e-6, "the cube stays where it was")
    mat = cube.material_slots[0].material
    props = mat.albam_custom_properties.get_custom_properties_for_appid("dmc4")
    group = mat.node_tree.nodes.get("MTFrameworkGroup")
    base = new_model._upstream_image(group.inputs["Diffuse BM"]) if group is not None else None
    check(base is not None and base.image == image and
          not any(n.type == "BSDF_PRINCIPLED" for n in mat.node_tree.nodes),
          "its material gets the MT Framework shader with the image as the basemap")
    check((props.vtype, props.func_skin, props.func_lighting, props.func_normalmap, props.func_specular, props.attr)
          == ("0x2", "0x0", "0x2", "0x0", "0x0", "0x10"),
          f"static functions: vtype 2, no skin, SH4SPOT, no normal / specular map, solid ({props.vtype}, "
          f"{props.func_skin}, {props.func_lighting})")
    check(image.albam_asset.app_id == "dmc4" and image.albam_asset.relative_path == r"model\game\crate\crate_bm.tex",
          f"its image gets a game path next to the model ({image.albam_asset.relative_path})")
    check(not bpy.ops.albam.mod_new.poll(), "New DMC4 Model isn't offered again on the model")

    class Layout:
        def __init__(self):
            self.texts = []
        def label(self, text="", icon="NONE"):
            self.texts.append(text)
        def column(self, **_):
            return self
        def operator(self, idname, **_):
            self.texts.append(idname)
    layout = Layout()
    check(new_model.ALBAM_PT_NewModel.poll(bpy.context), "the DMC4 Model panel shows on the new model")
    new_model.ALBAM_PT_NewModel.draw(type("P", (), {"layout": layout})(), bpy.context)
    check(any("crate.mod" in t for t in layout.texts) and any("converted" in t for t in layout.texts),
          f"it lists the model's path and what New DMC4 Model did ({layout.texts})")

    n_objects = len(bpy.data.objects)
    n_meshes = len(bpy.data.meshes)
    data, files = export(root)
    check(len(bpy.data.objects) == n_objects and len(bpy.data.meshes) == n_meshes,
          "export leaves no temporary objects or meshes")
    check(len(cube.data.vertices) == 8 and len(cube.data.polygons) == 6 and
          all(p.loop_total == 4 for p in cube.data.polygons), "the user's mesh is untouched (8 vertices, 6 quads)")
    m = parse(data)
    check(m.header.num_meshes == 1 and m.header.num_bones == 0 and m.meshes_data.meshes[0].num_vertices == 24
          and m.header.num_edges == 12,
          f"it exports 24 vertices / 12 triangles (split by face, triangulated: {m.meshes_data.meshes[0].num_vertices}"
          f" / {m.header.num_edges})")
    g = m.groups
    check(m.header.num_groups == 1 and g[0].group_index == 0 and
          abs(g[0].pos.x - 100) < 1e-3 and abs(g[0].pos.y - 300) < 1e-3 and abs(g[0].pos.z + 200) < 1e-3,
          f"one part record on the cube's centre in game cm ({[(x.group_index, x.pos.x, x.pos.y, x.pos.z) for x in g]})")
    check(m.materials_data.materials[0].basemap == 1 and
          m.materials_data.textures[0] == r"model\game\crate\crate_bm" and
          any(f.relative_path.lower().endswith("crate_bm.tex") for f in files),
          f"the basemap is written and its .tex exported ({list(m.materials_data.textures)})")
    back, back_meshes = reimport(data, r"model\game\crate\crate.mod")
    co = [back_meshes[0].matrix_world @ v.co for v in back_meshes[0].data.vertices]
    lo = Vector([min(c[i] for c in co) for i in range(3)])
    hi = Vector([max(c[i] for c in co) for i in range(3)])
    check((lo - Vector((0.5, 1.5, 2.5))).length < 1e-3 and (hi - Vector((1.5, 2.5, 3.5))).length < 1e-3,
          f"re-imported, the cube is where Blender had it ({tuple(round(x, 3) for x in lo)} - "
          f"{tuple(round(x, 3) for x in hi)})")
    normals = {tuple(round(x, 3) for x in v.normal) for v in back_meshes[0].data.vertices}
    check(len(normals) == 6, f"its normals are the 6 face normals (flat shading kept: {len(normals)})")

    # -- refusals -----------------------------------------------------------------------------------------------------
    cube.data.materials.clear()
    try:
        export(root)
        check(False, "a mesh without a material is refused")
    except AlbamCheckFailure as err:
        check("no material" in err.message, f"a mesh without a material is refused ({err.message})")
    cube.data.materials.append(mat)
    empty = bpy.data.objects.new("lonely", None)
    scene.collection.objects.link(empty)
    try:
        new_model.setup_new_model(bpy.context, empty, r"model\game\lonely\lonely.mod")
        check(False, "a model with no meshes is refused")
    except AlbamCheckFailure as err:
        check("no meshes" in err.message, f"a model with no meshes is refused ({err.message})")
    check(not empty.albam_asset.relative_path, "and nothing is set up")

    # -- a rig made in Blender ----------------------------------------------------------------------------------------
    arm_data = bpy.data.armatures.new("RigData")
    arm = bpy.data.objects.new("Rig", arm_data)
    scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    chain = []
    for i, (head, tail) in enumerate((((0, 0, 0), (0, 0, 0.5)), ((0, 0, 0.5), (0, 0.2, 1.0)), ((0, 0.2, 1.0), (0, 0.2, 1.5)))):
        eb = arm_data.edit_bones.new(("hip", "spine", "head")[i])
        eb.head, eb.tail = head, tail
        if chain:
            eb.parent = chain[-1]
            eb.use_connect = True
        chain.append(eb)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=0.2, depth=1.5, location=(0, 0.1, 0.75))
    body = bpy.context.object
    body.name = "Body"
    groups = {name: body.vertex_groups.new(name=name) for name in ("hip", "spine", "head")}
    for v in body.data.vertices:
        z = (body.matrix_world @ v.co).z
        if z < 0.5:
            groups["hip"].add([v.index], 1.0, "REPLACE")
        else:
            groups["spine"].add([v.index], 0.5, "REPLACE")
            groups["head"].add([v.index], 0.5, "REPLACE")
    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    body.data.materials.append(principled_material("BodyMat", dds_image("body_bm")))
    for o in bpy.context.selected_objects:
        o.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    rig_root, notes = new_model.setup_new_model(bpy.context, arm, r"model\game\rig\rig.mod")
    check(rig_root == arm and body.parent == arm, "the rig is the root and adopts the mesh it deforms")
    check([joints.joint_of(arm.data.bones[n]) for n in ("hip", "spine", "head")] == [0, 1, 2],
          "its bones become joints 0, 1, 2 in bone order")
    bprops = body.material_slots[0].material.albam_custom_properties.get_custom_properties_for_appid("dmc4")
    check((bprops.vtype, bprops.func_skin) == ("0x0", "0x3"), f"skinned functions: vtype 0, SKIN_4WT "
          f"({bprops.vtype}, {bprops.func_skin})")
    data, _ = export(arm)
    m = parse(data)
    bones = m.bones_data.bones_hierarchy
    check(m.header.num_bones == 3 and [b.idx_anim_map for b in bones] == [0, 1, 2] and
          [b.idx_parent for b in bones] == [255, 0, 1] and
          list(m.bones_data.bone_map[:4]) == [0, 1, 2, 255] and set(m.bones_data.bone_map[3:]) == {255},
          f"the bone table: joints 0-2, parents, joint map ({[b.idx_parent for b in bones]}, "
          f"{list(m.bones_data.bone_map[:4])})")
    world = mesh._joint_world_matrices(m.bones_data)
    worst = max(abs(a - b) for j in range(3)
                for ra, rb in zip(mesh._matrix_rows(m.bones_data.inverse_bind_matrices[j]) @ world[j],
                                  Matrix.Identity(4)) for a, b in zip(ra, rb))
    check(worst < 1e-4, f"inverse binds are the inverse of the chain (worst {worst:.2e})")
    check(m.header.num_bone_palettes == 1 and m.meshes_data.meshes[0].num_weight_bounds >= 2,
          "the mesh has a bone palette and weight bounds")
    back, back_meshes = reimport(data, r"model\game\rig\rig.mod")
    check(back.type == "ARMATURE", "re-imported, it has an armature")
    by_joint = {joints.joint_of(b): b for b in back.data.bones}
    worst = max((by_joint[joints.joint_of(arm.data.bones[n])].head_local - arm.data.bones[n].head_local).length
                for n in ("hip", "spine", "head"))
    check(worst < 1e-4, f"its bones are where Blender had them (worst {worst:.2e} m)")
    bm = back_meshes[0]
    names = {vg.index: vg.name for vg in bm.vertex_groups}
    top = [v for v in bm.data.vertices if (bm.matrix_world @ v.co).z > 1.0]
    ok = all(sorted(round(g.weight, 2) for g in v.groups if g.weight > 0) == [0.5, 0.5] for v in top)
    check(bool(top) and ok, "its weights come back (upper vertices half spine, half head)")

    # -- imported models pass through unchanged -----------------------------------------------------------------------
    rel = r"model\game\pl000\pl000_03.mod"
    if os.path.exists(os.path.join(common.NERO, rel)):
        scene.albam.rfs.add_root_folder("dmc4", common.NERO)
        item = next(i for i in scene.albam.rfs.file_list if i.name.lower().endswith(rel.replace("\\", "::")))
        coat = mesh.build_blender_model(item, bpy.context)
        coat_meshes = [c for c in coat.children_recursive if c.type == "MESH"]
        reasons = {o.name: mesh_prep.needs_preparing(coat, o) for o in coat_meshes}
        check(not any(reasons.values()), f"no imported mesh of pl000_03 needs preparing "
              f"({[k for k, v in reasons.items() if v][:5]})")
        src = parse(open(os.path.join(common.NERO, rel), "rb").read())
        out = parse(export(coat)[0])
        check([(g.group_index, g.pos.x, g.pos.y, g.pos.z, g.radius) for g in out.groups] ==
              [(g.group_index, g.pos.x, g.pos.y, g.pos.z, g.radius) for g in src.groups],
              "its part records are the file's")
    else:
        print("skipped: imported model checks (no Nero data)")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
