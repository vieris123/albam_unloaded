"""DMC4 .ean (effect flipbook) import / export, edited like UVs (efl/ean.py has the layout).

A flipbook becomes a mesh `EAN_<file>` with one quad face per frame: the face's UVs (layer `Flipbook`) are the frame's
rectangle on the texture sheet, and the material shows the sheet, so in Edit Mode the UV editor draws every frame
over the texture. Move / scale / snap them with the UV tools, Shift+D a face to add a frame, delete faces to remove
frames. Face attributes `ean_seq` (sequence) and `ean_frame` (order in the sequence; a duplicate copies it and lands
after its source) say where each frame goes. The per-sequence settings (default flags, pivot, grid) and the header
live in the `ean_data` custom property (JSON) and are edited in the Image Editor's Albam tab (Flipbook panel), which
also selects a sequence's frames, generates a sequence from its grid and makes a new sequence from selected frames.

UVs are `pixel / ean_uv_size` (the texture's size), V flipped (pixel y grows down, UV v up); export rounds each face's
UV bounds back to whole pixels, so untouched files export byte-identical. Every frame in the game's files has a
positive size, so a frame is just its bounds. SE files keep their stored per-frame UVs while the rect is unchanged.
"""
import json

import bmesh
import bpy

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.vfs import VirtualFileData
from .efl import ean

DATA_KEY = "ean_data"
SIZE_KEY = "ean_uv_size"
UV_LAYER = "Flipbook"
SEQ_ATTR = "ean_seq"
FRAME_ATTR = "ean_frame"
MAX_FRAMES = 4096
PIXEL = 0.001   # 3D size of one texture pixel (the 3D layout mirrors the sheet; only the UVs are exported)
ANIM_FLAG_HELP = ("The sequence's suggested animation flags (same bits as the particle's AnimFlag). The game doesn't "
                  "read them: the particle's AnimFlag decides, so change that one to change playback (the effect tools "
                  "likely copied this value in; most particles match it). 0x1 animate, 0x2 loop, "
                  "0x4 reverse, 0x8 remove the particle at the end (otherwise it holds the last frame), "
                  "0x100 / 0x200 flip U / V, 0x400 / 0x800 flip U / V at random per particle, 0x1000 rotate the "
                  "cell. 0x10 (random reverse) and 0x2000 (no frame blending) are Special Edition names that the "
                  "DX9 game isn't known to read")

_loading = False


# -- data ---------------------------------------------------------------------------------------------

def _seq_settings(s):
    return {"uvs": [list(u) for u in s.uvs], "default_anim_flag": s.default_anim_flag,
            "default_pat_center": list(s.default_pat_center), "con_pat_base_point": list(s.con_pat_base_point),
            "con_pat_col_num": s.con_pat_col_num, "con_pat_total_num": s.con_pat_total_num,
            "con_pat_size": list(s.con_pat_size)}


DEFAULT_SEQUENCE = {"uvs": [], "default_anim_flag": 0, "default_pat_center": [32, 32], "con_pat_base_point": [0, 0],
                    "con_pat_col_num": 1, "con_pat_total_num": 1, "con_pat_size": [64, 64]}


def get_data(ob):
    return json.loads(ob[DATA_KEY]) if ob is not None and DATA_KEY in ob else None


def set_data(ob, d):
    ob[DATA_KEY] = json.dumps(d, separators=(",", ":"))


def uv_size(ob):
    w, h = ob.get(SIZE_KEY, (256, 256))
    return int(w), int(h)


def _pow2(n):
    p = 1
    while p < n:
        p *= 2
    return p


def guess_size(anim, image=None):
    """Pixel size the UVs are expressed in: the texture's, else the SE file's stored UVs', else the frames' extent."""
    if image is not None and image.size[0] and image.size[1]:
        return tuple(image.size)
    size = ean.texture_size(anim)
    if size:
        return size
    right = max([x + w for s in anim.sequences for x, y, w, h in s.patterns] + [1])
    bottom = max([y + h for s in anim.sequences for x, y, w, h in s.patterns] + [1])
    return _pow2(right), _pow2(bottom)


def _rect_uvs(rect, size):
    x, y, w, h = rect
    W, H = size
    u0, u1, v0, v1 = x / W, (x + w) / W, 1.0 - (y + h) / H, 1.0 - y / H
    return [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]   # top-left, top-right, bottom-right, bottom-left


