"""Stand Rig panel for the Devil Trigger stand file (3D View sidebar > Stand Rig), put into the file by stand_rig.py.
Blender runs it when the file is opened with scripts allowed; otherwise open it in the Text Editor and Run Script.

Sword follows events: before each frame, Show Sword comes from event bit 31 (Stand Sword in Hand) of the first event
table of the stand's LMT animation playing (as uPlNeroDevil::updatePosition reads it): on = Yamato in the arm's right
hand, off = sheathed on the stand's joint 151.

The game only reads keys, so what the constraints make (IK, the arm's place on the stand, the retarget from Nero, the
sword grip) is baked when Albam exports an LMT of either armature (`animation.LMT_EXPORT_HOOKS`): each action marked
Bake on Export is copied, played with its other half (the stand action and the arm action in the same slot of the paired
LMTs, `arm_lmt_name`), the copy is baked and exported, and the copy is deleted, so the actions being edited keep only
their own keys. By default a stand action bakes when it keys the IK controls or the switches, and an arm action when its
stand half does. Only bones a constraint drives are baked (rotation, and location where the constraint sets it), and
every game joint the action doesn't key gets one constant key at the pose Blender shows (location too on the joints the
vanilla files move: stand 0, 150, 151, 164; arm 0, 150): the game holds a joint without a track as the motion before
left it (uModel::moveMotion), so unkeyed joints jerked when the next motion blended in. The stand's joint 0 is baked
without its turn, which goes into its children (spine_lower, hips; the pose is the same): no vanilla stand motion
rotates it (98 blocks), and turned it blends joint by joint against its counter-turning children into the next motion.
The arm's joint 0 keeps its turn (it places the arm on the stand; every vanilla arm motion rotates it). Albam's preview
of root motion (the root following the root_motion bone) is left out, as the game adds that itself.

Bake IK Frame (the key button next to each IK switch) keys one arm's bones on the current frame to the pose the IK
gives them, as ordinary FK keys (the right arm's forearm and hand into the arm's action), and can key that arm's IK
switch off from that frame. IK On Here (the button after it) turns it back on: the IK control and the pole move onto the
pose on screen and are keyed there, and the switch is keyed to 1. Neither keys anything before the action's first frame.

The grip switch (Right Hand Grip) says how much the right hand's fingers close on the sword while it's in the hand; at 0
the fingers play their own keys. Fingers from Grip (the key button next to it) keys the fingers (in the arm's action) on
the current frame to the pose on screen and keys the grip off from that frame, so the fingers start from the grip.

Remove Baked Keys thins the two actions playing after an old Bake for Export (a key on every frame): it deletes the keys
a constraint hides completely (IK on, the arm's place, the sword grip) and the keys in runs of one per frame that lie
on the line between their neighbours, keeping every frame where the bone's own keys show as it was, and the keys
before the action's first frame that change nothing.

A switch changed by hand while an action that doesn't key it plays is keyed (constant) on the action's first frame, and
so are the unkeyed switches of an action that bakes on export when another action is put on, as they were while it
played: each animation keeps its own value when another one is played in between.
"""
import contextlib
import bpy
from mathutils import Matrix, Quaternion

MARK = "albam_stand_rig"
FOLLOW, IK_L, IK_R = "follow_nero", "ik_arm_l", "ik_arm_r"
SWORD, SWORD_FOLLOW, GRIP_R = "show_sword", "sword_follows_events", "grip_r"
ROOT_MOTION = "root_motion"
HELPER_PREFIXES = ("MCH-", "FOL-", "IK-", "POLE-", "GRIP-", "IKP_", "IK_Foot")
IK_PROPS = ((IK_L, "Left Arm IK"), (IK_R, "Right Arm IK"))
SWITCHES = ((FOLLOW, "Follow Nero"),) + IK_PROPS + ((GRIP_R, "Right Hand Grip"),)
# the IK limbs' game joints, upper arm to hand, by armature: the right arm's forearm and hand are wp024's
LIMB_JOINTS = {"arm_l": (("stand", 8), ("stand", 9), ("stand", 10)), "arm_r": (("stand", 6), ("arm", 1), ("arm", 2))}
GRIP_FINGERS = range(3, 19)   # wp024's fingers
LOCATION_JOINTS = {"stand": (0, 150, 151, 164), "arm": (0, 150)}   # the joints the vanilla pl020 / wp024 LMTs move
BAKE = "stand_rig_bake"   # on an action: bake it at LMT export (missing: see bakes_on_export)
CONTROL_PREFIXES = ("IK-", "POLE-")
_EXPORTING = "stand_rig_ui_exporting"   # set while an export bakes: the arm isn't re-paired then


def rigs():
    stand = next((o for o in bpy.data.objects if o.get(MARK) == "stand"), None)
    arm = next((o for o in bpy.data.objects if o.get(MARK) == "arm"), None)
    return stand, arm


def _game(bone):
    return (bone.get("mtfw.anim_retarget") is not None and not bone.get("mtfw.not_joint")
            and bone.name != ROOT_MOTION and not bone.name.startswith(HELPER_PREFIXES))


def _root_motion_follow(ob, con):
    return con.type == "COPY_LOCATION" and con.target == ob and con.subtarget == ROOT_MOTION


def _active(con):
    return not con.mute and getattr(con, "enabled", True) and con.influence > 1e-6


def driven_bones(ob):
    """{bone name: whether its location is set too} for the game bones a constraint drives now"""
    out = {}
    for pb in ob.pose.bones:
        if not _game(ob.data.bones[pb.name]):
            continue
        cons = [c for c in pb.constraints if _active(c) and not _root_motion_follow(ob, c)]
        if cons:
            out[pb.name] = any(c.type in ("COPY_TRANSFORMS", "COPY_LOCATION", "CHILD_OF") or
                               (c.type == "TRANSFORM" and c.map_to == "LOCATION") for c in cons)
    return out


def _compat():
    from albam.lib import blender_compat
    return blender_compat


def _lmt_props(action):
    try:
        from albam.engines.mtfw import animation
        return animation.get_lmt_props(action)
    except Exception:
        return None


# -- the sword follows events ---------------------------------------------------------------------------------------

def event_value(action, frame):
    """the first event table's value at frame (the last event at or before it), or None without events"""
    props = _lmt_props(action)
    if props is None:
        return None
    from albam.engines.mtfw import animation
    best = None
    for i, event in enumerate(props.event_markers):
        if event.param_ev_type not in ("", "Hitbox"):
            continue
        marker = animation.find_event_marker(action, event, i)
        if marker is not None and marker.frame <= frame and (best is None or marker.frame >= best[0]):
            best = (marker.frame, event.encode())
    return None if best is None else best[1]


