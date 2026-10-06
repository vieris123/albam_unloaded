import os
from pathlib import PureWindowsPath

import bpy

from albam.apps import APPS
from albam.registry import blender_registry
from albam.vfs import TreeNode, VirtualFile


@blender_registry.register_blender_prop
class RealFile(bpy.types.PropertyGroup):
    """
    A file or folder on disk, listed under a root folder added by the user.
    Bytes are read from disk when needed, nothing is stored in the .blend
    """
    display_name: bpy.props.StringProperty()
    absolute_path: bpy.props.StringProperty()
    relative_path: bpy.props.StringProperty()  # windows style, relative to the root folder
    is_root: bpy.props.BoolProperty(default=False)
    is_expandable: bpy.props.BoolProperty(default=False)  # folders
    is_expanded: bpy.props.BoolProperty(default=False)
    is_importable: bpy.props.BoolProperty(default=False)
    category: bpy.props.StringProperty()
    tree_node: bpy.props.PointerProperty(type=TreeNode)  # only depth and root_id are used

    app_id: bpy.props.EnumProperty(name="", description="", items=APPS)
    vfs_id: bpy.props.StringProperty()

    # Same path helpers as VirtualFile, so import functions can take either
    extension = VirtualFile.extension
    relative_path_windows = VirtualFile.relative_path_windows
    relative_path_windows_no_ext = VirtualFile.relative_path_windows_no_ext
    root_vfile = VirtualFile.root_vfile
    get_vfs = VirtualFile.get_vfs
    _get_relative_path_windows = VirtualFile._get_relative_path_windows

    def get_bytes(self):
        with open(self.absolute_path, "rb") as f:
            return f.read()


