"""New DMC4 Model: make a .mod (v153) from objects made in Blender, with no game file to start from (2026-10-28).

Export always rebuilds a .mod on top of its source file (mesh.export_mod reads `albam_asset.original_bytes`). A new
model gets a generated **blank source** instead (`blank_mod153`): the 0x90-byte top level the game's loader reads
(rModel load 0xA53F50 checks only the magic and version 153), no bones, groups, materials or meshes, and the
header values every DX9 model has (reserved words 0, LOD distances 1000 / 3000, strip_type / memory 0) with light
group 3 (lights of groups 0 and 1: the uModel constructor's default and the most common value). Everything else is
built by the export as for an imported model:
- bones: with no source bones every joint is "added in Blender" (joints.export_layout); `joints.number_new_rig`
  numbers the rig's bones 0, 1, 2... in bone order first;
- part records (`mesh._serialize_groups`): one per part number the meshes use;
- meshes: transform, triangles and seams are handled at export (mesh_prep.py).

`setup_new_model` also makes the root's materials exportable: a material without the "MT Framework shader" group
gets it (`convert_material`), with the image feeding its Principled BSDF's Base Color as the basemap and shader
functions that exist in XfMaterialStandard.bfx for that vertex layout (skinned up to 4 weights: SKIN_4WT + vtype
0, more: SKIN_8WT + vtype 1, no armature: SKIN_NONE + vtype 2; lighting SH4SPOT, no normal / specular map:
every combination checked in the .bfx permutation table at 0x56C). Its images get the dmc4 app and a game path
next to the model. What it can't do is reported: images that aren't DDS (export needs DDS), normal maps (the game
wants DXT5nm, X in alpha), materials with no base texture.
"""
import struct
from pathlib import PureWindowsPath
from types import SimpleNamespace

import bpy

from albam.exceptions import AlbamCheckFailure
from albam.lib.blender import is_blimage_dds
from albam.registry import blender_registry
from . import joints
from .model_settings import model_root, set_light_group, set_lod_distances

APP_ID = "dmc4"
MOD_VERSION = 153
DEFAULT_LIGHT_GROUP = 3
DEFAULT_LOD = (1000, 3000)
HEADER_SIZE = 0x90   # header (72) + reserved_01 / 02 + bsphere + bbox_min / max + model_info: what rModel reads first
MAX_SKIN_4 = 4       # weights per vertex SKIN_4WT (vtype 0) holds; up to 8 need SKIN_8WT (vtype 1)


def blank_mod153(light_group=DEFAULT_LIGHT_GROUP, lod=DEFAULT_LOD):
    """a .mod v153 with nothing in it: the header (MOD, 153, every count and offset 0), reserved words 0, zero bounds,
    and model_info (middist, lowdist, light group, strip_type 0, memory 0, reserved 0)"""
    header = struct.pack("<4sBBHHH15I", b"MOD\x00", MOD_VERSION, 0, 0, 0, 0, *([0] * 15))
    data = header + struct.pack("<II", 0, 0) + bytes(48) + struct.pack("<iiIBBH", lod[0], lod[1], light_group, 0, 0, 0)
    assert len(data) == HEADER_SIZE
    return data


def _taken(ob):
    """True if ob already belongs to an Albam file (an imported or new model, an effect, a chain, collision...)"""
    for o in [ob] + list(_ancestors(ob)):
        if o.albam_asset.relative_path:
            return True
        if any(key.startswith(("efl_", "col_", "phs_", "sdl_", "pla_")) for key in o.keys()):
            return True
    return False


def _ancestors(ob):
    parent = ob.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def _armature_of(mesh_ob):
    for mod in mesh_ob.modifiers:
        if mod.type == "ARMATURE" and mod.object is not None:
            return mod.object
    return None


def root_candidate(ob):
    """the object New DMC4 Model turns into the model's root for the active object ob: an armature or an Empty is
    its own root; a mesh's root is its armature (parent, else its Armature modifier's object), else its parent
    Empty, else None (a new Empty is made for it)"""
    if ob is None:
        return None
    if ob.type in ("ARMATURE", "EMPTY"):
        return ob
    if ob.type != "MESH":
        return None
    for parent in _ancestors(ob):
        if parent.type in ("ARMATURE", "EMPTY"):
            return parent
    return _armature_of(ob)