def _on_frame(scene, depsgraph=None):
    stand = rigs()[0]
    if stand is None or not stand.get(SWORD_FOLLOW):
        return
    try:
        from albam.engines.mtfw import animation
        action, at = animation.playing_lmt(stand, scene.frame_current)
    except Exception:   # a frame handler must not raise
        return
    value = event_value(action, at) if action is not None else None
    if value is None:
        return
    in_hand = bool((value >> 31) & 1)
    if bool(stand.get(SWORD)) != in_hand:
        stand[SWORD] = in_hand
        stand.update_tag()   # a property set from Python doesn't re-run the drivers that read it
        for ob in bpy.data.objects:
            if ob.get(MARK) in ("arm", "sword"):
                ob.update_tag()


def paired_arm_action(stand_action, arm, report):
    """the arm's half of the stand's action: the action in the same slot of the matching wp024 LMT, else the action
    named arm_<stand action>, made (same slot, frames, loop, frame rate) and added to that LMT when there is none"""
    src = _lmt_props(stand_action)
    group = _arm_group(stand_action, arm, report)
    if group is not None and src is not None:
        found = next((r.action for r in group.actions if r.action is not None and _lmt_props(r.action) is not None
                      and _lmt_props(r.action).lmt_id == src.lmt_id), None)
        if found is not None:
            return found
    name = "arm_" + stand_action.name
    action = bpy.data.actions.get(name)
    if action is None:
        action = bpy.data.actions.new(name)
        action.use_fake_user = True
        if hasattr(action, "albam_asset"):
            action.albam_asset.app_id = "dmc4"
        dst = _lmt_props(action)
        if src is not None and dst is not None:
            for prop in ("lmt_id", "num_frames", "loop_frames", "source_fps"):
                if hasattr(src, prop):
                    setattr(dst, prop, getattr(src, prop))
        report.append(f"made {action.name} for the arm")
    if group is not None and src is not None:
        if not any(r.action == action for r in group.actions):
            group.num_slots = max(group.num_slots, src.lmt_id + 1)
            group.add(action)
            report.append(f"added {action.name} to {group.name} (slot {src.lmt_id})")
    elif group is None:
        report.append(f"{stand_action.name} is in no LMT: add it to one (LMT panel), and the arm's half {action.name} goes "
                      "in the arm's LMT")
    return action


def sync_arm(report):
    """the arm plays the half of the stand's action (its own keys go there)"""
    stand, arm = rigs()
    stand_action = stand.animation_data.action if stand is not None and stand.animation_data else None
    if stand_action is None or arm is None:
        return None
    action = paired_arm_action(stand_action, arm, report)
    current = arm.animation_data.action if arm.animation_data else None
    if current != action:
        _compat().assign_action(arm, action)
        report.append(f"the arm plays {action.name}")
    return action


_LAST = "stand_rig_ui_last_stand_action"   # the stand action the arm was last paired with


def _sync_timer():
    report = []
    try:
        sync_arm(report)
    except Exception as err:   # a timer must not raise
        report.append(f"couldn't pair the arm's action: {err}")
    for line in report:
        print("stand rig:", line)
    return None


def start_frame(action, ob):
    """the action's first frame: its earliest key on a game bone or root_motion (keys of the controls, the switches
    and helpers don't count, as in LMT export)"""
    frames = []
    for fc in _compat().action_fcurves(action):
        path = fc.data_path
        if not path.startswith('pose.bones["'):
            continue
        name = path[len('pose.bones["'):path.find('"]', len('pose.bones["'))]
        bone = ob.data.bones.get(name) if ob is not None else None
        if name == ROOT_MOTION or (bone is not None and _game(bone)):
            frames += [kp.co[0] for kp in fc.keyframe_points]
    return int(round(min(frames))) if frames else int(round(action.frame_range[0]))


def trim_before_start(action, ob):
    """removes the keys before the last key at or before the action's first frame on every curve: they change nothing
    from that frame on (the frame-before keys IK buttons used to leave on frame -1); the number removed"""
    start = start_frame(action, ob)
    removed = 0
    for fc in list(_compat().action_fcurves(action)):
        before = [kp.co[0] for kp in fc.keyframe_points if kp.co[0] <= start + 1e-4]
        if len(before) < 2:
            continue
        last = max(before)
        for kp in [kp for kp in fc.keyframe_points if kp.co[0] < last - 1e-4]:
            fc.keyframe_points.remove(kp)
            removed += 1
        fc.update()
    return removed


def _seen_values(ob, switches):
    action = ob.animation_data.action if ob.animation_data else None
    return (action.as_pointer() if action else 0, {p: float(ob[p]) for p in switches if p in ob.keys()})


def _key_switch(action, ob, prop, value, group):
    """keys an unkeyed switch (constant) on the action's first frame; a switch keyed that way alone (one key) takes the
    new value"""
    compat = _compat()
    fc = compat.fcurve_find(action, f'["{prop}"]', 0, ob)
    if fc is not None:
        if len(fc.keyframe_points) == 1 and abs(fc.keyframe_points[0].co[1] - value) > 1e-6:
            fc.keyframe_points[0].co[1] = value
            fc.update()
            print(f"{group.lower()}: {prop} = {value:g} on {action.name}")
        return
    fc = compat.fcurve_new(action, f'["{prop}"]', 0, group, ob)
    kp = fc.keyframe_points.insert(start_frame(action, ob), value, options={"FAST"})
    kp.interpolation = "CONSTANT"
    fc.update()
    print(f"{group.lower()}: {prop} = {value:g} keyed on {action.name}'s first frame")


def _key_switches(ob, switches, seen_key, group):
    """keys the switches the playing action doesn't key when they changed since last seen; when the action changed,
    the switches of the one played before as they were then, if it bakes on export (vanilla ones stay as they are)"""
    action = ob.animation_data.action if ob is not None and ob.animation_data else None
    seen = bpy.app.driver_namespace.get(seen_key)
    now = _seen_values(ob, switches) if ob is not None else None
    bpy.app.driver_namespace[seen_key] = now
    if seen is None or now is None:
        return
    if seen[0] != now[0]:
        before = next((a for a in bpy.data.actions if a.as_pointer() == seen[0]), None) if seen[0] else None
        if before is not None and bakes_on_export(before):
            for prop, value in seen[1].items():
                _key_switch(before, ob, prop, value, group)
        return
    if action is None:
        return
    for prop, value in now[1].items():
        if abs(seen[1].get(prop, value) - value) >= 1e-6:
            _key_switch(action, ob, prop, value, group)


