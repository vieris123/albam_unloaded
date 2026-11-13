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

`update_model` makes the model's materials and textures exportable, and runs again at every export, so whatever was
added since is picked up:
- a material without the "MT Framework shader" group gets it (`convert_material`): the Principled BSDF's (or any other
  shader's) Base Color, Alpha, Normal, Specular and Roughness inputs become the game's base, normal and mask maps,
  following packed channels through Separate Color nodes; functions that exist in XfMaterialStandard.bfx for that
  vertex layout (skinned up to 4 weights: SKIN_4WT + vtype 0, more: SKIN_8WT + vtype 1, no armature: SKIN_NONE + vtype
  2; lighting SH4SPOT; normal map and specular as found: every combination is in the .bfx table at 0x56C and most are
  common in the game's files);
- images that aren't DDS are converted (texture_convert.py);
- images get the dmc4 app and a game path next to the model.
New DMC4 Model and Update Materials & Textures also split meshes: a mesh record has one material and a bone palette of
32 bones. Export doesn't (it changes no objects): its checks name the meshes instead.
"""
from array import array
import struct
from pathlib import PureWindowsPath
from types import SimpleNamespace

import bmesh
import bpy

from albam.exceptions import AlbamCheckFailure
from albam.lib.blender import is_blimage_dds
from albam.registry import blender_registry
from . import joints, texture_convert
from .model_settings import model_root, set_light_group, set_lod_distances

APP_ID = "dmc4"
MOD_VERSION = 153
DEFAULT_LIGHT_GROUP = 3
DEFAULT_LOD = (1000, 3000)
HEADER_SIZE = 0x90   # header (72) + reserved_01 / 02 + bsphere + bbox_min / max + model_info: what rModel reads first
MAX_SKIN_4 = 4       # weights per vertex SKIN_4WT (vtype 0) holds; up to 8 need SKIN_8WT (vtype 1)
MAX_JOINTS = 254     # joint numbers 0-253
MAX_PATH = 63        # a texture path in the .mod's 64-byte table
ATTR = {"NONE": ("0x10", 8), "TEST": ("0x8", 100), "BLEND": ("0x40", 8)}   # alpha use -> attr, alpha_ref (DX9 models)
DEFAULT_POWER = 16.0 # SpecularPow when a roughness image varies over the surface
WARNING = "! "       # notes starting with this are things to fix
CUT_NORMALS = "albam_cut_normals"   # corner normals carried through a mesh split
AUTO_PATH = "_albam_auto_path"      # on an image: the game path this code gave it, so a path set by hand is left alone
SEPARATE_NODES = ("SEPARATE_COLOR", "SEPRGB", "SEPARATE_XYZ")


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


def _armature_under(ob):
    """the only armature among an Empty's descendants, else None"""
    found = [c for c in ob.children_recursive if c.type == "ARMATURE"]
    return found[0] if len(found) == 1 else None


def root_candidate(ob):
    """the object New DMC4 Model turns into the model's root for the active object ob. An armature is its own root,
    and so is an Empty unless it holds a rig (imported models are often Empty > armature > meshes: the rig is what
    makes the model skinned). A mesh's root is the armature deforming it, else its parent armature or Empty, else
    None (a new Empty is made for it)."""
    if ob is None:
        return None
    if ob.type == "ARMATURE":
        return ob
    if ob.type == "EMPTY":
        return _armature_under(ob) or ob
    if ob.type != "MESH":
        return None
    armature = _armature_of(ob)
    if armature is not None:
        return armature
    for parent in _ancestors(ob):
        if parent.type in ("ARMATURE", "EMPTY"):
            return root_candidate(parent)
    return None


def default_path(name):
    stem = texture_convert.game_name(name.split(".")[0], "model").lower()
    return f"model\\game\\{stem}\\{stem}.mod"


def ascii_path(path):
    """a game path with its non-ASCII parts replaced (ASCII parts are kept as they are, dots and all)"""
    *folders, name = path.split("\\")
    stem, dot, ext = name.rpartition(".")
    parts = [p if p.isascii() else texture_convert.game_name(p, "model") for p in folders + [stem]]
    return "\\".join(parts) + dot + ext


def _path_in_use(path, root=None):
    return any(model_root(o) is o and o is not root and o.albam_asset.relative_path.lower() == path.lower()
               for o in bpy.data.objects)


def _fix_model_path(root, notes):
    """a model from before default_path kept to ASCII: the path, and with it the folder its textures get"""
    old = root.albam_asset.relative_path
    if old.isascii():
        return
    new, stem, n = ascii_path(old), ascii_path(old)[:-len(".mod")], 1
    while _path_in_use(new, root):
        n += 1
        new = f"{stem}_{n}.mod"
    root.albam_asset.relative_path = new
    notes.append(f"game path changed to {new}: game paths are ASCII only")


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
        if _armature_of(ob) not in (None, root):   # selected, but another rig's
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


def _upstream(socket, depth=6):
    """(Image Texture node, channel) feeding socket, directly or through a few nodes; channel: 0-2 through a Separate
    Color node, 3 from the image's Alpha output, None for its colour. A mix factor is only followed last."""
    if depth < 0 or not socket.is_linked:
        return None, None
    link = socket.links[0]
    node = link.from_node
    if node.type == "TEX_IMAGE":
        return node, 3 if link.from_socket.name == "Alpha" else None
    if node.type in SEPARATE_NODES:
        found, _channel = _upstream(node.inputs[0], depth - 1)
        return found, list(node.outputs).index(link.from_socket) if found is not None else None
    for inp in sorted(node.inputs, key=lambda i: i.name in ("Fac", "Factor")):
        found, channel = _upstream(inp, depth - 1)
        if found is not None:
            return found, channel
    return None, None


def _upstream_image(socket, depth=6):
    """the Image Texture node feeding socket, directly or through a few nodes"""
    return _upstream(socket, depth)[0]


def _normal_source(socket, mat, notes):
    """the normal map behind a shader's Normal input: through a Normal Map node, past a Bump node, which is a height
    map and has nothing the game can read"""
    if not socket.is_linked:
        return None
    node = socket.links[0].from_node
    if node.type == "BUMP":
        notes.append(f"{WARNING}{mat.name}: a bump map isn't converted (the game takes normal maps)")
        return _normal_source(node.inputs["Normal"], mat, notes)
    if node.type == "NORMAL_MAP":
        return _upstream(node.inputs["Color"])[0]
    return _upstream(socket)[0]


def _surface_shader(nt, output):
    """the shader to read a material from: its Principled BSDF, else what feeds the output, past Mix / Add Shaders"""
    principled = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if principled is not None or output is None or not output.inputs["Surface"].is_linked:
        return principled
    node = output.inputs["Surface"].links[0].from_node
    while node.type in ("MIX_SHADER", "ADD_SHADER"):
        linked = [i.links[0].from_node for i in node.inputs if i.is_linked and i.name != "Fac"]
        linked = [n for n in linked if n.type != "BSDF_TRANSPARENT"]
        if not linked:
            return None
        node = linked[0]
    return node


def _alpha_source(nt, shader):
    """(node, channel) of the opacity: the Alpha input, or the factor of a Mix Shader with a Transparent BSDF"""
    alpha = shader.inputs.get("Alpha") if shader is not None else None
    if alpha is not None and alpha.is_linked:
        return _upstream(alpha)
    for node in nt.nodes:
        if node.type == "MIX_SHADER" and any(
                i.is_linked and i.links[0].from_node.type == "BSDF_TRANSPARENT" for i in node.inputs):
            return _upstream(node.inputs[0])
    return None, None


def _pbr_value(shader, names, default, mat, notes):
    """(constant, image node, channel) of a Principled input for a PBR material: an image (constant 1, the image
    scaled by it) or the input's value. names: the input's names across Blender versions"""
    socket = next((shader.inputs.get(n) for n in names if shader is not None and shader.inputs.get(n) is not None),
                  None)
    if socket is None:
        return default, None, None
    if socket.is_linked:
        node, channel = _upstream(socket)
        if node is not None and node.image is not None:
            return 1.0, node, channel
        notes.append(f"{mat.name}: its {socket.name} comes from nodes that aren't an image; "
                     f"{socket.default_value:.2f} is used")
    return float(socket.default_value), None, None


def _occlusion_source(nt):
    """(image node, channel) of the occlusion map in the glTF Material Output node Blender's glTF importer makes"""
    for node in nt.nodes:
        tree = getattr(node, "node_tree", None)
        if node.type == "GROUP" and tree is not None and tree.name.lower().startswith("gltf") and \
                "Occlusion" in node.inputs:
            found, channel = _upstream(node.inputs["Occlusion"])
            if found is not None and found.image is not None:
                return found, channel
    return None, None


def _pbr_material(mat, nt, shader, group, x, y, functions, notes):
    """the PBR part of a conversion (pbr.py): ORM mask / additional map images linked to the group, and the
    record's values {name: value}. None if dmc4_hook has no PBR shader for these functions (classic then)."""
    from . import pbr
    rough, rough_node, rough_ch = _pbr_value(shader, ("Roughness",), 0.5, mat, notes)
    metal, metal_node, metal_ch = _pbr_value(shader, ("Metallic",), 0.0, mat, notes)
    level, _node, _ch = _pbr_value(shader, ("Specular IOR Level", "Specular"), 0.5, mat, [])
    if _node is not None:
        notes.append(f"{mat.name}: a specular map isn't used by PBR materials; its strength is "
                     f"{pbr.DEFAULT_F0 / pbr.F0_PER_LEVEL:.2f}")
        level = pbr.DEFAULT_F0 / pbr.F0_PER_LEVEL
    weight, weight_node, weight_ch = _pbr_value(shader, ("Subsurface Weight", "Subsurface"), 0.0, mat, notes)
    radius_in = shader.inputs.get("Subsurface Radius") if shader is not None else None
    radius = tuple(radius_in.default_value) if radius_in is not None else (1.0, 0.2, 0.1)
    occ_node, occ_ch = _occlusion_source(nt)
    sss = weight_node is not None or weight > 0
    functions = dict(functions, func_lighting=4 if sss else 2)
    reason = pbr.unsupported_reason(functions)
    if reason is not None:
        notes.append(f"{mat.name}: made a classic material: {reason}")
        return None

    nodes = [n for n in (occ_node, rough_node, metal_node) if n is not None]
    if nodes:
        image = texture_convert.convert(
            texture_convert.ORM, [n.image if n is not None else None for n in (occ_node, rough_node, metal_node)],
            [occ_ch, rough_ch, metal_ch])[0]
        if image is None:
            notes.append(f"{WARNING}{mat.name}: can't read its roughness / metal / occlusion images (missing files?)")
            rough = 1.0 if rough_node is not None else rough   # NullWhite reads 1
            metal = 0.0 if metal_node is not None else metal
        else:
            node = _image_node(nt, image, nodes[0], (x, y - 600))
            nt.links.new(node.outputs["Color"], group.inputs["Specular MM"])
    scatter = (1.0, 1.0, 1.0)
    if sss:
        scatter = pbr.scatter_from_principled(1.0 if weight_node is not None else weight, radius)
        if weight_node is not None:
            image = texture_convert.convert(texture_convert.ADDITIONAL, [None, weight_node.image],
                                            [None, weight_ch])[0]
            if image is None:
                notes.append(f"{WARNING}{mat.name}: can't read {weight_node.image.name} (a missing file?)")
            else:
                node = _image_node(nt, image, weight_node, (x, y - 900))
                nt.links.new(node.outputs["Color"], group.inputs["Alpha Mask AM"])
    return {"func_lighting": pbr.THIN if sss else pbr.SH4SPOT, "func_specular": pbr.RIM,
            "envmap_bias": pbr.ENV_BIAS, "fresnel_factor": (rough, metal, level * pbr.F0_PER_LEVEL,
                                                             pbr.DEFAULT_REFLECTION),
            "lightmap_factor": scatter + (0.0,) if sss else pbr.DEFAULT_LIGHTMAP_FACTOR}


def _specular_power(shader):
    """SpecularPow for a shader's Roughness: the display's roughness = sqrt(2 / (power + 2)) turned around"""
    rough = shader.inputs.get("Roughness") if shader is not None else None
    if rough is None or rough.is_linked:
        return DEFAULT_POWER
    return min(max(2.0 / max(rough.default_value, 0.01) ** 2 - 2.0, 1.0), 100.0)


def _image_node(nt, image, like, location):
    """a new Image Texture node for image with the UVs of `like` (a source node, kept apart: a packed image feeds
    several slots)"""
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = image
    node.location = location
    if like is not None:
        node.interpolation, node.extension = like.interpolation, like.extension
        if like.inputs[0].is_linked:
            nt.links.new(like.inputs[0].links[0].from_socket, node.inputs[0])
    return node


def _prune(nt, output):
    """remove what no longer leads to the material's output (the old shader, its image and Normal Map nodes)"""
    keep, todo = set(), [output]
    while todo:
        node = todo.pop()
        if node.name in keep:
            continue
        keep.add(node.name)
        todo.extend(link.from_node for inp in node.inputs for link in inp.links)
    for node in list(nt.nodes):
        if node.name not in keep and node.type != "FRAME":
            nt.nodes.remove(node)


def convert_material(mat, skinned, weights, notes, flip_green=False, pbr=False):
    """give mat the MT Framework shader group and DMC4 properties, from what its shader shows (see the module doc).
    pbr: a PBR material for dmc4_hook's PbrMaterials (pbr.py) where it has a shader, else classic"""
    from . import material as mtfw_material
    mat.use_nodes = True
    nt = mat.node_tree
    mtfw_material._create_mtfw_shader()
    output = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None) or \
        next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    shader = _surface_shader(nt, output)
    colour_in = (shader.inputs.get("Base Color") or shader.inputs.get("Color")) if shader is not None else None
    base = _upstream(colour_in)[0] if colour_in is not None else None
    if base is None and colour_in is None:   # an unknown shader: its largest image is the best guess
        images = [n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image is not None]
        base = max(images, key=lambda n: n.image.size[0] * n.image.size[1], default=None)
    colour = tuple(colour_in.default_value) if colour_in is not None else (0.8, 0.8, 0.8, 1.0)
    alpha_node, alpha_channel = _alpha_source(nt, shader)
    normal = _normal_source(shader.inputs["Normal"], mat, notes) \
        if shader is not None and "Normal" in shader.inputs else None
    spec_in = (shader.inputs.get("Specular IOR Level") or shader.inputs.get("Specular")) if shader is not None else None
    specular, spec_channel = _upstream(spec_in) if spec_in is not None else (None, None)
    rough_in = shader.inputs.get("Roughness") if shader is not None else None
    rough, rough_channel = _upstream(rough_in) if rough_in is not None else (None, None)
    power = _specular_power(shader)
    for name in ("Emission Color", "Emission") if pbr else ("Metallic", "Emission Color", "Emission"):
        socket = shader.inputs.get(name) if shader is not None else None
        if socket is not None and socket.is_linked and _upstream_image(socket) is not None:
            notes.append(f"{mat.name}: its {name.lower()} map isn't used (the game has no slot for it)")

    if output is None:
        output = nt.nodes.new("ShaderNodeOutputMaterial")
    group = nt.nodes.new("ShaderNodeGroup")
    group.node_tree = bpy.data.node_groups[mtfw_material.MTFW_SHADER_NODEGROUP_NAME]
    group.name = "MTFrameworkGroup"
    group.width = 300
    group.location = (output.location[0] - 400, output.location[1])
    nt.links.new(group.outputs[0], output.inputs["Surface"])
    x, y = group.location[0] - 350, group.location[1]

    use = "NONE"
    image = None
    has_alpha = alpha_node is not None and alpha_node.image is not None
    if base is not None and base.image is not None:
        if is_blimage_dds(base.image) and not base.image.get(texture_convert.RECIPE_PROP):
            image, use = base.image, "TEST" if has_alpha else "NONE"
        else:
            other = alpha_node.image if has_alpha and alpha_node.image != base.image else None
            sources = [base.image, other] if other is not None else [base.image]
            channels = [None, alpha_channel] if other is not None else [None]
            image, use = texture_convert.convert(texture_convert.BASE, sources, channels, use_alpha=has_alpha)
            if image is None:
                notes.append(f"{WARNING}{mat.name}: can't read {base.image.name} (a missing file?)")
    if image is None:
        use = "NONE"
        image = texture_convert.solid_image(mat.name, colour)
        notes.append(f"{mat.name}: no base texture, made a flat colour one")
    node = _image_node(nt, image, base, (x, y))
    nt.links.new(node.outputs["Color"], group.inputs["Diffuse BM"])

    has_normal = False
    if normal is not None and normal.image is not None:
        image = normal.image
        if not (is_blimage_dds(image) and texture_convert.is_game_normal(image)):
            image = texture_convert.convert(texture_convert.NORMAL, [image], flip_green=flip_green)[0]
        if image is None:
            notes.append(f"{WARNING}{mat.name}: can't read {normal.image.name} (a missing file?)")
        else:
            node = _image_node(nt, image, normal, (x, y - 300))
            nt.links.new(node.outputs["Color"], group.inputs["Normal NM"])
            nt.links.new(node.outputs["Alpha"], group.inputs["Alpha NM"])
            has_normal = True

    vtype, func_skin = shader_functions(skinned, weights)
    functions = {"func_skin": func_skin, "func_lighting": 2, "func_normalmap": int(has_normal), "func_specular": 4,
                 "func_lightmap": 0, "func_multitexture": 0}
    pbr_values = _pbr_material(mat, nt, shader, group, x, y, functions, notes) if pbr else None

    has_mask = False
    spec_image = specular.image if specular is not None else None
    rough_image = rough.image if rough is not None else None
    if pbr_values is None and (spec_image is not None or rough_image is not None):
        image = texture_convert.convert(texture_convert.MASK, [spec_image, rough_image],
                                        [spec_channel, rough_channel])[0]
        if image is not None:
            node = _image_node(nt, image, specular or rough, (x, y - 600))
            nt.links.new(node.outputs["Color"], group.inputs["Specular MM"])
            has_mask = True
    _prune(nt, output)

    props = mat.albam_custom_properties.get_custom_properties_for_appid(APP_ID)
    props.vtype = hex(vtype)
    props.func_skin = hex(func_skin)
    props.func_lighting = "0x2"      # SH4SPOT
    props.func_normalmap = "0x1" if has_normal else "0x0"
    props.func_specular = "0x1" if has_mask else "0x0"
    props.func_lightmap = "0x0"
    props.func_multitexture = "0x0"
    props.attr, props.alpha_ref = ATTR[use]
    props.fresnel_factor = (0.0, 0.0, power, 0.0)   # no fresnel loss, no environment map
    props.lightmap_factor = (1.0, 1.0, 1.0, 0.0)
    props.envmap_bias = 0
    for name, value in (pbr_values or {}).items():
        setattr(props, name, value)
    record = SimpleNamespace()
    props.copy_custom_properties_to(record)
    mtfw_material.setup_dmc4_material(record, mat)


