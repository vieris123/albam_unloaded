import os

import bpy

from albam.apps import APPS
from albam.registry import blender_registry
from albam.vfs import ALBAM_OT_VirtualFileSystemCollapseToggle
from albam.rfs import ALBAM_OT_RealFileSystemCollapseToggle, compute_visible_items

# FIXME: store in app data
APP_DIRS_CACHE = {}
# FIXME: store in app data
APP_CONFIG_FILE_CACHE = {}


def update_app_data(self, context):
    current_app = context.scene.albam.apps.app_selected
    cached_dir = APP_DIRS_CACHE.get(current_app)
    cached_file = APP_CONFIG_FILE_CACHE.get(current_app)
    if cached_dir:
        context.scene.albam.apps.app_dir = cached_dir
    else:
        context.scene.albam.apps.app_dir = ""

    if cached_file:
        context.scene.albam.apps.app_config_filepath = cached_file
    else:
        context.scene.albam.apps.app_config_filepath = ""


def update_app_caches(self, context):
    current_app = context.scene.albam.apps.app_selected
    current_dir = context.scene.albam.apps.app_dir
    current_file = context.scene.albam.apps.app_config_filepath

    APP_DIRS_CACHE[current_app] = current_dir
    APP_CONFIG_FILE_CACHE[current_app] = current_file


@blender_registry.register_blender_prop_albam(name="apps")
class AlbamApps(bpy.types.PropertyGroup):
    app_selected : bpy.props.EnumProperty(name="", items=APPS, update=update_app_data)
    app_dir : bpy.props.StringProperty(name="", description="", update=update_app_caches)
    app_config_filepath : bpy.props.StringProperty(name="", update=update_app_caches)
    mouse_x: bpy.props.IntProperty()
    mouse_y: bpy.props.IntProperty()

    def get_app_config_filepath(self, app_id):
        return APP_CONFIG_FILE_CACHE.get(app_id)


@blender_registry.register_blender_prop_albam(name="import_settings")
class AlbamImportSettings(bpy.types.PropertyGroup):
    import_only_main_lods: bpy.props.BoolProperty(default=True)


class ImportFileBase:
    """Shared by the VFS and RFS import operators, subclasses define get_selected_item"""

    def execute(self, context):  # pragma: no cover
        item = self.get_selected_item(context)
        try:
            self._execute(item, context)
        except Exception:
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
        return {"FINISHED"}

    @staticmethod
    def _execute(item, context):
        import_function = blender_registry.import_registry[(item.app_id, item.extension)]

        bl_container = import_function(item, context)
        if not bl_container:
            return

        if bl_container.type != "ARMATURE":
            # armature building needs it linked to for building
            bpy.context.collection.objects.link(bl_container)
        for child in bl_container.children_recursive:
            if child.name in bpy.context.collection.objects:
                continue
            try:
                # already linked
                bpy.context.collection.objects.link(child)
            except RuntimeError:
                pass

    @classmethod
    def poll(cls, context):
        item = cls.get_selected_item(context)
        if not item or (item.app_id, item.extension) not in blender_registry.importable_extensions:
            return False
        custom_poll_func = blender_registry.import_operator_poll_funcs.get(item.extension)
        if custom_poll_func:
            return custom_poll_func(cls, context)
        return True


@blender_registry.register_blender_type
class ALBAM_OT_Import(ImportFileBase, bpy.types.Operator):
    """Import the selected archive file"""
    bl_idname = "albam.import_vfile"
    bl_label = "Import"

    @staticmethod
    def get_selected_item(context):
        # TODO: delete
        if len(context.scene.albam.vfs.file_list) == 0:
            return None
        index = context.scene.albam.vfs.file_list_selected_index
        try:
            item = context.scene.albam.vfs.file_list[index]
        except IndexError:
            # list might have been cleared
            return
        return item


@blender_registry.register_blender_type
class ALBAM_OT_ImportReal(ImportFileBase, bpy.types.Operator):
    """Import the selected game file"""
    bl_idname = "albam.import_real"
    bl_label = "Import"

    @staticmethod
    def get_selected_item(context):
        item = context.scene.albam.rfs.selected_item
        if item is None or item.is_expandable:
            return None
        return item


