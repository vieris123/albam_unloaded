"""Nero Rig panel (3D View sidebar > Nero Rig), put into the file by nero_rig.py. Blender runs it when the file is
opened with scripts allowed; otherwise open it in the Text Editor and Run Script.

Weapons follow events: before each frame, Red Queen's place and Blue Rose come from the first event table of the LMT
animation playing on Nero (event bits 27-28 and 26, as uPlWpRedQueen / uPlWpBlueRose::update read them).

The game only reads keys, so what the constraints make (IK, the finger grips) is baked when Albam exports the LMT
(`animation.LMT_EXPORT_HOOKS`): each action marked Bake on Export (by default the ones that key the IK controls or
switches) is copied, the copy is baked and exported, and the copy is deleted, so the actions being edited keep only
their own keys. Only bones a constraint drives are baked, and every game joint the action doesn't key gets one
constant key at the pose Blender shows: the game holds a joint without a track as the motion before left it
(uModel::moveMotion), so unkeyed deform bones jerked when the next motion blended in. Joint 0 (root) is baked
without its turn, which goes into its children (spine_lower, hips; the pose is the same): Nero's vanilla LMTs turn
it in 3 blocks of 231, and turned it blends joint by joint against its counter-turning children into the next
motion, so the body wobbled as a dodge ended. Albam's preview of root motion (the root following the
root_motion bone) is left out, as the game adds that itself: the bake holds root_motion at rest, so the feet controls
under it (and the IK legs) stay with the body.

Remove Baked Keys thins an action baked into before (a key on every frame): it deletes the keys a constraint hides
completely (IK on, a grip closed) and the keys in runs of one per frame that lie on the line between their neighbours,
keeping every frame where the bone's own keys show as it was.

Bake IK Frame (the key button next to each IK switch) keys one limb's bones on the current frame to the pose the IK
gives them, as ordinary FK keys, and can key that limb's IK switch off from that frame (on at the frame before, so
the frames before keep their IK): the limb holds the pose without the IK.

IK On Here (the button after it) turns it back on: the IK control and the pole move onto the pose on screen and are
keyed there, and the switch is keyed to 1, so the limb carries on from that pose under the IK. Neither keys anything
before the action's first frame.

The grip switches (Left / Right Hand Grip) say how much a hand's fingers close on the weapon it holds; at 0 the fingers
play their own keys (a gun spin). Fingers from Grip (the key button next to each) keys that hand's fingers on the
current frame to the pose on screen and keys the grip off from that frame, so the fingers start from the grip.

A switch changed by hand while an action that doesn't key it plays is keyed (constant) on the action's first frame, and
so are the unkeyed switches of an action that bakes on export when another action is put on, as they were while it
played: each animation keeps its own value when another one is played in between.
"""
import contextlib
import bpy
from mathutils import Matrix, Quaternion

MARK = "albam_nero_rig"
IK_PROPS = (("ik_arm_l", "Left Arm IK"), ("ik_arm_r", "Right Arm IK"), ("ik_leg_l", "Left Leg IK"),
            ("ik_leg_r", "Right Leg IK"))
GRIP_PROPS = (("grip_l", "Left Hand Grip"), ("grip_r", "Right Hand Grip"))
SWITCHES = IK_PROPS + GRIP_PROPS
GRIP_FINGERS = {"grip_l": range(116, 132), "grip_r": range(100, 116)}
PLACE, GUN, FOLLOW_EVENTS = "red_queen_place", "show_blue_rose", "weapons_follow_events"
PLACE_NAMES = ("back", "right hand", "left hand")
ROOT_MOTION = "root_motion"
HELPER_PREFIXES = ("MCH-", "FOL-", "IK-", "POLE-", "GRIP-", "IKP_", "IK_Foot")
LIMB_JOINTS = {"arm_l": (10, 11, 12), "arm_r": (6, 7, 8), "leg_l": (18, 19, 20), "leg_r": (14, 15, 16)}
BAKE = "nero_rig_bake"   # on an action: bake it at LMT export (missing: when it keys the IK controls or switches)
CONTROL_PREFIXES = ("IK-", "POLE-")