def _image_nodes(mat):
    return [n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image is not None] if mat.node_tree else []


def _update_images(mat, flip_green, notes):
    """bring the images of a DMC4 material up to date: converted ones with their sources, new ones in a slot converted"""
    from .material import _group_socket_name
    from .texture import MISSING_TEXTURE_PROP
    nt = mat.node_tree
    for node in _image_nodes(mat):
        image = node.image
        if image.get(MISSING_TEXTURE_PROP) or image.albam_asset.render_target:
            continue
        if image.get(texture_convert.RECIPE_PROP):
            node.image = texture_convert.refresh(image)
            continue
        if is_blimage_dds(image):
            continue
        socket = _group_socket_name(node.outputs["Color"])
        if socket is None:
            continue
        kind = texture_convert.SOCKET_KINDS.get(socket, texture_convert.BASE)
        props = mat.albam_custom_properties.get_custom_properties_for_appid(APP_ID)
        new = texture_convert.convert(kind, [image], flip_green=flip_green,
                                      use_alpha=int(props.attr, 16) != 0x10)[0]
        if new is None:
            notes.append(f"{WARNING}{mat.name}: can't read {image.name} (a missing file?)")
            continue
        node.image = new
        notes.append(f"{image.name}: converted to {new.name}")
        if socket == "Normal NM":
            group = nt.nodes.get("MTFrameworkGroup")
            if group is not None:
                nt.links.new(node.outputs["Alpha"], group.inputs["Alpha NM"])


