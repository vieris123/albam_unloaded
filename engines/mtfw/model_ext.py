"""ModelExtension lists in Blender (the format is in movedef/ext_list.py, dmc4_hook owns it).

A list is an Empty `EXT_<file>` with its text and elements in `albam_ext`, in the Export list at its game path
(`model_ext\\<file>.xml`), so Save to Game Folder delivers it. Elements are edited in Object Properties > Model Extension
List; an untouched list exports byte-identical. **Fill from Scene** lists the scene's chains and followed models.

**Preview Attachments** does what the runner's attachments do in the game, with named constraints that are never
exported: skin = Copy Transforms `ALBAM_FollowBody` from the owner's bone of the same joint number, on every shared bone
no chain holds (ModelAttach.cpp move_after: a chain keeps its joint); rigid = Child Of `ALBAM_Attach` on the model's
root, on the owner's joint.
"""
import math

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.vfs import VirtualFileData
from albam.engines.mtfw import joints
from albam.engines.mtfw.cns_chain import ARMATURE_PROP
from albam.engines.mtfw.movedef import doc as doc_module, ext_list

FOLLOW = "ALBAM_FollowBody"
ATTACH = "ALBAM_Attach"
EXTENSION = "xml"
FOLDER = "model_ext"
GAME_TO_BLENDER = Matrix.Rotation(math.pi / 2, 4, "X")      # model space: (x, y, z) -> (x, -z, y)


def _on_value(self, context):
    root = self.id_data
    if root.albam_ext.preview:
        apply_preview(root, context)


def _on_preview(self, context):
    if self.preview:
        apply_preview(self.id_data, context)
    else:
        clear_preview(self.id_data, context)


@blender_registry.register_blender_prop
class AlbamExtAttr(bpy.types.PropertyGroup):
    value: bpy.props.StringProperty(name="Value", description="The value in the file: its name's tooltip says what it "
                                                              "does", update=_on_value)


@blender_registry.register_blender_prop
class AlbamExtElem(bpy.types.PropertyGroup):
    tag: bpy.props.StringProperty()
    uid: bpy.props.IntProperty()
    parent: bpy.props.IntProperty(default=-1)
    src: bpy.props.IntProperty(default=-1)
    attrs: bpy.props.CollectionProperty(type=AlbamExtAttr)


@blender_registry.register_blender_props_to_type("Object", "albam_ext")
class AlbamExtList(bpy.types.PropertyGroup):
    source: bpy.props.StringProperty()
    elems: bpy.props.CollectionProperty(type=AlbamExtElem)
    preview: bpy.props.BoolProperty(
        name="Preview Attachments", default=False, update=_on_preview,
        description="Make this list's attachments follow their owners in the viewport, as they do in the game. "
                    "Preview only: the constraints are named ALBAM_ and never exported")


def is_list(ob):
    return ob is not None and ob.type == "EMPTY" and ob.albam_asset.extension == EXTENSION and \
        ob.albam_ext.source != ""


def list_doc(root):
    ext = root.albam_ext
    return doc_module.Doc(ext.source, [doc_module.Elem(e.uid, e.tag, e.tag, e.parent, e.src,
                                                       [(a.name, a.value) for a in e.attrs]) for e in ext.elems])


def store(root, d):
    ext = root.albam_ext
    ext.source = d.source
    ext.elems.clear()
    for e in d.elems:
        item = ext.elems.add()
        item.tag, item.uid, item.parent, item.src = e.tag, e.uid, e.parent, e.src
        for name, value in e.attrs:
            a = item.attrs.add()
            a.name, a.value = name, value


def _stem(path):
    return ext_list.normalize(ext_list.stem(path))


def scene_lists(context):
    return [o for o in context.scene.objects if is_list(o)]


def file_name(root):
    return root.albam_asset.relative_path.replace("/", "\\").rsplit("\\", 1)[-1]


def model_object(ob):
    """The .mod root `ob` belongs to, or None"""
    while ob is not None:
        if ob.albam_asset.extension == "mod":
            return ob
        ob = ob.parent
    return None


def models(context):
    """{normalized path: .mod root}, the first of a path, as the scene has them"""
    out = {}
    for ob in context.scene.objects:
        if ob.albam_asset.extension == "mod" and ob.albam_asset.relative_path:
            out.setdefault(_stem(ob.albam_asset.relative_path), ob)
    return out


def armature_of(root):
    """The armature of a .mod root, which may be an Empty holding it"""
    if root is None or root.type == "ARMATURE":
        return root
    return next((c for c in root.children if c.type == "ARMATURE"), None)


