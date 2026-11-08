"""ModelExtension lists in Blender (the format is in movedef/ext_list.py, dmc4_hook owns it).

A list is an Empty `EXT_<file>` with its text and elements in `albam_ext`, in the Export list at its game path
(`model_ext\\<file>.xml`), so Save to Game Folder delivers it. Elements are edited in Object Properties > Model Extension
List; an untouched list exports byte-identical. **Fill from Scene** lists the scene's chains and followed models.

**Preview Attachments** does what the runner's attachments do in the game, with named constraints that are never
exported: skin = Copy Transforms `ALBAM_FollowBody` from the owner's bone of the same joint number, on every shared bone
no chain or constraint entry holds; rigid = Child Of `ALBAM_Attach` on the model's root, on the owner's joint. <pin> /
<aim> / <offset> are bone constraints `ALBAM_Cns <list>`, with an Empty `EXTP_...` holding each offset (the world matrices
are in Vibed/ModelExt/schema.md). Constraint influence stands in for the runner's blend (close, not equal), an aim's
Damped Track only approximates its up axis, and an aim's limit isn't previewed.
"""
import math

import bpy
from mathutils import Euler, Matrix, Vector

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.vfs import VirtualFileData
from albam.engines.mtfw import cns_chain, joints, shape_keys
from albam.engines.mtfw.cns_chain import ARMATURE_PROP
from albam.engines.mtfw.movedef import doc as doc_module, ext_list

FOLLOW = "ALBAM_FollowBody"
ATTACH = "ALBAM_Attach"
CNS = "ALBAM_Cns"
HELPER_PROP = "ext_helper"
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
        if ob.parent == arm:     # the bone collection is the chain's truth; phs_joints may lag behind it
            held.update(j for j in cns_chain.chain_joints(ob, []) if j >= 0)
    return held


def _cns_issues(context, d, name, found):
    out = []
    for e, model in ext_list.constraints(d):
        path = _stem(model.get("path", ""))
        arm = armature_of(found.get(path))
        number = ext_list.joint_number(e)
        if arm is None or number is None:
            continue
        if _bone(arm, number) is None:
            out.append(("warning", name, f"<{e.tag}>: {arm.name} has no joint {number}"))
        elif number in chain_held(context, arm):
            out.append(("warning", name, f"<{e.tag}>: a chain holds joint {number} of {arm.name}, the game refuses this"))
        if e.tag != "offset":
            src = armature_of(source_root(context, e, path, found))
            to = ext_list.joint_number(e, "to")
            if src is not None and to is not None and _bone(src, to) is None:
                out.append(("warning", name, f"<{e.tag}>: {src.name} has no joint {to}"))
    return out


def listed_chains(context, model_path):
    """The chain objects the scene's lists put on a model: <chain clt=> under every <model> with that path"""
    by_path = {_stem(o.albam_asset.relative_path): o for o in chains(context)}
    out = []
    for root in scene_lists(context):
        d = list_doc(root)
        for model in d.children(d.root, "model"):
            if _stem(model.get("path", "")) == model_path:
                out += [by_path[p] for p in (_stem(c.get("clt", "")) for c in d.children(model, "chain"))
                        if p in by_path and by_path[p] not in out]
    return out


def _chain_slots(chain_obs):
    """{joint: is a tendril root} over chains (a root is a chain's first slot or one after a -1)"""
    out = {}
    for ob in chain_obs:
        slots = cns_chain.chain_joints(ob, [])
        for k, j in enumerate(slots):
            if j >= 0:
                out[j] = k == 0 or slots[k - 1] < 0
    return out


def _link_issues(context, d, name, found):
    """what the runner refuses (one log line each): a joint no listed chain of the model holds, two tendril roots"""
    out = []
    for e, model in ext_list.links(d):
        path = _stem(model.get("path", ""))
        values = ext_list.link_values(e)
        if values is None or armature_of(found.get(path)) is None:
            continue
        slots = _chain_slots(listed_chains(context, path))
        missing = [j for j in values[:2] if j not in slots]
        if missing:
            out.append(("warning", name, f"<link> {values[0]}-{values[1]}: no chain listed on {model.get('path')} holds "
                                         f"joint {missing[0]}, the game refuses it"))
        elif slots[values[0]] and slots[values[1]]:
            out.append(("warning", name, f"<link> {values[0]}-{values[1]}: both are tendril roots, which keep their "
                                         "animated place: the game refuses it"))
    return out


