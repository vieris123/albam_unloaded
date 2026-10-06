"""DMC4 .efl (effect list) static import (efl_import_plan.md M1c).

Each record becomes an Empty at its generator's offset, attached to joint ParentNo (bone mtfw.anim_retarget) of the armature
picked in the import options. All block fields are stored as custom properties. PrimModel
particles get real meshes (ported builders), Polygon and Billboard particles get textured quads, and
particles get an emissive material using their base texture. Nothing is simulated or animated.
Export (effect_export.py) writes the record objects' efl_* properties and generator transforms back.

Approximations (not verified in game, see the plan):
Verified against DX9 (efl_import_plan.md):
- Blending is the D3D9 equation from PrimMaterialFlags (BlendSrc / BlendDst / BlendOp = enum - 1), built as
  Emission(src * Fs) + Transparent(Fd); reverse-subtract (darkening) becomes a Transparent factor.
- TransMode is a scene-pass mask; particles without the main-view bit (1) get no geometry.
- Billboards are Scale x pattern pixels (x AspectRatio) centimetres, facing the camera; colour = Color0 x Intensity.
Approximations: static mode shows the first flipbook frame.
- With "Simulate particles", Billboard/Polygon/PrimModel records become animated particle systems
  (effect_sim.py + efl/sim.py); otherwise one static shape per record.
- The spawn filter (effect_filter.py) hides the records the game wouldn't build for the chosen group / surface.
"""
import math
from pathlib import PureWindowsPath
from types import SimpleNamespace

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from .efl import EffectList, EflError, VERSION_DX9
from .efl import ean, efs
from .efl.edit import block_props, keyframe_props, sub_props
from .efl.schema import bgra_to_rgba
from .efl.primmodel import build_from_block
from .efl.sim import CLOTH_TYPES, ROT_ORDERS, emission_space, keyframes_of as sim_keyframes_of, refracts
from . import effect_filter, effect_sim
from .texture import MISSING_TEXTURE_PROP, build_blender_textures

SCALE = 0.01   # game centimetres -> metres
EDGE_ALPHA_ATTR = "EdgeAlpha"
SIMULATED_TYPES = (0, 2, 6)   # Billboard, Polygon, PrimModel: instanced shapes
RIBBON_TYPES = (1, 3, 4, 12, 13, 14, 15)   # Polyline/Texline/Line (+ cloth), PolygonStrip: rebuilt meshes


def _filter_armatures(self, obj):
    return obj.type == "ARMATURE"


def _on_darken_strength(options, context):
    set_darken_strength(options.darken_strength)


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
    group_all: effect_filter.group_all_prop()
    group_bits: effect_filter.group_bits_prop()
    surface: effect_filter.surface_prop()
    darken_strength: bpy.props.FloatProperty(
        name="Darkening Strength", default=1.5, min=1.0, max=4.0, update=_on_darken_strength,
        description="How strongly darkening particles (BlendOp REVSUBTRACT) darken what's behind them. The game "
                    "subtracts their colour, which Blender can't do, so they dim the background instead: 1 is right "
                    "over white and too light over darker areas, higher values darken more but turn bright areas "
                    "too dark. Changes every imported effect at once; tune it by eye in Material Preview")


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
    layout.prop(options, "darken_strength")
    layout.label(text="Spawn filter (change it later in the Effect Editor):")
    effect_filter.draw_filter(layout, options)


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
    builder = _EffectBuilder(app_id, context, stem, armature, options,
                             masks=effect_filter.masks_from_options(options))
    builder.build(efl, getattr(file_item, "relative_path", ""), efl_bytes)
    return None   # objects are linked into their own collection already


OPTION_NAMES = ("build_geometry", "load_textures", "simulate", "sim_frames")


def rebuild_effect(context, root, efl_bytes):
    """Replace an imported effect with one built from efl_bytes (same file path, armature, start frame and import
    options); the new root's source bytes are efl_bytes. Returns the new root."""
    efl = EffectList.from_bytes(efl_bytes)
    asset = root.albam_asset
    app_id, relative_path = asset.app_id, asset.relative_path
    stem = root.get("efl_stem") or (root.name[4:] if root.name.startswith("EFL_") else root.name)
    stored = root.get("efl_options")
    scene_options = context.scene.albam.import_options_efl
    options = SimpleNamespace(**{name: (stored[name] if stored is not None and name in stored
                                        else getattr(scene_options, name)) for name in OPTION_NAMES})
    armature = root.parent if root.parent is not None and root.parent.type == "ARMATURE" else None
    start = root.get("efl_start_frame", context.scene.frame_current)
    masks = effect_filter.get_masks(root)
    root_basis = root.matrix_basis.copy()
    old_collection = root.users_collection[0] if root.users_collection else None
    parent_collection = context.scene.collection
    if old_collection is not None:
        for candidate in [context.scene.collection] + list(bpy.data.collections):
            if old_collection.name in candidate.children:
                parent_collection = candidate
                break

    exportable = context.scene.albam.exportable.file_list
    for i in reversed(range(len(exportable))):
        if exportable[i].bl_object == root:
            exportable.remove(i)
    doomed = {o for o in bpy.data.objects if o.get("efl_root") == root}
    if old_collection is not None:
        doomed |= set(old_collection.all_objects)
    doomed.add(root)
    from . import effect_sim
    for ob in doomed:
        effect_sim.forget(ob.name)
        bpy.data.objects.remove(ob)
    if old_collection is not None:
        bpy.data.collections.remove(old_collection)

    frame = context.scene.frame_current
    context.scene.frame_current = int(start)   # the builder starts playback and generator keys here
    try:
        builder = _EffectBuilder(app_id, context, stem, armature, options, parent_collection, masks)
        new_root = builder.build(efl, relative_path, efl_bytes)
    finally:
        context.scene.frame_current = frame
    new_root.matrix_basis = root_basis
    return new_root


