"""DMC4 .efl export: the imported file with the Blender-side edits written back.

The source bytes (root.albam_asset.original_bytes) are parsed again and rebuilt from the record objects:
- records: every record object with efl_record = i keeps source record i; source records without an object are
  removed; objects with efl_record = -1 are new records built from their efl_raw blocks (duplicates and records
  copied from other effects), appended in efl_serial order;
- fields: the efl_gen / efl_ptcl / efl_life / efl_move custom properties that differ from the file (efl/edit.py;
  offsets into the block and block types are read-only);
- keyframes: efl_kf {slot: {offset field: keyframe}}; sub-structs: efl_sub {slot: {offset field: fields}};
- the generator Empty's transform -> Pos / Quat / Scale (base values), in the frame of the joint it's parented
  to (the bone head frame) or of the effect root; channels driven by generator keyframes (F-curves) are skipped;
- re-parenting the Empty to another bone of the armature -> ParentNo = that bone's mtfw.anim_retarget.
Untouched records stay byte-identical. Structural edits (duplicate / remove / copy) rebuild the effect right away
(effect.rebuild_effect), so the scene always shows what would be exported.
"""
import base64

import bpy
from mathutils import Matrix, Quaternion

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.vfs import VirtualFileData
from .efl import EffectList, schema
from .efl.edit import (apply_keyframes, apply_props, apply_subs, as_list, record_from_raw, record_raw,
                       restructure)
from .efl.model import Block, SLOTS

SCALE = 0.01             # game centimetres -> metres
POS_TOLERANCE = 1e-3     # cm
SCALE_TOLERANCE = 1e-5
QUAT_TOLERANCE = 1e-6    # 1 - |dot|
NEW_RECORD = -1


def effect_root(ob):
    """The EFL root Empty an object belongs to (itself, or its efl_root), or None."""
    if ob is None:
        return None
    if ob.albam_asset.extension == "efl":
        return ob
    root = ob.get("efl_root")
    return root if root is not None and root.albam_asset.extension == "efl" else None


def record_object(ob):
    """The record (generator) Empty for an object of an effect: itself, the generator of a particle object, or the
    generator a rotation handle belongs to."""
    if ob is None:
        return None
    if "efl_record" in ob:
        return ob
    generator = ob.get("efl_generator") or ob.get(ROT_HANDLE_OF)
    return generator if generator is not None and "efl_record" in generator else None


# RelationType 2 (generator AxisFlags bits 8-11, Generator+0x110 from initChildGenerator 0x96BC3F): the generator
# follows its joint's position (Pos turned by the joint) but its rotation is its own Quat in world axes, not the
# joint's (uEffectVFR::setQuatParentOfs 0x9687B0). In Blender the generator Empty stays on the bone for its position,
# and a companion Empty under the effect root (game world axes) holds the rotation; a Copy Rotation constraint gives
# the generator that rotation, and export reads Quat from the companion.
ROT_HANDLE_KEY = "efl_rot_handle"        # generator -> companion
ROT_HANDLE_OF = "efl_rot_handle_of"      # companion -> generator
ROT_CONSTRAINT = "ALBAM_EFL_WorldRotation"
AT_JOINT_CONSTRAINT = "ALBAM_EFL_AtJoint"
RELATION_POSITION_ONLY = 2


def relation_type(ob):
    props = ob.get("efl_gen")
    return int(props.get("RelationType", 0)) if props is not None else 0


def rotation_handle(ob):
    """The companion Empty holding a RelationType 2 generator's world rotation, or None."""
    handle = ob.get(ROT_HANDLE_KEY) if ob is not None else None
    return handle if handle is not None and handle.get(ROT_HANDLE_OF) == ob else None