def nero():
    return next((o for o in bpy.data.objects if o.get(MARK) == "nero"), None)


def _game(bone):
    return (bone.get("mtfw.anim_retarget") is not None and not bone.get("mtfw.not_joint")
            and bone.name != ROOT_MOTION and not bone.name.startswith(HELPER_PREFIXES))


def _root_motion_follow(ob, con):
    return con.type == "COPY_LOCATION" and con.target == ob and con.subtarget == ROOT_MOTION


def _active(con):
    return not con.mute and getattr(con, "enabled", True) and con.influence > 1e-6


def driven_bones(ob):
    """the game bones a constraint drives now"""
    return [pb.name for pb in ob.pose.bones if _game(ob.data.bones[pb.name]) and
            any(_active(c) and not _root_motion_follow(ob, c) for c in pb.constraints)]


def _compat():
    from albam.lib import blender_compat
    return blender_compat


def _lmt_props(action):
    try:
        from albam.engines.mtfw import animation
        return animation.get_lmt_props(action)
    except Exception:
        return None


# -- weapons follow events -----------------------------------------------------------------------------------------

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
    ob = nero()
    if ob is None or not ob.get(FOLLOW_EVENTS):
        return
    try:
        from albam.engines.mtfw import animation
        action, at = animation.playing_lmt(ob, scene.frame_current)
    except Exception:   # a frame handler must not raise
        return
    value = event_value(action, at) if action is not None else None
    if value is None:
        return
    place, gun = min((value >> 27) & 3, 2), bool((value >> 26) & 1)
    if ob.get(PLACE) != place or bool(ob.get(GUN)) != gun:
        ob[PLACE], ob[GUN] = place, gun
        ob.update_tag()   # a property set from Python doesn't re-run the drivers that read it
        for weapon in bpy.data.objects:
            if weapon.get(MARK) in ("red_queen", "blue_rose"):
                weapon.update_tag()


# -- bake ----------------------------------------------------------------------------------------------------------

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


_SEEN = "nero_rig_ui_switches"         # (action pointer, switch values) last seen on Nero
_EXPORTING = "nero_rig_ui_exporting"   # set while an export bakes: the rig's own switch changes aren't keyed
_DEPSGRAPH = "nero_rig_ui_depsgraph"   # the depsgraph handler registered last time


def _switch_timer():
    try:
        _key_switches(nero(), [p for p, _ in SWITCHES], _SEEN, "Nero Rig")
    except Exception as err:   # a timer must not raise
        print("nero rig: couldn't key the switch:", err)
    return None


def _on_depsgraph(scene, depsgraph):
    """an IK or grip switch changed: key it on a timer (no data changes in the handler)"""
    ob = nero()
    if ob is None or bpy.app.driver_namespace.get(_EXPORTING):
        return
    if not any(isinstance(u.id, bpy.types.Object) and u.id.original == ob for u in depsgraph.updates):
        return
    if bpy.app.driver_namespace.get(_SEEN) != _seen_values(ob, [p for p, _ in SWITCHES]):
        if not bpy.app.timers.is_registered(_switch_timer):
            bpy.app.timers.register(_switch_timer, first_interval=0.0)

def _frames(action):
    a, b = start_frame(action, nero()), action.frame_range[1]
    props = _lmt_props(action)
    if props is not None and getattr(props, "num_frames", 0) > 0:
        b = max(b, a + props.num_frames - 1)
    return range(int(round(a)), int(round(b)) + 1)


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


LOCATION_JOINTS = (0, 150, 151, 152, 153)   # the joints Nero's vanilla LMTs give location tracks


