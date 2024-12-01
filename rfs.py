import copy
import os
import glob
from pathlib import PureWindowsPath

import bpy

from albam.apps import APPS
from albam.registry import blender_registry
from vfs import (VirtualFile, VirtualFileSystem, Tree, TreeNode,
                 ALBAM_OT_VirtualFileSystemCollapseToggleBase,
                 ALBAM_OT_VirtualFileSystemRemoveRootVFileBase)

@blender_registry.register_blender_prop
class RealFile(VirtualFile):
    # FIXME: consider strings, seems pretty inefficient

    app_id: bpy.props.EnumProperty(name="", description="", items=APPS)
    vfs_id: bpy.props.StringProperty()

    data_bytes: bpy.props.StringProperty(subtype="BYTE_STRING")  # noqa: F821

    def get_bytes(self):
        accessor = self.get_accessor()
        return accessor(self, bpy.context)

    def get_accessor(self):
        if self.absolute_path:
            return self.real_file_accessor
        if self.data_bytes:
            return lambda vfile, context: self.data_bytes
        vfs = getattr(bpy.context.scene.albam, self.vfs_id)
        root = vfs.file_list[self.tree_node.root_id]
        accessor_func = blender_registry.archive_accessor_registry.get(
            (self.app_id, root.extension)
        )
        if not accessor_func:
            raise RuntimeError("Archive item doesn't have an accessor")

        return accessor_func

    @staticmethod
    def real_file_accessor(file_item, context):
        with open(file_item.absolute_path, 'rb') as f:
            return f.read()

    def real_path_accessor(self):
        rfs = self.get_vfs()

class RealFileSystemBase(VirtualFileSystem):
    file_list : bpy.props.CollectionProperty(type=RealFile)
    file_list_selected_index : bpy.props.IntProperty()

    SEPARATOR = "::"
    VFS_ID = "rfs"

    def add_root_folder(self, app_id, absolute_path):
        path = PureWindowsPath(absolute_path)
        f = self.file_list.add()
        f.is_root = True
        f.name = path.name
        f.vfs_id = self.VFS_ID
        f.app_id = app_id
        f.display_name = path.name
        f.absolute_path = absolute_path
        f.is_expandable = True
        self._expand_archive(app_id, f)

    def add_vfile(self, vfile_data):
        vf = self.file_list.add()
        vf.vfs_id = self.VFS_ID
        vf.app_id = vfile_data.app_id
        vf.name = f"{vfile_data.app_id}::{vfile_data.name}"
        vf.display_name = vfile_data.name
        vf.absolute_path = vfile_data.absolute_path
        if not vfile_data.is_folder:
            vf.data_bytes = vfile_data.data_bytes or b""

        return vf

    def add_vfiles_as_tree(self, app_id, root_vfile_data, vfiles_data):
        root_id = f"{app_id}::{root_vfile_data.name}"
        tree = Tree(root_id, app_id)
        bl_vf = self.add_vfile(root_vfile_data)
        bl_vf.is_expandable = True
        bl_vf.is_root = True

        for vfile_data in vfiles_data:
            tree.add_node_from_path(vfile_data.relative_path, vfile_data)

        for node in tree.flatten():
            self._add_vf_from_treenode(bl_vf.app_id, root_id, node)

        return bl_vf

    def _expand_archive(self, app_id, rf):
        # Beware of chaning this, it was observed the reference
        # is lost in the middle of the loop below if using vf.name directly,
        # we get an empty string instead! Don't know why
        root_id = rf.name
        tree = Tree(root_id=rf.name, app_id=app_id)
        # TODO: popup if calling failed. Known exceptions + unexpected
        for rel_path in glob.glob(rf.absolute_path):
            tree.add_node_from_path(rel_path)
        for node in tree.flatten():
            self._add_vf_from_treenode(app_id, root_id, node)

    def _add_vf_from_treenode(self, app_id, root_id, node):
        child_vf = self.file_list.add()
        child_vf.vfs_id = self.VFS_ID
        child_vf.app_id = app_id
        child_vf.name = node["node_id"]
        child_vf.relative_path = node["relative_path"]
        child_vf.display_name = node["name"]
        child_vf.is_expandable = bool(node["children"])
        child_vf.category = blender_registry.file_categories.get((app_id, child_vf.extension), "")
        vfile = node["vfile"]
        if vfile:
            child_vf.data_bytes = vfile.data_bytes
        child_vf.tree_node.depth = node["depth"] + 1
        child_vf.tree_node.root_id = root_id
        for ancestor_id in node["ancestors_ids"]:
            ancestor_node = child_vf.tree_node_ancestors.add()
            ancestor_node.node_id = ancestor_id

    @property
    def selected_vfile(self):
        if len(self.file_list) == 0:
            return None
        index = self.file_list_selected_index
        try:
            vfile = self.file_list[index]
        except IndexError:
            # list might have been cleared
            return
        if not vfile.is_root and vfile.is_expandable:
            return None
        return vfile