def default_path(name):
    stem = "".join(c if c.isalnum() or c in "_-" else "_" for c in name.split(".")[0]).lower() or "model"
    return f"model\\game\\{stem}\\{stem}.mod"


def _parent_keep_transform(ob, root):
    world = ob.matrix_world.copy()
    ob.parent = root
    ob.parent_type = "OBJECT"
    ob.matrix_parent_inverse = root.matrix_world.inverted_safe()
    ob.matrix_world = world


def _meshes_to_adopt(context, root, selected):
    """meshes that belong to the model but aren't under its root: the selected meshes without an Albam owner, and
    (armature root) meshes deformed by it. root None = a new Empty (nothing is under it yet)"""
    candidates = list(selected)
    if root is not None and root.type == "ARMATURE":
        candidates += [o for o in context.scene.objects if o.type == "MESH" and _armature_of(o) == root]
    adopt = []
    for ob in candidates:
        if ob.type != "MESH" or ob == root or ob in adopt or _taken(ob):
            continue
        if root is not None and root in _ancestors(ob):
            continue
        adopt.append(ob)
    return adopt


def _weights_per_vertex(mesh_ob, joint_names):
    """the most joint weights any vertex of the mesh has"""
    group_is_joint = [vg.name in joint_names for vg in mesh_ob.vertex_groups]
    most = 0
    for v in mesh_ob.data.vertices:
        n = sum(1 for g in v.groups if g.weight > 0 and g.group < len(group_is_joint) and group_is_joint[g.group])
        most = max(most, n)
    return most


def shader_functions(skinned, weights):
    """(vtype, func_skin) for a mesh layout; see the module doc"""
    if not skinned:
        return 2, 0
    return (0, 3) if weights <= MAX_SKIN_4 else (1, 4)


def _upstream_image(socket, depth=4):
    """the Image Texture node feeding socket, directly or through up to `depth` nodes"""
    if depth < 0 or not socket.is_linked:
        return None
    node = socket.links[0].from_node
    if node.type == "TEX_IMAGE":
        return node
    for inp in node.inputs:
        found = _upstream_image(inp, depth - 1)
        if found is not None:
            return found
    return None


def convert_material(mat, skinned, weights, notes):
    """give mat the MT Framework shader group and DMC4 properties (see the module doc); returns its image nodes"""
    from . import material as mtfw_material
    mat.use_nodes = True
    nt = mat.node_tree
    mtfw_material._create_mtfw_shader()
    principled = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    base = _upstream_image(principled.inputs["Base Color"]) if principled else None
    alpha = bool(principled and principled.inputs["Alpha"].is_linked)
    normal = _upstream_image(principled.inputs["Normal"]) if principled else None
    colour = tuple(principled.inputs["Base Color"].default_value) if principled else (0.8, 0.8, 0.8, 1.0)

    group = nt.nodes.new("ShaderNodeGroup")
    group.node_tree = bpy.data.node_groups[mtfw_material.MTFW_SHADER_NODEGROUP_NAME]
    group.name = "MTFrameworkGroup"
    group.width = 300
    output = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None) or \
        nt.nodes.new("ShaderNodeOutputMaterial")
    group.location = (output.location[0] - 400, output.location[1])
    nt.links.new(group.outputs[0], output.inputs["Surface"])
    if base is not None:
        nt.links.new(base.outputs["Color"], group.inputs["Diffuse BM"])
        if alpha:
            nt.links.new(base.outputs["Alpha"], group.inputs["Alpha BM"])
    else:
        group.inputs["Diffuse BM"].default_value = colour
        notes.append(f"{mat.name}: no base texture (the game draws it untextured)")
    if normal is not None:
        notes.append(f"{mat.name}: normal map {normal.image.name if normal.image else ''} not connected: DMC4 "
                     "wants DXT5nm (X in alpha, Y in green); connect a converted one to Normal NM")
    if principled is not None:
        nt.nodes.remove(principled)

    props = mat.albam_custom_properties.get_custom_properties_for_appid(APP_ID)
    vtype, func_skin = shader_functions(skinned, weights)
    props.vtype = hex(vtype)
    props.func_skin = hex(func_skin)
    props.func_lighting = "0x2"      # SH4SPOT
    props.func_normalmap = "0x0"
    props.func_specular = "0x0"
    props.func_lightmap = "0x0"
    props.func_multitexture = "0x0"
    props.attr = "0x8" if alpha else "0x10"   # alpha test (NUKI) when the alpha was used, else solid
    record = SimpleNamespace()
    props.copy_custom_properties_to(record)
    mtfw_material.setup_dmc4_material(record, mat)
    return [base] if base is not None else []