def hold_unkeyed(context, action, frame):
    """a constant key, the pose Blender shows on frame, for every game joint the action doesn't rotate (and doesn't
    move, for the joints the game's LMTs move): the game keeps a joint without a track at the pose the motion before
    left it in (uModel::moveMotion copies the joints' current pose under the new motion's tracks), where Blender shows
    the rest pose. The number of joints"""
    ob = nero()
    compat = _compat()
    paths = {fc.data_path for fc in compat.fcurves_of(action, ob) if len(fc.keyframe_points)}
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
            q = pose.to_quaternion()
            _write(action, ob, b.name, "rotation_quaternion", 4, [frame], [q])
            keyed = True
        if int(b["mtfw.anim_retarget"]) in LOCATION_JOINTS and base + "location" not in paths:
            _write(action, ob, b.name, "location", 3, [frame], [pose.to_translation()])
            keyed = True
        count += keyed
    return count


def bake(context, action):
    """keys what the constraints make into `action`, which Nero plays; a line for the console"""
    ob = nero()
    compat = _compat()
    scene = context.scene
    keep = scene.frame_current
    follows = [c for pb in ob.pose.bones for c in pb.constraints if _root_motion_follow(ob, c) and not c.mute]
    for c in follows:
        c.mute = True
    # root motion out of everything: the feet and knee poles hang from root_motion, the root follows it
    root_motion = ob.pose.bones.get(ROOT_MOTION)
    held = [fc for fc in compat.fcurves_of(action, ob)
            if fc.data_path.startswith(f'pose.bones["{ROOT_MOTION}"].') and not fc.mute]
    for fc in held:
        fc.mute = True
    basis = root_motion.matrix_basis.copy() if root_motion else None
    if root_motion:
        root_motion.matrix_basis = Matrix.Identity(4)
    try:
        frames = list(_frames(action))
        bones = ob.data.bones
        candidates = [pb.name for pb in ob.pose.bones if _game(bones[pb.name]) and
                      any(not _root_motion_follow(ob, c) for c in pb.constraints)]
        # joint 0 only moves, as in the game's LMTs: its turn goes into its children (the pose stays the same).
        # Turned, it and the children counter-turning under it blend joint by joint into the next motion, and the
        # body wobbles for the length of the blend
        root = next((b.name for b in bones if _game(b) and int(b["mtfw.anim_retarget"]) == 0), None)
        root_family = [root] + [c.name for c in bones[root].children if _game(c)] if root else []
        candidates += [n for n in root_family if n not in candidates]
        samples = {name: [] for name in candidates}
        driven = set()
        turned = False
        for f in frames:
            scene.frame_set(f)
            context.view_layer.update()
            driven.update(driven_bones(ob))   # the grips switch with the weapons, so any frame counts
            final = {pb.name: pb.matrix.copy() for pb in ob.pose.bones}
            if root:
                rest_turn = bones[root].matrix_local.to_3x3()
                turned |= final[root].to_quaternion().rotation_difference(rest_turn.to_quaternion()).angle > 1e-4
                final[root] = Matrix.Translation(final[root].to_translation()) @ rest_turn.to_4x4()
            for name in candidates:
                pb = ob.pose.bones[name]
                rest = bones[name].matrix_local
                base = final[pb.parent.name] @ bones[pb.parent.name].matrix_local.inverted() @ rest \
                    if pb.parent else rest
                samples[name].append(base.inverted() @ final[name])
        samples = {name: mats for name, mats in samples.items()
                   if name in driven or (turned and name in root_family)}
        for name, mats in samples.items():
            if name == root:   # no turn: one key at rest, the location on every frame
                for channel in ("rotation_euler", "rotation_axis_angle"):
                    for i in range(4):
                        old = compat.fcurve_find(action, f'pose.bones["{name}"].{channel}', i, ob)
                        if old is not None:
                            compat.fcurve_remove(action, old, ob)
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
            for channel in ("rotation_euler", "rotation_axis_angle"):
                for i in range(4):
                    old = compat.fcurve_find(action, f'pose.bones["{name}"].{channel}', i, ob)
                    if old is not None:
                        compat.fcurve_remove(action, old, ob)
            ob.pose.bones[name].rotation_mode = "QUATERNION"
            _write(action, ob, name, "rotation_quaternion", 4, frames, quats)
            locations = [m.to_translation() for m in mats]
            if any(v.length > 1e-4 for v in locations):
                _write(action, ob, name, "location", 3, frames, locations)
        holds = hold_unkeyed(context, action, frames[0])
    finally:
        for c in follows:
            c.mute = False
        for fc in held:
            fc.mute = False
        if root_motion:
            root_motion.matrix_basis = basis
        scene.frame_set(keep)
    return f"{len(samples)} bones baked, {holds} unkeyed joints held at their pose"