def attach_rotation_handle(ob, root, rotation):
    """Give a bone-attached RelationType 2 generator its rotation companion; rotation = Quat in the root's frame."""
    old = rotation_handle(ob)
    if old is not None:
        bpy.data.objects.remove(old)
    handle = bpy.data.objects.new(ob.name + "_rot", None)
    for collection in ob.users_collection or root.users_collection:
        collection.objects.link(handle)
    handle.empty_display_type, handle.empty_display_size = "ARROWS", 0.08
    handle.parent = root
    handle.rotation_mode = "QUATERNION"
    handle.rotation_quaternion = rotation
    handle["efl_root"] = root
    handle[ROT_HANDLE_OF] = ob
    ob[ROT_HANDLE_KEY] = handle
    at_joint = handle.constraints.new("COPY_LOCATION")   # shown at the joint (following the generator would loop)
    at_joint.name = AT_JOINT_CONSTRAINT
    at_joint.target, at_joint.subtarget = ob.parent, ob.parent_bone
    world_rotation = ob.constraints.get(ROT_CONSTRAINT) or ob.constraints.new("COPY_ROTATION")
    world_rotation.name = ROT_CONSTRAINT
    world_rotation.target = handle
    world_rotation.mix_mode = "REPLACE"
    world_rotation.target_space = world_rotation.owner_space = "WORLD"
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    return handle


def detach_rotation_handle(ob):
    handle = rotation_handle(ob)
    if handle is not None:
        bpy.data.objects.remove(handle)
    constraint = ob.constraints.get(ROT_CONSTRAINT)
    if constraint is not None:
        ob.constraints.remove(constraint)
    ob.pop(ROT_HANDLE_KEY, None)


def all_record_objects(root):
    obs = [o for o in bpy.data.objects if "efl_record" in o and o.get("efl_root") == root]
    if not obs:   # imported before record objects pointed at their root
        for collection in root.users_collection:
            obs = [o for o in collection.all_objects if "efl_record" in o]
            if obs:
                break
    return obs


def record_objects(root):
    """{source record index: object}; raises if two objects claim the same record."""
    out, duplicates = {}, []
    for ob in all_record_objects(root):
        index = int(ob["efl_record"])
        if index < 0:
            continue
        if index in out:
            duplicates.append(f"{out[index].name} / {ob.name}")
        out[index] = ob
    if duplicates:
        raise AlbamCheckFailure(
            "Two objects edit the same effect record", details="; ".join(duplicates),
            solution="Use Effect Editor > Duplicate to copy records; delete the extra copy")
    return out


def new_record_objects(root):
    return sorted((o for o in all_record_objects(root) if int(o["efl_record"]) < 0),
                  key=lambda o: (o.get("efl_serial", 0), o.name))


def ordered_record_objects(root):
    """Record objects in the order export writes them."""
    objects = record_objects(root)
    return [objects[i] for i in sorted(objects)] + new_record_objects(root)


def source_bytes(root):
    data = root.albam_asset.original_bytes
    if not data and root.get("efl_data"):
        data = base64.b64decode(root["efl_data"])
    if not data:
        raise AlbamCheckFailure("The effect's source file isn't stored in the .blend",
                                details=root.name, solution="Re-import the .efl")
    return bytes(data)


def store_raw(ob, record):
    ob["efl_raw"] = {slot: {"type": btype, "data": base64.b64encode(data).decode("ascii")}
                     for slot, (btype, data) in record_raw(record).items()}


def _raw_of(ob):
    raw = ob.get("efl_raw")
    if raw is None:
        return None
    return {slot: (int(raw[slot]["type"]), base64.b64decode(raw[slot]["data"])) for slot in raw.keys()
            if slot in SLOTS}


def _replaced_of(ob):
    """{slot: (type, bytes)} of blocks a source record's object replaces (Change Type), or None."""
    raw = ob.get("efl_replaced")
    if not raw:
        return None
    return {slot: (int(raw[slot]["type"]), base64.b64decode(raw[slot]["data"])) for slot in raw.keys()
            if slot in SLOTS}


def _replace_block(efl, record, slot, block):
    """Put block in place of the record's slot block, at the same position in the file."""
    old = getattr(record, slot)
    index = next((i for i, b in enumerate(efl.blocks) if b is old), None) if old is not None else None
    if index is None:
        efl.blocks.append(block)
    else:
        efl.blocks[index] = block
    setattr(record, slot, block)