_SEEN = "stand_rig_ui_switches"   # (action pointer, switch values) last seen on the stand


def _switch_timer():
    try:
        _key_switches(rigs()[0], [p for p, _ in SWITCHES], _SEEN, "Stand Rig")
    except Exception as err:   # a timer must not raise
        print("stand rig: couldn't key the switch:", err)
    return None


def _on_depsgraph(scene, depsgraph):
    """the stand's action changed (LMT list, Action editor): pair the arm on a timer (no data changes in the handler);
    a switch changed: key it on a timer"""
    stand, arm = rigs()
    if stand is None or arm is None or bpy.app.driver_namespace.get(_EXPORTING):
        return
    if bpy.app.driver_namespace.get(_SEEN) != _seen_values(stand, [p for p, _ in SWITCHES]):
        if not bpy.app.timers.is_registered(_switch_timer):
            bpy.app.timers.register(_switch_timer, first_interval=0.0)
    action = stand.animation_data.action if stand.animation_data else None
    key = action.name if action is not None else None
    if bpy.app.driver_namespace.get(_LAST) == key:
        return
    bpy.app.driver_namespace[_LAST] = key
    if action is not None:
        bpy.app.timers.register(_sync_timer, first_interval=0.0)


def arm_lmt_name(stand_lmt_name):
    """the arm's LMT for a stand LMT: pl020 -> wp024 in the name (pl020_guardian_ex.lmt -> wp024_guardian_ex.lmt), else <name>_arm"""
    if "pl020" in stand_lmt_name:
        return stand_lmt_name.replace("pl020", "wp024")
    stem, dot, ext = stand_lmt_name.rpartition(".")
    return f"{stem}_arm.{ext}" if dot else f"{stand_lmt_name}_arm"


def _arm_group(stand_action, arm, report=None):
    """the arm's LMT that goes with the stand LMT holding the action (arm_lmt_name); with `report`, made when missing"""
    try:
        lmt_groups = bpy.context.scene.albam.lmt_groups
    except AttributeError:
        return None
    groups = list(lmt_groups.anim_group)
    stand_group = next((g for g in groups if any(r.action == stand_action for r in g.actions)), None)
    if stand_group is None:
        return None
    want = arm_lmt_name(stand_group.name)
    group = next((g for g in groups if g.armature == arm and g.name == want and g is not stand_group), None)
    if group is None and report is not None:
        group = lmt_groups.add(want)
        group.armature = arm
        group.num_slots = stand_group.num_slots
        report.append(f"made the arm's LMT {want} next to {stand_group.name}")
    return group


def _frames(actions):
    start, end = None, None
    stand, arm = rigs()
    for action in actions:
        owner = arm if is_arm_action(action) else stand
        a, b = start_frame(action, owner), action.frame_range[1]
        props = _lmt_props(action)
        if props is not None and getattr(props, "num_frames", 0) > 0:
            b = max(b, a + props.num_frames - 1)
        start = a if start is None else min(start, a)
        end = b if end is None else max(end, b)
    return range(int(round(start)), int(round(end)) + 1)


def _write(action, owner, bone, channel, size, frames, values):
    compat = _compat()
    path = f'pose.bones["{bone}"].{channel}'
    for i in range(size):
        old = compat.fcurve_find(action, path, i, owner)
        if old is not None:
            compat.fcurve_remove(action, old, owner)
        fc = compat.fcurve_new(action, path, i, bone, owner)
        fc.keyframe_points.add(len(frames))
        co = []
        for f, v in zip(frames, values):
            co += (f, v[i])
        fc.keyframe_points.foreach_set("co", co)
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
        fc.update()


def _joint_of(bone):
    return int(bone["mtfw.anim_retarget"])


def hold_unkeyed(context, ob, action, frame):
    """a constant key, the pose Blender shows on frame, for every game joint of `ob` the action doesn't rotate (and
    doesn't move, for the joints the vanilla LMTs move): the game keeps a joint without a track at the pose the motion
    before left it in (uModel::moveMotion copies the joints' current pose under the new motion's tracks), where Blender
    shows the rest pose. The number of joints"""
    paths = {fc.data_path for fc in _compat().fcurves_of(action, ob) if len(fc.keyframe_points)}
    moved = LOCATION_JOINTS.get(ob.get(MARK), ())
    context.scene.frame_set(frame)
    context.view_layer.update()
    count = 0
    for b in ob.data.bones:
        if not _game(b):
            continue
        pose = _visual_basis(ob, b.name)
        base = f'pose.bones["{b.name}"].'
        keyed = False
        if not any(base + channel in paths for channel in ROTATIONS):
            ob.pose.bones[b.name].rotation_mode = "QUATERNION"
            _write(action, ob, b.name, "rotation_quaternion", 4, [frame], [pose.to_quaternion()])
            keyed = True
        if _joint_of(b) in moved and base + "location" not in paths:
            _write(action, ob, b.name, "location", 3, [frame], [pose.to_translation()])
            keyed = True
        count += keyed
    return count


def _clear_other_rotations(action, ob, name):
    compat = _compat()
    for channel in ("rotation_euler", "rotation_axis_angle"):
        for i in range(4):
            old = compat.fcurve_find(action, f'pose.bones["{name}"].{channel}', i, ob)
            if old is not None:
                compat.fcurve_remove(action, old, ob)