class _EffectBuilder:
    def __init__(self, app_id, context, stem, armature, options, parent_collection=None, masks=None):
        self.app_id = app_id
        self.masks = masks or (effect_filter.ALL, effect_filter.ALL)   # spawn filter (effect_filter.py)
        self.context = context
        self.stem = stem
        self.armature = armature
        self.options = options
        self.images = {}
        self.anims = {}
        self.models = {}
        self.efs = {}
        self.current_generator = None
        self.materials = {}
        self.missing_textures = set()   # texture paths that couldn't be loaded (shown in the Effect Editor)
        parent = parent_collection or context.collection or context.scene.collection
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
        root["efl_stem"] = self.stem
        root["efl_options"] = {name: getattr(self.options, name) for name in OPTION_NAMES}
        root["efl_header"] = {"base_fps": efl.base_fps, "record_count": len(efl.records),
                              "has_unit_generator": efl.unit_gen is not None}
        root["efl_note"] = ("Approximate preview (static shapes, or simulated particles). Ranges are stored "
                            "flattened as [s, r, ...]; value = s + random * r. See Vibed/RE/efl_import_plan.md")
        if self.options.simulate:
            effect_sim.store_source(root, efl_bytes, self.context.scene.frame_current)
        for index, record in enumerate(efl.records):
            self.build_record(index, record, root)
        # export (effect_export.py) rebuilds the file from these bytes and the record objects' properties
        root.albam_asset.original_bytes = efl_bytes
        root.albam_asset.app_id = self.app_id
        root.albam_asset.relative_path = relative_path
        root.albam_asset.extension = "efl"
        exportable = self.context.scene.albam.exportable.file_list.add()
        exportable.bl_object = root
        root["efl_missing_textures"] = sorted(self.missing_textures)
        effect_filter.set_masks(root, *self.masks)
        effect_filter.apply_filter(root)
        return root

    def build_record(self, index, record, root):
        gen, ptcl = record.gen, record.ptcl
        ptcl_name = ptcl.type_name if ptcl else "NoParticle"
        move_name = record.move.type_name if record.move else "NoMove"
        ob = self.link(bpy.data.objects.new(f"{self.stem}.{index:02d}_{ptcl_name}", None))
        ob.empty_display_type = "ARROWS"
        ob.empty_display_size = 0.05
        ob["efl_record"] = index
        ob["efl_root"] = root
        ob["efl_particle_type"] = ptcl_name
        ob["efl_move_type"] = move_name
        keyframes, subs = {}, {}
        for key, block in record.blocks():
            if block is not None:
                ob[f"efl_{key}"] = block_props(block)
                keyframes[key], subs[key] = keyframe_props(block), sub_props(block)
        ob["efl_kf"] = keyframes      # {slot: {offset field: keyframe}}, written back by export
        ob["efl_sub"] = subs          # {slot: {offset field: collision/culling fields}}

        if gen is not None:
            ob.location = [c * SCALE for c in gen.get("Pos")]
            ob.rotation_mode = "QUATERNION"
            ob.rotation_quaternion = _quaternion(gen.get("Quat"))
            ob.scale = [s for s, _ in gen.get("Scale")]
            self.animate_generator(ob, gen, index)
        self._attach(ob, gen, root)
        self.current_generator = ob

        if ptcl is not None and ptcl.has("TransMode") and not ptcl.get("TransMode") & 1:
            ob["efl_hidden"] = "TransMode has no main-view bit: the game doesn't draw it in the normal view"
        elif ptcl is not None and self.options.build_geometry and self.options.simulate \
                and ptcl.type == 5 and gen is not None:
            source = self.model_source(ptcl.get("ModelPath"))
            if source is not None:
                info = self.sim_info(record)
                info.update(model_groups=source[1], model_zofs=ptcl.get("ModelZofs")
                            if ptcl.get("ModelAnimFlag") & 0x10000 or ptcl.get("ModelZofs") else 0.0)
                parts = max(len(source[1]), 1)   # one identity UV row per mesh part (the "pattern" is the part)
                info.update(effect_sim.table_info([[(ean.IDENTITY_AFFINE, 1, 1)] * parts]))
                effect_sim.create_model_object(self.collection, ob.name, ob, root, index, info, source[0])
            else:
                ob["efl_missing_model"] = ptcl.get("ModelPath")
        elif ptcl is not None and self.options.build_geometry and self.options.simulate \
                and ptcl.type == 10 and gen is not None:
            effect_sim.create_light_object(self.collection, ob.name, ob, root, index, self.sim_info(record))
        elif ptcl is not None and self.options.build_geometry and self.options.simulate \
                and ptcl.type in RIBBON_TYPES and gen is not None:
            effect_sim.create_line_object(self.collection, ob.name, ob, root, index, self.sim_info(record),
                                          self.material_for(ptcl))
        elif ptcl is not None and self.options.build_geometry:
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
        image = None
        base_map = _base_map(ptcl)
        if base_map and self.options.load_textures:
            image = self.image_for(base_map)
        tables = effect_sim.frame_tables(None, image, 0, ean)   # whole texture, its pixel size
        if ptcl.has("AnimPath") and ptcl.get("AnimPath") and base_map:
            tables = effect_sim.frame_tables(self.anim_for(ptcl.get("AnimPath")),
                                             self.images.get(base_map), ptcl.get("AnimFlag"), ean)
        rot_order = ptcl.get("RotOrder") if ptcl.has("PrimFlags") or ptcl.has("PolygonFlags") else 5
        extra = {}
        efs_parts = self.efs_for(gen.get("RangeStripPath")) if gen.get("RangeStripPath") else None
        if efs_parts:
            extra["range_strip"] = [c for part in efs_parts for point in part for c in point]
            extra["range_strip_sizes"] = [len(part) for part in efs_parts]
        move = record.move
        if move is not None and move.type == 3 and move.get("PathStripPath"):
            parts = self.efs_for(move.get("PathStripPath"))
            if parts:
                part = parts[min(max(move.get("PathStripPartsNo"), 0), len(parts) - 1)]
                extra["strip"] = [c for point in part for c in point]
        if ptcl.type in CLOTH_TYPES:
            axes = self.world_axes()
            if axes is not None:
                extra["world_axes"] = axes
        if move is not None and move.get("CollParamOffset"):
            ground = self.ground_height(record)
            if ground is not None:
                extra["ground_y"] = ground
        return {"kind": ptcl.type, "frames": self.options.sim_frames, "rot_order": rot_order,
                "space": emission_space(record),
                "particle_scale": gen.get("ParticleScale")[0] or 1.0, **effect_sim.table_info(tables), **extra}

    def animate_generator(self, ob, gen, index):
        """Generator keyframes (updateWorldMatrix 0x96BE10): 0x1D8 position, 0x1DC Euler rotation (AxisFlags
        order), 0x1CC scale, on the generator timer; baked as F-curves on the generator Empty."""
        keys = sim_keyframes_of(gen, {"KeyframePosParamOffset": "pos", "KeyframeRotParamOffset": "rot",
                                      "KeyframeScaleParamOffset": "scale"})
        if not keys:
            return
        import random
        from .efl import keyframe as kfm
        rng = random.Random(1000 + index)
        start = self.context.scene.frame_current
        fps = self.context.scene.render.fps / (self.context.scene.render.fps_base or 1.0)
        frames = self.options.sim_frames if self.options.simulate else 300
        order = ROT_ORDERS[gen.get("Order")] if 0 <= gen.get("Order") < len(ROT_ORDERS) else "XYZ"
        for name, kf in keys.items():
            rates = kfm.draw_rates(kf, rng)
            step = max(1, frames // 120)
            for game_frame in list(range(0, frames, step)) + [frames]:
                timer = max(game_frame - 1, 0) if kf.ref_type == 1 else game_frame
                value = kfm.evaluate(kf, timer, rates)
                if value is None:
                    continue
                scene_frame = start + game_frame * fps / 60.0
                if name == "pos":
                    ob.location = [c * SCALE for c in value]
                    ob.keyframe_insert("location", frame=scene_frame)
                elif name == "rot":
                    ob.rotation_quaternion = Euler(value, order).to_quaternion()
                    ob.keyframe_insert("rotation_quaternion", frame=scene_frame)
                else:
                    ob.scale = value
                    ob.keyframe_insert("scale", frame=scene_frame)
        ob["efl_animated"] = sorted(keys)

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
            mesh = self._polygon_mesh(ptcl, name)
        elif ptcl.type == 0 and ptcl.has("AspectRatio"):
            pivot = (0.0, 0.0)
            if ptcl.get("ParticleOptionFlag") & 0x10000:   # PAT_CENTER: the particle sits at pixel (cx, cy) of the cell
                w, h = self.frame_size(ptcl)
                cx, cy = ptcl.get("PatCenter")
                pivot = (0.5 - cx / w, cy / h - 0.5) if w and h else pivot
            mesh = _quad_mesh(f"{name}_billboard", 1.0, 1.0, pivot)   # 1 cm; sized by scale x pattern pixels
        else:
            return None
        if mesh is None:
            return None
        ob = self.link(bpy.data.objects.new(mesh.name, mesh))
        material = self.material_for(ptcl)
        if material is not None:
            mesh.materials.append(material)
        if as_source:   # transforms, tint and frame UVs are applied per particle
            return ob
        self.crop_to_frame(ptcl, mesh, ob)
        _tint_mesh(mesh, ptcl)

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
            w, h = self.frame_size(ptcl)
            size = ptcl.get("Scale")[0] * particle_scale
            ob.scale = (size * w * (ptcl.get("AspectRatio")[0] or 1.0), size * h, 1.0)
            camera = self.context.scene.camera
            if camera is not None:
                track = ob.constraints.new("DAMPED_TRACK")
                track.target = camera
                track.track_axis = "TRACK_Z"
        return ob

    def model_source(self, model_path):
        """(collection of the model's meshes in game axes, idx_group per mesh), imported once per path."""
        if model_path in self.models:
            return self.models[model_path]
        result = None
        try:
            item = self.context.scene.albam.rfs.get_vfile(self.app_id, model_path + ".mod")
        except KeyError:
            print(f"EFL: model {model_path}.mod not found under the Game Files roots")
            item = None
        if item is not None:
            from .mesh import build_blender_model
            exportable = self.context.scene.albam.exportable.file_list
            count_before = len(exportable)
            container = build_blender_model(item, self.context)
            while len(exportable) > count_before:   # effect models aren't exported with the scene
                exportable.remove(len(exportable) - 1)
            meshes = sorted((c for c in container.children if c.type == "MESH"), key=lambda c: c.name)
            source = bpy.data.collections.new(f"EFL_model_{PureWindowsPath(model_path).name}")
            source.use_fake_user = True   # not linked to the scene; read by the Collection Info node
            groups = []
            game_axes = Matrix.Rotation(-math.pi / 2, 4, "X")   # Albam meshes are Z-up; particles use game axes
            for i, mesh_ob in enumerate(meshes):
                mesh_ob.parent = None
                for modifier in list(mesh_ob.modifiers):
                    mesh_ob.modifiers.remove(modifier)
                for collection in list(mesh_ob.users_collection):
                    collection.objects.unlink(mesh_ob)
                mesh_ob.matrix_world = game_axes
                mesh_ob.name = f"{i:03d}_{mesh_ob.name}"
                source.objects.link(mesh_ob)
                props = mesh_ob.data.albam_custom_properties.get_custom_properties_for_appid(self.app_id)
                groups.append(int(getattr(props, "idx_group", i)))
            armature_data = container.data if container.type == "ARMATURE" else None
            bpy.data.objects.remove(container)
            if armature_data is not None and not armature_data.users:
                bpy.data.armatures.remove(armature_data)
            result = (source, groups) if meshes else None
        self.models[model_path] = result
        return result

    def efs_for(self, path):
        """Parts of an .efs curve (cm), or None if it isn't under the Game Files roots."""
        if path in self.efs:
            return self.efs[path]
        parts = None
        try:
            parts = efs.parse(self.context.scene.albam.rfs.get_vfile(self.app_id, path + ".efs").get_bytes())
        except KeyError:
            print(f"EFL: strip {path}.efs not found under the Game Files roots")
        except efs.EfsError as err:
            print(f"EFL: could not read {path}.efs: {err}")
        self.efs[path] = parts
        return parts

    def ground_height(self, record):
        """Ground plane (world z = 0, the character's feet) in the generator's game space at import, in cm;
        None if the generator isn't roughly upright there."""
        generator = self.current_generator
        if generator is None:
            return None
        self.context.view_layer.update()
        m = generator.matrix_world
        up = m.to_3x3() @ Vector((0.0, 1.0, 0.0))   # game Y in world
        if up.length < 1e-6 or up.normalized().z < 0.9:
            return None
        return -m.translation.z / (up.length * SCALE)

    def world_axes(self):
        """Game world axes -> the generator's game space at import (row-major 3x3), for world-fixed cloth pulls."""
        generator = self.current_generator
        if generator is None:
            return None
        self.context.view_layer.update()
        rot = generator.matrix_world.to_quaternion().to_matrix()
        game_to_blender = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
        m = rot.transposed() @ game_to_blender
        return [m[r][c] for r in range(3) for c in range(3)]

    def frame_size(self, ptcl):
        """Pixel size of the particle's first flipbook frame (the whole texture without a flipbook)."""
        image = self.images.get(_base_map(ptcl)) or None
        anim = self.anim_for(ptcl.get("AnimPath")) if ptcl.has("AnimPath") and ptcl.get("AnimPath") else None
        pattern = anim.pattern(ptcl.get("SeqNoMin"), ptcl.get("PatNoMin")) if anim is not None else None
        if pattern is not None:
            return abs(pattern[2]), abs(pattern[3])
        if image is not None and image.size[0]:
            return image.size[0], image.size[1]
        return 64, 64

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
        _set_shape_basis(mesh, prim.basis)
        mesh.update()
        return mesh

    def _polygon_mesh(self, ptcl, name):
        """Polygon quad (sub_9B54C0): Width / Height are half-extents; PolygonFixType picks the pivot, PolygonAxis
        the plane, DistortRate scales each corner. Carries the shape basis so keyframed sizes can be rebuilt."""
        w, h = ptcl.get("Width")[0], ptcl.get("Height")[0]
        pivot = ptcl.get("PolygonFixType")
        if pivot == 9:   # PatCenter of the first flipbook cell
            fw, fh = self.frame_size(ptcl)
            cx, cy = ptcl.get("PatCenter") if ptcl.has("PatCenter") else (fw / 2, fh / 2)
            u, v = (cx / fw * 2 if fw else 1.0), (cy / fh * 2 if fh else 1.0)
            (a0, a1), (b0, b1) = (-u, 2 - u), (v - 2, v)
        else:
            (a0, a1), (b0, b1) = POLYGON_PIVOTS.get(pivot, POLYGON_PIVOTS[0])
        axis_a, axis_b = POLYGON_PLANES.get(ptcl.get("PolygonAxis"), POLYGON_PLANES[4])
        distort = list(ptcl.get("DistortRate")) if ptcl.has("DistortRate") else [1.0] * 4
        corners = ((a0, b1), (a1, b1), (a0, b0), (a1, b0))   # c0..c3, DistortRate order
        basis = []
        for (ka, kb), d in zip(corners, distort):
            basis.append((tuple(c * ka * d for c in axis_a), (0.0, 0.0, 0.0),
                          tuple(c * kb * d for c in axis_b), (0.0, 0.0, 0.0)))
        verts = [tuple((A[i] * w + C[i] * h) * SCALE for i in range(3)) for A, _B, C, _D in basis]
        if not any(any(v) for v in verts):
            return None
        mesh = bpy.data.meshes.new(f"{name}_polygon")
        mesh.from_pydata(verts, [], [(2, 3, 1, 0)])
        uv_layer = mesh.uv_layers.new(name="UVMap")
        for loop_index, uv in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
            uv_layer.data[loop_index].uv = uv
        _set_edge_alpha(mesh, [1.0] * 4)
        _set_shape_basis(mesh, basis)
        mesh.update()
        return mesh

    # -- flipbooks ---------------------------------------------------------------------------

    def crop_to_frame(self, ptcl, mesh, ob):
        """Effect textures are flipbook sheets; show only the particle's first frame, as the game does at spawn."""
        if not (ptcl.has("AnimPath") and ptcl.get("AnimPath") and _base_map(ptcl)):
            return
        anim = self.anim_for(ptcl.get("AnimPath"))
        image = self.images.get(_base_map(ptcl))
        if anim is None or image is None:
            return
        width, height = image.size
        seq_no, pat_no = ptcl.get("SeqNoMin"), ptcl.get("PatNoMin")
        pattern = anim.pattern(seq_no, pat_no)
        if pattern is None or not width or not height:
            return
        (a, b, ou), (c, d, ov) = ean.uv_affine(pattern, width, height, ptcl.get("AnimFlag"))
        for loop_uv in mesh.uv_layers[0].data:
            u, v = loop_uv.uv
            loop_uv.uv = (a * u + b * v + ou, c * u + d * v + ov)
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
        base_path = _base_map(ptcl)
        blend = (ptcl.get("BlendSrc") + 1, ptcl.get("BlendDst") + 1, ptcl.get("BlendOp") + 1)
        refract = refracts(ptcl)
        # refraction strength = the record's base Intensity (keyframed intensity isn't followed)
        strength = min(max(ptcl.get("Intensity")[0], 0.0), 127.0) if refract and ptcl.has("Intensity") else 0.0
        key = (base_path, blend, refract, strength)
        if key in self.materials:
            return self.materials[key]
        image = self.image_for(base_path) if base_path and self.options.load_textures else None
        label = PureWindowsPath(base_path).name if base_path else ptcl.type_name
        if refract:
            material = _build_refract_material(f"EFL_{label}_refract", image, *blend, intensity=strength)
            if material.get("efl_distortion") and hasattr(self.context.scene.eevee, "use_raytracing"):
                self.context.scene.eevee.use_raytracing = True   # EEVEE refraction needs it (else world colour)
        else:
            material = _build_material(f"EFL_{label}", image, *blend)
        material["efl_blend"] = f"src {_D3DBLEND.get(blend[0], blend[0])}, dst {_D3DBLEND.get(blend[1], blend[1])}, " \
                                f"op {_D3DBLENDOP.get(blend[2], blend[2])}" + (", refraction" if refract else "")
        material["efl_base_map"] = base_path
        self.materials[key] = material
        return material

    def image_for(self, texture_path):
        if texture_path in self.images:
            return self.images[texture_path]
        image = next((im for im in bpy.data.images if im.get("efl_texture") == texture_path
                      and not im.get(MISSING_TEXTURE_PROP)), None)
        if image is not None:   # loaded by an earlier import or rebuild
            self.images[texture_path] = image
            return image
        source = SimpleNamespace(materials_data=SimpleNamespace(textures=[texture_path]))
        image = None
        try:
            images = build_blender_textures(self.app_id, self.context, source)
            image = images[0] if images else None
            if image is not None and image.get(MISSING_TEXTURE_PROP):
                # the texture loader's placeholder is a black 4x4 image with alpha 1: it would turn every particle
                # using it into a solid black shape, so the particle colour alone is used instead
                image = None
            if image is not None:
                image["efl_texture"] = texture_path
        except KeyError:
            print(f"EFL: texture {texture_path}.tex not found under the Game Files roots")
        except Exception as err:   # a bad texture shouldn't stop the effect import
            print(f"EFL: could not load {texture_path}.tex: {err}")
        if image is None:
            self.missing_textures.add(texture_path)
        self.images[texture_path] = image
        return image


# ---------------------------------------------------------------------------------------------

UNTEXTURED_PRIM_MODELS = (0, 2, 4)   # Ring, Sphere, Grid: renderPrimModelRing / Sphere / Grid never fetch a texture


def _base_map(ptcl):
    """The texture the game draws the particle with: BaseMapPath, except for the untextured PrimModel types (Ring,
    Sphere, Grid draw in a solid colour; their Tex variants 1 / 3 / 5 use the texture)."""
    if not ptcl.has("BaseMapPath"):
        return ""
    if ptcl.type == 6 and ptcl.has("PrimModelType") and ptcl.get("PrimModelType") in UNTEXTURED_PRIM_MODELS:
        return ""
    return ptcl.get("BaseMapPath")


# Polygon pivots (PolygonFixType): ((a0, a1), (b0, b1)) in units of the half-extents W, H
POLYGON_PIVOTS = {0: ((-1, 1), (-1, 1)), 1: ((0, 2), (-2, 0)), 2: ((-2, 0), (-2, 0)), 3: ((0, 2), (0, 2)),
                  4: ((-2, 0), (0, 2)), 5: ((-1, 1), (-2, 0)), 6: ((-1, 1), (0, 2)), 7: ((0, 2), (-1, 1)),
                  8: ((-2, 0), (-1, 1))}
# Polygon planes (PolygonAxis): directions of the width (a) and height (b) coordinates, game axes
POLYGON_PLANES = {0: ((0, 1, 0), (0, 0, 1)), 1: ((0, -1, 0), (0, 0, 1)), 2: ((-1, 0, 0), (0, 0, 1)),
                  3: ((1, 0, 0), (0, 0, 1)), 4: ((1, 0, 0), (0, 1, 0)), 5: ((-1, 0, 0), (0, 1, 0)),
                  6: ((1, 0, 0), (0, 1, 0))}
SHAPE_BASIS_ATTRS = ("shape_a", "shape_b", "shape_c", "shape_d")


def _set_shape_basis(mesh, basis):
    """Per-vertex shape basis (game cm -> Blender units) and the rest position, for the particle node group's
    per-particle shape rebuild."""
    if len(basis) != len(mesh.vertices):
        return
    for i, name in enumerate(SHAPE_BASIS_ATTRS):
        attr = mesh.attributes.new(name, "FLOAT_VECTOR", "POINT")
        attr.data.foreach_set("vector", [c * SCALE for vectors in basis for c in vectors[i]])
    rest = mesh.attributes.new("src_co", "FLOAT_VECTOR", "POINT")
    rest.data.foreach_set("vector", [c for v in mesh.vertices for c in v.co])


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


def _quad_mesh(name, width, height, pivot=(0.0, 0.0)):
    """Quad in the XY plane; pivot shifts it by a fraction of its size (PAT_CENTER billboards)."""
    if width <= 0 or height <= 0:
        return None
    hw, hh = width * SCALE / 2, height * SCALE / 2
    ox, oy = pivot[0] * width * SCALE, pivot[1] * height * SCALE
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-hw + ox, -hh + oy, 0.0), (hw + ox, -hh + oy, 0.0), (hw + ox, hh + oy, 0.0),
                      (-hw + ox, hh + oy, 0.0)], [], [(0, 1, 2, 3)])
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for i, uv in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        uv_layer.data[i].uv = uv
    _set_edge_alpha(mesh, [1.0] * 4)
    mesh.update()
    return mesh