def _follows_model(im, folder):
    """True if the image's game path should move with its model: one made here (images converted before the path was
    recorded count), not a game texture or a path set by hand"""
    path = im.albam_asset.relative_path
    if not path or im.albam_asset.original_bytes or str(PureWindowsPath(path).parent).lower() == folder.lower():
        return False
    stamp = im.get(AUTO_PATH)
    return stamp == path if stamp is not None else texture_convert.RECIPE_PROP in im


def _prepare_images(mat, folder, notes):
    """the material's images: the dmc4 app and, without one, a game path in the model's folder, unique and short
    enough for the .mod's path table (no extension in the table: the export adds .tex). A model given another path
    takes its textures along (the .mod's table holds their full paths)."""
    for node in _image_nodes(mat):
        im = node.image
        if im.albam_asset.original_bytes and im.albam_asset.app_id != APP_ID:
            notes.append(f"{WARNING}{im.name}: a texture of another game ({im.albam_asset.app_id})")
            continue
        im.albam_asset.app_id = APP_ID
        old = im.albam_asset.relative_path
        follow = _follows_model(im, folder)
        if old and old.isascii() and not follow:
            continue
        used = {other.albam_asset.relative_path.lower() for other in bpy.data.images if other != im}
        name = PureWindowsPath(old).stem if follow else im.name
        stem = texture_convert.stem_of(name)[:max(1, MAX_PATH - len(folder) - 1)]
        path, n = f"{folder}\\{stem}.tex", 1
        while path.lower() in used:
            n += 1
            path = f"{folder}\\{stem[:max(1, MAX_PATH - len(folder) - 4)]}_{n}.tex"
        im.albam_asset.relative_path = path
        im.albam_asset.extension = "tex"
        im[AUTO_PATH] = path
        if old:
            notes.append(f"{im.name}: game path changed to {path}" + ("" if follow else ": game paths are ASCII only"))


