"""Edit an imported scheduler (.sdl) or placement (.pla) as XML, in Blender's Text Editor: the way to do what the
object layout can't (add a unit or a property track, change a class), with dmc4_xml's XML format (the vendored
dmc4xml.xmlconv; class names in `dti` are hashed by it, so new ones work).

- Edit as XML (`albam.xml_edit`): the file as it is now (edits included: it goes through the exporter) becomes a
  Text block `<root>.xml`, shown in a Text Editor (one already open in any window, else a new window).
- Apply XML (`albam.xml_apply`, in the Object panel and the Text Editor's Albam tab): XML -> file bytes (read back
  to check them) -> the file's Empties are rebuilt in place, in the same collection, with the root's transform.
  Objects parented to one of the Empties from outside (e.g. a collision root riding a moving-floor unit) and
  constraints targeting them are re-attached by the Empty's path (names from the root down); what can't be found is
  reported. The rebuilt file is the new source (Revert is Undo).
"""
import xml.etree.ElementTree as ET

import bpy

from dmc4xml import xmlconv
from dmc4xml import pla as pla_codec, sdl as sdl_codec

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from . import placement, scheduler

KINDS = {
    "pla": (placement.ROOT_PROP, placement.TRACK_PROP, placement.build_pla, pla_codec, placement.build_pla_objects,
            "PLA_"),
    "sdl": (scheduler.ROOT_PROP, scheduler.TRACK_PROP, scheduler.build_sdl, sdl_codec, scheduler.build_sdl_objects,
            "SDL_"),
}
TEXT_ROOT = "albam_xml_root"        # Text block: name of the root Empty it edits


def xml_root_of(ob):
    """the SDL_ / PLA_ root Empty ob is or belongs to, or None"""
    while ob is not None:
        ext = ob.albam_asset.extension
        if ext in KINDS and KINDS[ext][0] in ob:
            return ob
        ob = ob.parent
    return None


def current_bytes(root):
    """the file as it would be exported now"""
    _, _, build, codec, _, _ = KINDS[root.albam_asset.extension]
    data, _notes = build(root)
    return codec.write(data)


def to_text(root):
    tree = xmlconv.to_xml(current_bytes(root))
    ET.indent(tree, space="  ")
    return ET.tostring(tree.getroot(), encoding="unicode") + "\n"


def from_text(root, text):
    """XML text -> file bytes for root's format, checked by reading them back"""
    ext = root.albam_asset.extension
    try:
        element = ET.fromstring(text)
    except ET.ParseError as err:
        line = err.position[0]
        lines = text.splitlines()
        shown = lines[line - 1].strip() if 0 < line <= len(lines) else ""
        raise AlbamCheckFailure("The XML can't be read", details=f"{err}\n{shown}",
                                solution="Fix the XML at that line (tags must close, attribute values need quotes).")
    # xmlconv skips elements it doesn't know: a mistyped track tag would silently drop the track
    known = set(xmlconv.RV_PLA_TAGS if ext == "pla" else xmlconv.RV_SDL_TAGS)
    unknown = sorted({f"<{e.tag} name=\"{e.get('name', '')}\">" for e in element.iter()
                      if e.tag.endswith("_track") and e.tag not in known})
    if unknown:
        raise AlbamCheckFailure("The XML has track types this format doesn't have", details="\n".join(unknown),
                                solution=f"Use one of: {', '.join(sorted(known - {'root_track'}))}.")
    try:
        data = xmlconv.from_xml(element, ext)
        KINDS[ext][3].read(data)
    except Exception as err:        # noqa: BLE001 - xmlconv / codec errors, bad numbers, unknown types
        raise AlbamCheckFailure("The XML doesn't make a valid file", details=f"{type(err).__name__}: {err}",
                                solution="Check the track you changed: tag name (e.g. unit_track, float_track), "
                                         "type-specific attributes (value, frame), and number formats.")
    return data


def _path(ob, root):
    """names from the root down to ob (root excluded)"""
    names = []
    while ob is not None and ob != root:
        names.append(ob.name)
        ob = ob.parent
    return tuple(reversed(names)) if ob == root else None