def bake(context, jobs, frames):
    """keys what the constraints make into each (armature, action) of `jobs`, the actions playing on them, over
    `frames` (both armatures play while it samples); a line per job"""
    stand, arm = rigs()
    scene = context.scene
    keep = scene.frame_current
    follows = [c for ob in (stand, arm) for pb in ob.pose.bones for c in pb.constraints
               if _root_motion_follow(ob, c) and not c.mute]
    for c in follows:
        c.mute = True
    report = []
    try:
        frames = list(frames)
        driven = {ob.name: {} for ob, _ in jobs}   # bone -> whether its location is set too, on any frame
        samples = {(ob.name, pb.name): [] for ob, _ in jobs for pb in ob.pose.bones if _game(ob.data.bones[pb.name])
                   and any(not _root_motion_follow(ob, c) for c in pb.constraints)}
        # the stand's joint 0 only moves, as in the vanilla stand LMTs: its turn goes into its children (the pose stays
        # the same). Turned, it and the children counter-turning under it blend joint by joint into the next motion
        roots = {}   # armature name -> (joint 0's bone, it and its game children)
        for ob, _ in jobs:
            if ob is not stand:
                continue
            bones = ob.data.bones
            root = next((b.name for b in bones if _game(b) and _joint_of(b) == 0), None)
            if root is not None:
                roots[ob.name] = (root, [root] + [c.name for c in bones[root].children if _game(c)])
                for name in roots[ob.name][1]:
                    samples.setdefault((ob.name, name), [])
        turned = {name: False for name in roots}
        for f in frames:
            scene.frame_set(f)
            context.view_layer.update()
            for ob, _ in jobs:
                for name, with_location in driven_bones(ob).items():
                    driven[ob.name][name] = driven[ob.name].get(name, False) or with_location
                final = {pb.name: pb.matrix.copy() for pb in ob.pose.bones}
                bones = ob.data.bones
                if ob.name in roots:
                    root = roots[ob.name][0]
                    rest_turn = bones[root].matrix_local.to_3x3()
                    turned[ob.name] |= \
                        final[root].to_quaternion().rotation_difference(rest_turn.to_quaternion()).angle > 1e-4
                    final[root] = Matrix.Translation(final[root].to_translation()) @ rest_turn.to_4x4()
                for key, mats in samples.items():
                    if key[0] != ob.name:
                        continue
                    pb = ob.pose.bones[key[1]]
                    rest = bones[pb.name].matrix_local
                    base = final[pb.parent.name] @ bones[pb.parent.name].matrix_local.inverted() @ rest \
                        if pb.parent else rest
                    mats.append(base.inverted() @ final[pb.name])
        for ob, action in jobs:
            baked = dict(driven[ob.name])
            root, family = roots.get(ob.name, (None, []))
            if turned.get(ob.name):
                for name in family:
                    baked.setdefault(name, False)
            for name, with_location in baked.items():
                mats = samples[(ob.name, name)]
                if name == root:   # no turn: one key at rest, the location on every frame
                    _clear_other_rotations(action, ob, name)
                    ob.pose.bones[name].rotation_mode = "QUATERNION"
                    _write(action, ob, name, "rotation_quaternion", 4, frames[:1], [Quaternion()])
                    _write(action, ob, name, "location", 3, frames, [m.to_translation() for m in mats])
                    continue
                quats, prev = [], None
                for m in mats:
                    q = m.to_quaternion()
                    if prev is not None and prev.dot(q) < 0:
                        q.negate()
                    quats.append(q)
                    prev = q
                _clear_other_rotations(action, ob, name)
                ob.pose.bones[name].rotation_mode = "QUATERNION"
                _write(action, ob, name, "rotation_quaternion", 4, frames, quats)
                locations = [m.to_translation() for m in mats]
                if with_location or any(v.length > 1e-4 for v in locations):
                    _write(action, ob, name, "location", 3, frames, locations)
            holds = hold_unkeyed(context, ob, action, frames[0])
            report.append(f"{ob.name}: {len(baked)} bones baked, {holds} unkeyed joints held at their pose" +
                          (", joint 0's turn moved into its children" if turned.get(ob.name) else ""))
    finally:
        for c in follows:
            c.mute = False
        scene.frame_set(keep)
    return report


# -- bake on export -------------------------------------------------------------------------------------------------

def _groups():
    try:
        return list(bpy.context.scene.albam.lmt_groups.anim_group)
    except AttributeError:
        return []


def _slot(action):
    props = _lmt_props(action)
    return props.lmt_id if props is not None else None


def arm_half(stand_action):
    """the arm action that goes with a stand action (paired_arm_action, without making anything), or None"""
    stand, arm = rigs()
    group = _arm_group(stand_action, arm)
    if group is not None:
        found = next((r.action for r in group.actions if r.action is not None and _slot(r.action) == _slot(stand_action)),
                     None)
        if found is not None:
            return found
    return bpy.data.actions.get("arm_" + stand_action.name)


def stand_half(arm_action):
    """the stand action that goes with an arm action: the same slot of the stand LMT whose arm LMT holds it, or the
    action named without its arm_ prefix"""
    stand, arm = rigs()
    groups = _groups()
    for group in groups:
        if group.armature != arm or not any(r.action == arm_action for r in group.actions):
            continue
        for g in groups:
            if g.armature == stand and arm_lmt_name(g.name) == group.name:
                found = next((r.action for r in g.actions if r.action is not None and
                              _slot(r.action) == _slot(arm_action)), None)
                if found is not None:
                    return found
    name = arm_action.name
    return bpy.data.actions.get(name[4:]) if name.startswith("arm_") else None


def is_arm_action(action):
    stand, arm = rigs()
    return any(g.armature == arm and any(r.action == action for r in g.actions) for g in _groups()) or \
        (action.name.startswith("arm_") and arm is not None and not
         any(g.armature == stand and any(r.action == action for r in g.actions) for g in _groups()))


def uses_rig(action):
    """the action keys the IK controls or the switches"""
    switches = {f'["{prop}"]' for prop, _ in SWITCHES}
    for fc in _compat().action_fcurves(action):
        path = fc.data_path
        if path in switches or (path.startswith('pose.bones["') and
                                path[len('pose.bones["'):].startswith(CONTROL_PREFIXES)):
            return True
    return False


def bakes_on_export(action):
    value = action.get(BAKE)
    if value is not None:
        return bool(value)
    if is_arm_action(action):
        stand_action = stand_half(action)
        return stand_action is not None and bakes_on_export(stand_action)
    return uses_rig(action)


def _snapshot(stand, arm):
    out = {}
    for ob in (stand, arm):
        ad = ob.animation_data
        out[ob.name] = {"action": ad.action if ad else None, "slot": getattr(ad, "action_slot", None) if ad else None,
                        "pose": {pb.name: (pb.rotation_mode, pb.matrix_basis.copy()) for pb in ob.pose.bones}}
    props = [prop for prop, _ in SWITCHES] + [SWORD, SWORD_FOLLOW]
    out["props"] = {k: stand[k] for k in props if k in stand.keys()}
    return out


def _reset_props(stand, state):
    """the switches and the sword as they were before the export: an action that doesn't key them plays them so"""
    for k, v in state["props"].items():
        stand[k] = v
    stand.update_tag()
    for ob in bpy.data.objects:
        if ob.get(MARK) in ("arm", "sword"):
            ob.update_tag()


def _restore(stand, arm, state):
    for ob in (stand, arm):
        mine = state[ob.name]
        _compat().assign_action(ob, mine["action"])
        ad = ob.animation_data
        if mine["slot"] is not None and getattr(ad, "action_slot", None) != mine["slot"]:
            ad.action_slot = mine["slot"]
        for name, (mode, basis) in mine["pose"].items():
            pb = ob.pose.bones.get(name)
            if pb is not None:
                pb.rotation_mode = mode
                pb.matrix_basis = basis
        ob.update_tag()
    _reset_props(stand, state)


