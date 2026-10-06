"""
Foot IK preview: reproduces DMC4's player foot planting (cLegIkCtrl + cCnsIK, see
Vibed/RE/ik_constraint_findings.md) on an imported armature, for previewing only.

In the game, after the animation is evaluated, each leg with foot IK enabled (event flags
right_foot_ik / left_foot_ik of the first event table) casts a ray from 30 above the animated
ankle to 14 below it. On a hit the ankle target becomes hit + 12 and a 2-bone IK
(thigh, shin, ankle as effector) reaches it, keeping the foot's rotation. On a miss the target is
the animated ankle. The IK fades in and out by a fixed amount per frame.

The rig:
- a hidden "FK ghost" object sharing the armature data plays the same action without IK,
  providing the animated ankle, knee and foot rotation without dependency cycles
- per leg: anchor (ankle of the ghost) > probe (12 below, snapped to the ground by two
  Shrinkwrap constraints covering the game's ray window) > target (12 above the probe),
  and a knee pole following the ghost's shin
- per leg, a hip > knee > ankle helper chain solved by Blender's IK (the game's leg bones are
  short and unconnected, which Blender's solver can't handle), with follow bones carrying the
  result to the real thigh and shin through Copy Transforms, plus Copy Rotation keeping the
  animated foot rotation. A frame change handler fades these from the action's events

Nothing here is exported: constraints and helper bones aren't keyed, and LMT export only reads
F-Curves. Distances are in Blender units, game units (cm) * 0.01.
"""
import math

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from albam.registry import blender_registry

PREFIX = "IKP_"
CONSTRAINT_PREFIX = "ALBAM_IKP_"
GHOST_PROP = "albam_ikp_ghost"
LEGS = {
    # side: game bone indices of thigh, shin, foot, toe and the event flag that enables it
    "R": ("14", "15", "16", "17", "right_foot_ik"),
    "L": ("18", "19", "20", "21", "left_foot_ik"),
}
RAY_ABOVE = 0.30
RAY_BELOW = 0.14
FOOT_OFFSET = 0.12
POLE_DISTANCE = 0.4
KNEE_PRE_BEND = 0.01


def _animation():
    # imported on first use, see anim_tools._animation
    from albam.engines.mtfw import animation
    return animation


def _filter_ground(self, obj):
    return obj.type == "MESH"


def _on_ground_changed(self, context):
    for obj in context.scene.objects:
        if obj.type != "ARMATURE" or not get_ghost(obj):
            continue
        for pose_bone in obj.pose.bones:
            for constraint in pose_bone.constraints:
                if constraint.type == "SHRINKWRAP" and constraint.name.startswith(CONSTRAINT_PREFIX):
                    constraint.target = self.ground


@blender_registry.register_blender_prop_albam(name="foot_ik_preview")
class AlbamFootIkPreviewSettings(bpy.types.PropertyGroup):
    ground: bpy.props.PointerProperty(
        type=bpy.types.Object,
        poll=_filter_ground,
        name="Ground",
        description="Mesh the feet are planted on",
        update=_on_ground_changed,
    )
    blend_speed: bpy.props.FloatProperty(
        name="Blend Speed",
        description="How much the IK fades in or out per frame when foot IK is turned on or off",
        default=0.1,
        min=0.001,
        max=1.0,
    )


def get_ghost(armature):
    ghost = armature.get(GHOST_PROP)
    return ghost if isinstance(ghost, bpy.types.Object) else None


def _leg_bones(armature):
    """{side: (thigh, shin, foot, toe or None)} bone names, by game bone index"""
    by_index = {}
    for bone in armature.data.bones:
        index = bone.get("mtfw.anim_retarget")
        if index is not None:
            by_index[str(index)] = bone.name
    legs = {}
    for side, (thigh, shin, foot, toe, _) in LEGS.items():
        names = [by_index.get(i) for i in (thigh, shin, foot)]
        if None in names:
            return None
        legs[side] = (*names, by_index.get(toe))
    return legs