def build_efl_bytes(root):
    """(file bytes, notes, record objects in file order) with every edit applied; raises AlbamCheckFailure."""
    bpy.context.view_layer.update()   # world matrices of moved / new record objects
    efl = EffectList.from_bytes(source_bytes(root))
    objects = record_objects(root)
    notes, problems = [], []
    bad = [i for i in objects if i >= len(efl.records)]
    if bad:
        raise AlbamCheckFailure("Record objects point past the effect's records", details=str(bad),
                                solution="Rebuild or re-import the effect")
    keep = sorted(objects)
    removed = [i for i in range(len(efl.records)) if i not in objects]
    notes += [f"record {i:02d} removed" for i in removed]
    extra, extra_obs = [], []
    for ob in new_record_objects(root):
        raw = _raw_of(ob)
        if not raw:
            problems.append(f"{ob.name}: a new record without block data (efl_raw)")
            continue
        extra.append(record_from_raw(raw))
        extra_obs.append(ob)
        notes.append(f"record added from {ob.name}")
    order = [objects[i] for i in keep] + extra_obs
    restructure(efl, keep, extra)
    for record, ob in zip(efl.records, order):   # blocks whose type was changed (efl/retype.py)
        for slot, (btype, data) in (_replaced_of(ob) or {}).items():
            _replace_block(efl, record, slot, Block(slot, btype, bytearray(data)))
            notes.append(f"{ob.name}: {slot} changed to {schema.type_name(slot, btype)}")

    for index, (record, ob) in enumerate(zip(efl.records, order)):
        label = f"record {index:02d} ({ob.name})"
        keyframes, subs = ob.get("efl_kf") or {}, ob.get("efl_sub") or {}
        for key in SLOTS:
            block = getattr(record, key)
            if block is None:
                continue
            for what, props, apply in ((key, ob.get(f"efl_{key}"), apply_props),
                                       (f"{key} keyframe", keyframes.get(key), apply_keyframes),
                                       (key, subs.get(key), apply_subs)):
                if props is None:
                    continue
                changes, block_problems = apply(block, props)
                problems += [f"{label} {what}: {p}" for p in block_problems]
                notes += [f"{label} {what}.{name}: {_short(old)} -> {_short(new)}" for name, old, new in changes]
        if record.gen is not None:
            changes, gen_problems = _write_generator(ob, root, record.gen)
            problems += [f"{label}: {p}" for p in gen_problems]
            notes += [f"{label} gen.{name}: {_short(old)} -> {_short(new)}" for name, old, new in changes]
    if problems:
        raise AlbamCheckFailure("Some effect edits can't be written", details="\n".join(problems),
                                solution="Fix or revert those values (Effect Editor, or the record Empties' "
                                         "custom properties)")
    return efl.to_bytes(), notes, order


def structure_changed(root):
    """True if records were added or removed, a block's type changed, or a linked .efs / .ean was edited since the
    effect was built (those are read at build time, so the preview needs a rebuild)."""
    count = EffectList.from_bytes(source_bytes(root)).records
    objects = record_objects(root)
    if new_record_objects(root) or len(objects) != len(count) or any(ob.get("efl_replaced") for ob in objects.values()):
        return True
    return bool(linked_changes(root))


def linked_changes(root):
    """[(object, bytes)] of the effect's linked .efs / .ean whose data differs from what the effect was built with."""
    from .effect import linked_bytes, linked_objects
    import zlib
    built = root.get("efl_linked_hash") or {}
    out = []
    for key, ob in linked_objects(root).items():
        data = linked_bytes(ob)
        if key not in built or f"{zlib.crc32(data):08x}" != str(built[key]):
            out.append((ob, data))
    return out


def _short(value):
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_short(v) for v in value) + "]"
    return value if isinstance(value, str) else repr(value)


def _animated_paths(ob):
    action = ob.animation_data.action if ob.animation_data else None
    return {fc.data_path for fc in action.fcurves} if action else set()


def _parent_frame(ob, root):
    """(world matrix of the frame Pos/Quat are in, joint number or None, problem or None)."""
    if ob.parent is not None and ob.parent_type == "BONE" and ob.parent.type == "ARMATURE":
        pose_bone = ob.parent.pose.bones.get(ob.parent_bone)
        if pose_bone is None:
            return root.matrix_world, None, f"parent bone {ob.parent_bone!r} not found"
        joint = pose_bone.bone.get("mtfw.anim_retarget")
        if joint is None:
            return (ob.parent.matrix_world @ pose_bone.matrix, None,
                    f"bone {ob.parent_bone!r} has no mtfw.anim_retarget (not a game joint)")
        return ob.parent.matrix_world @ pose_bone.matrix, int(joint), None
    if ob.parent is not None and ob.parent != root:
        return root.matrix_world, None, (f"parented to {ob.parent.name!r}: parent it to the effect root or to a "
                                         "bone of the armature")
    return root.matrix_world, None, None