def _add_frame(bm, uv, seq_layer, frame_layer, rect, size, seq_no, frame_no):
    x, y, w, h = rect
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    face = bm.faces.new([bm.verts.new((cx * PIXEL, -cy * PIXEL, 0.0)) for cx, cy in corners])
    for loop, co in zip(face.loops, _rect_uvs(rect, size)):
        loop[uv].uv = co
    face[seq_layer] = seq_no
    face[frame_layer] = frame_no
    return face


def _layers(bm):
    uv = bm.loops.layers.uv.get(UV_LAYER) or bm.loops.layers.uv.new(UV_LAYER)
    seq = bm.faces.layers.int.get(SEQ_ATTR) or bm.faces.layers.int.new(SEQ_ATTR)
    frame = bm.faces.layers.int.get(FRAME_ATTR) or bm.faces.layers.int.new(FRAME_ATTR)
    return uv, seq, frame


def _material(name, image):
    mat = bpy.data.materials.new(f"EAN_{name}")
    mat.use_nodes = True
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    nt.nodes.active = tex   # the UV editor shows the active image texture of the edited faces
    principled = nt.nodes.get("Principled BSDF")
    if principled is not None and image is not None:
        nt.links.new(tex.outputs["Color"], principled.inputs["Base Color"])
    return mat


def create_ean_object(name, anim, data, collection, image=None):
    """Flipbook mesh for a parsed .ean. image: the texture sheet it cuts up (shown in the UV editor)."""
    size = guess_size(anim, image)
    if image is None:   # a stand-in sheet of the right size, so the frames line up in the UV editor
        image = bpy.data.images.get(f"EAN_{name}_grid") or bpy.data.images.new(f"EAN_{name}_grid", size[0], size[1])
        image.generated_type = "UV_GRID"
    mesh = bpy.data.meshes.new(f"EAN_{name}")
    bm = bmesh.new()
    uv, seq_layer, frame_layer = _layers(bm)
    for s_no, s in enumerate(anim.sequences):
        for f_no, rect in enumerate(s.patterns):
            _add_frame(bm, uv, seq_layer, frame_layer, rect, size, s_no, f_no)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(_material(name, image))
    ob = bpy.data.objects.new(f"EAN_{name}", mesh)
    ob.display_type = "WIRE"
    collection.objects.link(ob)
    ob[SIZE_KEY] = list(size)
    set_data(ob, {"version": anim.version, "option_flag": anim.option_flag,
                  "tex_size": list(ean.texture_size(anim) or ()) or None,
                  "sequences": [_seq_settings(s) for s in anim.sequences]})
    ob.albam_asset.original_bytes = data
    ob.albam_asset.extension = "ean"
    return ob


def _faces(ob):
    """[(seq, frame, face index, rect)] from the mesh, read through bmesh so Edit Mode changes count."""
    in_edit = ob.mode == "EDIT"
    bm = bmesh.from_edit_mesh(ob.data) if in_edit else bmesh.new()
    if not in_edit:
        bm.from_mesh(ob.data)
    try:
        uv = bm.loops.layers.uv.get(UV_LAYER)
        seq, frame = bm.faces.layers.int.get(SEQ_ATTR), bm.faces.layers.int.get(FRAME_ATTR)
        if uv is None or seq is None or frame is None:
            raise AlbamCheckFailure("This flipbook mesh lost its frame data",
                                    details=f"it needs the UV map {UV_LAYER!r} and the face attributes "
                                            f"{SEQ_ATTR!r}, {FRAME_ATTR!r}", solution="Re-import the .ean")
        W, H = uv_size(ob)
        bm.faces.index_update()
        out = []
        for face in bm.faces:
            us = [loop[uv].uv[0] for loop in face.loops]
            vs = [loop[uv].uv[1] for loop in face.loops]
            x, y = round(min(us) * W), round((1.0 - max(vs)) * H)
            rect = (x, y, round(max(us) * W) - x, round((1.0 - min(vs)) * H) - y)
            out.append((face[seq], face[frame], face.index, rect))
        return out
    finally:
        if not in_edit:
            bm.free()