def remove_rig(armature):
    ghost = get_ghost(armature)
    for pose_bone in armature.pose.bones:
        for constraint in list(pose_bone.constraints):
            if constraint.name.startswith(CONSTRAINT_PREFIX):
                pose_bone.constraints.remove(constraint)
    helper_bones = [b.name for b in armature.data.bones if b.name.startswith(PREFIX)]
    if helper_bones:
        with _edit_mode(armature):
            for name in helper_bones:
                armature.data.edit_bones.remove(armature.data.edit_bones[name])
    if ghost is not None:
        bpy.data.objects.remove(ghost)
    if GHOST_PROP in armature:
        del armature[GHOST_PROP]


class _edit_mode:
    """Enter edit mode on the armature, restoring the previous mode and active object after"""

    def __init__(self, armature):
        self.armature = armature

    def __enter__(self):
        view_layer = bpy.context.view_layer
        self.previous_active = view_layer.objects.active
        self.previous_mode = bpy.context.mode
        if self.previous_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        view_layer.objects.active = self.armature
        bpy.ops.object.mode_set(mode="EDIT")

    def __exit__(self, *exc):
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.objects.active = self.previous_active
        if self.previous_mode == "POSE" and self.previous_active is not None:
            bpy.ops.object.mode_set(mode="POSE")