def _write_generator(ob, root, gen):
    changes, problems = [], []
    frame, joint, problem = _parent_frame(ob, root)
    if problem:
        problems.append(problem)
        return changes, problems
    old_parent = gen.get("ParentNo")
    if joint is not None and joint != old_parent:
        gen.set("ParentNo", joint)
        changes.append(("ParentNo", old_parent, joint))
    elif joint is None and old_parent >= 0 and "efl_unresolved_joint" not in ob:
        gen.set("ParentNo", -1)   # was attached to a joint at import, now detached
        changes.append(("ParentNo", old_parent, -1))

    location, rotation, scale = (frame.inverted_safe() @ ob.matrix_world).decompose()
    animated = _animated_paths(ob)
    handle = rotation_handle(ob) if joint is not None else None
    if handle is not None:   # RelationType 2: Quat is in world (root) axes, held by the companion
        rotation = (root.matrix_world.inverted_safe() @ handle.matrix_world).to_quaternion()
        animated = (animated - {"rotation_quaternion", "rotation_euler", "rotation_axis_angle"}) | \
            (_animated_paths(handle) & {"rotation_quaternion", "rotation_euler", "rotation_axis_angle"})
    if "location" not in animated:
        old = gen.get("Pos")
        new = [c / SCALE for c in location]
        if any(abs(a - b) > POS_TOLERANCE for a, b in zip(old, new)):
            gen.set("Pos", new)
            changes.append(("Pos", old, new))
    if not animated & {"rotation_quaternion", "rotation_euler", "rotation_axis_angle"}:
        old = gen.get("Quat")
        x, y, z, w = old
        old_q = Quaternion((w, x, y, z)) if any(old) else Quaternion()
        if old_q.magnitude > 0:
            old_q.normalize()
        if 1.0 - abs(old_q.dot(rotation)) > QUAT_TOLERANCE:
            q = rotation if old_q.dot(rotation) >= 0 else -rotation   # keep the stored sign
            new = [q.x, q.y, q.z, q.w]
            gen.set("Quat", new)
            changes.append(("Quat", old, new))
    if "scale" not in animated:
        old = gen.get("Scale")
        if any(abs(pair[0] - s) > SCALE_TOLERANCE for pair, s in zip(old, scale)):
            gen.set("Scale", [[s, pair[1]] for pair, s in zip(old, scale)])
            changes.append(("Scale", [p[0] for p in old], list(scale)))
    return changes, problems


@blender_registry.register_export_function(app_id="dmc4", extension="efl")
def export_efl(bl_obj):
    data, notes, _order = build_efl_bytes(bl_obj)
    asset = bl_obj.albam_asset
    print(f"EFL export {asset.relative_path}: {len(notes)} change(s)")
    for note in notes:
        print("  " + note)
    vfiles = [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]
    from .effect import linked_bytes, linked_objects
    for key, ob in sorted(linked_objects(bl_obj).items()):   # referenced .efs / .ean that were edited
        linked = linked_bytes(ob)
        if linked != bytes(ob.albam_asset.original_bytes):
            vfiles.append(VirtualFileData(ob.albam_asset.app_id, ob.albam_asset.relative_path, data_bytes=linked))
            notes.append(f"{ob.albam_asset.relative_path} changed")
            print(f"  also writes {ob.albam_asset.relative_path}")
    bl_obj["efl_export_notes"] = notes[:200]
    return vfiles


# -- applying edits to the scene --------------------------------------------------------------------