@contextlib.contextmanager
def export_hook(lmt_group, notes):
    """Albam's LMT export runs inside this: the LMT's actions marked Bake on Export are swapped for baked copies"""
    stand, arm = rigs()
    if stand is None or arm is None or lmt_group.armature not in (stand, arm):
        yield
        return
    exported = lmt_group.armature
    rows = [r for r in lmt_group.actions if r.action is not None and bakes_on_export(r.action)]
    if not rows:
        yield
        return
    from albam.engines.mtfw import animation
    context = bpy.context
    state = _snapshot(stand, arm)
    bpy.app.driver_namespace[_EXPORTING] = True
    swapped = []
    try:
        for row in rows:
            original = row.action
            other = arm_half(original) if exported == stand else stand_half(original)
            if other is None:
                notes.append(f"{original.name}: no {'arm' if exported == stand else 'stand'} action goes with it (the "
                             f"same slot of the paired LMT), so it was exported unbaked")
                continue
            for half in (original, other):
                if not any(len(fc.keyframe_points) for fc in _compat().action_fcurves(half)):
                    notes.append(f"{half.name} keys nothing: what the rig doesn't drive on its armature (the arm's "
                                 f"fingers without the grip) exports at the rest pose, whatever the viewport shows "
                                 f"(an empty action leaves the last animation's pose there)")
            copy = original.copy()
            copy.use_fake_user = False
            copy.name = original.name + " (baked)"
            swapped.append((row, original, copy))
            stand_action, arm_action = (copy, other) if exported == stand else (other, copy)
            _reset_props(stand, state)
            keyed = {fc.data_path for fc in _compat().action_fcurves(original if exported == stand else other)}
            unkeyed = [f"{label} {state['props'][prop]:g}" for prop, label in SWITCHES
                       if prop in state["props"] and f'["{prop}"]' not in keyed]
            if unkeyed:
                notes.append(f"{original.name}: baked with the switches its stand action doesn't key as they are now "
                             f"({', '.join(unkeyed)}): key them in the stand action to fix them")
            for ob, action in ((stand, stand_action), (arm, arm_action)):
                _compat().assign_action(ob, action)
                animation.follow_action(ob, action)   # the rest pose under it, as the game has for joints without tracks
            for line in bake(context, [(exported, copy)], _frames([stand_action, arm_action])):
                print(f"stand rig: {original.name}: {line} for export")
            row.action = copy
        yield
    finally:
        for row, original, copy in swapped:
            row.action = original
            notes[:] = [note.replace(copy.name, original.name) for note in notes]
        _restore(stand, arm, state)
        for _, _, copy in swapped:
            bpy.data.actions.remove(copy)
        bpy.app.driver_namespace[_SEEN] = _seen_values(stand, [p for p, _ in SWITCHES])
        bpy.app.driver_namespace.pop(_EXPORTING, None)
        action = stand.animation_data.action if stand.animation_data else None
        bpy.app.driver_namespace[_LAST] = action.name if action is not None else None
        context.scene.frame_set(context.scene.frame_current)


# -- clean actions baked into ---------------------------------------------------------------------------------------

ROTATIONS = ("rotation_quaternion", "rotation_euler", "rotation_axis_angle")
TOLERANCE = {"rotation_quaternion": 2e-4, "rotation_euler": 2e-4, "rotation_axis_angle": 2e-4, "location": 2e-5,
             "scale": 2e-5}


def _hidden(ob, pb):
    """the channels a constraint replaces completely on this frame"""
    out = set()
    for c in pb.constraints:
        if not _active(c) or _root_motion_follow(ob, c) or c.influence < 0.999:
            continue
        if getattr(c, "mix_mode", "REPLACE") != "REPLACE":
            continue
        if c.type == "COPY_TRANSFORMS":
            out.update(TOLERANCE)
        elif c.type == "COPY_ROTATION" and all(getattr(c, a, True) for a in ("use_x", "use_y", "use_z")):
            out.update(ROTATIONS)
    return out


def remove_baked_keys(context):
    stand, arm = rigs()
    jobs = [(ob, ob.animation_data.action) for ob in (stand, arm)
            if ob is not None and ob.animation_data is not None and ob.animation_data.action is not None]
    if not jobs:
        raise RuntimeError("Neither the stand nor the arm plays an action")
    compat = _compat()
    scene = context.scene
    keep = scene.frame_current
    bones = {ob.name: [pb for pb in ob.pose.bones if _game(ob.data.bones[pb.name]) and pb.constraints] for ob, _ in jobs}
    hidden = {(ob.name, pb.name): {} for ob, _ in jobs for pb in bones[ob.name]}   # -> {frame: channels hidden there}
    try:
        for f in _frames([action for _, action in jobs]):
            scene.frame_set(f)
            context.view_layer.update()
            for ob, _ in jobs:
                for pb in bones[ob.name]:
                    hidden[(ob.name, pb.name)][f] = _hidden(ob, pb)
    finally:
        scene.frame_set(keep)
    report = []
    for ob, action in jobs:
        removed = kept = 0
        for pb in bones[ob.name]:
            frames = hidden[(ob.name, pb.name)]
            if not any(frames.values()):
                continue
            for channel, tolerance in TOLERANCE.items():
                path = f'pose.bones["{pb.name}"].{channel}'
                curves = [fc for fc in compat.fcurves_of(action, ob) if fc.data_path == path and len(fc.keyframe_points)]
                if not curves:
                    continue
                r, k = _thin(curves, {f for f, ch in frames.items() if channel in ch}, tolerance)
                removed += r
                kept += k
                for fc in curves:
                    if not len(fc.keyframe_points):
                        compat.fcurve_remove(action, fc, ob)
        trimmed = trim_before_start(action, ob)
        report.append(f"{action.name}: {removed} frames of keys removed, {kept} kept, {trimmed} keys before the first "
                      "frame removed")
    scene.frame_set(keep)
    return report


def _key_at(fc, frame):
    return next((kp for kp in fc.keyframe_points if abs(kp.co[0] - frame) < 0.5), None)


