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
from .efl import EffectList
from .efl.edit import (apply_keyframes, apply_props, apply_subs, as_list, record_from_raw, record_raw,
                       restructure)
from .efl.model import SLOTS

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
    """The record (generator) Empty for an object of an effect: itself, or the generator of a particle object."""
    if ob is None:
        return None
    if "efl_record" in ob:
        return ob
    generator = ob.get("efl_generator")
    return generator if generator is not None and "efl_record" in generator else None


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
    """True if records were added or removed since the effect was built."""
    count = EffectList.from_bytes(source_bytes(root)).records
    return bool(new_record_objects(root)) or len(record_objects(root)) != len(count)


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
    bl_obj["efl_export_notes"] = notes[:200]
    return [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]


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
    ob = bpy.data.objects.new(source.name + "+", None)
    for collection in root.users_collection:
        collection.objects.link(ob)
    ob.empty_display_type, ob.empty_display_size = source.empty_display_type, source.empty_display_size
    for key in list(source.keys()):
        if key.startswith("efl_") and key not in ("efl_root", "efl_raw", "efl_record", "efl_serial"):
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

    target: bpy.props.EnumProperty(name="Effect", items=_effect_items)

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