def chains(context):
    return [o for o in context.scene.objects if o.type == "EMPTY" and o.albam_asset.extension in ("phs", "clt")]


def chain_held(context, arm):
    """Joint numbers `arm`'s chains hold: the game gives them to the chain, not the skin attachment"""
    held = set()
    for ob in chains(context):
        if ob.parent == arm:
            held.update(j for j in ob.get("phs_joints", ()) if j >= 0)
    return held


def scene_issues(context, lists):
    """Warnings only the scene can give: chains that would save under a name the runner can't load, and joints"""
    out = []
    found = models(context)
    chain_paths = {_stem(o.albam_asset.relative_path): o for o in chains(context)}
    for root in lists:
        d, name = list_doc(root), file_name(root)
        for e in d.elems:
            if e.tag == "chain":
                ob = chain_paths.get(_stem(e.get("clt", "")))
                if ob is not None and ob.albam_asset.extension != "clt":
                    out.append(("warning", name, f"{ob.name} saves as .phs: the runner loads {e.get('clt')}.clt, "
                                                 "so rename it on disk"))
            elif e.tag == "attach" and ext_list.effective_mode(e) == "skin":
                arm, owner = (armature_of(found.get(_stem(e.get(k, "")))) for k in ("path", "to"))
                if arm is None or owner is None:
                    continue
                theirs = {joints.joint_of(b): b for b in joints.joint_bones(owner)}
                for bone in joints.joint_bones(arm):
                    other = theirs.get(joints.joint_of(bone))
                    if other is not None and (other.head_local - bone.head_local).length > 1e-3:
                        out.append(("warning", name, f"{arm.name}: shared bone {bone.name} isn't at {owner.name}'s rest "
                                                     "pose, so its skin would jump"))
                        break
    return out


def all_issues(context, root=None):
    lists = scene_lists(context)
    if root is not None and root not in lists:
        lists.append(root)
    return ext_list.issues([(file_name(r), list_doc(r)) for r in lists]) + scene_issues(context, lists)


# ---- files -----------------------------------------------------------------------------------------------------------

def new_root(context, relative_path, text, data, app_id="dmc4"):
    name = file_name_of(relative_path)
    root = bpy.data.objects.new(f"EXT_{name}", None)
    root.empty_display_type = "CUBE"
    root.empty_display_size = 0.05
    context.collection.objects.link(root)
    asset = root.albam_asset
    asset.original_bytes = data
    asset.app_id, asset.relative_path, asset.extension = app_id, relative_path, EXTENSION
    store(root, ext_list.parse(text))
    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = root
    context.scene.albam.exportable.file_list.update()
    return root


def file_name_of(relative_path):
    return ext_list.stem(relative_path.replace("/", "\\").rsplit("\\", 1)[-1])


@blender_registry.register_import_function(app_id="dmc4", extension=EXTENSION, file_category="MODEL_EXT")
def load_ext(file_item, context):
    data = bytes(file_item.get_bytes())
    try:
        new_root(context, file_item.relative_path, data.decode("utf-8-sig"), data, file_item.app_id)
    except (UnicodeDecodeError, doc_module.MoveDefError) as err:
        raise AlbamCheckFailure("This isn't a ModelExtension list", details=str(err),
                                solution="Only nativePC\\model_ext lists (an <extensions> root) import here. Move "
                                         "files go through the Moves panel in the Dope Sheet.")
    return None         # it's an Empty in the active collection, nothing to link


@blender_registry.register_export_function(app_id="dmc4", extension=EXTENSION)
def export_ext(bl_obj):
    asset = bl_obj.albam_asset
    d = list_doc(bl_obj)
    errors = [f"{name}: {message}" for level, name, message in ext_list.issues([(file_name(bl_obj), d)])
              if level == "error"]
    if errors:
        raise AlbamCheckFailure(f"{file_name(bl_obj)} can't be exported", details="\n".join(errors),
                                solution="Fix these in Object Properties > Model Extension List.")
    text = d.text()
    data = bytes(asset.original_bytes)
    if not data or data.decode("utf-8-sig") != text:
        data = text.encode("utf-8")
    return [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]


# ---- from the scene --------------------------------------------------------------------------------------------------

def add_element(d, tag, parent, attrs):
    same = d.children(parent, tag)
    return d.add(tag, parent, attrs, after=same[-1] if same else None)


def _collision_root(chain):
    """The .mod root carrying a chain's shapes, or None"""
    col = chain.albam_phs.collision_shapes
    return model_object(col.get(ARMATURE_PROP) or col.parent) if col is not None else None


