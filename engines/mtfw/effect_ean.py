"""DMC4 .ean (effect flipbook) import / export and the Flipbook panel (efl/ean.py has the layout).

Import makes a holder Empty `EAN_<file>` whose `ean_data` custom property (JSON) keeps every field; the Flipbook
panel (3D View > Albam [Beta]) edits it: sequences, their default flags / pivot / grid, and the frame rectangles,
with Generate Grid to cut a sequence's frames from its grid, as the game's files were made. Export writes the
holder's data back with the file's own version (SE files keep their per-frame UVs, recomputed for changed
frames from the texture size their stored UVs imply).
"""
import json

import bpy

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.vfs import VirtualFileData
from .efl import ean

DATA_KEY = "ean_data"
MAX_FRAMES = 4096
ANIM_FLAG_HELP = ("Animation flags used when the particle doesn't override them (ANIM_FLAG): 0x1 animate, 0x2 loop, "
                  "0x4 reverse, 0x8 hold the last frame, 0x10 random reverse, 0x100 / 0x200 flip U / V, "
                  "0x400 / 0x800 random flips, 0x1000 rotate the cell, 0x2000 no blending between frames")

_loading = False


# -- data <-> JSON ----------------------------------------------------------------------------------

def anim_to_dict(anim):
    size = ean.texture_size(anim)
    return {"version": anim.version, "option_flag": anim.option_flag, "tex_size": list(size) if size else None,
            "sequences": [{"patterns": [list(p) for p in s.patterns], "uvs": [list(u) for u in s.uvs],
                           "default_anim_flag": s.default_anim_flag,
                           "default_pat_center": list(s.default_pat_center),
                           "con_pat_base_point": list(s.con_pat_base_point),
                           "con_pat_col_num": s.con_pat_col_num, "con_pat_total_num": s.con_pat_total_num,
                           "con_pat_size": list(s.con_pat_size)} for s in anim.sequences]}


def dict_to_anim(d):
    seqs = [ean.Sequence([tuple(p) for p in s["patterns"]], s["default_anim_flag"], tuple(s["default_pat_center"]),
                         tuple(s["con_pat_base_point"]), s["con_pat_col_num"], s["con_pat_total_num"],
                         tuple(s["con_pat_size"]), [tuple(u) for u in s.get("uvs", [])]) for s in d["sequences"]]
    return ean.EffectAnim(d["version"], seqs, d.get("option_flag", 0))


def get_data(ob):
    return json.loads(ob[DATA_KEY]) if ob is not None and DATA_KEY in ob else None


def set_data(ob, d):
    ob[DATA_KEY] = json.dumps(d, separators=(",", ":"))