@blender_registry.register_blender_prop_albam(name="rfs")
class RealFileSystem(bpy.types.PropertyGroup):
    file_list: bpy.props.CollectionProperty(type=RealFile)
    file_list_selected_index: bpy.props.IntProperty()
    search: bpy.props.StringProperty(
        name="Search",
        description="Only show items whose name contains this text",
        options={"TEXTEDIT_UPDATE"},
    )
    importable_only: bpy.props.BoolProperty(
        name="Importable Only",
        description="Hide files that can't be imported, and folders that don't contain any",
        default=True,
    )
    # Bumped on every change to the list or its expanded state, the UI list caches on it
    revision: bpy.props.IntProperty()

    SEPARATOR = "::"
    VFS_ID = "rfs"

    def get_vfile(self, app_id, relative_path):
        path = PureWindowsPath(relative_path)
        file_id = self.SEPARATOR.join((app_id,) + path.parts)
        return self.file_list[file_id]

    def select_vfile(self, app_id, relative_path):
        path = PureWindowsPath(relative_path)
        file_id = self.SEPARATOR.join((app_id,) + path.parts)
        self.file_list_selected_index = self.file_list.find(file_id)
        return self.file_list[file_id]

    @property
    def selected_item(self):
        try:
            return self.file_list[self.file_list_selected_index]
        except IndexError:
            # list might have been cleared
            return None

    def add_root_folder(self, app_id, absolute_path):
        """
        Add a folder and everything under it. Returns the root id.
        Adding a folder that is already listed just returns its id.
        """
        root_path = os.path.normpath(absolute_path)
        for f in self.file_list:
            if f.is_root and os.path.normcase(f.absolute_path) == os.path.normcase(root_path):
                return f.name

        display_name = os.path.basename(root_path) or root_path
        root_id = self._unique_root_id(app_id, display_name)
        # Don't use the item after adding more, file_list.add() invalidates references
        root = self.file_list.add()
        root.name = root_id
        root.vfs_id = self.VFS_ID
        root.app_id = app_id
        root.display_name = display_name
        root.absolute_path = root_path
        root.is_root = True
        root.is_expandable = True
        root.is_expanded = True

        self._add_folder_contents(app_id, root_id, root_path, root_path, depth=1)
        self.revision += 1
        return root_id

    def remove_root_folder(self, root_id):
        indices = [
            i for i, f in enumerate(self.file_list)
            if f.tree_node.root_id == root_id or (f.is_root and f.name == root_id)
        ]
        if len(indices) == len(self.file_list):
            self.file_list.clear()
        else:
            for i in reversed(indices):
                self.file_list.remove(i)
        self.file_list_selected_index = max(0, min(self.file_list_selected_index, len(self.file_list) - 1))
        self.revision += 1

    def refresh(self):
        """
        Re-scan all root folders from disk, keeping expanded folders and the selection.
        Returns the paths of root folders that no longer exist (they are removed).
        """
        roots = [(f.app_id, f.absolute_path) for f in self.file_list if f.is_root]
        expanded = {f.name for f in self.file_list if f.is_expanded}
        selected = self.selected_item
        selected_name = selected.name if selected else ""

        self.file_list.clear()
        missing = []
        for app_id, path in roots:
            if os.path.isdir(path):
                self.add_root_folder(app_id, path)
            else:
                missing.append(path)

        for f in self.file_list:
            f.is_expanded = f.name in expanded
        self.file_list_selected_index = max(0, self.file_list.find(selected_name))
        self.revision += 1
        return missing

    def collapse_all(self):
        for f in self.file_list:
            f.is_expanded = False
        self.revision += 1

    def _unique_root_id(self, app_id, display_name):
        root_id = f"{app_id}{self.SEPARATOR}{display_name}"
        n = 2
        while self.file_list.find(root_id) != -1:
            root_id = f"{app_id}{self.SEPARATOR}{display_name} ({n})"
            n += 1
        return root_id

    def _add_folder_contents(self, app_id, root_id, root_path, folder_path, depth):
        try:
            with os.scandir(folder_path) as it:
                entries = list(it)
        except OSError:
            return
        sort_key = lambda e: e.name.lower()  # noqa: E731
        folders = sorted((e for e in entries if e.is_dir()), key=sort_key)
        files = sorted((e for e in entries if not e.is_dir()), key=sort_key)

        for entry in folders:
            self._add_item(app_id, root_id, root_path, entry.path, depth, is_folder=True)
            self._add_folder_contents(app_id, root_id, root_path, entry.path, depth + 1)
        for entry in files:
            self._add_item(app_id, root_id, root_path, entry.path, depth, is_folder=False)

    def _add_item(self, app_id, root_id, root_path, absolute_path, depth, is_folder):
        relative_path = PureWindowsPath(os.path.relpath(absolute_path, root_path))
        f = self.file_list.add()
        f.name = self.SEPARATOR.join((app_id,) + relative_path.parts)
        f.vfs_id = self.VFS_ID
        f.app_id = app_id
        f.display_name = relative_path.name
        f.absolute_path = absolute_path
        f.relative_path = str(relative_path)
        f.is_expandable = is_folder
        f.tree_node.depth = depth
        f.tree_node.root_id = root_id
        if not is_folder:
            key = (app_id, f.extension)
            f.category = blender_registry.file_categories.get(key) or ""
            f.is_importable = key in blender_registry.import_registry


def compute_visible_items(depths, names, is_folder, is_importable, is_expanded, search="", importable_only=False):
    """
    Which items of a depth-first file list to show. Roots have depth 0 and are always shown.
    Files are shown if they pass the filters. With a filter active, folders are shown only if
    something under them is shown or, when not limiting to importable files, their name matches
    the search. While searching, matches are shown even inside collapsed folders.
    """
    search = search.lower()
    filtering = bool(search) or importable_only
    keep = [False] * len(depths)
    folder_stack = []

    for i, depth in enumerate(depths):
        while folder_stack and depths[folder_stack[-1]] >= depth:
            folder_stack.pop()

        if depth == 0:
            own_match = True
        elif is_folder[i]:
            own_match = not filtering or (bool(search) and not importable_only and search in names[i].lower())
        else:
            own_match = (not importable_only or is_importable[i]) and search in names[i].lower()

        if own_match:
            keep[i] = True
            for ancestor in reversed(folder_stack):
                if keep[ancestor]:
                    break
                keep[ancestor] = True

        if is_folder[i]:
            folder_stack.append(i)

    if search:
        return keep

    visible = [False] * len(depths)
    collapsed_depth = None
    for i, depth in enumerate(depths):
        if collapsed_depth is not None:
            if depth > collapsed_depth:
                continue
            collapsed_depth = None
        visible[i] = keep[i]
        if keep[i] and is_folder[i] and not is_expanded[i]:
            collapsed_depth = depth
    return visible


