"""Game joints of a model's armature: which Blender bone is which joint of the .mod bone table, so bones added in
Blender export (2026-10-16).

A bone is a game joint through its joint number (`mtfw.anim_retarget`, stored as a string by import): LMT tracks,
chains (.phs mBone), .col shapes and effects (ParentNo) all refer to joints by it. .mod export needs each bone's
index in the file's bone table (`export_layout`):
- the source file's bones keep their index, matched by joint number (renamed or reordered bones are fine; a deleted
  one is refused: every animation, chain, collision and effect file refers to it);
- bones added in Blender go after them, parents first. A new bone gets the highest free joint number below 254
  (`ensure_joint_numbers`, also run by LMT export and the chain / .col tools) unless it has one; a bone duplicated
  with Shift+D carries its original's number and gets a new one. Helper bones (`root_motion`, foot IK `IKP_` /
  `IK_Foot`, and bones marked Not a Game Joint) aren't joints.

What the game reads per joint (uModel::setModel 0x9E6D70; rModel's loader 0xA53F50 copies the tables raw): byte 0
the joint number, 1 the parent index, 2 the mirror (mSymmetryIndex, a bone index; 255 = left alone by mirrored
motions, updateMotionParam 0x9FA1E0), +8 mLength (= |offset| in every file) and +12 mOffset (the rest translation,
= the local matrix's translation in every file), the local (Lmat) and inverse bind (Imat) matrices and the joint table
(256 bytes, joint number -> index, rModel+0x120). Byte 3 (`idx_mapping`, 0 on Nero's coat, scattered values on bodies)
and +4 (`length`, no clear meaning) aren't read: new bones write 0 and their Blender length.
"""
import re

import bpy
from mathutils import Matrix

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry

