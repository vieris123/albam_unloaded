"""DMC4 .efl (effect list) static import (efl_import_plan.md M1c).

Each record becomes an Empty at its generator's offset, attached to joint ParentNo (bone mtfw.anim_retarget) of the armature
picked in the import options. All block fields are stored as custom properties. PrimModel
particles get real meshes (ported builders), Polygon and Billboard particles get textured quads, and
particles get an emissive material using their base texture. Nothing is simulated or animated.
Not exported: the parser in .efl can write files, but nothing maps Blender edits back yet.

Approximations (not verified in game, see the plan):
- TransMode 1 is treated as additive and 0 as alpha blend.
- Billboard quad edge = Scale * 100 cm, facing the scene camera; Polygon quads lie in the XY plane.
- Intensity is used as the emission strength. Flipbooks (.ean) show the first frame (SeqNoMin, PatNoMin), not animated.
- With "Simulate particles", Billboard/Polygon/PrimModel records become animated particle systems
  (effect_sim.py + efl/sim.py); otherwise one static shape per record.
"""
import math
from pathlib import PureWindowsPath
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Quaternion

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from .efl import EffectList, EflError, VERSION_DX9
from .efl import ean
from .efl.primmodel import build_from_block
from .efl.sim import ROT_ORDERS
from . import effect_sim
from .texture import build_blender_textures

SCALE = 0.01   # game centimetres -> metres
BILLBOARD_UNIT = 100.0   # cm per Billboard Scale unit (assumed)
EDGE_ALPHA_ATTR = "EdgeAlpha"
SIMULATED_TYPES = (0, 2, 6)   # Billboard, Polygon, PrimModel


def _filter_armatures(self, obj):
    return obj.type == "ARMATURE"


@blender_registry.register_blender_prop_albam(name="import_options_efl")
class ImportOptionsEFL(bpy.types.PropertyGroup):
    armature: bpy.props.PointerProperty(
        type=bpy.types.Object, poll=_filter_armatures,
        description="Attach generators to this armature's joints (ParentNo = the joint number Albam stores as mtfw.anim_retarget)")
    build_geometry: bpy.props.BoolProperty(
        name="Build geometry", default=True,
        description="Create PrimModel meshes and Polygon/Billboard quads")
    load_textures: bpy.props.BoolProperty(
        name="Load textures", default=True,
        description="Load base textures from the Game Files folder (it must be the arc root)")
    simulate: bpy.props.BoolProperty(
        name="Simulate particles", default=True,
        description="Emit and animate particles over time (approximation of the game's emitters), "
                    "starting at the current frame. Off: one static shape per generator")
    sim_frames: bpy.props.IntProperty(
        name="Frames", default=300, min=1, max=3600,
        description="Game frames (60 fps) to simulate; generators that loop forever stop emitting after this")


@blender_registry.register_import_options_custom_draw_func(extension="efl")
def draw_efl_options(panel_instance, context):
    panel_instance.bl_label = "EFL Options"
    options = context.scene.albam.import_options_efl
    layout = panel_instance.layout
    layout.prop(options, "armature")
    layout.prop(options, "build_geometry")
    layout.prop(options, "load_textures")
    layout.prop(options, "simulate")
    row = layout.row()
    row.enabled = options.simulate
    row.prop(options, "sim_frames")


@blender_registry.register_import_options_custom_poll_func(extension="efl")
def poll_efl_options(panel_instance, context):
    return True


@blender_registry.register_import_function(app_id="dmc4", extension="efl", file_category="EFFECT")
def load_efl(file_item, context):
    app_id = file_item.app_id
    efl_bytes = file_item.get_bytes()
    try:
        efl = EffectList.from_bytes(efl_bytes)
    except EflError as err:
        raise AlbamCheckFailure(
            "This .efl file can't be imported",
            details=str(err),
            solution=f"Only DMC4 DX9 effect lists (version {VERSION_DX9:#x}) are supported. "
                     "Special Edition files use a different layout.")

    options = context.scene.albam.import_options_efl
    armature = options.armature
    stem = PureWindowsPath(file_item.display_name).stem
    builder = _EffectBuilder(app_id, context, stem, armature, options)
    builder.build(efl, getattr(file_item, "relative_path", ""), efl_bytes)
    return None   # objects are linked into their own collection already