def _set_edge_alpha(mesh, alpha, rgb=(1.0, 1.0, 1.0)):
    """EdgeAlpha colour attribute: rgb = tint (colour x intensity), a = colour alpha x border fade."""
    attr = mesh.color_attributes.get(EDGE_ALPHA_ATTR) or \
        mesh.color_attributes.new(name=EDGE_ALPHA_ATTR, type="FLOAT_COLOR", domain="POINT")
    for i, a in enumerate(alpha):
        attr.data[i].color = (rgb[0], rgb[1], rgb[2], a)


def _tint_mesh(mesh, ptcl):
    """Static meshes: bake Color0 x Intensity into EdgeAlpha (simulated particles get it per point)."""
    attr = mesh.color_attributes.get(EDGE_ALPHA_ATTR)
    if attr is None or not ptcl.has("Color0"):
        return
    r, g, b, a = bgra_to_rgba(ptcl.get("Color0"))
    intensity = min(max(ptcl.get("Intensity")[0], 0.0), 127.0) if ptcl.has("Intensity") else 1.0
    if refracts(ptcl):   # intensity only scales the refraction offset
        intensity = 1.0
    for item in attr.data:
        edge = item.color[3]
        item.color = (r / 255 * intensity, g / 255 * intensity, b / 255 * intensity, edge * a / 255)