def uses_rig(action):
    """the action keys the IK controls or switches"""
    switches = {f'["{prop}"]' for prop, _ in SWITCHES}
    for fc in _compat().action_fcurves(action):
        path = fc.data_path
        if path in switches or (path.startswith('pose.bones["') and
                                path[len('pose.bones["'):].startswith(CONTROL_PREFIXES)):
            return True
    return False


def bakes_on_export(action):
    value = action.get(BAKE)
    return uses_rig(action) if value is None else bool(value)


def _snapshot(ob):
    ad = ob.animation_data
    props = [prop for prop, _ in SWITCHES] + [PLACE, GUN]
    return {"action": ad.action if ad else None, "slot": getattr(ad, "action_slot", None) if ad else None,
            "pose": {pb.name: (pb.rotation_mode, pb.matrix_basis.copy()) for pb in ob.pose.bones},
            "props": {k: ob[k] for k in props if k in ob.keys()}}


def _reset_props(ob, state):
    """the switches and weapons as they were before the export: an action that doesn't key them plays them so"""
    for k, v in state["props"].items():
        ob[k] = v
    ob.update_tag()


def _restore(ob, state):
    _compat().assign_action(ob, state["action"])
    ad = ob.animation_data
    if state["slot"] is not None and getattr(ad, "action_slot", None) != state["slot"]:
        ad.action_slot = state["slot"]
    for name, (mode, basis) in state["pose"].items():
        pb = ob.pose.bones.get(name)
        if pb is not None:
            pb.rotation_mode = mode
            pb.matrix_basis = basis
    _reset_props(ob, state)


@contextlib.contextmanager
def export_hook(lmt_group, notes):
    """Albam's LMT export runs inside this: the LMT's actions marked Bake on Export are swapped for baked copies"""
    ob = nero()
    rows = [r for r in lmt_group.actions if r.action is not None and bakes_on_export(r.action)] \
        if ob is not None and lmt_group.armature == ob else []
    if not rows:
        yield
        return
    from albam.engines.mtfw import animation
    context = bpy.context
    state = _snapshot(ob)
    bpy.app.driver_namespace[_EXPORTING] = True
    swapped = []
    try:
        for row in rows:
            original = row.action
            copy = original.copy()
            copy.use_fake_user = False
            copy.name = original.name + " (baked)"
            swapped.append((row, original, copy))
            _reset_props(ob, state)
            keyed = {fc.data_path for fc in _compat().action_fcurves(original)}
            unkeyed = [f"{label} {state['props'][prop]:g}" for prop, label in SWITCHES
                       if prop in state["props"] and f'["{prop}"]' not in keyed]
            if unkeyed:
                notes.append(f"{original.name}: baked with the switches it doesn't key as they are now "
                             f"({', '.join(unkeyed)}): key them in the action to fix them")
            _compat().assign_action(ob, copy)
            animation.follow_action(ob, copy)   # the rest pose under it, as the game has for joints without tracks
            print(f"nero rig: {original.name}: {bake(context, copy)} for export")
            row.action = copy
        yield
    finally:
        for row, original, copy in swapped:
            row.action = original
            notes[:] = [note.replace(copy.name, original.name) for note in notes]
        _restore(ob, state)
        for _, _, copy in swapped:
            bpy.data.actions.remove(copy)
        context.scene.frame_set(context.scene.frame_current)
        bpy.app.driver_namespace[_SEEN] = _seen_values(ob, [p for p, _ in SWITCHES])
        bpy.app.driver_namespace.pop(_EXPORTING, None)