def get_import_item(context):
    """The item import options apply to. dmc4 only uses the real file system"""
    item = None
    if context.scene.albam.apps.app_selected != "dmc4":
        item = ALBAM_OT_Import.get_selected_item(context)
    return item or ALBAM_OT_ImportReal.get_selected_item(context)


class ALBAM_UL_VirtualFileSystemUIBase:
    EXPAND_ICONS = {
        False: "TRIA_RIGHT",
        True: "TRIA_DOWN",
    }
    collapse_toggle_operator_cls = ALBAM_OT_VirtualFileSystemCollapseToggle

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        for _ in range(item.tree_node.depth):
            layout.split(factor=0.01)

        if item.is_expandable:
            icon = self.EXPAND_ICONS[item.is_expanded]
        elif item.category == "MESH":
            icon = "OUTLINER_OB_MESH"
        elif item.category == "ANIMATION":
            icon = "ACTION"
        elif item.category == "MATERIAL":
            icon = "MATERIAL"
        elif item.category == "TEXTURE":
            icon = "TEXTURE"
        else:
            icon = "DOT"
        col = layout.column()
        col.enabled = item.is_expandable
        op = col.operator(self.collapse_toggle_operator_cls.bl_idname, text="", icon=icon)
        op.button_index = index
        layout.column().label(text=item.display_name)

    def filter_items(self, context, data, propname):
        filtered_items = []
        # TODO: self.filter_name
        cache = self.collapse_toggle_operator_cls.NODES_CACHE

        item_list = getattr(data, propname)
        for item in item_list:
            if item.is_archive:
                filtered_items.append(self.bitflag_filter_item)

            elif all(cache.get(anc.node_id, False) for anc in item.tree_node_ancestors):
                filtered_items.append(self.bitflag_filter_item)

            else:
                filtered_items.append(0)

        return filtered_items, []


@blender_registry.register_blender_type
class ALBAM_UL_VirtualFileSystemUI(ALBAM_UL_VirtualFileSystemUIBase, bpy.types.UIList):
    pass

# Filter results per UI list, keyed on what they depend on. Recomputing on every
# redraw is slow with tens of thousands of files
_RFS_FILTER_CACHE = {}


@blender_registry.register_blender_type
class ALBAM_UL_RealFileSystemUI(bpy.types.UIList):
    EXPAND_ICONS = ALBAM_UL_VirtualFileSystemUIBase.EXPAND_ICONS
    CATEGORY_ICONS = {
        "MESH": "OUTLINER_OB_MESH",
        "ANIMATION": "ACTION",
        "COLLISION": "MOD_PHYSICS",
        "EFFECT": "PARTICLES",
        "PLACEMENT": "EMPTY_ARROWS",
        "SCHEDULE": "TIME",
        "CHAIN": "LINKED",
        "HITBOX": "MESH_CAPSULE",
        "MATERIAL": "MATERIAL",
        "TEXTURE": "TEXTURE",
    }

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if item.tree_node.depth:
            row.separator(factor=item.tree_node.depth * 1.5)

        if item.is_expandable:
            is_open = item.is_expanded or bool(data.search)
            op = row.operator(
                ALBAM_OT_RealFileSystemCollapseToggle.bl_idname,
                text="",
                icon=self.EXPAND_ICONS[is_open],
                emboss=False,
            )
            op.button_index = index
            row.label(text=item.display_name, icon="FILEBROWSER" if item.is_root else "FILE_FOLDER")
        else:
            # same width as the expand arrow, so file icons line up with folder icons
            row.label(text="", icon="BLANK1")
            sub = row.row(align=True)
            sub.active = item.is_importable
            sub.label(text=item.display_name, icon=self.CATEGORY_ICONS.get(item.category, "FILE"))

    def draw_filter(self, context, layout):
        # search and filter are drawn above the list by the panel
        pass

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        key = (data.as_pointer(), len(items), data.revision, data.search, data.importable_only)
        cached = _RFS_FILTER_CACHE.get(self.list_id)
        if cached and cached[0] == key:
            return cached[1], []

        depths, names, is_folder, is_importable, is_expanded = [], [], [], [], []
        for f in items:
            depths.append(f.tree_node.depth)
            names.append(f.display_name)
            is_folder.append(f.is_expandable)
            is_importable.append(f.is_importable)
            is_expanded.append(f.is_expanded)
        visible = compute_visible_items(
            depths, names, is_folder, is_importable, is_expanded, data.search, data.importable_only
        )
        flags = [self.bitflag_filter_item if v else 0 for v in visible]
        _RFS_FILTER_CACHE[self.list_id] = (key, flags)
        return flags, []