def _thin(curves, hidden_frames, tolerance):
    """removes the channel's keys (on all its curves at once) on hidden frames and in runs of one key per frame, as long
    as every frame that isn't hidden keeps its value; (frames removed, frames left)"""
    start = int(round(min(fc.range()[0] for fc in curves)))
    end = int(round(max(fc.range()[1] for fc in curves)))
    shown = [f for f in range(start, end + 1) if f not in hidden_frames]
    target = {f: [fc.evaluate(f) for fc in curves] for f in shown}
    keyed = sorted({int(round(kp.co[0])) for fc in curves for kp in fc.keyframe_points})
    present = set(keyed)
    removed = 0
    for f in keyed:
        if f not in hidden_frames and not (f - 1 in present and f + 1 in present):
            continue
        saved = []
        for fc in curves:
            kp = _key_at(fc, f)
            if kp is not None:
                saved.append((fc, tuple(kp.co), kp.interpolation))
                fc.keyframe_points.remove(kp)
                fc.update()
        lo = max((g for g in present if g < f), default=start)
        hi = min((g for g in present if g > f), default=end)
        if all(abs(fc.evaluate(g) - target[g][i]) <= tolerance
               for g in shown if lo <= g <= hi for i, fc in enumerate(curves)):
            present.discard(f)
            removed += 1
            continue
        for fc, co, interpolation in saved:
            kp = fc.keyframe_points.insert(co[0], co[1], options={"FAST"})
            kp.interpolation = interpolation
            fc.update()
    return removed, len(present)


# -- bake one frame -------------------------------------------------------------------------------------------------

def _set_key(action, ob, path, index, group, frame, value, interpolation=None):
    """a key written into the curve directly (Blender's insert-key preferences, such as Only Insert Needed, don't apply)"""
    compat = _compat()
    fc = compat.fcurve_find(action, path, index, ob) or compat.fcurve_new(action, path, index, group, ob)
    key = fc.keyframe_points.insert(frame, value, options={"FAST"})   # replaces a key on that frame; Blender 5's
    # REPLACE option means "only replace" and adds nothing
    if interpolation:
        key.interpolation = interpolation
    fc.update()
    return fc


def _visual_basis(ob, name):
    """the bone's pose relative to its rest and its parent, constraints included"""
    pb, bones = ob.pose.bones[name], ob.data.bones
    rest = bones[name].matrix_local
    base = pb.parent.matrix @ bones[pb.parent.name].matrix_local.inverted() @ rest if pb.parent else rest
    return base.inverted() @ pb.matrix


def _key_rotations(action, ob, poses, frame):
    """keys the bones' rotations on frame to the given rest-relative rotations, in each bone's rotation mode"""
    for n, q in poses.items():
        pb = ob.pose.bones[n]
        if pb.rotation_mode == "QUATERNION":
            if q.dot(pb.rotation_quaternion) < 0:
                q.negate()
            channel, values = "rotation_quaternion", q
        elif pb.rotation_mode == "AXIS_ANGLE":
            axis, angle = q.to_axis_angle()
            channel, values = "rotation_axis_angle", (angle, *axis)
        else:
            channel, values = "rotation_euler", q.to_euler(pb.rotation_mode, pb.rotation_euler)
        for i, v in enumerate(values):
            _set_key(action, ob, f'pose.bones["{n}"].{channel}', i, n, frame, v)


def _playing_action(ob, who):
    action = ob.animation_data.action if ob is not None and ob.animation_data else None
    if action is None:
        raise RuntimeError(f"The {who} plays no action: give it one first (LMT panel > Add Animation; the arm gets "
                           "the stand action's half by itself)")
    return action


def _owners():
    stand, arm = rigs()
    return {"stand": stand, "arm": arm}


def _limb_bones(limb):
    """[(armature, bone name)] of the limb's game joints, upper arm to hand"""
    owners = _owners()
    by_joint = {key: {_joint_of(b): b.name for b in ob.data.bones if b.get("mtfw.anim_retarget") is not None
                      and _game(b)} for key, ob in owners.items() if ob is not None}
    out = []
    for key, joint in LIMB_JOINTS[limb]:
        name = by_joint.get(key, {}).get(joint)
        if name is None:
            raise RuntimeError(f"The {key} has no joint {joint}: rebuild the rig (stand_rig.py)")
        out.append((owners[key], name))
    return out


def _key_visual(context, bones, frame):
    """keys each (armature, bone)'s rotation on frame to the pose on screen (constraints included), into the action
    its armature plays; the bones keyed"""
    context.view_layer.update()
    poses = {}
    for ob, name in bones:   # all read before any key changes them
        poses.setdefault(ob, {})[name] = _visual_basis(ob, name).to_quaternion()
    for ob, by_name in poses.items():
        _key_rotations(_playing_action(ob, "stand" if ob.get(MARK) == "stand" else "arm"), ob, by_name, frame)
    return len(bones)


def _switch_from(stand, action, prop, frame, value):
    """keys the switch to value on frame, and to its value now on the frame before when that frame has no key"""
    path = f'["{prop}"]'
    fc = _compat().fcurve_find(action, path, 0, stand)
    if frame > start_frame(action, stand) and (fc is None or
                                               not any(abs(k.co[0] - (frame - 1)) < 0.5 for k in fc.keyframe_points)):
        before = fc.evaluate(frame - 1) if fc is not None and len(fc.keyframe_points) else stand.get(prop, 0.0)
        _set_key(action, stand, path, 0, "Stand Rig", frame - 1, before, "CONSTANT")
    _set_key(action, stand, path, 0, "Stand Rig", frame, value, "CONSTANT")
    stand[prop] = value


def _refresh(context, frame):
    for ob in rigs():
        if ob is not None:
            ob.update_tag()
    context.scene.frame_set(frame)


def bake_ik_frame(context, limb, switch_off):
    stand, arm = rigs()
    stand_action = _playing_action(stand, "stand")
    frame = context.scene.frame_current
    bones = _limb_bones(limb)
    count = _key_visual(context, bones, frame)
    if switch_off:
        _switch_from(stand, stand_action, f"ik_{limb}", frame, 0.0)
    _refresh(context, frame)
    return f"{limb}: {count} bones keyed on frame {frame}" + (", IK off from here" if switch_off else "")


def fingers_from_grip(context):
    stand, arm = rigs()
    stand_action = _playing_action(stand, "stand")
    _playing_action(arm, "arm")
    frame = context.scene.frame_current
    names = [b.name for b in arm.data.bones if b.get("mtfw.anim_retarget") is not None and _game(b)
             and _joint_of(b) in GRIP_FINGERS]
    count = _key_visual(context, [(arm, n) for n in names], frame)
    _switch_from(stand, stand_action, GRIP_R, frame, 0.0)
    _refresh(context, frame)
    return f"{count} fingers keyed on frame {frame}, grip off from here"