# -- clean an action baked into -------------------------------------------------------------------------------------

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
    ob = nero()
    action = ob.animation_data.action if ob is not None and ob.animation_data else None
    if action is None:
        raise RuntimeError("Nero plays no action")
    compat = _compat()
    scene = context.scene
    keep = scene.frame_current
    bones = [pb for pb in ob.pose.bones if _game(ob.data.bones[pb.name]) and pb.constraints]
    hidden = {pb.name: {} for pb in bones}   # bone -> {frame: channels hidden there}
    try:
        for f in _frames(action):
            scene.frame_set(f)
            context.view_layer.update()
            for pb in bones:
                hidden[pb.name][f] = _hidden(ob, pb)
    finally:
        scene.frame_set(keep)
    removed = kept = 0
    for pb in bones:
        if not any(hidden[pb.name].values()):
            continue
        for channel, tolerance in TOLERANCE.items():
            path = f'pose.bones["{pb.name}"].{channel}'
            curves = [fc for fc in compat.fcurves_of(action, ob) if fc.data_path == path and len(fc.keyframe_points)]
            if not curves:
                continue
            r, k = _thin(curves, {f for f, ch in hidden[pb.name].items() if channel in ch}, tolerance)
            removed += r
            kept += k
            for fc in curves:
                if not len(fc.keyframe_points):
                    compat.fcurve_remove(action, fc, ob)
    trimmed = trim_before_start(action, ob)
    scene.frame_set(keep)
    return f"{action.name}: {removed} frames of keys removed, {kept} kept, {trimmed} keys before the first frame removed"


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


def _key_visual_rotations(context, ob, action, names, frame):
    """keys the bones' rotations on frame to the pose on screen (constraints included)"""
    context.view_layer.update()
    poses = {n: _visual_basis(ob, n).to_quaternion() for n in names}   # all read before any key changes them
    for n in names:
        pb = ob.pose.bones[n]
        q = poses[n]
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


def _switch_off_from(ob, action, prop, frame):
    """keys the switch to 0 on frame, and to its value now on the frame before when that frame has no key"""
    path = f'["{prop}"]'
    before = ob.get(prop, 0.0)
    fc = _compat().fcurve_find(action, path, 0, ob)
    if frame > start_frame(action, ob) and (fc is None or
                                            not any(abs(k.co[0] - (frame - 1)) < 0.5 for k in fc.keyframe_points)):
        _set_key(action, ob, path, 0, "Nero Rig", frame - 1, before, "CONSTANT")
    _set_key(action, ob, path, 0, "Nero Rig", frame, 0.0, "CONSTANT")
    ob[prop] = 0.0


def _playing_action(ob):
    action = ob.animation_data.action if ob is not None and ob.animation_data else None
    if action is None:
        raise RuntimeError("Nero plays no action: give him one first (LMT panel > Add Animation)")
    return action


def _game_bones_by_joint(ob):
    return {int(b["mtfw.anim_retarget"]): b.name for b in ob.data.bones
            if b.get("mtfw.anim_retarget") is not None and _game(b)}


def bake_ik_frame(context, limb, switch_off):
    ob = nero()
    action = _playing_action(ob)
    frame = context.scene.frame_current
    by_joint = _game_bones_by_joint(ob)
    names = [by_joint[j] for j in LIMB_JOINTS[limb]]
    _key_visual_rotations(context, ob, action, names, frame)
    if switch_off:
        _switch_off_from(ob, action, f"ik_{limb}", frame)
    ob.update_tag()
    context.scene.frame_set(frame)
    return f"{limb}: {len(names)} bones keyed on frame {frame}" + (", IK off from here" if switch_off else "")


