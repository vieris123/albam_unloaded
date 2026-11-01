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
from albam.lib import blender_compat as compat
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


# ---- Joint names ------------------------------------------------------------------------------------------------------

def _player_joints():
    """The player skeleton, joint number -> (name, parent joint; None = not checked). Read off Nero's pl000 and Dante's
    pl006 (2026-10-31): the body, arms, legs and fingers are the same on both; 153-155 are Dante's (chest, collars on
    the upper spine; Nero's 153 / 154 hang off the Devil Bringer forearm, so their parent doesn't match and they stay
    unnamed). The helper joints (2xx) are named by where they sit, not by a known role."""
    t = {0: ("root", None), 1: ("spine_lower", 0), 2: ("spine_upper", 1), 3: ("neck", 2), 4: ("head", 3),
         13: ("hips", 0), 152: ("weapon_back", 2), 153: ("chest", 2), 154: ("collar_r", 2), 155: ("collar_l", 2)}
    for s, arm, leg, hand, prop, arm_x, leg_x in (("r", 5, 14, 100, 150, 200, 208), ("l", 9, 18, 116, 151, 204, 212)):
        t[arm] = (f"shoulder_{s}", 2)
        t[arm + 1] = (f"upper_arm_{s}", arm)
        t[arm + 2] = (f"forearm_{s}", arm + 1)
        t[arm + 3] = (f"hand_{s}", arm + 2)
        t[leg] = (f"thigh_{s}", 13)
        t[leg + 1] = (f"shin_{s}", leg)
        t[leg + 2] = (f"foot_{s}", leg + 1)
        t[leg + 3] = (f"toe_{s}", leg + 2)
        wrist = arm + 3
        palm = hand + 9
        t[palm] = (f"palm_{s}", wrist)   # carries the ring and little fingers
        for base, finger, parent in ((hand, "thumb", wrist), (hand + 3, "index", wrist), (hand + 6, "middle", wrist),
                                     (palm + 1, "ring", palm), (palm + 4, "pinky", palm)):
            t[base] = (f"{finger}_1_{s}", parent)
            t[base + 1] = (f"{finger}_2_{s}", base)
            t[base + 2] = (f"{finger}_3_{s}", base + 1)
        t[prop] = (f"prop_{s}", wrist)   # what the hand holds
        t[arm_x] = (f"shoulder_deform_{s}", arm + 1)
        t[arm_x + 1] = (f"elbow_deform_{s}", arm + 2)
        t[arm_x + 2] = (f"wrist_deform_{s}", arm + 2)
        t[arm_x + 3] = (f"wrist_deform_2_{s}", arm_x + 2)
        t[leg_x] = (f"hip_deform_{s}", leg)
        t[leg_x + 1] = (f"buttock_{s}", leg)
        t[leg_x + 2] = (f"ankle_deform_{s}", leg + 1)
        t[leg_x + 3] = (f"knee_deform_{s}", leg + 1)
    return t


PLAYER_JOINTS = _player_joints()
CORE_JOINTS = range(22)   # body, arms and legs: a rig is a player-type skeleton when these all match
UNNAMED = "joint_{}"      # what Name Bones calls a joint the table has no name for


def player_joint_names(parents):
    """{joint: name} for a player-type skeleton, else {}. `parents` = {joint: parent joint or None}. Other models
    reuse the numbers for other bones (Nero's coat has its own 0-38), so the core joints must all have the table's
    parents, and every other joint gets its name only when its parent matches too."""
    if any(j not in parents or (PLAYER_JOINTS[j][1] is not None and parents[j] != PLAYER_JOINTS[j][1])
           for j in CORE_JOINTS):
        return {}
    return {j: name for j, (name, parent) in PLAYER_JOINTS.items()
            if j in parents and (parent is None or parents[j] == parent)}


def _parent_joint(bone):
    parent = bone.parent
    while parent is not None and is_helper(parent):
        parent = parent.parent
    return joint_of(parent) if parent is not None else None