def ean_from_object(ob):
    """The flipbook an EAN mesh currently describes (edits included)."""
    d = get_data(ob)
    frames = _faces(ob)
    count = max([len(d["sequences"])] + [s + 1 for s, _f, _i, _r in frames])
    seqs = []
    for s_no in range(count):
        st = d["sequences"][s_no] if s_no < len(d["sequences"]) else DEFAULT_SEQUENCE
        patterns = [rect for _s, _f, _i, rect in sorted(f for f in frames if f[0] == s_no)]
        seqs.append(ean.Sequence(patterns, st["default_anim_flag"], tuple(st["default_pat_center"]),
                                 tuple(st["con_pat_base_point"]), st["con_pat_col_num"], st["con_pat_total_num"],
                                 tuple(st["con_pat_size"]), [tuple(u) for u in st.get("uvs", [])]))
    return ean.EffectAnim(d["version"], seqs, d.get("option_flag", 0))


# -- import / export ----------------------------------------------------------------------------------

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
        if other is not None:   # a rebuild may have just removed it
            other.select_set(False)
    context.view_layer.objects.active = ob
    ob.select_set(True)
    return None   # linked above


def build_ean_bytes(ob):
    if get_data(ob) is None:
        raise AlbamCheckFailure("This object has no flipbook data", solution="Import the .ean again")
    anim = ean_from_object(ob)
    problems = []
    for i, s in enumerate(anim.sequences):
        if len(s.patterns) > 0xFFFF:
            problems.append(f"sequence {i}: too many frames")
        for j, rect in enumerate(s.patterns):
            if not all(-32768 <= v <= 32767 for v in rect):
                problems.append(f"sequence {i} frame {j}: {rect} doesn't fit 16 bits")
            elif rect[2] <= 0 or rect[3] <= 0:
                problems.append(f"sequence {i} frame {j}: zero or negative size {rect[2]} x {rect[3]}")
    if problems:
        raise AlbamCheckFailure("The flipbook can't be written", details="\n".join(problems[:20]),
                                solution="Fix those frames in the UV editor")
    d = get_data(ob)
    size = tuple(d["tex_size"]) if d.get("tex_size") else None
    try:
        return ean.to_bytes(anim, size)
    except ean.EanError as err:
        raise AlbamCheckFailure("The flipbook can't be written", details=str(err),
                                solution="Special Edition .ean files need their texture size to write changed frames")


@blender_registry.register_export_function(app_id="dmc4", extension="ean")
def export_ean(bl_obj):
    data = build_ean_bytes(bl_obj)
    asset = bl_obj.albam_asset
    return [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]


# -- editor state (sequence settings) -----------------------------------------------------------------

def _state(context=None):
    return (context or bpy.context).scene.albam.ean_editor


def _target(context):
    ob = context.active_object
    return ob if ob is not None and DATA_KEY in ob else None


def _write_sequence(state, context):
    if _loading or state.target is None:
        return
    d = get_data(state.target)
    if d is None:
        return
    while len(d["sequences"]) <= state.seq_index:
        d["sequences"].append(json.loads(json.dumps(DEFAULT_SEQUENCE)))
    s = d["sequences"][state.seq_index]
    s["default_anim_flag"] = int(state.default_anim_flag)
    s["default_pat_center"] = list(state.default_pat_center)
    s["con_pat_base_point"] = list(state.con_pat_base_point)
    s["con_pat_col_num"] = int(state.con_pat_col_num)
    s["con_pat_total_num"] = int(state.con_pat_total_num)
    s["con_pat_size"] = list(state.con_pat_size)
    set_data(state.target, d)


def _on_seq_index(state, context):
    if not _loading:
        load_sequence(state)


def load_target(state, ob):
    """Mirror an EAN mesh's sequences into the panel."""
    global _loading
    _loading = True
    try:
        state.target = ob
        state.sequences.clear()
        d = get_data(ob)
        if d is None:
            return
        anim = ean_from_object(ob)
        for i, s in enumerate(anim.sequences):
            item = state.sequences.add()
            item.name = f"Sequence {i}  ({len(s.patterns)} frames)"
        state.seq_index = min(state.seq_index, max(len(anim.sequences) - 1, 0))
    finally:
        _loading = False
    load_sequence(state)


def load_sequence(state):
    global _loading
    _loading = True
    try:
        d = get_data(state.target)
        if d is None:
            return
        s = d["sequences"][state.seq_index] if state.seq_index < len(d["sequences"]) else DEFAULT_SEQUENCE
        state.default_anim_flag = s["default_anim_flag"]
        state.default_pat_center = s["default_pat_center"]
        state.con_pat_base_point = s["con_pat_base_point"]
        state.con_pat_col_num = s["con_pat_col_num"]
        state.con_pat_total_num = s["con_pat_total_num"]
        state.con_pat_size = s["con_pat_size"]
    finally:
        _loading = False