def preview_links(arm):
    """[(bone a, bone b, max in Blender units, stiffness)] of the links the game would run on `arm`'s chains"""
    context = bpy.context
    found = models(context)
    out = []
    for root in scene_lists(context):
        d = list_doc(root)
        for e, model in ext_list.links(d):
            path = _stem(model.get("path", ""))
            values = ext_list.link_values(e)
            if values is None or armature_of(found.get(path)) != arm:
                continue
            slots = _chain_slots([c for c in listed_chains(context, path) if cns_chain.chain_armature(c) == arm])
            a, b = (_bone(arm, j) for j in values[:2])
            if a is None or b is None or values[0] not in slots or values[1] not in slots or \
                    (slots[values[0]] and slots[values[1]]):
                continue
            scale = sum(arm.matrix_world.to_scale()) / 3.0
            out.append((a.name, b.name, values[2] * 0.01 * scale, values[3]))
    return out


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
        out += _cns_issues(context, d, name, found)
        out += _link_issues(context, d, name, found)
        for e, _ in ext_list.shapes(d):
            ob = found.get(_stem(e.get("shp", "")))
            if ob is not None and not shape_keys.model_has_keys(ob):
                out.append(("warning", name, f"<shape> {e.get('shp')}: {ob.name} has no shape keys, so its export "
                                             "writes no .shp"))
    shaped = {_stem(m.get("path", "")) for root in scene_lists(context) for _, m in ext_list.shapes(list_doc(root))}
    for path, ob in found.items():
        if path not in shaped and shape_keys.model_has_keys(ob):
            out.append(("warning", ob.name, "has shape keys, but no list has a <shape> for it: they won't move in the "
                                            "game (Fill from Scene adds one)"))
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


# ---- own size (skeleton_match.keep_own_size) -------------------------------------------------------------------------

def _model_entry(context, model_path):
    """(list root, Doc, <model>) of the first list with a <model> for this path, else (None, None, None)"""
    for root in scene_lists(context):
        d = list_doc(root)
        for m in d.children(d.root, "model"):
            if _stem(m.get("path", "")) == _stem(model_path):
                return root, d, m
    return None, None, None


def _size_offsets(d, model, root_number):
    """the <offset>s that make the size: on the size root, and the scale-only one on joint 0"""
    return [e for e in d.children(model, "offset")
            if ext_list.joint_number(e) == root_number or
            (ext_list.joint_number(e) == 0 and [n for n, _ in e.attrs] == ["joint", "scale"])]


def set_size_offsets(context, model_path, root_number, s):
    """the model's list scales the size root by s and joint 0 by 1 / s (a list `<model>_size.xml` if no list has the
    model yet); the preview turns on. Returns the list's root object."""
    root, d, model = _model_entry(context, model_path)
    if root is None:
        root = new_root(context, f"{FOLDER}\\{file_name_of(model_path)}_size.xml", ext_list.new_list().text(), b"")
        d = list_doc(root)
        model = add_element(d, "model", d.root, [("path", ext_list.stem(model_path))])
    clear_preview(root, context)
    values = {root_number: f"{s:.6f}", 0: f"{1 / s:.6f}"}
    for e in d.children(model, "offset"):
        j = ext_list.joint_number(e)
        if j in values:
            e.set("scale", values.pop(j))
    for j, value in sorted(values.items(), key=lambda item: item[0] != root_number):     # the root's first
        add_element(d, "offset", model, [("joint", str(j)), ("scale", value)])
    store(root, d)
    if root.albam_ext.preview:
        apply_preview(root, context)
    else:
        root.albam_ext.preview = True
    return root


def clear_size_offsets(context, model_path, root_number):
    root, d, model = _model_entry(context, model_path)
    if root is None:
        return
    clear_preview(root, context)
    for e in _size_offsets(d, model, root_number):
        d.remove(e)
    store(root, d)
    _refresh(root, context)


# ---- from the scene --------------------------------------------------------------------------------------------------

def add_element(d, tag, parent, attrs):
    same = d.children(parent, tag)
    return d.add(tag, parent, attrs, after=same[-1] if same else None)


def _collision_root(chain):
    """The .mod root carrying a chain's shapes, or None"""
    col = chain.albam_phs.collision_shapes
    return model_object(col.get(ARMATURE_PROP) or col.parent) if col is not None else None