@blender_registry.register_blender_prop_albam(name="rfs")
class RealFileSystem(RealFileSystemBase, bpy.types.PropertyGroup):
    pass


@blender_registry.register_blender_type
class ALBAM_OT_RealFileSystemAddRootFolder(bpy.types.Operator):
    bl_idname = "albam.add_real_root_folder"
    bl_label = "Add Real Root Files"
    directory: bpy.props.StringProperty(subtype="DIR_PATH")  # NOQA
    files: bpy.props.CollectionProperty(name="added_files", type=bpy.types.OperatorFileListElement)  # NOQA
    filter_folder = bpy.props.BoolProperty(
        default=True,
        options={"HIDDEN"}
        )
    # FIXME: use registry, un-hardcode
    #filter_glob: bpy.props.StringProperty(default="*.arc;*.pak", options={"HIDDEN"})  # NOQA

    def invoke(self, context, event):  # pragma: no cover
        wm = context.window_manager
        wm.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):  # pragma: no cover
        self._execute(context, self.directory, self.files)
        context.scene.albam.rfs.file_list.update()
        return {"FINISHED"}

    @staticmethod
    def _execute(context, directory, files):
        app_id = context.scene.albam.apps.app_selected
        rfs = context.scene.albam.rfs
        for f in files:
            absolute_path = os.path.join(directory, f.name)
            rfs.add_root_folder(app_id, absolute_path)

@blender_registry.register_blender_type
class ALBAM_OT_RealFileSystemCollapseToggle(
        ALBAM_OT_VirtualFileSystemCollapseToggleBase, bpy.types.Operator):

    bl_idname = "albam.file_item_collapse_toggle"
    bl_label = "ALBAM_OT_VirtualFileSystemCollapseToggle"
    VFS_ID = "rfs"
    NODES_CACHE = {}

@blender_registry.register_blender_type
class ALBAM_OT_RealFileSystemRemoveRoot(
        ALBAM_OT_VirtualFileSystemRemoveRootVFileBase, bpy.types.Operator):

    bl_idname = "albam.remove_imported_real"
    bl_label = "Remove imported real files"
    VFS_ID = "rfs"


class RealFileData:
    # FIXME: normalize to posix path!

    def __init__(self, app_id, absolute_path, data_bytes=None):
        self.app_id = app_id
        self.absolute_path = absolute_path
        self.is_folder = os.path.isdir(absolute_path)
        self.name = os.path.basename(absolute_path)  # TODO: posix only
        if not self.is_folder:
            self.data_bytes = data_bytes

    @property
    def extension(self):
        """
        Allow up to 2 dots as an extension
        e.g. texname.tex.34 -> tex.34
        """
        SEP = "."
        name , _ , extension = self.relative_path.rpartition(SEP)
        if SEP in name:
            _, __, extension0 = name.rpartition(SEP)
            extension = SEP.join((extension0, extension))
        return extension