def build_rig(armature, ground):
    """Build the preview rig, replacing an existing one. Returns {side: knee error after calibration}"""
    legs = _leg_bones(armature)
    if legs is None:
        raise ValueError("The armature has no game leg bones (indices 14-16 and 18-20)")
    remove_rig(armature)

    ghost = bpy.data.objects.new(f"{armature.name}.fk_ghost", armature.data)
    collection = armature.users_collection[0] if armature.users_collection else bpy.context.scene.collection
    collection.objects.link(ghost)
    ghost.hide_render = True
    copy = ghost.constraints.new("COPY_TRANSFORMS")
    copy.target = armature
    ghost.animation_data_create()
    armature[GHOST_PROP] = ghost
    bpy.context.view_layer.update()  # creates the ghost's pose
    _copy_pose_constraints(armature, ghost)

    with _edit_mode(armature):
        edit_bones = armature.data.edit_bones
        up = Vector((0.0, 0.0, 0.05))
        for side, (thigh, shin, foot, toe) in legs.items():
            hip = edit_bones[thigh].head.copy()
            knee = edit_bones[shin].head.copy()
            ankle = edit_bones[foot].head.copy()
            forward = Vector((0.0, -1.0, 0.0))
            if toe:
                toe_dir = edit_bones[toe].head - ankle
                toe_dir.z = 0.0
                if toe_dir.length > 1e-4:
                    forward = toe_dir.normalized()

            def new_bone(name, head, parent=None, tail=None, like=None):
                bone = edit_bones.new(PREFIX + name + "_" + side)
                bone.head = head
                bone.tail = tail if tail is not None else head + up
                bone.use_deform = False
                if like is not None:
                    bone.matrix = edit_bones[like].matrix.copy()
                    bone.length = edit_bones[like].length
                bone.parent = parent
                return bone

            anchor = new_bone("anchor", ankle)
            probe = new_bone("probe", ankle - Vector((0.0, 0.0, FOOT_OFFSET)), anchor)
            new_bone("target", ankle, probe)
            knee_anchor = new_bone("knee_anchor", knee, like=shin)
            new_bone("pole", knee + forward * POLE_DISTANCE, knee_anchor)

            # Blender's IK solver uses bone lengths and puts the effector at a bone tail, so it
            # can't solve the game's short, unconnected leg bones. It solves this hip > knee > ankle
            # chain instead, and the follow bones (children with the real bones' rest frames)
            # carry the result to the real thigh and shin. The rest legs are straight, which the
            # solver can't bend from, so the helper knee is bent slightly forward
            ik_knee = knee + forward * KNEE_PRE_BEND
            ik_thigh = new_bone("ik_thigh", hip, edit_bones[thigh].parent, tail=ik_knee)
            ik_shin = new_bone("ik_shin", ik_knee, ik_thigh, tail=ankle)
            ik_shin.use_connect = True
            new_bone("follow_thigh", hip, ik_thigh, like=thigh)
            new_bone("follow_shin", knee, ik_shin, like=shin)

    pose_bones = armature.pose.bones
    for side, (thigh, shin, foot, toe) in legs.items():
        def helper(name):
            return pose_bones[PREFIX + name + "_" + side]

        constraint = helper("anchor").constraints.new("COPY_LOCATION")
        constraint.name = CONSTRAINT_PREFIX + "FkAnkle"
        constraint.target = ghost
        constraint.subtarget = foot

        # the game's ray goes from 30 above to 14 below the ankle. The probe sits 12 below the
        # ankle, so search 42 up and 2 down from it
        for axis, limit in (("POS_Z", RAY_ABOVE + FOOT_OFFSET), ("NEG_Z", RAY_BELOW - FOOT_OFFSET)):
            constraint = helper("probe").constraints.new("SHRINKWRAP")
            constraint.name = CONSTRAINT_PREFIX + "Ground" + axis
            constraint.target = ground
            constraint.shrinkwrap_type = "PROJECT"
            constraint.project_axis = axis
            constraint.project_axis_space = "WORLD"
            constraint.project_limit = limit

        constraint = helper("knee_anchor").constraints.new("COPY_TRANSFORMS")
        constraint.name = CONSTRAINT_PREFIX + "FkKnee"
        constraint.target = ghost
        constraint.subtarget = shin

        ik = helper("ik_shin").constraints.new("IK")
        ik.name = CONSTRAINT_PREFIX + "IK"
        ik.target = armature
        ik.subtarget = helper("target").name
        ik.pole_target = armature
        ik.pole_subtarget = helper("pole").name
        ik.chain_count = 2
        ik.use_stretch = False

        # the fade happens here, between the animation and the IK result
        for bone, follow in ((thigh, "follow_thigh"), (shin, "follow_shin")):
            constraint = pose_bones[bone].constraints.new("COPY_TRANSFORMS")
            constraint.name = CONSTRAINT_PREFIX + "Follow"
            constraint.target = armature
            constraint.subtarget = helper(follow).name

        # the game keeps the animated foot rotation (mKeepRot)
        keep = pose_bones[foot].constraints.new("COPY_ROTATION")
        keep.name = CONSTRAINT_PREFIX + "KeepRot"
        keep.target = ghost
        keep.subtarget = foot

    errors = _calibrate_poles(armature, ghost, legs)
    ghost.animation_data.action = armature.animation_data.action if armature.animation_data else None
    ghost.hide_set(True)
    update_rig(bpy.context.scene, armature)
    return errors


def _copy_pose_constraints(armature, ghost):
    """
    The ghost must pose exactly like the armature without the preview, so it gets the armature's
    own pose constraints (e.g. the hips following the root_motion bone, added by LMT import),
    with references to the armature pointed at the ghost
    """
    for pose_bone in armature.pose.bones:
        for src in pose_bone.constraints:
            if src.name.startswith(CONSTRAINT_PREFIX):
                continue
            dst = ghost.pose.bones[pose_bone.name].constraints.new(src.type)
            properties = [p.identifier for p in src.bl_rna.properties if not p.is_readonly]
            # targets first, subtargets are validated against them
            for name in sorted(properties, key=lambda n: n not in ("target", "pole_target")):
                value = getattr(src, name)
                if value == armature:
                    value = ghost
                try:
                    setattr(dst, name, value)
                except (AttributeError, TypeError, ValueError):
                    pass