@blender_registry.register_blender_type
class ALBAM_PT_ImportSection(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_ImportSection"
    bl_label = "Import"
    bl_region_type = "UI"
    bl_space_type = "VIEW_3D"

    def draw(self, context):
        row = self.layout.row()
        row.prop(context.scene.albam.apps, "app_selected")
        # Experimental for reengine
        if os.getenv("ALBAM_ENABLE_REEN"):
            row.operator("albam.app_config_popup", icon="OPTIONS")


@blender_registry.register_blender_type
class ALBAM_PT_RealFileSystem(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_RealFileSystem"
    bl_label = "Game Files"
    bl_parent_id = "ALBAM_PT_ImportSection"
    bl_region_type = "UI"
    bl_space_type = "VIEW_3D"

    def draw(self, context):
        layout = self.layout
        rfs = context.scene.albam.rfs

        row = layout.row(align=True)
        row.operator("albam.add_real_root_folder", icon="NEWFOLDER")
        row.operator("albam.remove_imported_real", text="", icon="X")
        row.operator("albam.collapse_real_folders", text="", icon="FULLSCREEN_EXIT")
        row.operator("albam.refresh_real_folders", text="", icon="FILE_REFRESH")

        if len(rfs.file_list) == 0:
            layout.label(text="Add a folder of extracted arc files", icon="INFO")
            return

        row = layout.row(align=True)
        row.prop(rfs, "search", text="", icon="VIEWZOOM")
        row.prop(rfs, "importable_only", text="", icon="FILTER")
        layout.template_list(
            "ALBAM_UL_RealFileSystemUI",
            "rfs",
            rfs,
            "file_list",
            rfs,
            "file_list_selected_index",
            sort_lock=True,
            rows=12,
        )


@blender_registry.register_blender_type
class ALBAM_PT_ImportOptionsCustom(bpy.types.Panel):
    # TODO: better class name
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_ImportOptionsCustom"
    bl_label = ""
    bl_parent_id = "ALBAM_PT_RealFileSystem"
    bl_region_type = "UI"
    bl_space_type = "VIEW_3D"

    def draw(self, context):
        current_item = get_import_item(context)
        if not current_item:
            return
        ext = current_item.extension
        draw_func = blender_registry.import_options_custom_draw_funcs.get(ext)
        if not draw_func:
            return
        draw_func(self, context)

    @classmethod
    def poll(self, context):
        current_item = get_import_item(context)
        if not current_item:
            return False
        ext = current_item.extension
        poll_func = blender_registry.import_options_custom_poll_funcs.get(ext)
        if not poll_func:
            return False
        return poll_func(self, context)


@blender_registry.register_blender_type
class ALBAM_PT_RealFileSystemImport(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_RealFileSystemImport"
    bl_label = "Import Game File"
    bl_options = {"HIDE_HEADER"}
    bl_parent_id = "ALBAM_PT_RealFileSystem"
    bl_region_type = "UI"
    bl_space_type = "VIEW_3D"

    def draw(self, context):
        item = ALBAM_OT_ImportReal.get_selected_item(context)
        text = f"Import {item.display_name}" if item and item.is_importable else "Import"
        row = self.layout.row(align=True)
        row.scale_y = 1.4
        row.operator("albam.import_real", text=text, icon="IMPORT")
        row.operator("wm.import_options", text="", icon="OPTIONS")


@blender_registry.register_blender_type
class ALBAM_PT_VirtualFileSystem(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_VirtualFileSystem"
    bl_label = "Archives"
    bl_parent_id = "ALBAM_PT_ImportSection"
    bl_region_type = "UI"
    bl_space_type = "VIEW_3D"

    @classmethod
    def poll(cls, context):
        # dmc4 archives aren't browsable, its files are extracted and added as Game Files
        return context.scene.albam.apps.app_selected != "dmc4"

    def draw(self, context):
        layout = self.layout
        vfs = context.scene.albam.vfs

        row = layout.row(align=True)
        row.operator("albam.add_files", icon="FILE_NEW")
        row.operator("albam.save_file", text="", icon="SORT_ASC")
        row.operator("albam.remove_imported", text="", icon="X")
        layout.template_list(
            "ALBAM_UL_VirtualFileSystemUI",
            "vfs",
            vfs,
            "file_list",
            vfs,
            "file_list_selected_index",
            sort_lock=True,
            rows=8,
        )
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("albam.import_vfile", text="Import", icon="IMPORT")
        row.operator("wm.import_options", text="", icon="OPTIONS")


@blender_registry.register_blender_type
class ALBAM_OT_AppConfigPopup(bpy.types.Operator):
    bl_label = ""
    bl_idname = "albam.app_config_popup"

    # TODO: warning icon if required settings not present

    def invoke(self, context, event):
        x = context.scene.albam.apps.mouse_x
        y = context.scene.albam.apps.mouse_y
        if x and y:
            context.window.cursor_warp(x, y)
        else:
            context.scene.albam.apps.mouse_x = event.mouse_x
            context.scene.albam.apps.mouse_y = event.mouse_y
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        context.scene.albam.apps.mouse_x = 0
        context.scene.albam.apps.mouse_y = 0
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout

        apps = context.scene.albam.apps
        try:
            app_index = apps["app_selected"]
        except KeyError:
            # default, before actually selecting
            app_index = 0
        app_selected_name = apps.bl_rna.properties["app_selected"].enum_items[app_index].name
        layout.label(text=f"{app_selected_name}")
        layout.row()

        row = self.layout.row(heading="App Folder:", align=True)
        row.prop(context.scene.albam.apps, "app_dir")
        row.operator("albam.app_dir_setter", text="", icon="FILEBROWSER")

        row = self.layout.row(heading="App Config:", align=True)
        row.prop(context.scene.albam.apps, "app_config_filepath")
        row.operator("albam.app_config_filepath_setter", text="", icon="FILEBROWSER")


@blender_registry.register_blender_type
class ALBAM_OT_AppDirSetter(bpy.types.Operator):
    bl_idname = "albam.app_dir_setter"
    bl_label = "Select App Folder"

    DIRECTORY = bpy.props.StringProperty(subtype="DIR_PATH")
    directory: DIRECTORY

    def invoke(self, context, event):
        wm = context.window_manager
        wm.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.scene.albam.apps.app_dir = self.directory
        bpy.ops.albam.app_config_popup("INVOKE_DEFAULT")
        return {"FINISHED"}

    def cancel(self, context):
        bpy.ops.albam.app_config_popup("INVOKE_DEFAULT")


@blender_registry.register_blender_type
class ALBAM_OT_SetAppConfigPath(bpy.types.Operator):
    bl_idname = "albam.app_config_filepath_setter"
    bl_label = "Select App Config"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # NOQA

    def invoke(self, context, event):
        wm = context.window_manager
        wm.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.scene.albam.apps.app_config_filepath = self.filepath
        bpy.ops.albam.app_config_popup("INVOKE_DEFAULT")
        return {"FINISHED"}

    def cancel(self, context):
        bpy.ops.albam.app_config_popup("INVOKE_DEFAULT")


@blender_registry.register_blender_type
class ALBAM_WM_OT_ImportOptions(bpy.types.Operator):
    """Set settings for importing"""
    bl_label = "Import Options"
    bl_idname = "wm.import_options"

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        import_settings = context.scene.albam.import_settings
        layout = self.layout
        layout.prop(import_settings, "import_only_main_lods", text="Import main LODs only")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