def _keep_faces(ob, faces, slot=None):
    """reduce a mesh to some of its faces (indices), and to one material slot if slot is given. The normals are kept as
    they were: along the cut Blender would recompute them from fewer faces, and the game would show a seam."""
    me = ob.data
    keep = set(faces)
    cut = len(keep) < len(me.polygons)
    material = ob.material_slots[slot].material if slot is not None else None
    if cut:
        normals = array("f", bytes(4 * 3 * len(me.loops)))
        me.corner_normals.foreach_get("vector", normals)
        me.attributes.new(CUT_NORMALS, "FLOAT_VECTOR", "CORNER").data.foreach_set("vector", normals)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in keep], context="FACES")
    if slot is not None:
        for face in bm.faces:
            face.material_index = 0
    bm.to_mesh(me)
    bm.free()
    if cut:
        normals = array("f", bytes(4 * 3 * len(me.loops)))
        me.attributes[CUT_NORMALS].data.foreach_get("vector", normals)
        me.attributes.remove(me.attributes[CUT_NORMALS])
        me.normals_split_custom_set([tuple(normals[i:i + 3]) for i in range(0, len(normals), 3)])
    if slot is not None:
        me.materials.clear()
        me.materials.append(material)


def _copy_mesh(ob, name):
    """a copy of a mesh object with its own data: same parent, modifiers and collections"""
    copy = ob.copy()
    copy.data = ob.data.copy()
    copy.name = name
    for collection in ob.users_collection:
        collection.objects.link(copy)
    return copy