@blender_registry.register_blender_type
class ALBAM_OT_RealFileSystemAddRootFolder(bpy.types.Operator):
    """Add a folder of extracted game files"""
    bl_idname = "albam.add_real_root_folder"
    bl_label = "Add Folder"
    directory: bpy.props.StringProperty(subtype="DIR_PATH")  # NOQA
    files: bpy.props.CollectionProperty(name="added_files", type=bpy.types.OperatorFileListElement)  # NOQA
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})  # NOQA

    def invoke(self, context, event):  # pragma: no cover
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):  # pragma: no cover
        app_id = context.scene.albam.apps.app_selected
        rfs = context.scene.albam.rfs
        # Folders selected in the browser, or the folder the browser is in if none
        paths = [os.path.join(self.directory, f.name) for f in self.files if f.name]
        paths = [p for p in paths if os.path.isdir(p)] or [self.directory]
        root_id = None
        for path in paths:
            root_id = rfs.add_root_folder(app_id, path)
        if root_id:
            rfs.file_list_selected_index = rfs.file_list.find(root_id)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_RealFileSystemRemoveRoot(bpy.types.Operator):
    """Remove the selected item's root folder from the list (nothing is deleted from disk)"""
    bl_idname = "albam.remove_imported_real"
    bl_label = "Remove Folder"

    def execute(self, context):
        rfs = context.scene.albam.rfs
        item = rfs.selected_item
        rfs.remove_root_folder(item.name if item.is_root else item.tree_node.root_id)
        return {"FINISHED"}

    @classmethod
    def poll(cls, context):
        return context.scene.albam.rfs.selected_item is not None


@blender_registry.register_blender_type
class ALBAM_OT_RealFileSystemRefresh(bpy.types.Operator):
    """Re-scan the added folders from disk"""
    bl_idname = "albam.refresh_real_folders"
    bl_label = "Refresh"

    def execute(self, context):
        missing = context.scene.albam.rfs.refresh()
        if missing:
            self.report({"WARNING"}, f"Removed folders that no longer exist: {', '.join(missing)}")
        return {"FINISHED"}

    @classmethod
    def poll(cls, context):
        return len(context.scene.albam.rfs.file_list) > 0


@blender_registry.register_blender_type
class ALBAM_OT_RealFileSystemCollapseAll(bpy.types.Operator):
    """Collapse all folders"""
    bl_idname = "albam.collapse_real_folders"
    bl_label = "Collapse All"

    def execute(self, context):
        context.scene.albam.rfs.collapse_all()
        return {"FINISHED"}

    @classmethod
    def poll(cls, context):
        return len(context.scene.albam.rfs.file_list) > 0


@blender_registry.register_blender_type
class ALBAM_OT_RealFileSystemCollapseToggle(bpy.types.Operator):
    """Expand or collapse this folder"""
    bl_idname = "albam.real_file_item_collapse_toggle"
    bl_label = "Expand/Collapse"
    bl_options = {"INTERNAL"}

    button_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        rfs = context.scene.albam.rfs
        item = rfs.file_list[self.button_index]
        item.is_expanded = not item.is_expanded
        rfs.file_list_selected_index = self.button_index
        rfs.revision += 1
        return {"FINISHED"}