DARKEN_GROUP = "ALBAM_EFL_Darken_v3"   # v3: Strength only (v2's Enabled switch was dropped)


def _darken_group():
    """Shared node group for REVSUBTRACT transmittance: max(Fd - Strength x Source, 0). One Strength value for every
    effect material, set by the Darkening Strength option."""
    group = bpy.data.node_groups.get(DARKEN_GROUP)
    if group is not None:
        return group
    group = bpy.data.node_groups.new(DARKEN_GROUP, "ShaderNodeTree")
    group.interface.new_socket("Fd", in_out="INPUT", socket_type="NodeSocketVector")
    group.interface.new_socket("Source", in_out="INPUT", socket_type="NodeSocketVector")
    group.interface.new_socket("Transmittance", in_out="OUTPUT", socket_type="NodeSocketVector")
    nodes, links = group.nodes, group.links
    inp, out = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    strength = nodes.new("ShaderNodeValue")
    strength.name = strength.label = "Strength"
    albam = getattr(getattr(bpy.context, "scene", None), "albam", None)
    strength.outputs[0].default_value = albam.import_options_efl.darken_strength if albam else 1.5
    scale = nodes.new("ShaderNodeVectorMath")
    scale.operation = "SCALE"
    links.new(inp.outputs["Source"], scale.inputs[0])
    links.new(strength.outputs[0], scale.inputs["Scale"])
    sub = nodes.new("ShaderNodeVectorMath")
    sub.operation = "SUBTRACT"
    links.new(inp.outputs["Fd"], sub.inputs[0])
    links.new(scale.outputs["Vector"], sub.inputs[1])
    clamp = nodes.new("ShaderNodeVectorMath")
    clamp.operation = "MAXIMUM"
    links.new(sub.outputs["Vector"], clamp.inputs[0])
    clamp.inputs[1].default_value = (0.0, 0.0, 0.0)
    links.new(clamp.outputs["Vector"], out.inputs["Transmittance"])
    for i, n in enumerate((inp, strength, scale, sub, clamp, out)):
        n.location = (i * 200 - 500, 0)
    return group