class _EffectBuilder:
    def __init__(self, app_id, context, stem, armature, options):
        self.app_id = app_id
        self.context = context
        self.stem = stem
        self.armature = armature
        self.options = options
        self.images = {}
        self.anims = {}
        self.materials = {}
        parent = context.collection or context.scene.collection
        self.collection = bpy.data.collections.new(f"EFL_{stem}")
        parent.children.link(self.collection)

    def link(self, ob):
        self.collection.objects.link(ob)
        return ob

    def build(self, efl, relative_path, efl_bytes=b""):
        root = self.link(bpy.data.objects.new(f"EFL_{self.stem}", None))
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = 0.1
        root.rotation_euler = (math.pi / 2, 0.0, 0.0)   # game Y-up -> Blender Z-up
        if self.armature:
            root.parent = self.armature
        root["efl_path"] = relative_path
        root["efl_header"] = {"base_fps": efl.base_fps, "record_count": len(efl.records),
                              "has_unit_generator": efl.unit_gen is not None}
        root["efl_note"] = ("Approximate preview (static shapes, or simulated particles). Ranges are stored "
                            "flattened as [s, r, ...]; value = s + random * r. See Vibed/RE/efl_import_plan.md")
        if self.options.simulate:
            effect_sim.store_source(root, efl_bytes, self.context.scene.frame_current)
        for index, record in enumerate(efl.records):
            self.build_record(index, record, root)

    def build_record(self, index, record, root):
        gen, ptcl = record.gen, record.ptcl
        ptcl_name = ptcl.type_name if ptcl else "NoParticle"
        move_name = record.move.type_name if record.move else "NoMove"
        ob = self.link(bpy.data.objects.new(f"{self.stem}.{index:02d}_{ptcl_name}", None))
        ob.empty_display_type = "ARROWS"
        ob.empty_display_size = 0.05
        ob["efl_record"] = index
        ob["efl_particle_type"] = ptcl_name
        ob["efl_move_type"] = move_name
        for key, block in record.blocks():
            if block is not None:
                ob[f"efl_{key}"] = _block_props(block)

        if gen is not None:
            ob.location = [c * SCALE for c in gen.get("Pos")]
            ob.rotation_mode = "QUATERNION"
            ob.rotation_quaternion = _quaternion(gen.get("Quat"))
            ob.scale = [s for s, _ in gen.get("Scale")]
        self._attach(ob, gen, root)

        if ptcl is not None and self.options.build_geometry:
            simulated = self.options.simulate and ptcl.type in SIMULATED_TYPES and gen is not None
            shape_ob = self.build_particle_shape(ptcl, gen, ob.name, as_source=simulated)
            if shape_ob is not None:
                shape_ob.parent = ob
                if simulated:
                    effect_sim.create_sim_object(self.collection, ob.name, ob, shape_ob, root, index,
                                                 self.sim_info(record))
        return ob

    def sim_info(self, record):
        ptcl, gen = record.ptcl, record.gen
        rects = [(0.0, 0.0, 1.0, 1.0)]
        if ptcl.has("AnimPath") and ptcl.get("AnimPath") and ptcl.get("BaseMapPath"):
            rects = effect_sim.frame_rects(self.anim_for(ptcl.get("AnimPath")), ptcl.get("SeqNoMin"),
                                           self.images.get(ptcl.get("BaseMapPath")), ptcl.get("AnimFlag"), ean)
        rot_order = ptcl.get("RotOrder") if ptcl.has("PrimFlags") or ptcl.has("PolygonFlags") else 5
        return {"kind": ptcl.type, "frames": self.options.sim_frames, "rot_order": rot_order,
                "particle_scale": gen.get("ParticleScale")[0] or 1.0,
                "rects": [c for rect in rects for c in rect]}

    def joint_bones(self):
        """MT joint number -> bone. ParentNo is the joint number (bone['mtfw.anim_retarget'], the .mod's
        idx_anim_map), not the hierarchy index: Nero's hand effects use joints 150/151 = bones 25/52."""
        if not hasattr(self, "_joint_bones"):
            self._joint_bones = {}
            if self.armature is not None:
                for bone in self.armature.data.bones:
                    joint = bone.get("mtfw.anim_retarget")
                    if joint is not None:
                        self._joint_bones.setdefault(int(joint), bone)
        return self._joint_bones

    def _attach(self, ob, gen, root):
        parent_no = gen.get("ParentNo") if gen is not None else -1
        bone = self.joint_bones().get(parent_no) if parent_no >= 0 else None
        if bone is None:
            ob.parent = root
            if parent_no >= 0:
                ob["efl_unresolved_joint"] = parent_no
            return
        # bone frames are the game joint frames (mesh.py: swap @ inverse bind matrix), so the generator's
        # Pos/Quat apply as-is in the bone head frame; Blender parents to the tail, hence the inverse
        ob.parent = self.armature
        ob.parent_type = "BONE"
        ob.parent_bone = bone.name
        ob.matrix_parent_inverse = Matrix.Translation((0.0, -bone.length, 0.0))

    # -- particles ---------------------------------------------------------------------------

    def build_particle_shape(self, ptcl, gen, name, as_source=False):
        """Static shape, or with as_source the untransformed, uncropped shape the particle system instances."""
        if ptcl.type == 6:
            mesh = self._prim_model_mesh(ptcl, name)
        elif ptcl.type == 2 and ptcl.has("Width"):
            w, h = ptcl.get("Width")[0], ptcl.get("Height")[0]
            mesh = _quad_mesh(f"{name}_polygon", w, h)
        elif ptcl.type == 0 and ptcl.has("AspectRatio"):
            size = BILLBOARD_UNIT if as_source else ptcl.get("Scale")[0] * BILLBOARD_UNIT
            aspect = ptcl.get("AspectRatio")[0] or 1.0
            mesh = _quad_mesh(f"{name}_billboard", size * aspect, size)
        else:
            return None
        if mesh is None:
            return None
        ob = self.link(bpy.data.objects.new(mesh.name, mesh))
        material = self.material_for(ptcl)
        if material is not None:
            mesh.materials.append(material)
        if as_source:   # transforms and frame UVs are applied per particle
            return ob
        self.crop_to_frame(ptcl, mesh, ob)

        particle_scale = gen.get("ParticleScale")[0] if gen is not None else 1.0
        particle_scale = particle_scale or 1.0
        if ptcl.type == 6:
            ob.rotation_mode = _euler_order(ptcl.get("RotOrder"))
            ob.rotation_euler = [s for s, _ in ptcl.get("Rot")]
            draw_scale = ptcl.get("Scale")[0] or 1.0
            ob.scale = [(s or 1.0) * draw_scale * particle_scale for s, _ in ptcl.get("ModelScale")]
        elif ptcl.type == 2:
            ob.rotation_mode = _euler_order(ptcl.get("RotOrder"))
            ob.rotation_euler = [s for s, _ in ptcl.get("Rot")]
            ob.scale = [(ptcl.get("Scale")[0] or 1.0) * particle_scale] * 3
        else:
            ob.scale = [particle_scale] * 3
            camera = self.context.scene.camera
            if camera is not None:
                track = ob.constraints.new("DAMPED_TRACK")
                track.target = camera
                track.track_axis = "TRACK_Z"
            ob["efl_note"] = f"Billboard size assumed Scale x {BILLBOARD_UNIT:g} cm; faces the scene camera"
        return ob

    def _prim_model_mesh(self, ptcl, name):
        prim = build_from_block(ptcl)
        if not prim.faces:
            return None
        mesh = bpy.data.meshes.new(f"{name}_prim")
        mesh.from_pydata([(x * SCALE, y * SCALE, z * SCALE) for x, y, z in prim.vertices], [], prim.faces)
        uv_layer = mesh.uv_layers.new(name="UVMap")
        for loop_index, (u, v) in enumerate(prim.uvs):
            uv_layer.data[loop_index].uv = (u, 1.0 - v)
        _set_edge_alpha(mesh, prim.alpha)
        mesh.update()
        return mesh

    # -- flipbooks ---------------------------------------------------------------------------

    def crop_to_frame(self, ptcl, mesh, ob):
        """Effect textures are flipbook sheets; show only the particle's first frame, as the game does at spawn."""
        if not (ptcl.has("AnimPath") and ptcl.get("AnimPath") and ptcl.get("BaseMapPath")):
            return
        anim = self.anim_for(ptcl.get("AnimPath"))
        image = self.images.get(ptcl.get("BaseMapPath"))
        if anim is None or image is None:
            return
        width, height = image.size
        seq_no, pat_no = ptcl.get("SeqNoMin"), ptcl.get("PatNoMin")
        pattern = anim.pattern(seq_no, pat_no)
        if pattern is None or not width or not height:
            return
        rect, rotate = ean.pattern_uv_rect(pattern, width, height, ptcl.get("AnimFlag"))
        for loop_uv in mesh.uv_layers[0].data:
            u, v = ean.map_uv((loop_uv.uv[0], 1.0 - loop_uv.uv[1]), rect, rotate)
            loop_uv.uv = (u, 1.0 - v)
        sequence = anim.sequences[min(seq_no, len(anim.sequences) - 1)]
        ob["efl_frame"] = {"sequence": seq_no, "pattern": pat_no, "pattern_count": len(sequence.patterns),
                           "rect_px": list(pattern)}

    def anim_for(self, anim_path):
        if anim_path in self.anims:
            return self.anims[anim_path]
        anim = None
        try:
            anim = ean.parse(self.context.scene.albam.rfs.get_vfile(self.app_id, anim_path + ".ean").get_bytes())
        except KeyError:
            print(f"EFL: flipbook {anim_path}.ean not found under the Game Files roots; showing the whole texture")
        except ean.EanError as err:
            print(f"EFL: could not read {anim_path}.ean: {err}")
        self.anims[anim_path] = anim
        return anim

    # -- materials ---------------------------------------------------------------------------

    def material_for(self, ptcl):
        if not ptcl.has("TransMode"):
            return None
        base_path = ptcl.get("BaseMapPath") if ptcl.has("BaseMapPath") else ""
        color = ptcl.get("Color0") if ptcl.has("Color0") else [255, 255, 255, 255]
        intensity = ptcl.get("Intensity")[0] if ptcl.has("Intensity") else 1.0
        trans_mode = ptcl.get("TransMode")
        key = (base_path, trans_mode, tuple(color), intensity)
        if key in self.materials:
            return self.materials[key]
        image = self.image_for(base_path) if base_path and self.options.load_textures else None
        label = PureWindowsPath(base_path).name if base_path else ptcl.type_name
        material = _build_material(f"EFL_{label}", image, color, intensity, additive=trans_mode == 1)
        material["efl_trans_mode"] = trans_mode
        material["efl_base_map"] = base_path
        self.materials[key] = material
        return material

    def image_for(self, texture_path):
        if texture_path in self.images:
            return self.images[texture_path]
        image = None
        source = SimpleNamespace(materials_data=SimpleNamespace(textures=[texture_path]))
        try:
            images = build_blender_textures(self.app_id, self.context, source)
            image = images[0] if images else None
        except KeyError:
            print(f"EFL: texture {texture_path}.tex not found under the Game Files roots")
        except Exception as err:   # a bad texture shouldn't stop the effect import
            print(f"EFL: could not load {texture_path}.tex: {err}")
        self.images[texture_path] = image
        return image