def _find(root, path):
    ob = root
    for name in path:
        ob = next((c for c in ob.children if c.name == name), None)
        if ob is None:
            return None
    return ob


def rebuild(context, root, data):
    """Replace root's objects with ones built from data (same collection, name, transform, parent). Returns (new
    root, problems)."""
    ext = root.albam_asset.extension
    root_prop, track_prop, _, _, build_objects, prefix = KINDS[ext]
    tree = [root] + [o for o in root.children_recursive if track_prop in o]
    tree_set = set(tree)
    paths = {o: _path(o, root) for o in tree}

    # what's attached from outside: children of the Empties and constraints targeting them
    outside = []
    for ob in root.children_recursive:
        if ob not in tree_set and ob.parent in tree_set:
            outside.append((ob, paths[ob.parent], ob.parent_type, ob.parent_bone, ob.matrix_parent_inverse.copy(),
                            ob.matrix_basis.copy()))
    targets = []
    for ob in bpy.data.objects:
        if ob in tree_set:
            continue
        for con in getattr(ob, "constraints", []):
            if getattr(con, "target", None) in tree_set:
                targets.append((ob, con.name, paths[con.target]))
    asset = root.albam_asset
    keep = {"app_id": asset.app_id, "relative_path": asset.relative_path, "extension": asset.extension}
    stem = root.name[len(prefix):] if root.name.startswith(prefix) else root.name
    name = root.name
    parent, parent_type, parent_bone = root.parent, root.parent_type, root.parent_bone
    parent_inverse, basis = root.matrix_parent_inverse.copy(), root.matrix_basis.copy()
    collection = root.users_collection[0] if root.users_collection else None

    exportable = context.scene.albam.exportable.file_list
    for i in reversed(range(len(exportable))):
        if exportable[i].bl_object == root:
            exportable.remove(i)
    for ob, *_ in outside:
        world = ob.matrix_world.copy()
        ob.parent = None
        ob.matrix_world = world
    for ob in tree:
        bpy.data.objects.remove(ob)

    class _Asset:
        app_id, relative_path, extension = keep["app_id"], keep["relative_path"], keep["extension"]
    new_root = build_objects(data, stem, _Asset, context, collection)
    new_root.name = name
    new_root.parent, new_root.parent_type = parent, parent_type
    if parent is not None and parent_type == "BONE":
        new_root.parent_bone = parent_bone
    new_root.matrix_parent_inverse = parent_inverse
    new_root.matrix_basis = basis

    problems = []
    for ob, path, ptype, pbone, pinv, pbasis in outside:
        target = _find(new_root, path)
        if target is None:
            problems.append(f"{ob.name} was on {'/'.join(path)}, which is gone: left in place, unparented")
            continue
        ob.parent, ob.parent_type = target, ptype
        if ptype == "BONE":
            ob.parent_bone = pbone
        ob.matrix_parent_inverse = pinv
        ob.matrix_basis = pbasis
    for ob, con_name, path in targets:
        target = _find(new_root, path)
        con = ob.constraints.get(con_name)
        if con is None:
            continue
        if target is None:
            problems.append(f"{ob.name}: constraint {con_name} targeted {'/'.join(path)}, which is gone")
        else:
            con.target = target
    return new_root, problems


def _text_for(root):
    return bpy.data.texts.get(f"{root.name}.xml")