def set_darken_strength(value):
    _darken_group().nodes["Strength"].outputs[0].default_value = value


REFRACT_IOR = 1.5
REFRACT_GAIN = 2.0   # normal tilt per unit of screen offset: deviation ~ tilt x (1 - 1 / IOR), screen ~ 0.7 rad wide


def _build_refract_material(name, image, src, dst, op, intensity=0.0):
    """Refraction particles (ParticleOptionFlag 0x10, XfPrim PRIM_EX_REFRACT pixel shader): the game draws the screen
    behind them, offset by (BaseMap.rg - 0.5) x Intensity / 100, times the particle colour, with alpha = BaseMap.a x
    particle alpha, through the normal blend equation. Blender materials can't sample the screen, so the offset is left
    out and the source colour is taken as background x colour: transmittance = colour x Fs (op) Fd. The texture only
    gives alpha."""
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

    def node(kind, x, y, **props):
        n = nodes.new(kind)
        n.location = (x, y)
        for key, value in props.items():
            setattr(n, key, value)
        return n

    def vmath(op_name, a, b, x, y):
        n = node("ShaderNodeVectorMath", x, y, operation=op_name)
        for i, value in enumerate((a, b)):
            if isinstance(value, tuple):
                n.inputs[i].default_value = value
            else:
                links.new(value, n.inputs[i])
        return n.outputs["Vector"]

    tint = node("ShaderNodeVertexColor", -900, 200, layer_name=EDGE_ALPHA_ATTR)
    color = vmath("MULTIPLY", tint.outputs["Color"], (1.0, 1.0, 1.0), -650, 200)
    if image is not None:
        tex = node("ShaderNodeTexImage", -900, -100)
        tex.image = image
        alpha_node = node("ShaderNodeMath", -650, -50, operation="MULTIPLY")
        links.new(tex.outputs["Alpha"], alpha_node.inputs[0])
        links.new(tint.outputs["Alpha"], alpha_node.inputs[1])
        alpha = alpha_node.outputs["Value"]
    else:
        alpha = tint.outputs["Alpha"]
    if image is not None and intensity > 0 and (src, dst, op) == (5, 6, 1):
        # alpha blend: lerp(background, refracted x colour, alpha) = mix(Transparent, Refraction(colour), alpha).
        # The bend tilts the normal (facing the camera) along the camera axes by the game's screen offset
        # (BaseMap.rg - 0.5) x Intensity / 100, +v down. The texture is read raw, as the game does (undo sRGB).
        # EEVEE refracts only Dithered materials with raytracing (weakly); Cycles bends properly.
        mat.surface_render_method = "DITHERED"
        if hasattr(mat, "use_raytrace_refraction"):
            mat.use_raytrace_refraction = True
        if hasattr(mat, "thickness_mode"):
            mat.thickness_mode = "SLAB"
        raw = node("ShaderNodeGamma", -650, -300)
        links.new(tex.outputs["Color"], raw.inputs["Color"])
        raw.inputs["Gamma"].default_value = 1.0 / 2.2
        sep = node("ShaderNodeSeparateXYZ", -450, -300)
        links.new(raw.outputs[0], sep.inputs[0])
        k = intensity / 100.0 * REFRACT_GAIN

        def offset(channel, sign, x, y):
            n = node("ShaderNodeMath", x, y, operation="MULTIPLY_ADD")   # (c - 0.5) * k = c * k - 0.5 * k
            links.new(sep.outputs[channel], n.inputs[0])
            n.inputs[1].default_value = sign * k
            n.inputs[2].default_value = -0.5 * sign * k
            return n.outputs["Value"]

        def camera_axis(vector, y):
            n = node("ShaderNodeVectorTransform", -250, y, vector_type="VECTOR", convert_from="CAMERA",
                     convert_to="WORLD")
            n.inputs[0].default_value = vector
            return n.outputs[0]

        geometry = node("ShaderNodeNewGeometry", -250, -150)
        bend_u = vmath("SCALE", camera_axis((1.0, 0.0, 0.0), -450), (0.0, 0.0, 0.0), -50, -450)
        links.new(offset("X", 1.0, -250, -600), bend_u.node.inputs["Scale"])
        bend_v = vmath("SCALE", camera_axis((0.0, 1.0, 0.0), -750), (0.0, 0.0, 0.0), -50, -750)
        links.new(offset("Y", -1.0, -250, -900), bend_v.node.inputs["Scale"])
        normal = vmath("NORMALIZE", vmath("ADD", vmath("ADD", geometry.outputs["Incoming"], bend_u, 150, -400),
                                          bend_v, 300, -500), (0.0, 0.0, 0.0), 450, -500)
        refraction = node("ShaderNodeBsdfRefraction", 600, -250)
        refraction.inputs["IOR"].default_value = REFRACT_IOR
        refraction.inputs["Roughness"].default_value = 0.0
        links.new(color, refraction.inputs["Color"])
        links.new(normal, refraction.inputs["Normal"])
        clear = node("ShaderNodeBsdfTransparent", 600, 0)
        mix = node("ShaderNodeMixShader", 780, 0)
        links.new(alpha, mix.inputs["Fac"])
        links.new(clear.outputs[0], mix.inputs[1])
        links.new(refraction.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs["Surface"])
        mat["efl_distortion"] = True
        return mat

    splat = node("ShaderNodeCombineXYZ", -450, -100)
    for axis in "XYZ":
        links.new(alpha, splat.inputs[axis])
    alpha3 = splat.outputs["Vector"]

    def factor(kind, x, y):
        if kind == 1:
            return (0.0, 0.0, 0.0)
        if kind == 3:
            return color
        if kind == 4:
            return vmath("SUBTRACT", (1.0, 1.0, 1.0), color, x, y)
        if kind in (5, 11):
            return alpha3
        if kind == 6:
            return vmath("SUBTRACT", (1.0, 1.0, 1.0), alpha3, x, y)
        return (1.0, 1.0, 1.0)   # ONE, and the background-dependent factors

    def as_socket(value, x, y):
        return vmath("MULTIPLY", value, (1.0, 1.0, 1.0), x, y) if isinstance(value, tuple) else value

    fs, fd = factor(src, -250, 200), factor(dst, -250, -200)
    source = vmath("MULTIPLY", color, as_socket(fs, -50, 250), 50, 150)   # background x colour x Fs, over background
    fd = as_socket(fd, 50, -200)
    if op == 3:     # REVSUBTRACT: background * Fd - background * colour * Fs
        trans = vmath("MAXIMUM", vmath("SUBTRACT", fd, source, 250, 0), (0.0, 0.0, 0.0), 450, 0)
    elif op == 2:   # SUBTRACT: background * colour * Fs - background * Fd
        trans = vmath("MAXIMUM", vmath("SUBTRACT", source, fd, 250, 0), (0.0, 0.0, 0.0), 450, 0)
    else:
        trans = vmath("ADD", source, fd, 250, 0)
    transparent = node("ShaderNodeBsdfTransparent", 650, 0)
    links.new(trans, transparent.inputs["Color"])
    links.new(transparent.outputs[0], out.inputs["Surface"])
    return mat