def fill_from_scene(context, root):
    """Lists every chain of the scene and every model following another (ALBAM_FollowBody), skipping what the list
    has, models that carry another's collision shapes first (a chain finds its collision model when it spawns). Returns
    how many entries were added."""
    d = list_doc(root)
    known = {_stem(ob.albam_asset.relative_path): ob for ob in models(context).values()}
    carriers = set()
    for chain in chains(context):
        target = _collision_root(chain)
        if target is not None and target != model_object(chain.parent):
            carriers.add(_stem(target.albam_asset.relative_path))
    added = 0
    for path, ob in sorted(known.items(), key=lambda item: item[0] not in carriers):
        arm = armature_of(ob)
        if arm is None or any(_stem(a.get("path", "")) == path for a in d.children(d.root, "attach")):
            continue
        cons = (c for p in arm.pose.bones for c in p.constraints if c.name == FOLLOW and c.target is not None)
        con = next(cons, None)
        owner = model_object(con.target) if con is not None else None
        if owner is not None:
            add_element(d, "attach", d.root, [("path", ext_list.stem(ob.albam_asset.relative_path)),
                                              ("to", ext_list.stem(owner.albam_asset.relative_path))])
            added += 1
    for ob in chains(context):
        model = model_object(ob.parent)
        clt = ext_list.stem(ob.albam_asset.relative_path)
        if model is None or any(_stem(c.get("clt", "")) == _stem(clt) for c in d.elems if c.tag == "chain"):
            continue
        path = ext_list.stem(model.albam_asset.relative_path)
        parent = next((m for m in d.children(d.root, "model") if _stem(m.get("path", "")) == _stem(path)), None)
        if parent is None:
            parent = add_element(d, "model", d.root, [("path", path)])
        attrs = [("clt", clt)]
        col = ob.albam_phs.collision_shapes
        if col is not None:
            attrs.append(("col", ext_list.stem(col.albam_asset.relative_path)))
            target = _collision_root(ob)
            if target is not None:
                collision = ext_list.stem(target.albam_asset.relative_path)
                if not parent.has("collision_model"):
                    parent.set("collision_model", collision)
                elif _stem(parent.get("collision_model")) != _stem(collision):
                    attrs.append(("collision_model", collision))
        add_element(d, "chain", parent, attrs)
        added += 1
    store(root, d)
    return added


# ---- preview ---------------------------------------------------------------------------------------------------------

def rigid_matrix(attach):
    """T R S of a rigid attachment in Blender units; the rotation is the runner's euler_quat (q = qz qy qx: x first)"""
    pos, rot, scale = ext_list.rigid_offset(attach)
    q = Euler([math.radians(a) for a in rot], "XYZ").to_quaternion()
    return Matrix.Translation(Vector(pos) * 0.01) @ Quaternion(q).to_matrix().to_4x4() @ \
        Matrix.Diagonal((*scale, 1.0))


def _remove_constraints(context, attached):
    arm = armature_of(attached)
    if arm is not None:
        for pose in arm.pose.bones:
            for con in [c for c in pose.constraints if c.name == FOLLOW]:
                pose.constraints.remove(con)
    for con in [c for c in attached.constraints if c.name == ATTACH]:
        attached.constraints.remove(con)


def _attach(context, attach, found):
    attached, owner = (found.get(_stem(attach.get(k, ""))) for k in ("path", "to"))
    if attached is None or owner is None:
        return
    arm, owner_arm = armature_of(attached), armature_of(owner)
    _remove_constraints(context, attached)
    if ext_list.effective_mode(attach) == "skin":
        if arm is None or owner_arm is None:
            return
        theirs = {joints.joint_of(b): b.name for b in joints.joint_bones(owner_arm)}
        held = chain_held(context, arm)
        for bone in joints.joint_bones(arm):
            number = joints.joint_of(bone)
            if number is not None and number in theirs and number not in held:
                con = arm.pose.bones[bone.name].constraints.new("COPY_TRANSFORMS")
                con.name = FOLLOW
                con.target, con.subtarget = owner_arm, theirs[number]
        return
    con = attached.constraints.new("CHILD_OF")
    con.name = ATTACH
    con.target = owner_arm or owner
    offset = rigid_matrix(attach)
    joint = attach.get("joint", "-1")
    wanted = int(joint) if joint.lstrip("-").isdigit() else -1
    bone = next((b for b in joints.joint_bones(owner_arm) if joints.joint_of(b) == wanted), None) if owner_arm else None
    if bone is None:        # -1 or a joint it lacks: the owner's root, model space
        con.inverse_matrix = GAME_TO_BLENDER @ offset @ GAME_TO_BLENDER.inverted()
        return
    con.subtarget = bone.name
    con.inverse_matrix = offset @ GAME_TO_BLENDER.inverted()      # the bone's frame is the game joint's