def fingers_from_grip(context, prop):
    ob = nero()
    action = _playing_action(ob)
    frame = context.scene.frame_current
    by_joint = _game_bones_by_joint(ob)
    names = [by_joint[j] for j in GRIP_FINGERS[prop] if j in by_joint]
    _key_visual_rotations(context, ob, action, names, frame)
    _switch_off_from(ob, action, prop, frame)
    ob.update_tag()
    context.scene.frame_set(frame)
    return f"{prop}: {len(names)} fingers keyed on frame {frame}, grip off from here"


# -- IK back on ----------------------------------------------------------------------------------------------------

def _controls(limb):
    part, side = limb.split("_")[0], limb[-1]
    return f"IK-{'hand' if part == 'arm' else 'foot'}_{side}", f"POLE-{limb}"


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
    ob = nero()
    action = ob.animation_data.action if ob is not None and ob.animation_data else None
    if action is None:
        raise RuntimeError("Nero plays no action: give him one first (LMT panel > Add Animation)")
    scene = context.scene
    frame = scene.frame_current
    by_joint = {int(b["mtfw.anim_retarget"]): b.name for b in ob.data.bones
                if b.get("mtfw.anim_retarget") is not None and _game(b)}
    names = [by_joint[j] for j in LIMB_JOINTS[limb]]
    control, pole = (ob.pose.bones[n] for n in _controls(limb))
    context.view_layer.update()
    shown = {n: ob.pose.bones[n].matrix.copy() for n in names}   # the pose on screen, which the IK takes over
    if frame > start_frame(action, ob):   # nothing before the first frame to keep
        _hold_before(action, ob, control, _channels(control), frame)
        _hold_before(action, ob, pole, _channels(pole, rotation=False), frame)

    u, m, e = (shown[n].to_translation() for n in names)
    old_q = control.rotation_quaternion.copy()
    control.matrix = shown[names[2]]   # the control's rest is the end joint's; no update before the keys below: it
    # would play the curves just keyed back over the new values
    pole.matrix = Matrix.Translation(_pole_position(u, m, e, pole.matrix.to_translation())) @ \
        pole.matrix.to_3x3().to_4x4()
    if control.rotation_mode == "QUATERNION" and control.rotation_quaternion.dot(old_q) < 0:
        control.rotation_quaternion.negate()
    for pb, channels in ((control, _channels(control)), (pole, _channels(pole, rotation=False))):
        for channel in channels:
            for i, v in enumerate(getattr(pb, channel)):
                _set_key(action, ob, f'pose.bones["{pb.name}"].{channel}', i, pb.name, frame, v)

    prop = f"ik_{limb}"
    path = f'["{prop}"]'
    compat = _compat()
    fc = compat.fcurve_find(action, path, 0, ob)
    if frame > start_frame(action, ob) and (fc is None or
                                            not any(abs(k.co[0] - (frame - 1)) < 0.5 for k in fc.keyframe_points)):
        before = fc.evaluate(frame - 1) if fc is not None and len(fc.keyframe_points) else ob.get(prop, 0.0)
        _set_key(action, ob, path, 0, "Nero Rig", frame - 1, before, "CONSTANT")
    _set_key(action, ob, path, 0, "Nero Rig", frame, 1.0, "CONSTANT")
    ob[prop] = 1.0
    ob.update_tag()
    scene.frame_set(frame)
    context.view_layer.update()
    moved = max((ob.pose.bones[n].matrix.to_translation() - shown[n].to_translation()).length for n in names)
    return f"{limb}: IK on from frame {frame} (the limb moved {moved * 1000:.1f} mm)"


class NERORIG_OT_ik_on_here(bpy.types.Operator):
    """Turn this limb's IK back on from the current frame without a jump: the IK control and the pole go to the pose
    on screen and are keyed there (and on the frame before as they were, so earlier frames don't change), and the IK
    switch is keyed to 1 from this frame"""
    bl_idname = "nero_rig.ik_on_here"
    bl_label = "IK On Here"
    bl_options = {"REGISTER", "UNDO"}

    limb: bpy.props.EnumProperty(
        name="Limb", items=[(k, k.replace("_", " ").title(), f"The {k.replace('_', ' ')}'s bones") for k in LIMB_JOINTS],
        description="The arm or leg whose IK comes back on")

    @classmethod
    def poll(cls, context):
        return nero() is not None

    def execute(self, context):
        try:
            line = ik_on_here(context, self.limb)
        except RuntimeError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        self.report({"INFO"}, line)
        return {"FINISHED"}