@blender_registry.register_blender_prop
class AlbamEanSequenceItem(bpy.types.PropertyGroup):
    pass


@blender_registry.register_blender_prop_albam(name="ean_editor")
class AlbamEanEditor(bpy.types.PropertyGroup):
    target: bpy.props.PointerProperty(type=bpy.types.Object)
    sequences: bpy.props.CollectionProperty(type=AlbamEanSequenceItem)
    seq_index: bpy.props.IntProperty(update=_on_seq_index,
                                     description="Click a sequence to edit its settings; Select Frames shows its frames")
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


# -- operators ----------------------------------------------------------------------------------------

def _edit_bmesh(ob):
    """(bmesh, done) for the object's mesh in either mode; call done() to write it back."""
    if ob.mode == "EDIT":
        bm = bmesh.from_edit_mesh(ob.data)
        return bm, lambda: bmesh.update_edit_mesh(ob.data)
    bm = bmesh.new()
    bm.from_mesh(ob.data)

    def done():
        bm.to_mesh(ob.data)
        bm.free()
        ob.data.update()
    return bm, done


class _EanOperator:
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _target(context) is not None


@blender_registry.register_blender_type
class ALBAM_OT_EanLoad(_EanOperator, bpy.types.Operator):
    """Show this flipbook's sequences in the panel"""
    bl_idname = "albam.ean_load"
    bl_label = "Edit Flipbook"

    def execute(self, context):
        load_target(_state(context), _target(context))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EanSelectSequence(_EanOperator, bpy.types.Operator):
    """Enter Edit Mode with only the selected sequence's frames selected, so the UV editor shows them over the
    texture. Edit them with the UV tools (G / S, UV > Round to Pixels); Shift+D a frame to add one after it"""
    bl_idname = "albam.ean_select_sequence"
    bl_label = "Select Frames"

    def execute(self, context):
        ob = _target(context)
        state = _state(context)
        if ob.mode != "EDIT":
            bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bm, done = _edit_bmesh(ob)
        seq = bm.faces.layers.int.get(SEQ_ATTR)
        for face in bm.faces:
            face.select_set(seq is not None and face[seq] == state.seq_index)
        bm.select_flush_mode()
        done()
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EanNewSequence(_EanOperator, bpy.types.Operator):
    """Move the selected frames (faces) into a new sequence at the end, keeping their order. Particles pick
    sequences by number (SeqNoMin)"""
    bl_idname = "albam.ean_new_sequence"
    bl_label = "New Sequence from Selected"

    def execute(self, context):
        ob = _target(context)
        state = _state(context)
        anim = ean_from_object(ob)
        bm, done = _edit_bmesh(ob)
        uv, seq, frame = _layers(bm)
        chosen = sorted((f for f in bm.faces if f.select), key=lambda f: (f[seq], f[frame], f.index))
        if not chosen:
            done()
            self.report({"WARNING"}, "Select the frames (faces) for the new sequence first")
            return {"CANCELLED"}
        new_no = len(anim.sequences)
        for i, face in enumerate(chosen):
            face[seq], face[frame] = new_no, i
        done()
        d = get_data(ob)
        src = d["sequences"][state.seq_index] if state.seq_index < len(d["sequences"]) else DEFAULT_SEQUENCE
        while len(d["sequences"]) < new_no:
            d["sequences"].append(json.loads(json.dumps(DEFAULT_SEQUENCE)))
        d["sequences"].append(dict(json.loads(json.dumps(src)), uvs=[]))
        set_data(ob, d)
        state.seq_index = new_no
        load_target(state, ob)
        self.report({"INFO"}, f"Sequence {new_no}: {len(chosen)} frames")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EanGenerateGrid(_EanOperator, bpy.types.Operator):
    """Replace the selected sequence's frames with its grid: Cells frames of Cell Size, Columns per row, starting at
    Grid Start, read row by row. The pivot is set to the cell centre"""
    bl_idname = "albam.ean_generate_grid"
    bl_label = "Generate Grid"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        ob = _target(context)
        state = _state(context)
        _write_sequence(state, context)
        d = get_data(ob)
        while len(d["sequences"]) <= state.seq_index:
            d["sequences"].append(json.loads(json.dumps(DEFAULT_SEQUENCE)))
        s = d["sequences"][state.seq_index]
        total, cols = int(s["con_pat_total_num"]), max(int(s["con_pat_col_num"]), 1)
        if total > MAX_FRAMES:
            self.report({"ERROR"}, f"At most {MAX_FRAMES} frames")
            return {"CANCELLED"}
        (bx, by), (w, h) = s["con_pat_base_point"], s["con_pat_size"]
        bm, done = _edit_bmesh(ob)
        uv, seq, frame = _layers(bm)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f[seq] == state.seq_index], context="FACES")
        size = uv_size(ob)
        for j in range(total):
            _add_frame(bm, uv, seq, frame, (bx + (j % cols) * w, by + (j // cols) * h, w, h), size,
                       state.seq_index, j)
        done()
        s["uvs"] = []
        s["default_pat_center"] = [w // 2, h // 2]
        set_data(ob, d)
        load_target(state, ob)
        self.report({"INFO"}, f"{total} frames generated")
        return {"FINISHED"}


# -- panel (Image Editor > Albam tab, next to the texture's own settings) -----------------------------

@blender_registry.register_blender_type
class ALBAM_UL_EanSequences(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon="RENDERLAYERS")


@blender_registry.register_blender_type
class ALBAM_PT_EanFlipbook(bpy.types.Panel):
    bl_label = "Flipbook"
    bl_idname = "ALBAM_PT_EanFlipbook"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Albam"

    @classmethod
    def poll(cls, context):
        return _target(context) is not None

    def draw(self, context):
        layout = self.layout
        state = _state(context)
        ob = _target(context)
        layout.label(text=ob.albam_asset.relative_path or ob.name, icon="IMAGE_DATA")
        w, h = uv_size(ob)
        layout.label(text=f"Frames are UVs over a {w} x {h} sheet")
        if state.target != ob:
            layout.operator("albam.ean_load", icon="GREASEPENCIL")
            return
        layout.template_list("ALBAM_UL_EanSequences", "", state, "sequences", state, "seq_index", rows=3)
        row = layout.row(align=True)
        row.operator("albam.ean_select_sequence", icon="RESTRICT_SELECT_OFF")
        row.operator("albam.ean_new_sequence", icon="ADD")
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


# -- new flipbooks ------------------------------------------------------------------------------------

PATH_MAX = 63   # str64 field, NUL-terminated


def _clean_path(path):
    path = path.strip().replace("/", "\\")
    return path[:-4] if path.lower().endswith(".ean") else path


def new_flipbook(name, image, cols, cells, cell_size):
    """A DX9 flipbook with one sequence cut from a grid over image."""
    w, h = cell_size
    patterns = [((j % cols) * w, (j // cols) * h, w, h) for j in range(cells)]
    seq = ean.Sequence(patterns, 0, (w // 2, h // 2), (0, 0), cols, cells, (w, h))
    return ean.EffectAnim(ean.VERSION_DX9, [seq])


class _NewFlipbookProps:
    path: bpy.props.StringProperty(
        name="Game Path", maxlen=PATH_MAX,
        description="Where the flipbook goes in the game files, without the extension, e.g. "
                    "effect\\ean\\com\\my_sheet. Export writes it there; Patch adds it to the .arc")
    columns: bpy.props.IntProperty(name="Columns", default=4, min=1, max=256,
                                   description="Frames per row of the grid cut from the texture")
    cells: bpy.props.IntProperty(name="Frames", default=16, min=1, max=MAX_FRAMES,
                                 description="Number of frames, read row by row")
    cell_size: bpy.props.IntVectorProperty(name="Frame Size", size=2, default=(64, 64), min=1, max=0x7FFF,
                                           description="Width and height of one frame in pixels")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "path")
        layout.prop(self, "columns")
        layout.prop(self, "cells")
        layout.prop(self, "cell_size")

    def fit(self, image):
        if image is not None and image.size[0] and image.size[1]:   # Columns x Columns cells over the texture
            self.cell_size = (max(image.size[0] // self.columns, 1), max(image.size[1] // self.columns, 1))


@blender_registry.register_blender_type
class ALBAM_OT_EanNew(_NewFlipbookProps, bpy.types.Operator):
    """Make a new .ean flipbook for the active effect record's particle and point the particle at it (AnimPath): a
    grid of frames cut from the particle's texture, which you can then reshape in the UV editor. The effect rebuilds
    so the preview uses it; exporting the effect writes the new file. The particle's AnimFlag / PatSpeed decide how
    it plays"""
    bl_idname = "albam.ean_new"
    bl_label = "New Flipbook"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        from .effect_export import record_object
        record = record_object(context.active_object)
        return record is not None and "AnimPath" in (record.get("efl_ptcl") or {})

    def _image(self, record):
        """The particle's texture, as loaded by the effect import (None for untextured PrimModels)."""
        ptcl = record["efl_ptcl"]
        base = ptcl.get("BaseMapPath", "")
        if int(ptcl.get("type", -1)) == 6 and int(ptcl.get("PrimModelType", 1)) in (0, 2, 4):
            base = ""   # untextured PrimModels (effect._base_map)
        return next((im for im in bpy.data.images if base and im.get("efl_texture") == base), None)

    def invoke(self, context, event):
        from .effect_export import effect_root, record_object
        record = record_object(context.active_object)
        root = effect_root(record)
        number = int(record["efl_record"])
        self.path = "effect\\ean\\com\\" + f"{root.get('efl_stem', 'effect')}_{number if number >= 0 else 'new'}"
        self.fit(self._image(record))
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        from .effect import linked_objects
        from .effect_export import _report_failure, apply_to_scene, effect_root, record_object
        record = record_object(context.active_object)
        root = effect_root(record)
        path = _clean_path(self.path)
        if not path or len(path.encode("latin-1", "replace")) > PATH_MAX:
            self.report({"ERROR"}, f"Give a game path of 1 to {PATH_MAX} characters")
            return {"CANCELLED"}
        if f"ean:{path}" in linked_objects(root):
            self.report({"ERROR"}, f"This effect already has a flipbook at {path}")
            return {"CANCELLED"}
        image = self._image(record)
        anim = new_flipbook(path, image, self.columns, self.cells, tuple(self.cell_size))
        collection = root.users_collection[0] if root.users_collection else context.scene.collection
        ob = create_ean_object(path.rsplit("\\", 1)[-1], anim, b"", collection, image)
        ob.albam_asset.app_id = root.albam_asset.app_id
        ob.albam_asset.relative_path = path + ".ean"
        ob.parent = root
        ob["efl_root"] = root
        ob["efl_linked"] = f"ean:{path}"
        record["efl_ptcl"]["AnimPath"] = path
        try:
            apply_to_scene(context, root)
        except Exception as err:
            return _report_failure(self, err)
        self.report({"INFO"}, f"New flipbook {path}.ean ({self.cells} frames); edit it from Linked files")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EanNewForImage(_NewFlipbookProps, bpy.types.Operator):
    """Make a new .ean flipbook for the image shown here: a grid of frames over it, as a mesh whose faces' UVs are the
    frames (edit them in the UV editor). It's added to the Export list"""
    bl_idname = "albam.ean_new_for_image"
    bl_label = "New Flipbook for this Image"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "image", None) is not None

    def invoke(self, context, event):
        image = context.space_data.image
        stem = image.get("efl_texture", image.name).rsplit("\\", 1)[-1].replace("_BM", "")
        self.path = "effect\\ean\\com\\" + stem
        self.fit(image)
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        path = _clean_path(self.path)
        if not path or len(path.encode("latin-1", "replace")) > PATH_MAX:
            self.report({"ERROR"}, f"Give a game path of 1 to {PATH_MAX} characters")
            return {"CANCELLED"}
        image = context.space_data.image
        anim = new_flipbook(path, image, self.columns, self.cells, tuple(self.cell_size))
        ob = create_ean_object(path.rsplit("\\", 1)[-1], anim, b"", context.collection or context.scene.collection,
                               image)
        ob.albam_asset.app_id = "dmc4"
        ob.albam_asset.relative_path = path + ".ean"
        context.scene.albam.exportable.file_list.add().bl_object = ob
        for other in context.view_layer.objects:
            if other is not None:   # a rebuild may have just removed it
                other.select_set(False)
        context.view_layer.objects.active = ob
        ob.select_set(True)
        load_target(_state(context), ob)
        self.report({"INFO"}, f"New flipbook {path}.ean ({self.cells} frames)")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_PT_EanNew(bpy.types.Panel):
    bl_label = "New Flipbook"
    bl_idname = "ALBAM_PT_EanNew"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Albam"

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "image", None) is not None and _target(context) is None

    def draw(self, context):
        self.layout.operator("albam.ean_new_for_image", icon="ADD")