def _calibrate_poles(armature, ghost, legs):
    """
    The knee bend plane depends on the pole angle, which depends on bone orientations.
    The rest pose has straight legs, so bend the ghost's knees and pick the angle where the IK
    knee lands on the ghost's knee
    """
    main_action = armature.animation_data.action if armature.animation_data else None
    if armature.animation_data:
        armature.animation_data.action = None
    # clearing the action leaves the last evaluated pose, start both from the rest pose
    main_pose = {pb.name: pb.matrix_basis.copy() for pb in armature.pose.bones}
    for pb in list(armature.pose.bones) + list(ghost.pose.bones):
        pb.matrix_basis = Matrix.Identity(4)
    shrinkwraps = [c for pb in armature.pose.bones for c in pb.constraints
                   if c.type == "SHRINKWRAP" and c.name.startswith(CONSTRAINT_PREFIX)]
    for constraint in shrinkwraps:
        constraint.mute = True

    view_layer = bpy.context.view_layer
    for side, (thigh, shin, foot, toe) in legs.items():
        for pb in (ghost.pose.bones[thigh], ghost.pose.bones[shin]):
            pb.matrix_basis = Matrix.Identity(4)
        view_layer.update()
        _rotate_pose_bone(ghost.pose.bones[thigh], math.radians(-30))  # knee forward
        view_layer.update()
        _rotate_pose_bone(ghost.pose.bones[shin], math.radians(60))  # ankle back
        view_layer.update()
        _set_weight(armature, (thigh, shin, foot), 1.0)

    errors = {}
    for side, (thigh, shin, foot, toe) in legs.items():
        ik = armature.pose.bones[PREFIX + "ik_shin_" + side].constraints[CONSTRAINT_PREFIX + "IK"]

        def knee_error(angle):
            ik.pole_angle = angle
            view_layer.update()
            return (armature.pose.bones[shin].head - ghost.pose.bones[shin].head).length

        best = min((math.radians(a) for a in range(-180, 180, 5)), key=knee_error)
        step = math.radians(2.5)
        while step > math.radians(0.01):
            best = min((best - step, best, best + step), key=knee_error)
            step /= 2
        errors[side] = knee_error(best)

    for side, (thigh, shin, foot, toe) in legs.items():
        for pb in (ghost.pose.bones[thigh], ghost.pose.bones[shin]):
            pb.matrix_basis = Matrix.Identity(4)
    for constraint in shrinkwraps:
        constraint.mute = False
    for pb in armature.pose.bones:
        pb.matrix_basis = main_pose[pb.name]
    if armature.animation_data:
        armature.animation_data.action = main_action
    view_layer.update()
    return errors


def _rotate_pose_bone(pose_bone, angle):
    """Rotate a pose bone about the armature X axis through its head"""
    head = pose_bone.head.copy()
    pose_bone.matrix = (
        Matrix.Translation(head) @ Matrix.Rotation(angle, 4, "X") @ Matrix.Translation(-head) @ pose_bone.matrix
    )


def foot_ik_weights(action, frame, blend_speed):
    """
    {side: IK influence} at a frame, from the foot IK flags of the action's first event table.
    An event's value holds until the next event, and the influence moves toward the flag by
    blend_speed per frame, starting fully at the first event's state
    """
    animation = _animation()
    events = []
    if action is not None:
        props = animation.get_lmt_props(action)
        for i, event in enumerate(props.event_markers):
            if event.param_ev_type == "Sound":
                continue
            marker = animation.find_event_marker(action, event, i)
            if marker is not None:
                events.append((marker.frame, event))
    events.sort(key=lambda e: e[0])

    weights = {}
    for side, (*_, flag) in LEGS.items():
        states = [(f, 1.0 if getattr(e, flag) else 0.0) for f, e in events]
        if not states or frame < states[0][0]:
            weights[side] = states[0][1] if states else 0.0
            continue
        weight = states[0][1]
        for i, (start, target) in enumerate(states):
            if start > frame:
                break
            end = states[i + 1][0] if i + 1 < len(states) else None
            until = frame if end is None or end > frame else end
            step = blend_speed * (until - start)
            weight = min(target, weight + step) if target > weight else max(target, weight - step)
        weights[side] = weight
    return weights