def apply_to_scene(context, root, rebuild=False):
    """Replay the preview with the edits; rebuild the effect objects when records were added/removed (or asked).
    Returns (root, notes, rebuilt). The active record keeps being the active object."""
    active = record_object(context.view_layer.objects.active)
    data, notes, order = build_efl_bytes(root)
    if not rebuild and not structure_changed(root):
        from . import effect_sim
        effect_sim.store_source(root, data, root.get("efl_start_frame", context.scene.frame_current))
        effect_sim.invalidate()
        from .effect_filter import apply_filter
        apply_filter(root)
        context.scene.frame_set(context.scene.frame_current)
        _refresh_editor(context)
        return root, notes, False
    active_index = order.index(active) if active in order else None
    from .effect import rebuild_effect
    new_root = rebuild_effect(context, root, data)
    target = new_root
    if active_index is not None:
        target = next((o for o in all_record_objects(new_root) if int(o["efl_record"]) == active_index), new_root)
    for ob in context.view_layer.objects:
        if ob is not None:   # inside an operator the list can still hold the objects the rebuild removed
            ob.select_set(False)
    if target.name in context.view_layer.objects:
        context.view_layer.objects.active = target
        target.select_set(True)
    context.scene.frame_set(context.scene.frame_current)
    _refresh_editor(context)
    return new_root, notes, True


def _refresh_editor(context):
    from .effect_editor import refresh_editor
    refresh_editor(context)


def _report_failure(op, err):
    op.report({"ERROR"}, f"{err.message}: {err.details}" if isinstance(err, AlbamCheckFailure) else str(err))
    return {"CANCELLED"}


@blender_registry.register_blender_type
class ALBAM_OT_EflApplyEdits(bpy.types.Operator):
    """Replay the particle preview with the edits. Rebuilds the effect's objects when records were added or
    removed (textures, materials and shapes are rebuilt only by Rebuild Effect)"""
    bl_idname = "albam.efl_apply_edits"
    bl_label = "Apply Edits to Preview"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return effect_root(context.active_object) is not None

    def execute(self, context):
        try:
            _root, notes, rebuilt = apply_to_scene(context, effect_root(context.active_object))
        except Exception as err:
            return _report_failure(self, err)
        self.report({"INFO"}, f"{len(notes)} edit(s) applied" + (" (effect rebuilt)" if rebuilt else ""))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EflRebuild(bpy.types.Operator):
    """Rebuild the effect's objects from the edited file: materials, textures, shapes and particles"""
    bl_idname = "albam.efl_rebuild"
    bl_label = "Rebuild Effect"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return effect_root(context.active_object) is not None

    def execute(self, context):
        try:
            _root, notes, _ = apply_to_scene(context, effect_root(context.active_object), rebuild=True)
        except Exception as err:
            return _report_failure(self, err)
        self.report({"INFO"}, f"Effect rebuilt with {len(notes)} edit(s)")
        return {"FINISHED"}


def _copy_record_object(context, source, root, parent):
    """New record Empty for root, carrying source's edits and its current block data."""
    src_root = effect_root(source)
    raw = _raw_of(source)
    if raw is None:
        efl = EffectList.from_bytes(source_bytes(src_root))
        raw = record_raw(efl.records[int(source["efl_record"])])
    raw.update(_replaced_of(source) or {})
    ob = bpy.data.objects.new(source.name + "+", None)
    for collection in root.users_collection:
        collection.objects.link(ob)
    ob.empty_display_type, ob.empty_display_size = source.empty_display_type, source.empty_display_size
    for key in list(source.keys()):
        if key.startswith("efl_") and key not in ("efl_root", "efl_raw", "efl_record", "efl_serial",
                                                  "efl_filtered", "efl_replaced"):
            value = source[key]
            ob[key] = value.to_dict() if hasattr(value, "to_dict") else (
                value.to_list() if hasattr(value, "to_list") else value)
    ob["efl_record"] = NEW_RECORD
    ob["efl_root"] = root
    ob["efl_serial"] = max([int(o.get("efl_serial", 0)) for o in all_record_objects(root)] + [0]) + 1
    ob["efl_raw"] = {slot: {"type": btype, "data": base64.b64encode(data).decode("ascii")}
                     for slot, (btype, data) in raw.items()}
    ob.rotation_mode = source.rotation_mode
    joint = -1
    if source.parent is not None and source.parent_type == "BONE" and source.parent.type == "ARMATURE":
        bone = source.parent.data.bones.get(source.parent_bone)
        joint = int(bone.get("mtfw.anim_retarget", -1)) if bone is not None else -1
    elif "efl_gen" in source:
        joint = int(source["efl_gen"].get("ParentNo", -1))
    bone = None
    if parent is not None and joint >= 0:
        bone = next((b for b in parent.data.bones if b.get("mtfw.anim_retarget") == joint), None)
    ob.pop("efl_unresolved_joint", None)
    if bone is not None:   # same attachment as the importer: Pos/Quat in the bone head frame
        ob.parent, ob.parent_type, ob.parent_bone = parent, "BONE", bone.name
        ob.matrix_parent_inverse = Matrix.Translation((0.0, -bone.length, 0.0))
    else:
        ob.parent = root
        if joint >= 0:
            ob["efl_unresolved_joint"] = joint
    ob.matrix_basis = source.matrix_basis.copy()
    ob.pop(ROT_HANDLE_KEY, None)
    for constraint in list(ob.constraints):
        ob.constraints.remove(constraint)
    source_handle = rotation_handle(source)
    if source_handle is not None and ob.parent_type == "BONE" and ob.parent is not None:
        rotation = (effect_root(source).matrix_world.inverted_safe() @ source_handle.matrix_world).to_quaternion()
        attach_rotation_handle(ob, root, rotation)
    return ob