def game_joint_names(armature_ob):
    """{joint: name} of an armature's bones (player-type skeletons only, see player_joint_names)"""
    if armature_ob is None or armature_ob.type != "ARMATURE":
        return {}
    parents = {}
    for b in joint_bones(armature_ob):
        j = joint_of(b)
        if j is not None:
            parents.setdefault(j, _parent_joint(b))
    return player_joint_names(parents)


def joint_label(armature_ob, joint, names=None):
    """'100 thumb_1_r' (the joint's name on a player-type skeleton), else '100'"""
    name = (game_joint_names(armature_ob) if names is None else names).get(joint)
    return f"{joint} {name}" if name else str(joint)


def player_joint_hint(joint):
    """what a joint number is in the player skeleton: 'thigh_r, under 13 hips', or None"""
    entry = PLAYER_JOINTS.get(joint)
    if entry is None:
        return None
    name, parent = entry
    return name if parent is None else f"{name}, under {parent} {PLAYER_JOINTS[parent][0]}"


def joint_choices(armature_ob):
    """[(joint, label, used by bone name or None)] for the joint picker: every player skeleton joint, and the other
    numbers the armature's bones have"""
    used = {}
    for b in joint_bones(armature_ob):
        j = joint_of(b)
        if j is not None:
            used.setdefault(j, b.name)
    out = []
    for j in sorted(set(PLAYER_JOINTS) | set(used)):
        hint = player_joint_hint(j)
        out.append((j, f"{j} {hint}" if hint else str(j), used.get(j)))
    return out


def _owned_actions(armature_ob):
    """the armature's actions besides the one it plays (Blender fixes that one when a bone is renamed): its LMTs',
    and on Blender 5 the ones with a slot made for it"""
    actions = set()
    for scene in bpy.data.scenes:
        for group in scene.albam.lmt_groups.anim_group:
            if group.armature == armature_ob:
                actions.update(item.action for item in group.actions if item.action is not None)
    identifier = "OB" + armature_ob.name
    for action in bpy.data.actions:
        if any(slot.identifier == identifier for slot in getattr(action, "slots", ())):
            actions.add(action)
    return actions


def _rename_in_action(action, renamed):
    from albam.lib import blender_compat as compat
    prefix = 'pose.bones["'
    groups = set()
    for fc in compat.action_fcurves(action):
        path = fc.data_path
        if path.startswith(prefix):
            end = path.find('"]', len(prefix))
            new = renamed.get(path[len(prefix):end]) if end > 0 else None
            if new is not None:
                fc.data_path = prefix + new + path[end:]
        if fc.group is not None:
            groups.add(fc.group)
    for group in groups:
        if group.name in renamed:
            group.name = renamed[group.name]


def _wanted_names(armature_ob, names):
    """{bone name: its joint's name} for the bones Name Bones would rename"""
    bones = [b for b in joint_bones(armature_ob) if joint_of(b) is not None]
    counts = {}
    for b in bones:
        counts[joint_of(b)] = counts.get(joint_of(b), 0) + 1
    wanted = {b.name: names.get(joint_of(b), UNNAMED.format(joint_of(b))) for b in bones if counts[joint_of(b)] == 1}
    return {old: new for old, new in wanted.items() if old != new}