def fill_from_scene(context, root):
    """Lists every chain of the scene, every model following another (ALBAM_FollowBody) and a <shape> for every model
    with shape keys no list has one for, skipping what the list has, models that carry another's collision shapes
    first (runners before 2026-11-03 need that order). Returns how many entries were added."""
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
    shaped = {_stem(m.get("path", "")) for root_ in scene_lists(context) for _, m in ext_list.shapes(list_doc(root_))}
    shaped |= {_stem(m.get("path", "")) for _, m in ext_list.shapes(d)}
    for path, ob in sorted(known.items()):
        if path in shaped or not shape_keys.model_has_keys(ob):
            continue
        stem = ext_list.stem(ob.albam_asset.relative_path)     # the .mod export writes <model>.shp / .shw
        parent = next((m for m in d.children(d.root, "model") if _stem(m.get("path", "")) == path), None)
        if parent is None:
            parent = add_element(d, "model", d.root, [("path", stem)])
        rest, _, active = shape_keys.model_weight_lists(ob)
        # list 0 plays from the start: the clip on the Keys now (an idle), else the set values; clips for moves only
        # take no list here (MoveDef <shape> starts them)
        attrs = [("shp", stem)] + ([("shw", active or rest)] if active or rest else [])
        add_element(d, "shape", parent, attrs)
        added += 1
    store(root, d)
    return added


# ---- preview ---------------------------------------------------------------------------------------------------------

def offset_matrix(elem):
    """T R S of an entry in Blender units; the rotation is the runner's euler_quat (q = qz qy qx: x first)"""
    pos, rot, scale = ext_list.offset_values(elem)
    q = Euler([math.radians(a) for a in rot], "XYZ").to_quaternion()
    return Matrix.Translation(Vector(pos) * 0.01) @ q.to_matrix().to_4x4() @ Matrix.Diagonal((*scale, 1.0))


def _bone(arm, number):
    if arm is None or number is None:
        return None
    return next((b for b in joints.joint_bones(arm) if joints.joint_of(b) == number), None)


def source_root(context, e, model_path, found):
    """The .mod root an entry's `to` joint is on: of=, else what the model is attached to, else itself. (A coat's owner
    isn't in any list, so a coat's entries need of= in the preview.)"""
    of = e.get("of", "")
    if of.lower() == "self":
        return found.get(model_path)
    if of:
        return found.get(_stem(of))
    for root in scene_lists(context):
        d = list_doc(root)
        for attach in d.children(d.root, "attach"):
            if _stem(attach.get("path", "")) == model_path:
                return found.get(_stem(attach.get("to", "")), found.get(model_path))
    return found.get(model_path)


def _helper(root, label, matrix, arm=None, bone=None):
    """An Empty holding an offset, on `bone` of `arm` (the bone's head frame) or free"""
    ob = bpy.data.objects.new(f"EXTP_{label}", None)
    ob.empty_display_size = 0.02
    ob.hide_render = True
    ob[HELPER_PROP] = root
    root.users_collection[0].objects.link(ob)
    if arm is not None:
        ob.parent = arm
    if bone is not None:
        ob.parent_type, ob.parent_bone = "BONE", bone.name
        ob.matrix_parent_inverse = Matrix.Translation((0.0, -bone.length, 0.0))
    ob.matrix_basis = matrix
    return ob


def _add(pose, kind, name, target, subtarget="", influence=1.0):
    con = pose.constraints.new(kind)
    con.name = name
    con.target = target
    if subtarget:
        con.subtarget = subtarget
    con.influence = influence
    return con


def _pin(root, e, pose, name, src, bone):
    blend = ext_list.blend_of(e)
    has_offset = any(e.has(n) for n in ("pos", "rot", "scale"))
    helper = _helper(root, f"{pose.name}_pin", offset_matrix(e), src, bone) if has_offset else None
    target, sub = (helper, "") if helper is not None else (src, bone.name)
    if e.get("mode", "all") == "all":
        _add(pose, "COPY_TRANSFORMS", name, target, sub, blend)
        return
    _add(pose, "COPY_ROTATION", name, target, sub, blend)
    if helper is None:
        return
    pos, _, scale = ext_list.offset_values(e)
    if scale != [1.0] * 3:
        _add(pose, "COPY_SCALE", name, helper, "", blend)
    if pos != [0.0] * 3:        # the source's axes: the offset's own position, read in the source joint's space
        con = _add(pose, "COPY_LOCATION", name, helper, "", blend)
        con.use_offset = True
        con.target_space = con.owner_space = "CUSTOM"
        con.space_object, con.space_subtarget = src, bone.name


