"""Per-model settings of an imported .mod that live in its header (model_info, 0x80):
- the light group (0x88): uModel::setModel copies it into uModel.mLightGroup, a bit mask of the light groups that
  light the model (Light effects carry the same kind of mask in LightGroupFlag);
- the level-of-detail distances middist / lowdist (0x80 / 0x84, s32): uModel::transDefault 0x9F1950 (and the Devil
  Trigger, reflection and dissolve passes) picks LOD 1 (near) while the draw origin's depth key is <= middist, 2 (mid)
  up to lowdist, 4 (far) beyond, unless uModel.Render.mLOD forces one; a mesh draws when its LOD mask
  (mesh.level_of_detail) has that bit. The shadow pass draws the far meshes (n4 = 4). The depth key is the
  view depth times the draw-order scale (cTrans context +0x1F0), clamped to 0xFFD: not centimetres. Every DX9 model
  has 1000 / 3000 and every mesh mask 255 (all LODs), so the stock game never switches.
strip_type (0x8C) is 0 everywhere and the next 3 bytes are left-over data: export keeps the source's."""
import struct

import bpy

from albam.registry import blender_registry

LIGHT_GROUP_OFFSET = 0x88   # mod 153 / 156 header: model_info.light_group
LOD_OFFSET = 0x80           # model_info.middist, lowdist (s32 each)
LOD_BITS = ("Near", "Mid", "Far")   # mesh.level_of_detail bits 0-2 = LOD 1 / 2 / 4
GROUP_BITS = 32
MOD_APPS = ("dmc4", "re5")   # .mod versions 153 / 156 share the model_info layout


def model_root(ob):
    """The imported .mod object that ob is, or belongs to; None for anything else."""
    while ob is not None:
        if ob.albam_asset.extension == "mod" and ob.albam_asset.original_bytes:
            return ob
        ob = ob.parent
    return None


def file_light_group(ob):
    data = ob.albam_asset.original_bytes
    return struct.unpack_from("<I", data, LIGHT_GROUP_OFFSET)[0] if len(data) >= LIGHT_GROUP_OFFSET + 4 else 0


def light_group_value(settings):
    return sum(1 << i for i in range(GROUP_BITS) if settings.light_group[i])


def set_light_group(settings, value):
    settings.light_group = [bool(value >> i & 1) for i in range(GROUP_BITS)]
    settings.loaded = True


def file_lod_distances(ob):
    data = ob.albam_asset.original_bytes
    return struct.unpack_from("<ii", data, LOD_OFFSET) if len(data) >= LOD_OFFSET + 8 else (1000, 3000)


def set_lod_distances(settings, middist, lowdist):
    settings.middist, settings.lowdist = middist, lowdist
    settings.lod_loaded = True


def export_lod_distances(ob, default):
    """(middist, lowdist) to write for ob: its edited values, or default (the source file's) if never loaded."""
    settings = ob.albam_mod
    return (settings.middist, settings.lowdist) if settings.lod_loaded else default


def export_light_group(ob, default):
    """The light group to write for ob: its edited value, or default (the source file's) if never loaded."""
    settings = ob.albam_mod
    return light_group_value(settings) if settings.loaded else default


@blender_registry.register_blender_props_to_type("Object", "albam_mod")
class AlbamModSettings(bpy.types.PropertyGroup):
    loaded: bpy.props.BoolProperty(
        description="The settings hold the model's own values (set on import, or by Load from File)")
    light_group: bpy.props.BoolVectorProperty(
        name="Light Group", size=GROUP_BITS,
        description="Light groups that light this model in the game: tick a group to have its lights shine on the "
                    "model. A light (including a Light effect, through its LightGroupFlag) lights the model when "
                    "they share at least one group. The most common value in the game's models is groups 0 and 1")
    lod_loaded: bpy.props.BoolProperty(
        description="The level-of-detail distances hold the model's own values (set on import, or by Load from File)")
    middist: bpy.props.IntProperty(
        name="Near Up To", min=0, max=0xFFD,
        description="Meshes marked Near draw while the model is closer than this; beyond it, Mid meshes draw. In "
                    "the game's draw-depth units (the view depth scaled to 0-4093), not centimetres. Every game "
                    "model has 1000")
    lowdist: bpy.props.IntProperty(
        name="Mid Up To", min=0, max=0xFFD,
        description="Meshes marked Mid draw up to this depth; beyond it, Far meshes draw (and shadows always use "
                    "the Far meshes). Draw-depth units, 0-4093. Every game model has 3000")