def _image_nodes(mat):
    return [n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image is not None] if mat.node_tree else []


def _prepare_images(mat, folder, notes):
    """the material's images: the dmc4 app and, without one, a game path in the model's folder (no extension: the
    export adds .tex); images that aren't DDS are reported"""
    for node in _image_nodes(mat):
        im = node.image
        if im.albam_asset.original_bytes and im.albam_asset.app_id != APP_ID:
            notes.append(f"{im.name}: a texture of another game ({im.albam_asset.app_id})")
            continue
        im.albam_asset.app_id = APP_ID
        if not im.albam_asset.relative_path:
            stem = "".join(c if c.isalnum() or c in "_-" else "_" for c in im.name.rsplit(".", 1)[0]) or "texture"
            im.albam_asset.relative_path = f"{folder}\\{stem}.tex"
            im.albam_asset.extension = "tex"
        if not im.albam_asset.original_bytes and not is_blimage_dds(im):
            notes.append(f"{im.name}: not a DDS image; export needs DDS (save it as .dds and reload it)")


def setup_new_model(context, ob, path):
    """Make a new DMC4 model of ob (see root_candidate) at game path `path`. Returns (root, notes)."""
    from albam.engines.mtfw import material as mtfw_material
    path = path.strip().replace("/", "\\")
    if not path.lower().endswith(".mod"):
        path += ".mod"
    if any(model_root(o) is o and o.albam_asset.relative_path.lower() == path.lower() for o in bpy.data.objects):
        raise AlbamCheckFailure(f"{path} is already a model in this file", details=path,
                                solution="Pick another game path")
    selected = [o for o in context.selected_objects if o.type == "MESH"]
    root = root_candidate(ob)
    if root is None:   # a lone mesh: a new Empty root for it and the other selected meshes
        selected = selected or ([ob] if ob is not None and ob.type == "MESH" else [])
    elif _taken(root):
        raise AlbamCheckFailure(f"{root.name} already belongs to an Albam file", details=root.name,
                                solution="Pick an armature, Empty or mesh that isn't part of an imported file")
    # checked before anything changes: a refused operator leaves no undo step
    adopt = _meshes_to_adopt(context, root, selected)
    owned = [c for c in root.children_recursive if c.type == "MESH"] if root is not None else []
    if not owned and not adopt:
        name = root.name if root is not None else (ob.name if ob is not None else "")
        raise AlbamCheckFailure(f"{name} has no meshes", details=name,
                                solution="Parent the model's meshes to it first, or select them too")
    notes = []
    if root is None:
        root = bpy.data.objects.new(PureWindowsPath(path).stem, None)
        root.empty_display_type = "PLAIN_AXES"
        for collection in (ob.users_collection if ob is not None else [context.collection]):
            collection.objects.link(root)
    for mesh_ob in adopt:
        _parent_keep_transform(mesh_ob, root)
    if adopt:
        notes.append(f"parented {len(adopt)} mesh(es) to {root.name}: " + ", ".join(o.name for o in adopt))
    meshes = [c for c in root.children_recursive if c.type == "MESH"]

    skinned = root.type == "ARMATURE"
    if skinned:
        numbered = joints.number_new_rig(root)
        if numbered:
            notes.append(f"numbered {len(numbered)} bones as game joints {numbered[0][1]}-{numbered[-1][1]}")
    joint_names = {b.name for b in joints.joint_bones(root)} if skinned else set()

    folder = str(PureWindowsPath(path).parent)
    default_material = None
    weights_of = {}
    for mesh_ob in meshes:
        if not any(slot.material for slot in mesh_ob.material_slots):
            if default_material is None:
                default_material = bpy.data.materials.new(f"{root.name}_material")
            if mesh_ob.material_slots:
                mesh_ob.material_slots[0].material = default_material
            else:
                mesh_ob.data.materials.append(default_material)
            notes.append(f"{mesh_ob.name}: had no material, got {default_material.name}")
        weights = _weights_per_vertex(mesh_ob, joint_names) if skinned else 0
        for slot in mesh_ob.material_slots:
            if slot.material is not None:
                weights_of[slot.material] = max(weights_of.get(slot.material, 0), weights)
    for mat, weights in weights_of.items():
        if not mat.node_tree or not mtfw_material._has_mtfw_shader_group(mat):
            convert_material(mat, skinned, weights, notes)
            notes.append(f"{mat.name}: converted to a DMC4 material")
        _prepare_images(mat, folder, notes)

    asset = root.albam_asset
    asset.app_id = APP_ID
    asset.relative_path = path
    asset.extension = "mod"
    asset.original_bytes = blank_mod153()
    set_light_group(root.albam_mod, DEFAULT_LIGHT_GROUP)
    set_lod_distances(root.albam_mod, *DEFAULT_LOD)
    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = root
    context.scene.albam.exportable.file_list.update()
    return root, notes