def grid_patterns(seq):
    """Frames cut from a sequence's grid: ConPatTotalNum cells of ConPatSize, ConPatColNum per row, from the base."""
    cols = max(int(seq["con_pat_col_num"]), 1)
    (bx, by), (w, h) = seq["con_pat_base_point"], seq["con_pat_size"]
    return [[bx + (j % cols) * w, by + (j // cols) * h, w, h] for j in range(int(seq["con_pat_total_num"]))]


# -- import / export --------------------------------------------------------------------------------

@blender_registry.register_import_function(app_id="dmc4", extension="ean", file_category="EFFECT")
def load_ean(file_item, context):
    data = file_item.get_bytes()
    try:
        anim = ean.parse(data)
    except ean.EanError as err:
        raise AlbamCheckFailure("This .ean file can't be imported", details=str(err),
                                solution="Only DMC4 effect flipbook (.ean) files are supported")
    name = file_item.display_name.rsplit(".", 1)[0]
    ob = create_ean_object(name, anim, data, context.collection or context.scene.collection)
    ob.albam_asset.app_id = file_item.app_id
    ob.albam_asset.relative_path = getattr(file_item, "relative_path", "") or file_item.display_name
    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = ob
    for other in context.view_layer.objects:
        other.select_set(False)
    context.view_layer.objects.active = ob
    ob.select_set(True)
    return None   # linked above


def create_ean_object(name, anim, data, collection):
    """Holder Empty carrying a parsed flipbook (edited in the Flipbook panel)."""
    ob = bpy.data.objects.new(f"EAN_{name}", None)
    ob.empty_display_type = "PLAIN_AXES"
    ob.empty_display_size = 0.05
    collection.objects.link(ob)
    set_data(ob, anim_to_dict(anim))
    ob.albam_asset.original_bytes = data
    ob.albam_asset.extension = "ean"
    return ob


def ean_from_object(ob):
    """The flipbook an EAN holder currently describes (edits included)."""
    return dict_to_anim(get_data(ob))


def build_ean_bytes(ob):
    d = get_data(ob)
    if d is None:
        raise AlbamCheckFailure("This object has no flipbook data", solution="Import the .ean again")
    problems = []
    for i, s in enumerate(d["sequences"]):
        for j, (x, y, w, h) in enumerate(s["patterns"]):
            if not all(-32768 <= v <= 32767 for v in (x, y, w, h)):
                problems.append(f"sequence {i} frame {j}: values must fit -32768..32767")
        if len(s["patterns"]) > 0xFFFF:
            problems.append(f"sequence {i}: too many frames")
    if problems:
        raise AlbamCheckFailure("The flipbook can't be written", details="\n".join(problems[:20]),
                                solution="Fix those frames in the Flipbook panel")
    size = tuple(d["tex_size"]) if d.get("tex_size") else None
    try:
        return ean.to_bytes(dict_to_anim(d), size)
    except ean.EanError as err:
        raise AlbamCheckFailure("The flipbook can't be written", details=str(err),
                                solution="Special Edition .ean files need their texture size to write changed frames")


@blender_registry.register_export_function(app_id="dmc4", extension="ean")
def export_ean(bl_obj):
    data = build_ean_bytes(bl_obj)
    asset = bl_obj.albam_asset
    return [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]


# -- editor state -----------------------------------------------------------------------------------

def _state(context=None):
    return (context or bpy.context).scene.albam.ean_editor


def _write_sequence(state, context):
    """Copy the sequence widgets into the target's data."""
    global _loading
    if _loading or state.target is None:
        return
    d = get_data(state.target)
    if d is None or not 0 <= state.seq_index < len(d["sequences"]):
        return
    s = d["sequences"][state.seq_index]
    s["default_anim_flag"] = int(state.default_anim_flag)
    s["default_pat_center"] = list(state.default_pat_center)
    s["con_pat_base_point"] = list(state.con_pat_base_point)
    s["con_pat_col_num"] = int(state.con_pat_col_num)
    s["con_pat_total_num"] = int(state.con_pat_total_num)
    s["con_pat_size"] = list(state.con_pat_size)
    set_data(state.target, d)


def _write_frame(item, context):
    state = _state(context)
    if _loading or state.target is None:
        return
    d = get_data(state.target)
    if d is None or not 0 <= state.seq_index < len(d["sequences"]):
        return
    frames = d["sequences"][state.seq_index]["patterns"]
    try:   # "...frames[N]"
        index = int(item.path_from_id().rsplit("[", 1)[1].rstrip("]"))
    except (ValueError, IndexError):
        return
    if index >= len(frames):
        return
    frames[index] = list(item.rect)
    set_data(state.target, d)


def _on_seq_index(state, context):
    if not _loading:
        load_sequence(state)


def load_target(state, ob):
    """Mirror an EAN holder's sequences into the panel."""
    global _loading
    _loading = True
    try:
        state.target = ob
        state.sequences.clear()
        d = get_data(ob)
        if d is None:
            return
        for i, s in enumerate(d["sequences"]):
            item = state.sequences.add()
            item.name = f"Sequence {i}  ({len(s['patterns'])} frames)"
        state.seq_index = min(state.seq_index, max(len(d["sequences"]) - 1, 0))
    finally:
        _loading = False
    load_sequence(state)


def load_sequence(state):
    global _loading
    _loading = True
    try:
        state.frames.clear()
        d = get_data(state.target)
        if d is None or not 0 <= state.seq_index < len(d["sequences"]):
            return
        s = d["sequences"][state.seq_index]
        state.default_anim_flag = s["default_anim_flag"]
        state.default_pat_center = s["default_pat_center"]
        state.con_pat_base_point = s["con_pat_base_point"]
        state.con_pat_col_num = s["con_pat_col_num"]
        state.con_pat_total_num = s["con_pat_total_num"]
        state.con_pat_size = s["con_pat_size"]
        for j, rect in enumerate(s["patterns"]):
            item = state.frames.add()
            item.name = f"Frame {j}"
            item.rect = rect
        state.frame_index = min(state.frame_index, max(len(s["patterns"]) - 1, 0))
    finally:
        _loading = False


@blender_registry.register_blender_prop
class AlbamEanSequenceItem(bpy.types.PropertyGroup):
    pass


@blender_registry.register_blender_prop
class AlbamEanFrameItem(bpy.types.PropertyGroup):
    rect: bpy.props.IntVectorProperty(
        name="Rectangle", size=4, min=-32768, max=32767, update=_write_frame,
        description="The frame's pixel rectangle on the texture sheet: X, Y of its top-left corner, then width and "
                    "height")


@blender_registry.register_blender_prop_albam(name="ean_editor")
class AlbamEanEditor(bpy.types.PropertyGroup):
    target: bpy.props.PointerProperty(type=bpy.types.Object)
    sequences: bpy.props.CollectionProperty(type=AlbamEanSequenceItem)
    seq_index: bpy.props.IntProperty(update=_on_seq_index, description="Click a sequence to edit it")
    frames: bpy.props.CollectionProperty(type=AlbamEanFrameItem)
    frame_index: bpy.props.IntProperty(description="Click a frame to select it")
    default_anim_flag: bpy.props.IntProperty(name="Default Anim Flags", min=0, max=0xFFFF, update=_write_sequence,
                                             description=ANIM_FLAG_HELP)
    default_pat_center: bpy.props.IntVectorProperty(
        name="Pivot", size=2, update=_write_sequence,
        description="The frames' pivot in pixels, measured from a frame's top-left corner (usually its centre); "
                    "particles that use PatCenter turn around it")
    con_pat_base_point: bpy.props.IntVectorProperty(
        name="Grid Start", size=2, update=_write_sequence,
        description="Pixel position of the grid's first cell (top-left). Used by Generate Grid")
    con_pat_col_num: bpy.props.IntProperty(
        name="Columns", min=0, max=0xFFFF, update=_write_sequence,
        description="Cells per row of the grid. Used by Generate Grid")
    con_pat_total_num: bpy.props.IntProperty(
        name="Cells", min=0, max=0xFFFF, update=_write_sequence,
        description="Number of cells (frames) in the grid, row by row. Used by Generate Grid")
    con_pat_size: bpy.props.IntVectorProperty(
        name="Cell Size", size=2, min=0, max=0xFFFF, update=_write_sequence,
        description="Width and height of one grid cell in pixels. Used by Generate Grid")
    show_frames: bpy.props.BoolProperty(name="Frames", default=True, description="Show the sequence's frame list")


# -- operators --------------------------------------------------------------------------------------

def _target(context):
    ob = context.active_object
    return ob if ob is not None and DATA_KEY in ob else None


class _EanOperator:
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _target(context) is not None

    def edit(self, context, change):
        """Apply change(d, state) to the target's data, then reload the panel."""
        state = _state(context)
        ob = _target(context)
        if state.target != ob:
            load_target(state, ob)
        d = get_data(ob)
        message = change(d, state)
        set_data(ob, d)
        load_target(state, ob)
        if message:
            self.report({"INFO"}, message)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EanLoad(bpy.types.Operator):
    """Show this flipbook's sequences and frames in the panel"""
    bl_idname = "albam.ean_load"
    bl_label = "Edit Flipbook"

    @classmethod
    def poll(cls, context):
        return _target(context) is not None

    def execute(self, context):
        load_target(_state(context), _target(context))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EanSequenceAdd(_EanOperator, bpy.types.Operator):
    """Add a sequence after the selected one, copying its grid settings and frames"""
    bl_idname = "albam.ean_sequence_add"
    bl_label = "Add Sequence"

    def execute(self, context):
        def change(d, state):
            seqs = d["sequences"]
            src = seqs[state.seq_index] if seqs else {
                "patterns": [], "uvs": [], "default_anim_flag": 0, "default_pat_center": [32, 32],
                "con_pat_base_point": [0, 0], "con_pat_col_num": 1, "con_pat_total_num": 1, "con_pat_size": [64, 64]}
            copy = json.loads(json.dumps(src))
            at = state.seq_index + 1 if seqs else 0
            seqs.insert(at, copy)
            state.seq_index = at
        return self.edit(context, change)


@blender_registry.register_blender_type
class ALBAM_OT_EanSequenceRemove(_EanOperator, bpy.types.Operator):
    """Remove the selected sequence. Particles pick sequences by number (SeqNoMin), so later ones move down"""
    bl_idname = "albam.ean_sequence_remove"
    bl_label = "Remove Sequence"

    @classmethod
    def poll(cls, context):
        d = get_data(_target(context))
        return d is not None and len(d["sequences"]) > 1

    def execute(self, context):
        def change(d, state):
            d["sequences"].pop(state.seq_index)
            state.seq_index = max(min(state.seq_index, len(d["sequences"]) - 1), 0)
        return self.edit(context, change)


@blender_registry.register_blender_type
class ALBAM_OT_EanFrameAdd(_EanOperator, bpy.types.Operator):
    """Add a frame after the selected one (a copy of it, moved one cell to the right)"""
    bl_idname = "albam.ean_frame_add"
    bl_label = "Add Frame"

    def execute(self, context):
        def change(d, state):
            s = d["sequences"][state.seq_index]
            frames = s["patterns"]
            src = frames[state.frame_index] if frames else [0, 0] + list(s["con_pat_size"])
            at = state.frame_index + 1 if frames else 0
            frames.insert(at, [src[0] + src[2], src[1], src[2], src[3]] if frames else src)
            s["uvs"] = []   # recomputed on export
            state.frame_index = at
        return self.edit(context, change)


@blender_registry.register_blender_type
class ALBAM_OT_EanFrameRemove(_EanOperator, bpy.types.Operator):
    """Remove the selected frame"""
    bl_idname = "albam.ean_frame_remove"
    bl_label = "Remove Frame"

    @classmethod
    def poll(cls, context):
        state = _state(context)
        return _target(context) is not None and len(state.frames) > 0

    def execute(self, context):
        def change(d, state):
            s = d["sequences"][state.seq_index]
            if s["patterns"]:
                s["patterns"].pop(min(state.frame_index, len(s["patterns"]) - 1))
                s["uvs"] = []
            state.frame_index = max(min(state.frame_index, len(s["patterns"]) - 1), 0)
        return self.edit(context, change)


@blender_registry.register_blender_type
class ALBAM_OT_EanGenerateGrid(_EanOperator, bpy.types.Operator):
    """Replace the selected sequence's frames with its grid: Cells frames of Cell Size, Columns per row, starting at
    Grid Start, read row by row. The pivot is set to the cell centre"""
    bl_idname = "albam.ean_generate_grid"
    bl_label = "Generate Grid"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        def change(d, state):
            s = d["sequences"][state.seq_index]
            if s["con_pat_total_num"] > MAX_FRAMES:
                return f"At most {MAX_FRAMES} frames"
            s["patterns"] = grid_patterns(s)
            s["uvs"] = []
            w, h = s["con_pat_size"]
            s["default_pat_center"] = [w // 2, h // 2]
            state.frame_index = 0
            return f"{len(s['patterns'])} frames generated"
        return self.edit(context, change)


# -- panel ------------------------------------------------------------------------------------------

@blender_registry.register_blender_type
class ALBAM_UL_EanSequences(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon="RENDERLAYERS")


@blender_registry.register_blender_type
class ALBAM_UL_EanFrames(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=str(index))
        for i, label in enumerate(("X", "Y", "W", "H")):
            row.prop(item, "rect", index=i, text=label)


@blender_registry.register_blender_type
class ALBAM_PT_EanEditor(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_EanEditor"
    bl_label = "Flipbook"
    bl_region_type = "UI"
    bl_space_type = "VIEW_3D"

    @classmethod
    def poll(cls, context):
        return _target(context) is not None

    def draw(self, context):
        layout = self.layout
        state = _state(context)
        ob = _target(context)
        layout.label(text=ob.albam_asset.relative_path or ob.name, icon="IMAGE_DATA")
        if state.target != ob:
            layout.operator("albam.ean_load", icon="GREASEPENCIL")
            return
        d = get_data(ob)
        size = d.get("tex_size")
        if size:
            layout.label(text=f"Texture size from the stored UVs: {size[0]} x {size[1]}")
        row = layout.row()
        row.template_list("ALBAM_UL_EanSequences", "", state, "sequences", state, "seq_index", rows=3)
        col = row.column(align=True)
        col.operator("albam.ean_sequence_add", text="", icon="ADD")
        col.operator("albam.ean_sequence_remove", text="", icon="REMOVE")
        if not len(state.sequences):
            return
        box = layout.box()
        box.prop(state, "default_anim_flag")
        box.prop(state, "default_pat_center")
        grid = box.column(align=True)
        grid.label(text="Grid")
        grid.prop(state, "con_pat_base_point")
        grid.prop(state, "con_pat_col_num")
        grid.prop(state, "con_pat_total_num")
        grid.prop(state, "con_pat_size")
        box.operator("albam.ean_generate_grid", icon="MESH_GRID")
        header = layout.row()
        header.prop(state, "show_frames", icon="TRIA_DOWN" if state.show_frames else "TRIA_RIGHT", emboss=False)
        if state.show_frames:
            row = layout.row()
            row.template_list("ALBAM_UL_EanFrames", "", state, "frames", state, "frame_index", rows=5)
            col = row.column(align=True)
            col.operator("albam.ean_frame_add", text="", icon="ADD")
            col.operator("albam.ean_frame_remove", text="", icon="REMOVE")