class NERORIG_OT_bake_ik_frame(bpy.types.Operator):
    """Key this limb's bones on the current frame to the pose the IK gives them (ordinary FK keys), and key its IK
    switch off from this frame, so the limb keeps the pose without the IK. IK On Here (the button beside it) turns
    the IK back on later"""
    bl_idname = "nero_rig.bake_ik_frame"
    bl_label = "Bake IK Frame"
    bl_options = {"REGISTER", "UNDO"}

    limb: bpy.props.EnumProperty(
        name="Limb", items=[(k, k.replace("_", " ").title(), f"The {k.replace('_', ' ')}'s bones") for k in LIMB_JOINTS],
        description="The arm or leg whose IK pose is keyed")
    switch_off: bpy.props.BoolProperty(
        name="Switch IK Off Here", default=True,
        description="Also key the limb's IK switch to 0 on this frame (and to its current value on the frame before, "
                    "when that frame has no key), so the keyed pose plays from here")

    @classmethod
    def poll(cls, context):
        return nero() is not None

    def execute(self, context):
        try:
            line = bake_ik_frame(context, self.limb, self.switch_off)
        except RuntimeError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        self.report({"INFO"}, line)
        return {"FINISHED"}


class NERORIG_OT_fingers_from_grip(bpy.types.Operator):
    """Key this hand's fingers on the current frame to the pose on screen (the grip on the weapon, or the blend the
    grip switch gives) and key the grip off from this frame (the frame before keeps its value), so the fingers start
    from the grip and can be posed by hand, as for a gun spin. Key the grip switch back to 1 to close the hand on the
    weapon again"""
    bl_idname = "nero_rig.fingers_from_grip"
    bl_label = "Fingers from Grip"
    bl_options = {"REGISTER", "UNDO"}

    grip: bpy.props.EnumProperty(
        name="Hand", items=[(k, label, f"The {label.lower()}'s fingers") for k, label in GRIP_PROPS],
        description="The hand whose fingers are keyed")

    @classmethod
    def poll(cls, context):
        return nero() is not None

    def execute(self, context):
        try:
            line = fingers_from_grip(context, self.grip)
        except RuntimeError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        self.report({"INFO"}, line)
        return {"FINISHED"}


class NERORIG_OT_remove_baked_keys(bpy.types.Operator):
    """Thin the action Nero plays after an old Bake for Export (a key on every frame): delete the keys a constraint
    hides completely (IK on, a grip closed) and the keys in one-per-frame runs that lie on the line between their
    neighbours, so every frame where the bone's own keys show stays as it was; also the keys before the action's first
    frame that change nothing (the frame -1 keys the IK buttons used to leave). LMT export does the bake now"""
    bl_idname = "nero_rig.remove_baked_keys"
    bl_label = "Remove Baked Keys"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ob = nero()
        return ob is not None and ob.animation_data is not None and ob.animation_data.action is not None

    def execute(self, context):
        try:
            line = remove_baked_keys(context)
        except RuntimeError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        print("nero rig:", line)
        self.report({"INFO"}, line)
        return {"FINISHED"}