def _show_text(context, text):
    """Show text in a Text Editor: one already on screen, else a new window turned into one (sidebar open on the
    Albam tab, where Apply XML is). False if there's no window (background mode)."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "TEXT_EDITOR":
                area.spaces.active.text = text
                return True
    if context.window is None:
        return False
    before = set(context.window_manager.windows)
    try:
        bpy.ops.wm.window_new()
    except RuntimeError:
        return False
    new = [w for w in context.window_manager.windows if w not in before]
    if not new:
        return False
    area = max(new[0].screen.areas, key=lambda a: a.width * a.height)
    area.ui_type = "TEXT_EDITOR"
    space = area.spaces.active
    space.text = text
    space.show_line_numbers = True
    space.show_syntax_highlight = True
    space.show_region_ui = True
    return True


@blender_registry.register_blender_type
class ALBAM_OT_XmlEdit(bpy.types.Operator):
    """Write this scheduler / placement (with your edits) as XML into a Text block, to add units or property tracks
    or change anything the objects can't. Edit it in the Text Editor, then Apply XML"""
    bl_idname = "albam.xml_edit"
    bl_label = "Edit as XML"

    @classmethod
    def poll(cls, context):
        return xml_root_of(context.object) is not None

    def execute(self, context):
        root = xml_root_of(context.object)
        try:
            content = to_text(root)
        except Exception:                   # noqa: BLE001 - shown in the popup
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
            return {"CANCELLED"}
        text = _text_for(root) or bpy.data.texts.new(f"{root.name}.xml")
        text.clear()
        text.write(content)
        text[TEXT_ROOT] = root.name
        text.cursor_set(0)
        if _show_text(context, text):
            self.report({"INFO"}, f"{text.name} is open in the Text Editor: edit it, then Apply XML (sidebar, "
                                  "Albam tab)")
        else:
            self.report({"INFO"}, f"Open {text.name} in a Text Editor to edit it, then Apply XML")
        return {"FINISHED"}


def _apply_target(context):
    """(root, text) for Apply XML: the Text Editor's text, or the selected object's root and its text"""
    space = getattr(context, "space_data", None)
    text = getattr(space, "text", None) if space is not None and space.type == "TEXT_EDITOR" else None
    if text is not None and TEXT_ROOT in text:
        root = bpy.data.objects.get(text[TEXT_ROOT])
        return (root, text) if root is not None and xml_root_of(root) == root else (None, text)
    root = xml_root_of(getattr(context, "object", None))
    return (root, _text_for(root)) if root is not None else (None, None)


@blender_registry.register_blender_type
class ALBAM_OT_XmlApply(bpy.types.Operator):
    """Rebuild the scheduler / placement from its edited XML: the file's objects are replaced (same collection and
    transform; objects you parented to them are re-attached). Undo goes back"""
    bl_idname = "albam.xml_apply"
    bl_label = "Apply XML"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        root, text = _apply_target(context)
        return root is not None and text is not None

    def execute(self, context):
        root, text = _apply_target(context)
        try:
            data = from_text(root, text.as_string())
            new_root, problems = rebuild(context, root, data)
        except Exception:                   # noqa: BLE001 - shown in the popup
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
            return {"CANCELLED"}
        text[TEXT_ROOT] = new_root.name
        for p in problems:
            print(f"XML apply {new_root.name}: {p}")
        if problems:
            self.report({"WARNING"}, f"Rebuilt {new_root.name}; {len(problems)} attachment(s) lost (see console)")
        else:
            self.report({"INFO"}, f"Rebuilt {new_root.name} from {text.name}")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_PT_XmlEditObject(bpy.types.Panel):
    bl_label = "Scheduler / Placement XML"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return xml_root_of(context.object) is not None

    def draw(self, context):
        root = xml_root_of(context.object)
        layout = self.layout
        if root != context.object:
            layout.label(text=f"File: {root.name}", icon="OBJECT_DATA")
        row = layout.row()
        row.operator("albam.xml_edit", icon="TEXT")
        row.operator("albam.xml_apply", icon="FILE_REFRESH")
        text = _text_for(root)
        layout.label(text=f"Text: {text.name}" if text else "No XML yet: Edit as XML makes one",
                     icon="INFO")


@blender_registry.register_blender_type
class ALBAM_PT_XmlEditText(bpy.types.Panel):
    bl_label = "Albam XML"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "Albam"

    @classmethod
    def poll(cls, context):
        text = getattr(context.space_data, "text", None)
        return text is not None and TEXT_ROOT in text

    def draw(self, context):
        root, text = _apply_target(context)
        layout = self.layout
        if root is None:
            layout.label(text=f"{text[TEXT_ROOT]} isn't in this file any more", icon="ERROR")
            return
        layout.label(text=f"Edits {root.name}", icon="OBJECT_DATA")
        layout.operator("albam.xml_apply", icon="FILE_REFRESH")
        layout.label(text="Tags: unit_track, float_track, vector_track ...", icon="INFO")