# ---------------------------------------------------------------------------------------------

def _quaternion(xyzw):
    x, y, z, w = xyzw
    if not any(xyzw):
        return Quaternion()
    q = Quaternion((w, x, y, z))
    q.normalize()
    return q


def _euler_order(nibble):
    """RotOrder enum (setMatFromAngle 0x95FF60): 0 ZYX, 1 ZXY, 2 YZX, 3 YXZ, 4 XZY, 5 XYZ."""
    return ROT_ORDERS[nibble] if 0 <= nibble < len(ROT_ORDERS) else "XYZ"


def _quad_mesh(name, width, height):
    if width <= 0 or height <= 0:
        return None
    hw, hh = width * SCALE / 2, height * SCALE / 2
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-hw, -hh, 0.0), (hw, -hh, 0.0), (hw, hh, 0.0), (-hw, hh, 0.0)], [], [(0, 1, 2, 3)])
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for i, uv in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        uv_layer.data[i].uv = uv
    _set_edge_alpha(mesh, [1.0] * 4)
    mesh.update()
    return mesh


def _set_edge_alpha(mesh, alpha):
    attr = mesh.color_attributes.new(name=EDGE_ALPHA_ATTR, type="FLOAT_COLOR", domain="POINT")
    for i, a in enumerate(alpha):
        attr.data[i].color = (1.0, 1.0, 1.0, a)