def name_bones(armature_ob):
    """Renames a player-type skeleton's bones after their joints (`thumb_1_r`; a joint without a name: `joint_153`),
    which is what import does for them. Returns {old name: new name} ({} = not a player-type skeleton).

    Blender itself fixes the vertex groups, constraints, bone-parented objects (effects, collision shapes) and the
    action the armature plays; this fixes its other actions (LMTs), the chain preview's stored pose and new bones'
    mirror names. Bones sharing a joint number (a Shift+D copy not renumbered yet) keep their names."""
    names = game_joint_names(armature_ob)
    if not names:
        return {}
    wanted = _wanted_names(armature_ob, names)
    if not wanted:
        return {}
    data = armature_ob.data
    # two passes, so a bone can take a name another bone of the rig still has
    for k, old in enumerate(wanted):
        data.bones[old].name = f"albam_tmp_{k}"
    renamed = {}
    for k, (old, new) in enumerate(wanted.items()):
        bone = data.bones[f"albam_tmp_{k}"]
        bone.name = new
        renamed[old] = bone.name   # Blender suffixes a name held by a bone outside the rig's joints
    for action in _owned_actions(armature_ob):
        _rename_in_action(action, renamed)
    for ob in bpy.data.objects:
        base = ob.get("_phs_preview_base") if ob.parent == armature_ob else None
        if base is not None:
            for old in [key for key in base.keys() if key in renamed]:
                base[renamed[old]] = base[old]
                del base[old]
    for b in data.bones:
        if b.get(MIRROR_PROP) in renamed:
            b[MIRROR_PROP] = renamed[b[MIRROR_PROP]]
    return renamed


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
    if bone is not None and not (value and from_game_file(bone)):   # export needs the game model's bones
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
        description="A Blender-only helper bone: not exported to the .mod and given no joint number. Bones of the "
                    "imported game model can't be marked (its animations, chains and collision refer to them)")


@blender_registry.register_blender_type
class ALBAM_PT_GameJoint(bpy.types.Panel):
    bl_label = "Game Joint"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"

    @classmethod
    def poll(cls, context):
        # any armature: a rig too big for a model has its helper bones marked before New DMC4 Model numbers it
        ob = context.object
        return ob is not None and ob.type == "ARMATURE" and (context.bone is not None or context.edit_bone is not None)

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
        row = layout.row(align=True)
        row.operator("albam.set_not_joint", text="Mark Selected", icon="HIDE_ON").value = True
        row.operator("albam.set_not_joint", text="Unmark Selected", icon="HIDE_OFF").value = False
        if is_helper(bone):
            if not bone.get(NOT_JOINT_PROP):
                layout.label(text="Albam helper bone: not exported", icon="INFO")
            return
        col = layout.column()
        added = bool(bone.get(ADDED_PROP)) or JOINT_PROP not in bone
        row = col.row(align=True)
        row.enabled = added
        row.prop(settings, "number")
        if added:
            op = row.operator("albam.pick_joint_number", text="", icon="VIEWZOOM")
            op.armature, op.bone = ob.name, bone.name
        if not added:
            col.label(text="From the game file (fixed)", icon="LOCKED")
        names = game_joint_names(ob)
        j = joint_of(bone)
        if added and j is not None:
            hint = player_joint_hint(j)
            col.label(text=f"Player skeleton: {hint}" if hint else "Not a player skeleton joint", icon="BONE_DATA")
            parent = _parent_joint(bone)
            if hint and PLAYER_JOINTS[j][1] is not None and parent != PLAYER_JOINTS[j][1]:
                where = "has no parent joint" if parent is None else f"is under joint {parent}"
                col.label(text=f"(this bone {where})", icon="BLANK1")
        elif j is not None and names.get(j) and names[j] != bone.name:
            col.label(text=f"Player joint {joint_label(ob, j, names)}", icon="BONE_DATA")
        if added:
            col.prop_search(settings, "mirror", ob.data, "bones")
        if names and _wanted_names(ob, names):
            layout.operator("albam.name_bones_by_joint", icon="SORTALPHA")


def from_game_file(bone):
    """a bone of the imported .mod (its joint number came from the file): export needs it, so it can't be a helper"""
    return JOINT_PROP in bone and not bone.get(ADDED_PROP)


def set_not_joint(bones, value):
    """mark / unmark bones Not a Game Joint. Returns (changed bone names, skipped game-file bone names)."""
    changed, skipped = [], []
    for b in bones:
        if value and from_game_file(b):
            skipped.append(b.name)
        elif bool(b.get(NOT_JOINT_PROP)) != value:
            b[NOT_JOINT_PROP] = int(value)
            changed.append(b.name)
    return changed, skipped