def split_by_material(meshes, notes):
    """one material per mesh: a mesh using several becomes one object per material, with its modifiers and weights.
    Unused slots go too: export reads a mesh's first slot. Returns the new objects."""
    made = []
    for ob in meshes:
        used = sorted({p.material_index for p in ob.data.polygons})
        used = [i for i in used if i < len(ob.material_slots)]
        if len(ob.material_slots) < 2 or not used:
            continue
        faces = {i: [p.index for p in ob.data.polygons if p.material_index == i] for i in used}
        for index in used[1:]:
            material = ob.material_slots[index].material
            copy = _copy_mesh(ob, f"{ob.name}_{material.name if material else index}")
            _keep_faces(copy, faces[index], index)
            made.append(copy)
        if len(used) > 1:
            notes.append(f"{ob.name}: split into {len(used)} meshes, one per material")
        _keep_faces(ob, faces[used[0]], used[0])
    return made


def _bone_parts(ob, names):
    """[faces (indices)] per part, each weighted to at most MAX_MESH_BONES bones. Faces are grouped by the bones they
    use, biggest sets first, each set going to the part it adds the fewest bones to: bones are local, so parts stay
    in one piece. A single face over the limit (an n-gon) stays alone: export's check names it."""
    limit = joints.MAX_MESH_BONES
    bone_of = {vg.index: vg.name for vg in ob.vertex_groups if vg.name in names}
    vertex_bones = [frozenset(bone_of[g.group] for g in v.groups if g.weight > 0 and g.group in bone_of)
                    for v in ob.data.vertices]
    by_bones = {}
    for poly in ob.data.polygons:
        key = frozenset().union(*(vertex_bones[i] for i in poly.vertices))
        by_bones.setdefault(key, []).append(poly.index)
    parts = []
    for key in sorted(by_bones, key=lambda k: (-len(k), sorted(k))):
        fitting = [p for p in parts if len(p["bones"] | key) <= limit]
        part = min(fitting, key=lambda p: len(key - p["bones"]), default=None)
        if part is None:
            part = {"bones": set(), "faces": []}
            parts.append(part)
        part["bones"] |= key
        part["faces"] += by_bones[key]
    return [p["faces"] for p in parts]