# D3D9 enums (the file stores them minus 1)
_D3DBLEND = {1: "ZERO", 2: "ONE", 3: "SRCCOLOR", 4: "INVSRCCOLOR", 5: "SRCALPHA", 6: "INVSRCALPHA",
             7: "DESTALPHA", 8: "INVDESTALPHA", 9: "DESTCOLOR", 10: "INVDESTCOLOR", 11: "SRCALPHASAT"}
_D3DBLENDOP = {1: "ADD", 2: "SUBTRACT", 3: "REVSUBTRACT", 4: "MIN", 5: "MAX"}


def _build_material(name, image, src, dst, op):
    """result = src_colour * Fs (op) background * Fd, with src colour = texture rgb * EdgeAlpha rgb and
    alpha = texture a * EdgeAlpha a. Built as Emission + Transparent; factors that depend on the background
    (DEST*) fall back to ONE, MIN/MAX to ADD."""
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
    out.location = (1100, 0)

    def node(kind, x, y, **props):
        n = nodes.new(kind)
        n.location = (x, y)
        for key, value in props.items():
            setattr(n, key, value)
        return n

    def vmath(op_name, a, b, x, y):
        n = node("ShaderNodeVectorMath", x, y, operation=op_name)
        for i, value in enumerate((a, b)):
            if isinstance(value, tuple):
                n.inputs[i].default_value = value
            else:
                links.new(value, n.inputs[i])
        return n.outputs["Vector"]

    def splat(scalar, x, y):
        n = node("ShaderNodeCombineXYZ", x, y)
        for axis in "XYZ":
            links.new(scalar, n.inputs[axis])
        return n.outputs["Vector"]

    tint = node("ShaderNodeVertexColor", -900, 200, layer_name=EDGE_ALPHA_ATTR)
    if image is not None:
        tex = node("ShaderNodeTexImage", -900, -50)
        tex.image = image
        color = vmath("MULTIPLY", tex.outputs["Color"], tint.outputs["Color"], -650, 150)
        alpha_node = node("ShaderNodeMath", -650, -100, operation="MULTIPLY")
        links.new(tex.outputs["Alpha"], alpha_node.inputs[0])
        links.new(tint.outputs["Alpha"], alpha_node.inputs[1])
        alpha = alpha_node.outputs["Value"]
    else:
        color = vmath("MULTIPLY", tint.outputs["Color"], (1.0, 1.0, 1.0), -650, 150)
        alpha = tint.outputs["Alpha"]
    alpha3 = splat(alpha, -450, -150)

    def factor(kind, x, y):
        if kind == 1:
            return (0.0, 0.0, 0.0)
        if kind == 3:
            return color
        if kind == 4:
            return vmath("SUBTRACT", (1.0, 1.0, 1.0), color, x, y)
        if kind in (5, 11):
            return alpha3
        if kind == 6:
            return vmath("SUBTRACT", (1.0, 1.0, 1.0), alpha3, x, y)
        return (1.0, 1.0, 1.0)   # ONE, and the background-dependent factors

    fs, fd = factor(src, -250, 200), factor(dst, -250, -200)

    def as_socket(value, x, y):
        return vmath("MULTIPLY", value, (1.0, 1.0, 1.0), x, y) if isinstance(value, tuple) else value

    emission = node("ShaderNodeEmission", 500, 150)
    transparent = node("ShaderNodeBsdfTransparent", 500, -150)
    if op == 3:   # REVSUBTRACT: background * Fd - src * Fs. Blender can't subtract light per layer, so the background
        # is dimmed instead, by max(Fd - Strength * src * Fs, 0) (_darken_group; Strength 1 = exact over white)
        darken = node("ShaderNodeGroup", 250, -150)
        darken.node_tree = _darken_group()
        links.new(as_socket(fd, -50, -250), darken.inputs["Fd"])
        links.new(vmath("MULTIPLY", color, as_socket(fs, -50, 250), 100, 100), darken.inputs["Source"])
        links.new(darken.outputs["Transmittance"], transparent.inputs["Color"])
        emission.inputs["Strength"].default_value = 0.0
    else:
        links.new(vmath("MULTIPLY", color, as_socket(fs, -50, 250), 250, 200), emission.inputs["Color"])
        if op == 2:   # SUBTRACT: src - background, approximated as the source alone
            transparent.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        else:
            links.new(as_socket(fd, 250, -200), transparent.inputs["Color"])
    add = node("ShaderNodeAddShader", 800, 0)
    links.new(emission.outputs[0], add.inputs[0])
    links.new(transparent.outputs[0], add.inputs[1])
    links.new(add.outputs[0], out.inputs["Surface"])
    return mat