# -- IK back on ----------------------------------------------------------------------------------------------------

def _channels(pb, rotation=True):
    rotation_path = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(
        pb.rotation_mode, "rotation_euler")
    return ("location", rotation_path) if rotation else ("location",)


def _hold_before(action, ob, pb, channels, frame):
    """keys the bone's channels on the frame before as they play there, so moving the bone on frame doesn't change
    the frames before it"""
    compat = _compat()
    for channel in channels:
        path = f'pose.bones["{pb.name}"].{channel}'
        for i, now in enumerate(getattr(pb, channel)):
            fc = compat.fcurve_find(action, path, i, ob)
            if fc is not None and any(abs(k.co[0] - (frame - 1)) < 0.5 for k in fc.keyframe_points):
                continue
            value = fc.evaluate(frame - 1) if fc is not None and len(fc.keyframe_points) else now
            _set_key(action, ob, path, i, pb.name, frame - 1, value)


def _pole_position(u, m, e, current):
    """a point on the side the middle joint bends to, in the plane of the limb, as far from the limb's line as the
    pole is now"""
    line = e - u
    if line.length < 1e-6:
        return current
    d = line.normalized()

    def off(p):
        return (p - u) - d * (p - u).dot(d)
    side = off(m)
    if side.length < 1e-4:   # a straight limb: keep the pole's side
        side = off(current)
        if side.length < 1e-6:
            return current
    return m + side.normalized() * max(off(current).length, 0.1)


def ik_on_here(context, limb):
    stand, arm = rigs()
    action = _playing_action(stand, "stand")
    scene = context.scene
    frame = scene.frame_current
    bones = _limb_bones(limb)
    side = limb[-1]
    control, pole = stand.pose.bones[f"IK-hand_{side}"], stand.pose.bones[f"POLE-arm_{side}"]
    context.view_layer.update()
    to_stand = stand.matrix_world.inverted()
    # the pose on screen, which the IK takes over, in the stand's armature space (the controls live there)
    shown = [to_stand @ ob.matrix_world @ ob.pose.bones[n].matrix for ob, n in bones]
    shown_world = [ob.matrix_world @ ob.pose.bones[n].matrix for ob, n in bones]
    if frame > start_frame(action, stand):   # nothing before the first frame to keep
        _hold_before(action, stand, control, _channels(control), frame)
        _hold_before(action, stand, pole, _channels(pole, rotation=False), frame)

    u, m, e = (s.to_translation() for s in shown)
    old_q = control.rotation_quaternion.copy()
    control.matrix = shown[2]   # the control's rest is the hand's; no update before the keys below: it would play
    # the curves just keyed back over the new values
    pole.matrix = Matrix.Translation(_pole_position(u, m, e, pole.matrix.to_translation())) @ \
        pole.matrix.to_3x3().to_4x4()
    if control.rotation_mode == "QUATERNION" and control.rotation_quaternion.dot(old_q) < 0:
        control.rotation_quaternion.negate()
    for pb, channels in ((control, _channels(control)), (pole, _channels(pole, rotation=False))):
        for channel in channels:
            for i, v in enumerate(getattr(pb, channel)):
                _set_key(action, stand, f'pose.bones["{pb.name}"].{channel}', i, pb.name, frame, v)
    _switch_from(stand, action, f"ik_{limb}", frame, 1.0)
    _refresh(context, frame)
    context.view_layer.update()
    moved = max(((ob.matrix_world @ ob.pose.bones[n].matrix).to_translation() - s.to_translation()).length
                for (ob, n), s in zip(bones, shown_world))
    note = "" if stand.get(FOLLOW, 0.0) < 1e-6 else " (Follow Nero is on: the IK shows only as it goes off)"
    return f"{limb}: IK on from frame {frame} (the arm moved {moved * 1000:.1f} mm){note}"


_LIMB_ITEMS = [("arm_l", "Left Arm", "The left arm's bones (on the stand)"),
               ("arm_r", "Right Arm", "The right arm's bones (the upper arm on the stand, the forearm and hand on wp024)")]


class STANDRIG_OT_ik_on_here(bpy.types.Operator):
    """Turn this arm's IK back on from the current frame without a jump: the IK control and the pole go to the pose on
    screen and are keyed there (and on the frame before as they were, so earlier frames don't change), and the IK
    switch is keyed to 1 from this frame"""
    bl_idname = "stand_rig.ik_on_here"
    bl_label = "IK On Here"
    bl_options = {"REGISTER", "UNDO"}

    limb: bpy.props.EnumProperty(name="Arm", items=_LIMB_ITEMS, description="The arm whose IK comes back on")

    @classmethod
    def poll(cls, context):
        stand, arm = rigs()
        return stand is not None and arm is not None

    def execute(self, context):
        try:
            line = ik_on_here(context, self.limb)
        except RuntimeError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        self.report({"INFO"}, line)
        return {"FINISHED"}


class STANDRIG_OT_bake_ik_frame(bpy.types.Operator):
    """Key this arm's bones on the current frame to the pose the IK gives them (ordinary FK keys; the right arm's
    forearm and hand go into the arm's action), and key its IK switch off from this frame, so the arm keeps the pose
    without the IK. IK On Here (the button beside it) turns the IK back on later"""
    bl_idname = "stand_rig.bake_ik_frame"
    bl_label = "Bake IK Frame"
    bl_options = {"REGISTER", "UNDO"}

    limb: bpy.props.EnumProperty(name="Arm", items=_LIMB_ITEMS, description="The arm whose IK pose is keyed")
    switch_off: bpy.props.BoolProperty(
        name="Switch IK Off Here", default=True,
        description="Also key the arm's IK switch to 0 on this frame (and to its current value on the frame before, "
                    "when that frame has no key), so the keyed pose plays from here")

    @classmethod
    def poll(cls, context):
        stand, arm = rigs()
        return stand is not None and arm is not None

    def execute(self, context):
        try:
            line = bake_ik_frame(context, self.limb, self.switch_off)
        except RuntimeError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        self.report({"INFO"}, line)
        return {"FINISHED"}


class STANDRIG_OT_fingers_from_grip(bpy.types.Operator):
    """Key the right hand's fingers (in the arm's action) on the current frame to the pose on screen (the grip on the
    sword, or the blend the grip switch gives) and key the grip off from this frame (the frame before keeps its value),
    so the fingers start from the grip and can be posed by hand. Key the grip switch back to 1 to close the hand on the
    sword again"""
    bl_idname = "stand_rig.fingers_from_grip"
    bl_label = "Fingers from Grip"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        stand, arm = rigs()
        return stand is not None and arm is not None

    def execute(self, context):
        try:
            line = fingers_from_grip(context)
        except RuntimeError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        self.report({"INFO"}, line)
        return {"FINISHED"}