def _build_material(name, image, color, intensity, additive):
    """Emission (texture rgb * Color0) with alpha = texture a * Color0 a * edge alpha."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.use_backface_culling = False
    if hasattr(mat, "surface_render_method"):   # Blender 4.2+
        mat.surface_render_method = "BLENDED"
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (900, 0)

    rgb = nodes.new("ShaderNodeRGB")
    rgb.location = (-600, 200)
    rgb.outputs[0].default_value = (color[0] / 255, color[1] / 255, color[2] / 255, 1.0)
    edge = nodes.new("ShaderNodeVertexColor")
    edge.layer_name = EDGE_ALPHA_ATTR
    edge.location = (-600, -200)

    tint = nodes.new("ShaderNodeMix")
    tint.data_type = "RGBA"
    tint.blend_type = "MULTIPLY"
    tint.inputs["Factor"].default_value = 1.0
    tint.location = (-250, 200)
    links.new(rgb.outputs[0], tint.inputs["B"])

    alpha = nodes.new("ShaderNodeMath")
    alpha.operation = "MULTIPLY"
    alpha.inputs[1].default_value = color[3] / 255
    alpha.location = (-250, -150)
    alpha_edge = nodes.new("ShaderNodeMath")
    alpha_edge.operation = "MULTIPLY"
    alpha_edge.location = (-50, -150)
    links.new(alpha.outputs[0], alpha_edge.inputs[0])
    links.new(edge.outputs["Alpha"], alpha_edge.inputs[1])

    if image is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.location = (-600, 0)
        links.new(tex.outputs["Color"], tint.inputs["A"])
        links.new(tex.outputs["Alpha"], alpha.inputs[0])
    else:
        tint.inputs["A"].default_value = (1.0, 1.0, 1.0, 1.0)
        alpha.inputs[0].default_value = 1.0

    emission = nodes.new("ShaderNodeEmission")
    emission.location = (250, 150)
    emission.inputs["Strength"].default_value = max(float(intensity), 0.0)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (250, -100)

    if additive:
        # additive: transparent background + emission weighted by alpha
        weighted = nodes.new("ShaderNodeMix")
        weighted.data_type = "RGBA"
        weighted.blend_type = "MULTIPLY"
        weighted.inputs["Factor"].default_value = 1.0
        weighted.location = (50, 250)
        links.new(tint.outputs["Result"], weighted.inputs["A"])
        links.new(alpha_edge.outputs[0], weighted.inputs["B"])
        links.new(weighted.outputs["Result"], emission.inputs["Color"])
        add = nodes.new("ShaderNodeAddShader")
        add.location = (600, 0)
        links.new(transparent.outputs[0], add.inputs[0])
        links.new(emission.outputs[0], add.inputs[1])
        links.new(add.outputs[0], out.inputs["Surface"])
    else:
        links.new(tint.outputs["Result"], emission.inputs["Color"])
        mix = nodes.new("ShaderNodeMixShader")
        mix.location = (600, 0)
        links.new(alpha_edge.outputs[0], mix.inputs["Fac"])
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(emission.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


def _idprop(value):
    """Blender ID properties: 32-bit ints, flat numeric arrays."""
    if isinstance(value, list):
        flat = []
        stack = list(value)
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack[0:0] = item
            else:
                flat.append(item)
        if any(isinstance(v, int) and not -2 ** 31 <= v < 2 ** 31 for v in flat):
            return [float(v) for v in flat]
        return flat
    if isinstance(value, int) and not -2 ** 31 <= value < 2 ** 31:
        return f"{value:#010x}"
    return value


def _block_props(block):
    props = {"type": block.type, "type_name": block.type_name, "struct": block.struct.name}
    for name, value in block.fields().items():
        props[name] = _idprop(value)
    for name, value in block.bits().items():
        props[name] = _idprop(value)
    return props