def split_by_bones(root, notes):
    """split the meshes weighted to more bones than a bone palette holds. Returns the new objects."""
    made = []
    if root.type != "ARMATURE":
        return made
    names = {b.name for b in joints.joint_bones(root)}
    for ob in joints.model_meshes(root):
        count = len(joints.weighted_bones(ob, names))
        if count <= joints.MAX_MESH_BONES:
            continue
        parts = _bone_parts(ob, names)
        for n, faces in enumerate(parts[1:], 2):
            copy = _copy_mesh(ob, f"{ob.name}_{n}")
            _keep_faces(copy, faces)
            made.append(copy)
        _keep_faces(ob, parts[0])
        notes.append(f"{ob.name}: weighted to {count} bones, split into {len(parts)} meshes")
    return made


def split_meshes(root, notes):
    """one material and at most 32 bones per mesh"""
    split_by_material(joints.model_meshes(root), notes)
    split_by_bones(root, notes)


def update_model(root, default_material=False):
    """Make everything under a model's root exportable (see the module doc); nothing to do on a model that already
    is. default_material: meshes without a material get one (New DMC4 Model; at export that's left to its check, a
    mesh with none is more likely a mistake). Returns notes, those starting with WARNING need the user."""
    from . import material as mtfw_material
    notes = []
    _fix_model_path(root, notes)
    skinned = root.type == "ARMATURE"
    joint_names = {b.name for b in joints.joint_bones(root)} if skinned else set()
    flip_green = bool(root.get("mod_normal_directx"))
    folder = str(PureWindowsPath(root.albam_asset.relative_path).parent)
    default = None
    to_convert, ready = {}, []
    for mesh_ob in joints.model_meshes(root):
        if default_material and not any(slot.material for slot in mesh_ob.material_slots):
            if default is None:
                default = bpy.data.materials.new(f"{root.name}_material")
            if mesh_ob.material_slots:
                mesh_ob.material_slots[0].material = default
            else:
                mesh_ob.data.materials.append(default)
            notes.append(f"{mesh_ob.name}: had no material, got {default.name}")
        for mat in (slot.material for slot in mesh_ob.material_slots if slot.material is not None):
            if mat.node_tree and mtfw_material._has_mtfw_shader_group(mat):
                if mat not in ready:
                    ready.append(mat)
                continue
            weights = _weights_per_vertex(mesh_ob, joint_names) if skinned else 0
            to_convert[mat] = max(to_convert.get(mat, 0), weights)
    for mat, weights in to_convert.items():
        convert_material(mat, skinned, weights, notes, flip_green, pbr=root.albam_mod.pbr)
        kind = "PBR " if mat.albam_custom_properties.get_custom_properties_for_appid(APP_ID).func_specular == "0x4" \
            else ""
        notes.append(f"{mat.name}: converted to a DMC4 {kind}material")
        _prepare_images(mat, folder, notes)
    from . import pbr
    for mat in ready:
        _update_images(mat, flip_green, notes)
        _prepare_images(mat, folder, notes)
        pbr.update_display(mat)   # PBR materials set by hand or saved before the preview had PBR inputs
    return notes