def apply_preview(root, context):
    d = list_doc(root)
    found = models(context)
    for attach in d.children(d.root, "attach"):
        _attach(context, attach, found)


def clear_preview(root, context):
    d = list_doc(root)
    found = models(context)
    for attach in d.children(d.root, "attach"):
        attached = found.get(_stem(attach.get("path", "")))
        if attached is not None:
            _remove_constraints(context, attached)


# ---- operators -------------------------------------------------------------------------------------------------------

def next_path(context):
    used = {ob.albam_asset.relative_path.lower() for ob in context.scene.objects}
    name, n = "list", 1
    while f"{FOLDER}\\{name}.xml" in used:
        n += 1
        name = f"list{n}"
    return f"{FOLDER}\\{name}.xml"


@blender_registry.register_blender_type
class ALBAM_OT_ExtNew(bpy.types.Operator):
    """Make a new ModelExtension list, added to the Export list so Save to Game Folder delivers it"""
    bl_idname = "albam.ext_new"
    bl_label = "New Extension List"
    bl_options = {"REGISTER", "UNDO"}

    path: bpy.props.StringProperty(name="Game Path", description="Where it goes under nativePC. The game reads every "
                                                                 ".xml in model_ext, in name order")
    fill: bpy.props.BoolProperty(name="Fill from Scene", default=True,
                                 description="List the scene's chains and followed models right away")

    def invoke(self, context, event):
        self.path = next_path(context)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        path = self.path.strip().replace("/", "\\")
        if not path.lower().endswith(".xml"):
            path += ".xml"
        if any(ob.albam_asset.relative_path.lower() == path.lower() for ob in context.scene.objects):
            self.report({"ERROR"}, f"{path} is already in this scene")
            return {"CANCELLED"}
        d = ext_list.new_list()
        text = d.text()
        root = new_root(context, path, text, b"")
        if self.fill:
            fill_from_scene(context, root)
        for ob in context.selected_objects:
            ob.select_set(False)
        context.view_layer.objects.active = root
        root.select_set(True)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_ExtFill(bpy.types.Operator):
    """List the scene's chains, and the models following another, that this list doesn't have yet. Models are found
    from their chains' parents and collision shapes"""
    bl_idname = "albam.ext_fill"
    bl_label = "Fill from Scene"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return is_list(context.object)

    def execute(self, context):
        added = fill_from_scene(context, context.object)
        self.report({"INFO"}, f"{added} entries added")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_ExtAdd(bpy.types.Operator):
    """Add an empty entry to this list"""
    bl_idname = "albam.ext_add"
    bl_label = "Add Entry"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    tag: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    parent: bpy.props.IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        return {"attach": "Add a model riding on another one",
                "model": "Add a model to put chains on",
                "chain": "Add a chain to this model",
                "hide": "Add a model not to draw"}.get(properties.tag, "Add an entry")

    @classmethod
    def poll(cls, context):
        return is_list(context.object)

    def execute(self, context):
        root = context.object
        d = list_doc(root)
        parent = d.by_uid(self.parent) if self.parent >= 0 else d.root
        add_element(d, self.tag, parent, [(n, "") for n in ext_list.REQUIRED[self.tag]])
        store(root, d)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_ExtRemove(bpy.types.Operator):
    """Remove this entry, with the chains under it"""
    bl_idname = "albam.ext_remove"
    bl_label = "Remove Entry"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    uid: bpy.props.IntProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        root = context.object
        if root.albam_ext.preview:
            clear_preview(root, context)
        d = list_doc(root)
        d.remove(d.by_uid(self.uid))
        store(root, d)
        if root.albam_ext.preview:
            apply_preview(root, context)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_ExtSetAttr(bpy.types.Operator):
    """Add this setting to the entry, or take it out so the game's default applies"""
    bl_idname = "albam.ext_set_attr"
    bl_label = "Add / Remove Setting"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    uid: bpy.props.IntProperty(options={"HIDDEN", "SKIP_SAVE"})
    attr: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        root = context.object
        d = list_doc(root)
        e = d.by_uid(self.uid)
        if e.has(self.attr):
            e.remove(self.attr)
        else:
            a = ext_list.spec(e.tag, self.attr)
            e.set(self.attr, a.default if a is not None else "")
        store(root, d)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_ExtAttrInfo(bpy.types.Operator):
    """What this setting does"""
    bl_idname = "albam.ext_attr_info"
    bl_label = "Setting Info"
    bl_options = {"INTERNAL"}

    tag: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    attr: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        a = ext_list.spec(properties.tag, properties.attr)
        if a is None:
            return "The runner doesn't read this; it's kept in the file as it is"
        return a.help + (f"\nAbsent: {a.default}" if a.default else "")

    def execute(self, context):
        return {"FINISHED"}