@blender_registry.register_blender_type
class ALBAM_OT_ModNew(bpy.types.Operator):
    """Make a new DMC4 model (.mod) from this armature, Empty or mesh, with no game file to start from: its meshes
    (and a rig's bones) become the model, materials get the DMC4 shader, and it's added to the Export list"""
    bl_idname = "albam.mod_new"
    bl_label = "New DMC4 Model"
    bl_options = {"REGISTER", "UNDO"}

    path: bpy.props.StringProperty(
        name="Game Path",
        description="Where the model goes in the game, with .mod (e.g. model\\game\\mymodel\\mymodel.mod). Its new "
                    "textures go in the same folder")

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type in ("ARMATURE", "EMPTY", "MESH") and not _taken(ob)

    def invoke(self, context, event):
        root = root_candidate(context.object)
        self.path = default_path((root or context.object).name)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            root, notes = setup_new_model(context, context.object, self.path)
        except AlbamCheckFailure:
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
            return {"CANCELLED"}
        for note in notes:
            print(f"[Albam] {root.name}: {note}")
        root["mod_new_notes"] = "\n".join(notes)
        warn = [n for n in notes if "not a DDS" in n or "not connected" in n or "another game" in n]
        self.report({"WARNING" if warn else "INFO"},
                    f"{root.name} is a new DMC4 model ({root.albam_asset.relative_path}); "
                    + (f"{len(warn)} thing(s) to fix before export, see the panel" if warn else "export it from the Export list"))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_PT_NewModel(bpy.types.Panel):
    bl_label = "DMC4 Model"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        ob = context.object
        if ob is None or context.scene.albam.apps.app_selected != APP_ID:
            return False
        root = model_root(ob)
        return (root is not None and root.get("mod_new_notes") is not None) or \
            (ob.type in ("ARMATURE", "EMPTY", "MESH") and not _taken(ob))

    def draw(self, context):
        layout = self.layout
        root = model_root(context.object)
        if root is not None:
            notes = root.get("mod_new_notes", "")
            layout.label(text=f"New model: {root.albam_asset.relative_path}", icon="OBJECT_DATA")
            for note in notes.split("\n") if notes else []:
                icon = "ERROR" if ("not a DDS" in note or "not connected" in note or "another game" in note) \
                    else "INFO"
                layout.label(text=note, icon=icon)
            return
        col = layout.column()
        col.label(text="Not part of a game model yet.")
        col.operator("albam.mod_new", icon="ADD")
