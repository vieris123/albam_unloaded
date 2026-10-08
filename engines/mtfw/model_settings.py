"""Per-model settings of an imported .mod that live in its header: for now the light group (model_info.light_group,
header 0x88). In the game uModel::setModel copies it into uModel.mLightGroup: a bit mask of the light groups that
light the model (Light effects carry the same kind of mask in LightGroupFlag)."""
import struct

import bpy

from albam.registry import blender_registry

LIGHT_GROUP_OFFSET = 0x88   # mod 153 / 156 header: model_info.light_group
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
                    "model. A light (including a Light effect, through its LightGroupFlag) most likely lights the "
                    "model when they share a group. The most common value in the game's models is groups 0 and 1")


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