@blender_registry.register_blender_type
class ALBAM_OT_SetNotJoint(bpy.types.Operator):
    bl_idname = "albam.set_not_joint"
    bl_label = "Set Not a Game Joint"
    bl_description = ("Mark (or unmark) every selected bone as Not a Game Joint: Blender-only helpers (controls, "
                      "retarget or IK bones) that export leaves out of the .mod and the LMTs. Bones of the imported "
                      "game model are skipped: its animations, chains and collision refer to them")
    bl_options = {"REGISTER", "UNDO"}

    value: bpy.props.BoolProperty(
        name="Not a Game Joint", default=True,
        description="On: mark the selected bones as Blender-only helpers. Off: make them game joints again")

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == "ARMATURE" and ob.mode != "EDIT"

    def execute(self, context):
        bones = compat.selected_bones(context.object)
        if not bones:
            self.report({"WARNING"}, "No bones selected")
            return {"CANCELLED"}
        changed, skipped = set_not_joint(bones, self.value)
        msg = f"{'Marked' if self.value else 'Unmarked'} {len(changed)} bone(s)"
        if skipped:
            msg += f"; skipped {len(skipped)} bone(s) of the game model ({', '.join(skipped[:5])}" + \
                   ("...)" if len(skipped) > 5 else ")")
        self.report({"WARNING"} if skipped else {"INFO"}, msg)
        return {"FINISHED"} if changed else {"CANCELLED"}


_choice_items = []   # dynamic enum items must stay referenced while Blender shows them


def _joint_items(self, context):
    _choice_items.clear()
    ob = bpy.data.objects.get(self.armature)
    if ob is None or ob.type != "ARMATURE":
        return _choice_items
    for j, label, user in joint_choices(ob):
        if user == self.bone:
            label += "  (this bone)"
        elif user is not None:
            label += f"  (used by {user})"
        _choice_items.append((str(j), label, ""))
    return _choice_items


@blender_registry.register_blender_type
class ALBAM_OT_PickJointNumber(bpy.types.Operator):
    bl_idname = "albam.pick_joint_number"
    bl_label = "Pick Joint Number"
    bl_description = ("Search the player skeleton's joint numbers by name (14 thigh_r, 100 thumb_1_r ...) and give "
                      "one to this bone. Numbers another bone already has are marked and refused. A rig that uses "
                      "the player's numbers can play the player's animations")
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    bl_property = "joint"

    armature: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    bone: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    joint: bpy.props.EnumProperty(name="Joint", items=_joint_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        ob = bpy.data.objects.get(self.armature)
        pose_bone = ob.pose.bones.get(self.bone) if ob is not None and ob.pose is not None else None
        if pose_bone is None:
            self.report({"ERROR"}, "The bone is gone")
            return {"CANCELLED"}
        value = int(self.joint)
        user = next((b.name for b in joint_bones(ob) if joint_of(b) == value and b.name != self.bone), None)
        if user is not None:
            self.report({"ERROR"}, f"Joint {value} is already bone {user}'s")
            return {"CANCELLED"}
        pose_bone.albam_joint.number = value
        hint = player_joint_hint(value)
        self.report({"INFO"}, f"{self.bone}: joint {value}" + (f" ({hint})" if hint else ""))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_NameBonesByJoint(bpy.types.Operator):
    bl_idname = "albam.name_bones_by_joint"
    bl_label = "Name Bones by Joint"
    bl_description = ("Rename this player-type rig's bones after their game joints (thumb_1_r, thigh_l ...; joints "
                      "without a name: joint_<number>), as import now does. Vertex groups, LMT actions, effects, "
                      "chains and collision shapes follow the new names; joint numbers don't change")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return is_game_armature(ob) and ob.mode != "EDIT"

    def execute(self, context):
        renamed = name_bones(context.object)
        if not renamed:
            self.report({"INFO"}, "Nothing to rename (not a player-type skeleton, or already named)")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Renamed {len(renamed)} bone(s)")
        return {"FINISHED"}