def _mesh_lod_props(mesh):
    return mesh.albam_custom_properties.get_custom_properties_for_appid("dmc4")


def _get_lod_mask(self):
    value = _mesh_lod_props(self.id_data).level_of_detail
    return [bool(value >> i & 1) for i in range(len(LOD_BITS))]


def _set_lod_mask(self, flags):
    props = _mesh_lod_props(self.id_data)
    value = props.level_of_detail & ~0b111
    props.level_of_detail = value | sum(1 << i for i, on in enumerate(flags) if on)


@blender_registry.register_blender_props_to_type("Mesh", "albam_lod")
class AlbamMeshLod(bpy.types.PropertyGroup):
    """The mesh's LOD mask (its level_of_detail custom property) as three toggles; the other bits are kept"""
    levels: bpy.props.BoolVectorProperty(
        name="Draw At", size=len(LOD_BITS), get=_get_lod_mask, set=_set_lod_mask,
        description="The distances this mesh draws at in the game: Near (closer than Near Up To), Mid, Far (also "
                    "used for its shadow). Game meshes draw at all three. For LOD meshes: give the detailed mesh "
                    "Near, a lighter copy Mid / Far")


@blender_registry.register_blender_type
class ALBAM_OT_ModLoadSettings(bpy.types.Operator):
    """Read the model settings from the imported file, so they can be edited (models imported before these settings
    existed don't have them yet)"""
    bl_idname = "albam.mod_load_settings"
    bl_label = "Load from File"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return model_root(context.object) is not None

    def execute(self, context):
        root = model_root(context.object)
        set_light_group(root.albam_mod, file_light_group(root))
        set_lod_distances(root.albam_mod, *file_lod_distances(root))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_PT_ModSettings(bpy.types.Panel):
    bl_label = "Model Settings"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_parent_id = "ALBAM_PT_AssetObject"

    @classmethod
    def poll(cls, context):
        root = model_root(context.object)
        return root is not None and root.albam_asset.app_id in MOD_APPS

    def draw(self, context):
        root = model_root(context.object)
        layout = self.layout
        if root != context.object:
            layout.label(text=f"Model: {root.name}", icon="OBJECT_DATA")
        settings = root.albam_mod
        if not settings.loaded:
            layout.label(text=f"Light Group: {file_light_group(root):#x} (from the file)")
            layout.operator("albam.mod_load_settings", icon="IMPORT")
            return
        value = light_group_value(settings)
        row = layout.row()
        row.label(text="Light Group", icon="LIGHT")
        row.label(text=f"{value:#x}")
        grid = layout.grid_flow(row_major=True, columns=8, even_columns=True, align=True)
        for i in range(GROUP_BITS):
            grid.prop(settings, "light_group", index=i, text=str(i), toggle=True)
        changed = value != file_light_group(root)
        layout.label(text="Changed from the file's value" if changed else "Same as the file", icon="INFO")

        box = layout.box()
        box.label(text="Level of Detail", icon="MOD_DECIM")
        if not settings.lod_loaded:
            middist, lowdist = file_lod_distances(root)
            box.label(text=f"Near up to {middist}, Mid up to {lowdist} (from the file)")
            box.operator("albam.mod_load_settings", icon="IMPORT")
        else:
            col = box.column(align=True)
            col.prop(settings, "middist")
            col.prop(settings, "lowdist")
            if settings.middist > settings.lowdist:
                box.label(text="Near Up To is beyond Mid Up To: Mid meshes never draw", icon="ERROR")
        ob = context.object
        if ob is not None and ob.type == "MESH" and ob.data is not None:
            row = box.row(align=True)
            row.label(text=f"{ob.name} draws at:")
            for i, name in enumerate(LOD_BITS):
                row.prop(ob.data.albam_lod, "levels", index=i, text=name, toggle=True)