def setup_new_model(context, ob, path, normal_directx=False, pbr=True):
    """Make a new DMC4 model of ob (see root_candidate) at game path `path`; pbr: its materials become PBR materials
    (model_settings.AlbamModSettings.pbr). Returns (root, notes)."""
    path = path.strip().replace("/", "\\")
    if not path.lower().endswith(".mod"):
        path += ".mod"
    typed, path = path, ascii_path(path)
    if _path_in_use(path):
        raise AlbamCheckFailure(f"{path} is already a model in this file", details=path,
                                solution="Pick another game path")
    selected = [o for o in context.selected_objects if o.type == "MESH"]
    root = root_candidate(ob)
    if root is None:   # a lone mesh: a new Empty root for it and the other selected meshes
        selected = selected or ([ob] if ob is not None and ob.type == "MESH" else [])
    elif _taken(root):
        raise AlbamCheckFailure(f"{root.name} already belongs to an Albam file", details=root.name,
                                solution="Pick an armature, Empty or mesh that isn't part of an imported file")
    elif ob is not None and ob != root and ob.type == "EMPTY":   # Empty > armature: meshes beside the rig come along
        selected += [c for c in ob.children_recursive if c.type == "MESH" and c not in selected]
    # checked before anything changes: a refused operator leaves no undo step
    if root is not None and root.type == "ARMATURE" and len(joints.joint_bones(root)) > MAX_JOINTS:
        raise AlbamCheckFailure(
            f"{root.name} has too many bones",
            details=f"{len(joints.joint_bones(root))} bones, a model holds {MAX_JOINTS}",
            solution="Select the helper bones in Pose Mode and use Bone Properties > Game Joint > Mark Selected, or "
                     "move part of the model (hair, cloth) to its own armature and model")
    adopt = _meshes_to_adopt(context, root, selected)
    owned = joints.model_meshes(root) if root is not None else []
    if not owned and not adopt:
        name = root.name if root is not None else (ob.name if ob is not None else "")
        raise AlbamCheckFailure(f"{name} has no meshes", details=name,
                                solution="Parent the model's meshes to it first, or select them too")
    notes = [f"game path changed to {path}: game paths are ASCII only"] if path != typed else []
    if root is None:
        root = bpy.data.objects.new(PureWindowsPath(path).stem, None)
        root.empty_display_type = "PLAIN_AXES"
        for collection in (ob.users_collection if ob is not None else [context.collection]):
            collection.objects.link(root)
    for mesh_ob in adopt:
        _parent_keep_transform(mesh_ob, root)
    if adopt:
        notes.append(f"parented {len(adopt)} mesh(es) to {root.name}: " + ", ".join(o.name for o in adopt))
    if any(abs(s - 1.0) > 1e-3 for s in root.scale):
        notes.append(f"{WARNING}{root.name} is scaled {tuple(round(s, 3) for s in root.scale)}: bones ignore that "
                     "scale. Apply it (Object > Apply > Scale)")

    if root.type == "ARMATURE":
        numbered = joints.number_new_rig(root)
        if numbered:
            notes.append(f"numbered {len(numbered)} bones as game joints {numbered[0][1]}-{numbered[-1][1]}")

    asset = root.albam_asset
    asset.app_id = APP_ID
    asset.relative_path = path
    asset.extension = "mod"
    asset.original_bytes = blank_mod153()
    split_meshes(root, notes)
    if normal_directx:
        root["mod_normal_directx"] = 1
    root.albam_mod.pbr = pbr
    notes += update_model(root, default_material=True)
    set_light_group(root.albam_mod, DEFAULT_LIGHT_GROUP)
    set_lod_distances(root.albam_mod, *DEFAULT_LOD)
    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = root
    context.scene.albam.exportable.file_list.update()
    return root, notes