def _offset(root, e, pose, name):
    label = f"{pose.name}_offset"
    matrix = offset_matrix(e)
    if ext_list.is_true(e.get("add", "true")):
        con = _add(pose, "COPY_TRANSFORMS", name, _helper(root, label, matrix))     # owner x target, both world
        con.mix_mode = "AFTER_FULL"
        return
    arm, parent = pose.id_data, pose.bone.parent
    helper = _helper(root, label, matrix, arm, parent) if parent is not None else \
        _helper(root, label, GAME_TO_BLENDER @ matrix, arm)
    _add(pose, "COPY_TRANSFORMS", name, helper)


def _constraint(context, root, e, model, found):
    path = _stem(model.get("path", ""))
    arm = armature_of(found.get(path))
    number = ext_list.joint_number(e)
    bone = _bone(arm, number)
    if bone is None or number in chain_held(context, arm) or ext_list.game_held(path, number) is not None:
        return      # refused in the game
    pose = arm.pose.bones[bone.name]
    name = f"{CNS} {root.name}"
    if e.tag == "offset":
        _offset(root, e, pose, name)
        return
    src = armature_of(source_root(context, e, path, found))
    target = _bone(src, ext_list.joint_number(e, "to"))
    if target is None:
        return
    if e.tag == "pin":
        _pin(root, e, pose, name, src, target)
        return
    con = _add(pose, "DAMPED_TRACK", name, src, target.name, ext_list.blend_of(e))
    axis = e.get("axis", "+z").lower()
    con.track_axis = ("TRACK_NEGATIVE_" if axis[0] == "-" else "TRACK_") + axis[-1].upper()


def claimed(context):
    """{model path: joints with a constraint entry}: they beat a skin attachment's follow"""
    out = {}
    for root in scene_lists(context):
        for e, model in ext_list.constraints(list_doc(root)):
            out.setdefault(_stem(model.get("path", "")), set()).add(ext_list.joint_number(e))
    return out


def _remove_follow(attached):
    arm = armature_of(attached)
    if arm is not None:
        for pose in arm.pose.bones:
            for con in [c for c in pose.constraints if c.name == FOLLOW]:
                pose.constraints.remove(con)
    for con in [c for c in attached.constraints if c.name == ATTACH]:
        attached.constraints.remove(con)


def _attach(context, attach, found, taken):
    path = _stem(attach.get("path", ""))
    attached, owner = found.get(path), found.get(_stem(attach.get("to", "")))
    if attached is None or owner is None:
        return
    arm, owner_arm = armature_of(attached), armature_of(owner)
    if ext_list.effective_mode(attach) == "skin":
        if arm is None or owner_arm is None:
            return
        theirs = {joints.joint_of(b): b.name for b in joints.joint_bones(owner_arm)}
        held = chain_held(context, arm) | taken.get(path, set())
        for bone in joints.joint_bones(arm):
            number = joints.joint_of(bone)
            if number is not None and number in theirs and number not in held:
                _add(arm.pose.bones[bone.name], "COPY_TRANSFORMS", FOLLOW, owner_arm, theirs[number])
        return
    con = attached.constraints.new("CHILD_OF")
    con.name = ATTACH
    con.target = owner_arm or owner
    offset = offset_matrix(attach)
    bone = _bone(owner_arm, ext_list.joint_number(attach))
    if bone is None:        # -1 or a joint it lacks: the owner's root, model space
        con.inverse_matrix = GAME_TO_BLENDER @ offset @ GAME_TO_BLENDER.inverted()
        return
    con.subtarget = bone.name
    con.inverse_matrix = offset @ GAME_TO_BLENDER.inverted()      # the bone's frame is the game joint's


def clear_preview(root, context):
    d = list_doc(root)
    found = models(context)
    for attach in d.children(d.root, "attach"):
        attached = found.get(_stem(attach.get("path", "")))
        if attached is not None:
            _remove_follow(attached)
    name = f"{CNS} {root.name}"
    for ob in context.scene.objects:
        if ob.type == "ARMATURE":
            for pose in ob.pose.bones:
                for con in [c for c in pose.constraints if c.name.startswith(name)]:
                    pose.constraints.remove(con)
    for ob in [o for o in bpy.data.objects if o.get(HELPER_PROP) == root]:
        bpy.data.objects.remove(ob)


def apply_preview(root, context):
    clear_preview(root, context)
    d = list_doc(root)
    found = models(context)
    taken = claimed(context)
    for attach in d.children(d.root, "attach"):
        _attach(context, attach, found, taken)
    seen = set()
    for e, model in ext_list.constraints(d):
        key = (_stem(model.get("path", "")), ext_list.joint_number(e))
        if key not in seen:     # the first entry on a joint wins
            seen.add(key)
            _constraint(context, root, e, model, found)