@blender_registry.register_blender_type
class ALBAM_OT_EflDuplicateRecord(bpy.types.Operator):
    """Add a copy of the active record (generator, particle, life and move, with their edits) to its effect"""
    bl_idname = "albam.efl_duplicate_record"
    bl_label = "Duplicate Record"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return record_object(context.active_object) is not None

    def execute(self, context):
        source = record_object(context.active_object)
        root = effect_root(source)
        parent = source.parent if source.parent is not None and source.parent.type == "ARMATURE" else None
        name = source.name
        ob = _copy_record_object(context, source, root, parent)
        context.view_layer.objects.active = ob
        try:
            apply_to_scene(context, root)
        except Exception as err:
            return _report_failure(self, err)
        self.report({"INFO"}, f"Record duplicated from {name}")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_EflRemoveRecord(bpy.types.Operator):
    """Remove the active record from its effect"""
    bl_idname = "albam.efl_remove_record"
    bl_label = "Remove Record"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return record_object(context.active_object) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        ob = record_object(context.active_object)
        root = effect_root(ob)
        if len(all_record_objects(root)) <= 1:
            self.report({"ERROR"}, "An effect needs at least one record")
            return {"CANCELLED"}
        name = ob.name
        detach_rotation_handle(ob)
        for child in [o for o in bpy.data.objects if o.get("efl_generator") == ob]:
            bpy.data.objects.remove(child)
        bpy.data.objects.remove(ob)
        context.view_layer.objects.active = root
        try:
            apply_to_scene(context, root)
        except Exception as err:
            return _report_failure(self, err)
        self.report({"INFO"}, f"Removed {name}")
        return {"FINISHED"}


def _effect_items(self, context):
    current = effect_root(context.active_object)
    items = [(o.name, o.name, o.albam_asset.relative_path) for o in bpy.data.objects
             if o.albam_asset.extension == "efl" and o != current]
    return items or [("", "(no other effect imported)", "")]


@blender_registry.register_blender_type
class ALBAM_OT_EflCopyRecordTo(bpy.types.Operator):
    """Copy the active record into another imported effect (attached to the same joint when its armature has it)"""
    bl_idname = "albam.efl_copy_record_to"
    bl_label = "Copy Record to Effect"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "target"

    target: bpy.props.EnumProperty(name="Effect", items=_effect_items,
                                  description="The imported effect to copy the record into")

    @classmethod
    def poll(cls, context):
        return record_object(context.active_object) is not None

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        source = record_object(context.active_object)
        root = bpy.data.objects.get(self.target)
        if root is None or root.albam_asset.extension != "efl":
            self.report({"ERROR"}, "Pick an imported effect")
            return {"CANCELLED"}
        parent = root.parent if root.parent is not None and root.parent.type == "ARMATURE" else None
        name = source.name
        ob = _copy_record_object(context, source, root, parent)
        context.view_layer.objects.active = ob
        try:
            apply_to_scene(context, root)
        except Exception as err:
            return _report_failure(self, err)
        self.report({"INFO"}, f"Copied {name} into {self.target}")
        return {"FINISHED"}


def keyframe_prop_lists(prop):
    """(frames, params) of a keyframe prop as lists."""
    return as_list(prop.get("frames")) or [], as_list(prop.get("params")) or []