def _report_notes(op, root, notes, done):
    for note in notes:
        print(f"[Albam] {root.name}: {note}")
    root["mod_new_notes"] = "\n".join(notes)
    warn = [n for n in notes if n.startswith(WARNING)]
    op.report({"WARNING" if warn else "INFO"},
              done + (f"; {len(warn)} thing(s) to fix, see the DMC4 Model panel" if warn else ""))


@blender_registry.register_blender_type
class ALBAM_OT_ModNew(bpy.types.Operator):
    """Make a new DMC4 model (.mod) from this armature, Empty or mesh, with no game file to start from: its meshes
    (and a rig's bones) become the model, materials and textures are converted to the game's, and it's added to the
    Export list"""
    bl_idname = "albam.mod_new"
    bl_label = "New DMC4 Model"
    bl_options = {"REGISTER", "UNDO"}

    path: bpy.props.StringProperty(
        name="Game Path",
        description="Where the model goes in the game, with .mod (e.g. model\\game\\mymodel\\mymodel.mod). Its new "
                    "textures go in the same folder. English letters, digits, _ and - only: anything else is replaced")
    normal_directx: bpy.props.BoolProperty(
        name="DirectX Normal Maps",
        description="Turn on if the model's normal maps are made the DirectX way (green pointing down, usual for "
                    "models taken from other games). Off for maps that look right in Blender's Normal Map node")
    pbr: bpy.props.BoolProperty(
        name="PBR Materials", default=True,
        description="Convert the materials to PBR (roughness, metal, occlusion and subsurface from the Principled "
                    "BSDF), drawn by dmc4_hook's PbrMaterials. Off: the game's own shading, which works without "
                    "dmc4_hook")

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type in ("ARMATURE", "EMPTY", "MESH") and not _taken(ob) and \
            not _taken(root_candidate(ob) or ob)

    def invoke(self, context, event):
        root = root_candidate(context.object)
        self.path = default_path((root or context.object).name)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            root, notes = setup_new_model(context, context.object, self.path, self.normal_directx, self.pbr)
        except AlbamCheckFailure:
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
            return {"CANCELLED"}
        _report_notes(self, root, notes, f"{root.name} is a new DMC4 model ({root.albam_asset.relative_path})")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_ModUpdate(bpy.types.Operator):
    """Bring this model up to date: split meshes with several materials or more than 32 bones, and convert materials
    without the DMC4 shader, images that aren't DDS and textures whose source image changed. Export does the
    conversions by itself, but only this splits meshes"""
    bl_idname = "albam.mod_update"
    bl_label = "Update Materials & Textures"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and model_root(context.object) is not None

    def execute(self, context):
        root = model_root(context.object)
        notes = []
        split_meshes(root, notes)
        notes += update_model(root)
        _report_notes(self, root, notes, f"{root.name}: {len(notes)} change(s)" if notes else f"{root.name} is up to date")
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
        if ob is None:
            return False
        root = model_root(ob)
        return (root is not None and root.albam_asset.app_id == APP_ID) or ALBAM_OT_ModNew.poll(context)

    def draw(self, context):
        layout = self.layout
        root = model_root(context.object)
        if root is not None:
            notes = root.get("mod_new_notes", "")
            layout.label(text=f"Model: {root.albam_asset.relative_path}", icon="OBJECT_DATA")
            layout.operator("albam.mod_update", icon="FILE_REFRESH")
            layout.prop(root.albam_mod, "pbr")
            if root.type == "ARMATURE":
                layout.operator("albam.match_skeleton", icon="ARMATURE_DATA")
            for note in notes.split("\n") if notes else []:
                warn = note.startswith(WARNING)
                layout.label(text=note[len(WARNING):] if warn else note, icon="ERROR" if warn else "INFO")
            return
        col = layout.column()
        col.label(text="Not part of a game model yet.")
        col.operator("albam.mod_new", icon="ADD")