def _refresh(root, context):
    if root.albam_ext.preview:
        apply_preview(root, context)


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
    """List the scene's chains, the models following another and the models with shape keys (a <shape> entry), that
    this list doesn't have yet. Models are found from their chains' parents and collision shapes"""
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
                "pin": "Make a joint of this model follow another joint",
                "aim": "Make an axis of a joint of this model point at another joint",
                "offset": "Move, turn or scale a joint of this model",
                "link": "Keep two chain joints of this model within a distance, so neighbouring tendrils can't part. "
                        "The chain preview runs it",
                "shape": "Make this model's shape keys move in the game: the .shp and .shw its .mod export writes",
                "weights": "Play another weight list (.shw) with this shape's, 4 lists in all",
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
        _refresh(root, context)
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
        _refresh(root, context)
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
        _refresh(root, context)
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


def _joint_items(context, kind, uid):
    d = list_doc(context.object)
    e = d.by_uid(uid)
    path = _stem(d.parent_of(e).get("path", ""))
    found = models(context)
    ob = found.get(path) if kind == "joint" else source_root(context, e, path, found)
    arm = armature_of(ob)
    if arm is None:
        return []
    return [(str(joints.joint_of(b)), f"{joints.joint_of(b)} {b.name}", "") for b in joints.joint_bones(arm)
            if joints.joint_of(b) is not None]


def _path_items(self, context):
    kind = self.kind
    if kind in ("joint", "source"):
        _pick_items[:] = _joint_items(context, kind, self.uid) or [("", "(no armature found)", "")]
        return _pick_items
    wanted = {"model": ("mod",), "of": ("mod",), "chain": ("phs", "clt"), "col": ("col",), "shape": ("shp",),
              "weights": ("shw",)}.get(kind, ())
    paths = {ext_list.stem(o.albam_asset.relative_path) for o in context.scene.objects
             if o.albam_asset.extension in wanted and o.albam_asset.relative_path}
    for o in models(context).values():      # what the .mod exports of models with shape keys will write
        if kind in ("shape", "weights") and shape_keys.model_has_keys(o):
            if kind == "shape":
                paths.add(ext_list.stem(o.albam_asset.relative_path))
            else:
                _, clips, _ = shape_keys.model_weight_lists(o)
                paths |= set(clips) | {ext_list.stem(o.albam_asset.relative_path)}
    for item in context.scene.albam.rfs.file_list:
        if item.name.lower().endswith(tuple(f".{w}" for w in wanted)) and not item.is_expandable:
            paths.add(ext_list.stem(item.relative_path))
    _pick_items[:] = [(p, p, "") for p in sorted(paths, key=str.lower)] or [("", "(none found)", "")]
    return _pick_items


@blender_registry.register_blender_type
class ALBAM_OT_ExtPickPath(bpy.types.Operator):
    """Pick from the scene: a path (the Game Files too), or a joint by its bone's name"""
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


CHILD_BUTTONS = {
    "model": (("chain", "Chain"), ("pin", "Pin"), ("aim", "Aim"), ("offset", "Offset"), ("link", "Link"),
              ("shape", "Shape")),
    "shape": (("weights", "Weights"),),
}


def _draw_elem(layout, ext, item, by_parent):
    box = layout.box()
    head = box.row(align=True)
    head.label(text=f"<{item.tag}>")
    for tag, label in CHILD_BUTTONS.get(item.tag, ()):
        op = head.operator("albam.ext_add", text=label, icon="ADD")
        op.tag, op.parent = tag, item.uid
    head.operator("albam.ext_remove", text="", icon="X").uid = item.uid
    specs = ext_list.ELEMENTS.get(item.tag, ())
    present = {a.name for a in item.attrs}
    for a in item.attrs:
        row = box.row(align=True)
        s = ext_list.spec(item.tag, a.name)
        info = row.operator("albam.ext_attr_info", text=a.name, emboss=False)
        info.tag, info.attr = item.tag, a.name
        row.prop(a, "value", text="")
        if s is not None and s.kind in ("model", "of", "chain", "col", "joint", "source", "shape", "weights"):
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
    for child in by_parent.get(item.uid, ()):
        _draw_elem(box, ext, child, by_parent)
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
            _draw_elem(layout, ext, item, by_parent)