JOINT_PROP = "mtfw.anim_retarget"
ADDED_PROP = "mtfw.added"          # set on bones that got their joint number in Blender (editable in the panel)
MIRROR_PROP = "mtfw.mirror"        # a new bone's mirror: bone name, "" = automatic
NOT_JOINT_PROP = "mtfw.not_joint"  # helper bones the game shouldn't get
RESERVED = (254, 255)              # 255 = root motion in LMTs, 254 = skipped by LMT import
MAX_BONES = 255                    # indices 0-254; 255 means "no parent / no mirror"
HELPER_NAMES = ("root_motion",)
HELPER_PREFIXES = ("IKP_", "IK_Foot")
# the game's model space (Y up) in Blender's armature space: a root joint's frame (animation.GAME_FRAME)
GAME_FRAME = Matrix(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
COPY_SUFFIX = re.compile(r"\.\d{3,}$")


def joint_of(bone):
    value = bone.get(JOINT_PROP)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def is_helper(bone):
    return (bone.name in HELPER_NAMES or bone.name.startswith(HELPER_PREFIXES) or bool(bone.get(NOT_JOINT_PROP)))


def joint_bones(armature_ob):
    """the armature's bones that are game joints, in Blender's order (parents before children)"""
    return [b for b in armature_ob.data.bones if not is_helper(b)]


def is_game_armature(armature_ob):
    return armature_ob is not None and armature_ob.type == "ARMATURE" and \
        any(JOINT_PROP in b for b in armature_ob.data.bones)


def _sync_edit_mode(armature_ob):
    if armature_ob.mode == "EDIT":
        armature_ob.update_from_editmode()


def _reserved_by_lmts(armature_ob):
    """joint numbers the scene's LMTs on this armature animate without a bone here (tracks import kept: joints of
    the character's other models, which share the LMT); a new joint must not take them"""
    used = set()
    scene = bpy.context.scene
    groups = getattr(getattr(scene, "albam", None), "lmt_groups", None)
    if groups is None:
        return used
    from albam.engines.mtfw.animation import get_kept_tracks
    for group in groups.anim_group:
        if group.armature != armature_ob:
            continue
        for row in group.actions:
            if row.action is not None:
                used.update(k["joint"] for k in get_kept_tracks(row.action))
    return used


def ensure_joint_numbers(armature_ob):
    """Give every joint bone a joint number: bones without one, and all but one of the bones sharing one (a
    Shift+D copy keeps its original's number; the bone whose name has no .001-style suffix keeps it), get the
    highest free number below 254. Returns [(bone name, number)] for the bones that got one."""
    _sync_edit_mode(armature_ob)
    bones = joint_bones(armature_ob)
    holders = {}
    for b in bones:
        j = joint_of(b)
        if j is not None:
            holders.setdefault(j, []).append(b)
    needs = [b for b in bones if joint_of(b) is None]
    for j, group in holders.items():
        if len(group) < 2 or j in RESERVED:
            continue
        keeper = next((b for b in group if not COPY_SUFFIX.search(b.name)), group[0])
        needs.extend(b for b in group if b != keeper)
    if not needs:
        return []
    renumbered = {b.name for b in needs}
    taken = {joint_of(b) for b in bones if b.name not in renumbered and joint_of(b) is not None}
    taken |= set(RESERVED) | _reserved_by_lmts(armature_ob)
    free = [j for j in range(253, -1, -1) if j not in taken]
    if len(free) < len(needs):
        raise AlbamCheckFailure(
            "No free joint numbers left", f"{len(needs)} new bones, {len(free)} numbers free (0-253)",
            "Remove some bones, or mark helper bones Not a Game Joint (Bone Properties > Game Joint)")
    assigned = []
    for b, j in zip(needs, free):
        b[JOINT_PROP] = str(j)
        b[ADDED_PROP] = 1
        assigned.append((b.name, j))
    return assigned


def number_new_rig(armature_ob):
    """For a new model (new_model.py): bones without a joint number get the lowest free ones in Blender's bone order
    (parents first), so a rig made in Blender starts at joint 0 like the game's. Bones that have a number keep it
    (a rig taken from a game model keeps its animations). Returns [(bone name, number)] for the bones numbered."""
    _sync_edit_mode(armature_ob)
    bones = joint_bones(armature_ob)
    taken = {joint_of(b) for b in bones if joint_of(b) is not None} | set(RESERVED)
    needs = [b for b in bones if joint_of(b) is None]
    free = [j for j in range(254) if j not in taken]
    if len(free) < len(needs):
        raise AlbamCheckFailure(
            "Too many bones", f"{len(needs)} bones without a joint number, {len(free)} numbers free (0-253)",
            "Remove some bones, or mark helper bones Not a Game Joint (Bone Properties > Game Joint)")
    assigned = []
    for b, j in zip(needs, free):
        b[JOINT_PROP] = str(j)
        b[ADDED_PROP] = 1
        assigned.append((b.name, j))
    return assigned


def export_layout(armature_ob, src_bones):
    """[(bone, source index or None)] in .mod bone-table order: the source file's bones by joint number, then the
    bones added in Blender, parents first. Raises AlbamCheckFailure for deleted source bones, too many bones, and a
    source bone moved under a new one (a parent must come before its children)."""
    ensure_joint_numbers(armature_ob)
    bones = joint_bones(armature_ob)
    by_joint = {}
    for b in bones:
        by_joint.setdefault(joint_of(b), []).append(b)
    entries, taken, missing = [], set(), []
    for i, src in enumerate(src_bones):
        candidates = [b for b in by_joint.get(src.idx_anim_map, []) if b.name not in taken]
        # joint 255 can repeat (a model's unanimated joints): prefer the bone still named by its index
        b = next((c for c in candidates if c.name == str(i)), candidates[0] if candidates else None)
        if b is None:
            missing.append(f"index {i} (joint {src.idx_anim_map})")
            continue
        taken.add(b.name)
        entries.append((b, i))
    if missing:
        raise AlbamCheckFailure(
            "Bones of the source model were deleted", "Missing: " + ", ".join(missing[:20]),
            "Undo the deletion. Removing a game model's bones isn't supported yet: its animations, chains, collision "
            "shapes and effects refer to them by joint number")
    entries += [(b, None) for b in bones if b.name not in taken]
    if len(entries) > MAX_BONES:
        raise AlbamCheckFailure(
            "Too many bones", f"{len(entries)} joints, the .mod bone table holds {MAX_BONES}",
            "Remove bones, or mark helper bones Not a Game Joint (Bone Properties > Game Joint)")
    index = {b.name: i for i, (b, _) in enumerate(entries)}
    wrong = [b.name for i, (b, _) in enumerate(entries)
             if b.parent is not None and index.get(b.parent.name, -1) > i]
    if wrong:
        raise AlbamCheckFailure(
            "Bones of the source model were moved under new bones", ", ".join(wrong[:20]),
            "The game needs every parent before its children, and new bones go after the model's own: parent the "
            "new bones under the model's bones instead")
    return entries


def bone_index_map(entries):
    return {b.name: i for i, (b, _) in enumerate(entries)}


def parent_index(bone, index):
    """the bone-table index of the bone's parent; 255 = none (or a helper bone, which isn't exported)"""
    parent = bone.parent
    while parent is not None and parent.name not in index:
        parent = parent.parent
    return index[parent.name] if parent is not None else 255


def local_matrix(bone, index):
    """the joint's Lmat (game units, column form; the file stores it transposed): its rest frame in its parent's,
    or in the game's model space for a root"""
    parent = bone.parent
    while parent is not None and parent.name not in index:
        parent = parent.parent
    base = parent.matrix_local if parent is not None else GAME_FRAME
    m = base.inverted() @ bone.matrix_local
    m.translation *= 100.0
    return m


def mirror_index(bone, index, armature_ob):
    """a new bone's mirror (bone-table index): the bone picked in Game Joint, else the bone whose rest head and tail
    are its reflection across the model's X = 0 plane, else itself on the centre line, else 255 (not mirrored)"""
    picked = bone.get(MIRROR_PROP) or ""
    if picked:
        return index.get(picked, 255)
    head, tail = bone.head_local, bone.tail_local
    if abs(head.x) < 1e-4 and abs(tail.x) < 1e-4:
        return index[bone.name]
    best = None
    for other in armature_ob.data.bones:
        if other.name == bone.name or other.name not in index:
            continue
        dh = (other.head_local - head.reflect((1.0, 0.0, 0.0))).length
        if dh < 1e-3:
            dt = (other.tail_local - tail.reflect((1.0, 0.0, 0.0))).length
            score = dh + dt
            if best is None or score < best[0]:
                best = (score, other.name)
    return index[best[1]] if best else 255


# ---- Bone Properties > Game Joint ------------------------------------------------------------------------------------

def _data_bone(self):
    """the armature Bone behind a PoseBone's albam_joint group"""
    for ob in bpy.data.objects:
        if ob.type == "ARMATURE" and ob.pose is not None:
            for pb in ob.pose.bones:
                if pb.albam_joint.as_pointer() == self.as_pointer():
                    return pb.bone
    return None


def _get_number(self):
    bone = _data_bone(self)
    j = joint_of(bone) if bone is not None else None
    return -1 if j is None else j


def _set_number(self, value):
    """refuses numbers another bone of the armature has, and the reserved ones (no way to report from a setter:
    the field just keeps its value)"""
    bone = _data_bone(self)
    if bone is None or value in RESERVED or not 0 <= value <= 253:
        return
    arm = bone.id_data
    if any(joint_of(b) == value for b in arm.bones if b != bone):
        return
    bone[JOINT_PROP] = str(value)
    bone[ADDED_PROP] = 1


def _get_mirror(self):
    bone = _data_bone(self)
    return (bone.get(MIRROR_PROP) or "") if bone is not None else ""


def _set_mirror(self, value):
    bone = _data_bone(self)
    if bone is not None:
        bone[MIRROR_PROP] = value


def _get_not_joint(self):
    bone = _data_bone(self)
    return bool(bone.get(NOT_JOINT_PROP)) if bone is not None else False


def _set_not_joint(self, value):
    bone = _data_bone(self)
    if bone is not None:
        bone[NOT_JOINT_PROP] = int(value)


@blender_registry.register_blender_props_to_type("PoseBone", "albam_joint")
class AlbamGameJoint(bpy.types.PropertyGroup):
    number: bpy.props.IntProperty(
        name="Joint Number", get=_get_number, set=_set_number, min=-1, max=253,
        description="The number LMT tracks, chains, collision shapes and effects use for this bone. -1: none yet "
                    "(given on export, the highest free number). Another bone's number, 254 and 255 are refused")
    mirror: bpy.props.StringProperty(
        name="Mirror Bone", get=_get_mirror, set=_set_mirror,
        description="The bone mirrored animations swap this one with (left / right pairs). Empty: automatic (the "
                    "bone at the reflected position across the model's centre, itself on the centre line, else none)")
    not_joint: bpy.props.BoolProperty(
        name="Not a Game Joint", get=_get_not_joint, set=_set_not_joint,
        description="A Blender-only helper bone: not exported to the .mod and given no joint number")


@blender_registry.register_blender_type
class ALBAM_PT_GameJoint(bpy.types.Panel):
    bl_label = "Game Joint"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"

    @classmethod
    def poll(cls, context):
        return is_game_armature(context.object) and (context.bone is not None or context.edit_bone is not None)

    def draw(self, context):
        layout = self.layout
        ob = context.object
        if context.mode == "EDIT_ARMATURE" or context.bone is None:
            layout.label(text="Leave Edit Mode to see the joint settings", icon="INFO")
            return
        bone = context.bone
        pose_bone = ob.pose.bones.get(bone.name)
        if pose_bone is None:
            return
        settings = pose_bone.albam_joint
        layout.prop(settings, "not_joint")
        if is_helper(bone):
            if not bone.get(NOT_JOINT_PROP):
                layout.label(text="Albam helper bone: not exported", icon="INFO")
            return
        col = layout.column()
        added = bool(bone.get(ADDED_PROP)) or JOINT_PROP not in bone
        row = col.row()
        row.enabled = added
        row.prop(settings, "number")
        if not added:
            col.label(text="From the game file (fixed)", icon="LOCKED")
        if added:
            col.prop_search(settings, "mirror", ob.data, "bones")