_pick_items = []


def _path_items(self, context):
    kind = self.kind
    wanted = {"model": ("mod",), "chain": ("phs", "clt"), "col": ("col",)}.get(kind, ())
    paths = {ext_list.stem(o.albam_asset.relative_path) for o in context.scene.objects
             if o.albam_asset.extension in wanted and o.albam_asset.relative_path}
    for item in context.scene.albam.rfs.file_list:
        if item.name.lower().endswith(tuple(f".{w}" for w in wanted)) and not item.is_expandable:
            paths.add(ext_list.stem(item.relative_path))
    _pick_items[:] = [(p, p, "") for p in sorted(paths, key=str.lower)] or [("", "(none found)", "")]
    return _pick_items


@blender_registry.register_blender_type
class ALBAM_OT_ExtPickPath(bpy.types.Operator):
    """Pick a path from the scene and the Game Files"""
    bl_idname = "albam.ext_pick_path"
    bl_label = "Pick Path"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    bl_property = "choice"

    uid: bpy.props.IntProperty(options={"HIDDEN", "SKIP_SAVE"})
    attr: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    kind: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    choice: bpy.props.EnumProperty(items=_path_items, options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        root = context.object
        item = next((e for e in root.albam_ext.elems if e.uid == self.uid), None)
        attr = next((a for a in item.attrs if a.name == self.attr), None) if item is not None else None
        if attr is not None and self.choice:
            attr.value = self.choice
        return {"FINISHED"}


def _draw_elem(layout, ext, item, level_tag=None):
    box = layout.box()
    head = box.row(align=True)
    head.label(text=f"<{item.tag}>")
    if item.tag == "model":
        op = head.operator("albam.ext_add", text="Chain", icon="ADD")
        op.tag, op.parent = "chain", item.uid
    head.operator("albam.ext_remove", text="", icon="X").uid = item.uid
    specs = ext_list.ELEMENTS.get(item.tag, ())
    present = {a.name for a in item.attrs}
    for a in item.attrs:
        row = box.row(align=True)
        s = ext_list.spec(item.tag, a.name)
        info = row.operator("albam.ext_attr_info", text=a.name, emboss=False)
        info.tag, info.attr = item.tag, a.name
        row.prop(a, "value", text="")
        if s is not None and s.kind in ("model", "chain", "col"):
            pick = row.operator("albam.ext_pick_path", text="", icon="VIEWZOOM")
            pick.uid, pick.attr, pick.kind = item.uid, a.name, s.kind
        if a.name not in ext_list.REQUIRED.get(item.tag, ()):
            op = row.operator("albam.ext_set_attr", text="", icon="REMOVE")
            op.uid, op.attr = item.uid, a.name
    missing = [s for s in specs if s.name not in present]
    if missing:
        row = box.row(align=True)
        for s in missing:
            op = row.operator("albam.ext_set_attr", text=s.name, icon="ADD")
            op.uid, op.attr = item.uid, s.name
    return box


@blender_registry.register_blender_type
class ALBAM_PT_ModelExtList(bpy.types.Panel):
    bl_idname = "ALBAM_PT_ModelExtList"
    bl_label = "Model Extension List"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return is_list(ob) or (ob is not None and model_object(ob) is not None)

    def draw(self, context):
        layout = self.layout
        root = context.object
        if not is_list(root):
            layout.operator("albam.ext_new", icon="ADD")
            return
        ext = root.albam_ext
        layout.label(text=root.albam_asset.relative_path, icon="FILE_TEXT")
        row = layout.row(align=True)
        row.operator("albam.ext_fill", icon="IMPORT")
        row.prop(ext, "preview", toggle=True, icon="CONSTRAINT_BONE")
        for level, name, message in all_issues(context, root):
            layout.label(text=f"{name}: {message}", icon="ERROR" if level == "error" else "INFO")
        top = next((e.uid for e in ext.elems if e.parent < 0), 0)
        row = layout.row(align=True)
        for tag, label in (("attach", "Attach"), ("model", "Model"), ("hide", "Hide")):
            op = row.operator("albam.ext_add", text=label, icon="ADD")
            op.tag, op.parent = tag, top
        by_parent = {}
        for item in ext.elems:
            by_parent.setdefault(item.parent, []).append(item)
        for item in by_parent.get(top, ()):
            box = _draw_elem(layout, ext, item)
            for child in by_parent.get(item.uid, ()):
                _draw_elem(box, ext, child)