class STANDRIG_OT_remove_baked_keys(bpy.types.Operator):
    """Thin the actions the stand and the arm play after an old Bake for Export (a key on every frame): delete the keys
    a constraint hides completely (IK on, the arm's place, the sword grip) and the keys in one-per-frame runs that lie
    on the line between their neighbours, so every frame where the bone's own keys show stays as it was; also the keys
    before the action's first frame that change nothing. LMT export does the bake now"""
    bl_idname = "stand_rig.remove_baked_keys"
    bl_label = "Remove Baked Keys"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        stand, arm = rigs()
        return stand is not None and arm is not None

    def execute(self, context):
        try:
            lines = remove_baked_keys(context)
        except RuntimeError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        for line in lines:
            print("stand rig:", line)
        self.report({"INFO"}, "; ".join(lines))
        return {"FINISHED"}


class STANDRIG_PT_panel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Stand Rig"
    bl_label = "Stand Rig"

    @classmethod
    def poll(cls, context):
        return rigs()[0] is not None

    def draw(self, context):
        stand, arm = rigs()
        layout = self.layout
        col = layout.column(align=True)
        if FOLLOW in stand.keys():
            col.prop(stand, f'["{FOLLOW}"]', text="Follow Nero", slider=True)
        for prop, label in IK_PROPS:
            if prop in stand.keys():
                row = col.row(align=True)
                row.prop(stand, f'["{prop}"]', text=label, slider=True)
                row.operator(STANDRIG_OT_bake_ik_frame.bl_idname, text="", icon="KEYFRAME_HLT").limb = prop[3:]
                row.operator(STANDRIG_OT_ik_on_here.bl_idname, text="", icon="CON_KINEMATIC").limb = prop[3:]
        box = layout.box()
        box.label(text="Sword (wp040)")
        if SWORD_FOLLOW in stand.keys():
            box.prop(stand, f'["{SWORD_FOLLOW}"]', text="Follow Events")
        if SWORD in stand.keys():
            sub = box.column(align=True)
            sub.enabled = not stand.get(SWORD_FOLLOW)
            sub.prop(stand, f'["{SWORD}"]', text="In Hand" if stand.get(SWORD) else "In Hand (sheathed now)")
        if GRIP_R in stand.keys():
            row = box.row(align=True)
            row.prop(stand, f'["{GRIP_R}"]', text="Right Hand Grip", slider=True)
            row.operator(STANDRIG_OT_fingers_from_grip.bl_idname, text="", icon="KEYFRAME_HLT")
        for ob, title in ((stand, "Stand bones"), (arm, "Arm bones (wp024)")):
            if ob is None or not len(ob.data.collections):
                continue
            box = layout.box()
            box.label(text=title)
            grid = box.grid_flow(columns=2, align=True)
            for coll in ob.data.collections:
                grid.prop(coll, "is_visible", text=coll.name, toggle=True)
        if hasattr(bpy.types.Action, "stand_rig_bake_on_export"):
            box = layout.box()
            for ob in (stand, arm):
                action = ob.animation_data.action if ob is not None and ob.animation_data else None
                if action is not None:
                    box.label(text=action.name, icon="ACTION")
                    box.prop(action, "stand_rig_bake_on_export")
            box.operator(STANDRIG_OT_remove_baked_keys.bl_idname, icon="KEY_DEHLT")
        help_box = layout.box()
        for line in ("Pose the stand armature; the right hand's fingers",
                     "are on wp024 (select both, Ctrl+Tab).",
                     "LMT export bakes the IK, the arm and the grip."):
            help_box.label(text=line)


CLASSES = (STANDRIG_OT_bake_ik_frame, STANDRIG_OT_ik_on_here, STANDRIG_OT_fingers_from_grip,
           STANDRIG_OT_remove_baked_keys, STANDRIG_PT_panel)


_STASH = "stand_rig_ui_classes"   # the classes registered last time (running the text again replaces them)


_HANDLER = "stand_rig_ui_handler"   # the depsgraph handler registered last time
_FRAME = "stand_rig_ui_frame"       # the frame handler registered last time
_HOOK = "stand_rig_ui_export_hook"  # the LMT export hook registered last time


def _hooks():
    try:
        from albam.engines.mtfw import animation
    except Exception:
        return None
    return getattr(animation, "LMT_EXPORT_HOOKS", None)


def _get_bake(self):
    return bakes_on_export(self)


def _set_bake(self, value):
    self[BAKE] = bool(value)


def unregister():
    for cls in reversed(bpy.app.driver_namespace.pop(_STASH, ())):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    handler = bpy.app.driver_namespace.pop(_HANDLER, None)
    if handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(handler)
    handler = bpy.app.driver_namespace.pop(_FRAME, None)
    if handler in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(handler)
    bpy.app.driver_namespace.pop(_LAST, None)
    bpy.app.driver_namespace.pop(_SEEN, None)
    hook, hooks = bpy.app.driver_namespace.pop(_HOOK, None), _hooks()
    if hooks is not None and hook in hooks:
        hooks.remove(hook)
    if hasattr(bpy.types.Action, "stand_rig_bake_on_export"):
        del bpy.types.Action.stand_rig_bake_on_export


def register():
    unregister()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.driver_namespace[_STASH] = CLASSES
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    bpy.app.driver_namespace[_HANDLER] = _on_depsgraph
    bpy.app.handlers.frame_change_pre.append(_on_frame)
    bpy.app.driver_namespace[_FRAME] = _on_frame
    bpy.types.Action.stand_rig_bake_on_export = bpy.props.BoolProperty(
        name="Bake on Export", get=_get_bake, set=_set_bake,
        description="LMT export bakes what the rig's constraints make (IK, the arm's place on the stand, Follow Nero, "
                    "the sword grip) "
                    "into a copy of this action, played with its other half (stand or arm, the same slot of the paired "
                    "LMT), and exports the copy; the action keeps only its own keys. On by default for a stand action "
                    "that keys the IK controls or switches, and for an arm action whose stand half bakes; off exports "
                    "the keys as they are (a vanilla or already retargeted animation)")
    hooks = _hooks()
    if hooks is None:
        print("stand rig: this Albam has no LMT export hook: update Albam, or the constraints won't be exported")
    else:
        hooks.append(export_hook)
        bpy.app.driver_namespace[_HOOK] = export_hook


register()