class NERORIG_PT_panel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Nero Rig"
    bl_label = "Nero Rig"

    @classmethod
    def poll(cls, context):
        return nero() is not None

    def draw(self, context):
        ob = nero()
        layout = self.layout
        col = layout.column(align=True)
        for prop, label in IK_PROPS:
            if prop in ob.keys():
                row = col.row(align=True)
                row.prop(ob, f'["{prop}"]', text=label, slider=True)
                row.operator(NERORIG_OT_bake_ik_frame.bl_idname, text="", icon="KEYFRAME_HLT").limb = prop[3:]
                row.operator(NERORIG_OT_ik_on_here.bl_idname, text="", icon="CON_KINEMATIC").limb = prop[3:]
        box = layout.box()
        box.label(text="Weapons")
        if FOLLOW_EVENTS in ob.keys():
            box.prop(ob, f'["{FOLLOW_EVENTS}"]', text="Follow Events")
        sub = box.column(align=True)
        sub.enabled = not ob.get(FOLLOW_EVENTS)
        if PLACE in ob.keys():
            place = ob.get(PLACE, 0)
            sub.prop(ob, f'["{PLACE}"]', text=f"Red Queen: {PLACE_NAMES[place] if 0 <= place < 3 else '?'}")
        if GUN in ob.keys():
            sub.prop(ob, f'["{GUN}"]', text="Blue Rose")
        grips = box.column(align=True)
        for prop, label in GRIP_PROPS:
            if prop in ob.keys():
                row = grips.row(align=True)
                row.prop(ob, f'["{prop}"]', text=label, slider=True)
                row.operator(NERORIG_OT_fingers_from_grip.bl_idname, text="", icon="KEYFRAME_HLT").grip = prop
        if len(ob.data.collections):
            box = layout.box()
            box.label(text="Bones")
            grid = box.grid_flow(columns=2, align=True)
            for coll in ob.data.collections:
                grid.prop(coll, "is_visible", text=coll.name, toggle=True)
        action = ob.animation_data.action if ob.animation_data else None
        if action is not None and hasattr(action, "nero_rig_bake_on_export"):
            box = layout.box()
            box.label(text=action.name, icon="ACTION")
            box.prop(action, "nero_rig_bake_on_export")
            box.operator(NERORIG_OT_remove_baked_keys.bl_idname, icon="KEY_DEHLT")
        help_box = layout.box()
        for line in ("The coat swings by the chain preview",
                     "(PHS_ objects > Chain): play forward.",
                     "LMT export bakes the IK and the grips."):
            help_box.label(text=line)


CLASSES = (NERORIG_OT_bake_ik_frame, NERORIG_OT_ik_on_here, NERORIG_OT_fingers_from_grip, NERORIG_OT_remove_baked_keys,
           NERORIG_PT_panel)
_STASH = "nero_rig_ui_classes"     # the classes registered last time (running the text again replaces them)
_HANDLER = "nero_rig_ui_handler"   # the frame handler registered last time
_HOOK = "nero_rig_ui_export_hook"  # the LMT export hook registered last time


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
    if handler in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(handler)
    hook, hooks = bpy.app.driver_namespace.pop(_HOOK, None), _hooks()
    if hooks is not None and hook in hooks:
        hooks.remove(hook)
    if hasattr(bpy.types.Action, "nero_rig_bake_on_export"):
        del bpy.types.Action.nero_rig_bake_on_export
    handler = bpy.app.driver_namespace.pop(_DEPSGRAPH, None)
    if handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(handler)
    bpy.app.driver_namespace.pop(_SEEN, None)


def register():
    unregister()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.driver_namespace[_STASH] = CLASSES
    bpy.app.handlers.frame_change_pre.append(_on_frame)
    bpy.app.driver_namespace[_HANDLER] = _on_frame
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    bpy.app.driver_namespace[_DEPSGRAPH] = _on_depsgraph
    bpy.types.Action.nero_rig_bake_on_export = bpy.props.BoolProperty(
        name="Bake on Export", get=_get_bake, set=_set_bake,
        description="LMT export bakes what the rig's constraints make (IK, finger grips) into a copy of this action and "
                    "exports the copy; the action keeps only its own keys. On by default when the action keys the IK "
                    "controls or switches; off exports the action's keys as they are (a vanilla animation)")
    hooks = _hooks()
    if hooks is None:
        print("nero rig: this Albam has no LMT export hook: update Albam, or the IK and the grips won't be exported")
    else:
        hooks.append(export_hook)
        bpy.app.driver_namespace[_HOOK] = export_hook


register()