def update_rig(scene, armature):
    """Sync the ghost's action and set the IK influences for the current frame"""
    ghost = get_ghost(armature)
    if ghost is None:
        return
    action = armature.animation_data.action if armature.animation_data else None
    if ghost.animation_data and ghost.animation_data.action != action:
        ghost.animation_data.action = action
    legs = _leg_bones(armature)
    if legs is None:
        return
    weights = foot_ik_weights(action, scene.frame_current, scene.albam.foot_ik_preview.blend_speed)
    for side, (thigh, shin, foot, toe) in legs.items():
        _set_weight(armature, (thigh, shin, foot), weights[side])


def _set_weight(armature, bones, weight):
    """Fade a leg between the animation (0) and the IK result (1)"""
    for bone in bones:
        for constraint in armature.pose.bones[bone].constraints:
            if constraint.name.startswith(CONSTRAINT_PREFIX) and abs(constraint.influence - weight) > 1e-6:
                constraint.influence = weight


@persistent
def _on_frame_change(scene, depsgraph=None):
    for obj in scene.objects:
        if obj.type == "ARMATURE" and GHOST_PROP in obj:
            update_rig(scene, obj)


def register_handlers():
    if _on_frame_change not in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.append(_on_frame_change)


def unregister_handlers():
    for handler in list(bpy.app.handlers.frame_change_pre):
        if getattr(handler, "__name__", "") == _on_frame_change.__name__ and \
                getattr(handler, "__module__", "") == __name__:
            bpy.app.handlers.frame_change_pre.remove(handler)


def _active_armature(context):
    lmt = _animation().get_active_lmt(context)
    return lmt.armature if lmt else None


@blender_registry.register_blender_type
class ALBAM_OT_FootIkPreviewBuild(bpy.types.Operator):
    """Build (or rebuild) the in-game foot IK preview on the LMT's armature"""
    bl_idname = "albam.foot_ik_preview_build"
    bl_label = "Build Foot IK Preview"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_armature(context) is not None and context.scene.albam.foot_ik_preview.ground is not None

    def execute(self, context):
        armature = _active_armature(context)
        try:
            errors = build_rig(armature, context.scene.albam.foot_ik_preview.ground)
        except ValueError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        worst = max(errors.values()) if errors else 0.0
        if worst > 0.01:
            self.report({"WARNING"}, f"Knee direction may be off by up to {worst * 100:.1f} cm")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_FootIkPreviewRemove(bpy.types.Operator):
    """Remove the foot IK preview from the LMT's armature"""
    bl_idname = "albam.foot_ik_preview_remove"
    bl_label = "Remove Foot IK Preview"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature = _active_armature(context)
        return armature is not None and get_ghost(armature) is not None

    def execute(self, context):
        remove_rig(_active_armature(context))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_PT_FootIkPreview(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_context = "action"
    bl_region_type = "UI"
    bl_idname = "ALBAM_PT_FootIkPreview"
    bl_parent_id = "ALBAM_PT_LmtSection"
    bl_label = "Foot IK Preview"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _active_armature(context) is not None

    def draw(self, context):
        layout = self.layout
        settings = context.scene.albam.foot_ik_preview
        armature = _active_armature(context)
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(settings, "ground")
        col.prop(settings, "blend_speed")

        built = get_ghost(armature) is not None
        row = layout.row(align=True)
        row.operator("albam.foot_ik_preview_build", text="Rebuild" if built else "Build", icon="CON_KINEMATIC")
        row.operator("albam.foot_ik_preview_remove", text="", icon="X")
        if built:
            action = armature.animation_data.action if armature.animation_data else None
            weights = foot_ik_weights(action, context.scene.frame_current, settings.blend_speed)
            layout.label(text=f"IK this frame: right {weights['R']:.0%}, left {weights['L']:.0%}")
        else:
            layout.label(text="Preview only, never exported", icon="INFO")
