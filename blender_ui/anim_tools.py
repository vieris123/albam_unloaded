import os

import bpy

from albam.registry import blender_registry


def _animation():
    # animation.py needs kaitaistruct, which is only importable once register() has put
    # albam_vendor on sys.path, so it's imported on first use instead of with this module
    from albam.engines.mtfw import animation
    return animation


def get_lmt_props(action):
    return _animation().get_lmt_props(action)


def get_active_lmt(context):
    return _animation().get_active_lmt(context)


def get_active_anim(context):
    return _animation().get_active_anim(context)


def get_active_event(context):
    return _animation().get_active_event(context)


def find_event_marker(action, event, index):
    return _animation().find_event_marker(action, event, index)


def link_legacy_events(action):
    return _animation().link_legacy_events(action)


def unique_marker_name(action, base):
    return _animation().unique_marker_name(action, base)


EVENT_TYPE_ICONS = {"Hitbox": "MESH_CUBE", "Sound": "SPEAKER"}

# Slot use counts of the LMT being drawn, so list rows can flag clashes without
# recounting every animation per row. Filled by the Animations panel before drawing the list
_SLOT_COUNTS = {}


class LmtPanelBase:
    bl_category = "Albam [Beta]"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_context = "action"
    bl_region_type = "UI"


def _active_action(context):
    anim = get_active_anim(context)
    return anim.action if anim else None


@blender_registry.register_blender_type
class ALBAM_UL_LmtList(bpy.types.UIList):

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon="FILE")
        layout.label(text=f"{len(item.actions)} anims")


@blender_registry.register_blender_type
class ALBAM_UL_LmtAnimList(bpy.types.UIList):

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if not item.action:
            layout.alert = True
            layout.label(text=f"{item.name or 'Animation'} (action missing)", icon="ERROR")
            return
        slot = get_lmt_props(item.action).lmt_id
        clash = _SLOT_COUNTS.get(slot, 0) > 1 or slot >= data.num_slots
        layout.label(text=item.action.name, icon="ACTION")
        sub = layout.row()
        sub.alert = clash
        sub.label(text=f"Slot {slot}", icon="ERROR" if clash else "NONE")


@blender_registry.register_blender_type
class ALBAM_UL_LmtEventList(bpy.types.UIList):

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        action = data.id_data
        marker = find_event_marker(action, item, index)
        icon = EVENT_TYPE_ICONS.get(item.param_ev_type, "MARKER_HLT")
        if marker is None:
            layout.alert = True
            layout.label(text=f"{item.marker_name or 'Event'} (marker missing)", icon="ERROR")
            return
        layout.label(text=marker.name, icon=icon)
        row = layout.row()
        row.alignment = "RIGHT"
        row.label(text=f"{marker.frame}   0x{item.encode():08X}")


@blender_registry.register_blender_type
class ALBAM_PT_LmtSection(LmtPanelBase, bpy.types.Panel):
    bl_idname = "ALBAM_PT_LmtSection"
    bl_label = "LMT"

    def draw(self, context):
        layout = self.layout
        groups = context.scene.albam.lmt_groups
        if len(groups.anim_group) == 0:
            layout.label(text="Import an .lmt from Game Files, or", icon="INFO")
            layout.operator("albam.new_lmt", icon="ADD")
            return

        row = layout.row()
        row.template_list(
            "ALBAM_UL_LmtList", "lmt", groups, "anim_group", groups, "active_group_id", sort_lock=True, rows=2
        )
        col = row.column(align=True)
        col.operator("albam.new_lmt", icon="ADD", text="")
        col.operator("albam.remove_lmt", icon="REMOVE", text="")

        lmt = get_active_lmt(context)
        if lmt is None:
            return
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(lmt, "armature")
        col.prop(lmt, "num_slots")

        row = layout.row()
        row.scale_y = 1.3
        row.operator("albam.export_anim", text="Export LMT", icon="EXPORT")


@blender_registry.register_blender_type
class ALBAM_PT_AlbamActionSection(LmtPanelBase, bpy.types.Panel):
    bl_idname = "ALBAM_PT_AlbamActionSection"
    bl_parent_id = "ALBAM_PT_LmtSection"
    bl_label = "Animations"

    @classmethod
    def poll(cls, context):
        return get_active_lmt(context) is not None

    def draw(self, context):
        layout = self.layout
        lmt = get_active_lmt(context)

        _SLOT_COUNTS.clear()
        _SLOT_COUNTS.update(lmt.slot_counts())
        row = layout.row()
        row.template_list(
            "ALBAM_UL_LmtAnimList", "action", lmt, "actions", lmt, "active_id", sort_lock=True, rows=4
        )
        col = row.column(align=True)
        col.operator("albam.add_anim", icon="ADD", text="")
        col.operator("albam.remove_anim", icon="REMOVE", text="")

        action = _active_action(context)
        if action is None:
            return
        props = get_lmt_props(action)

        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        sub = col.row()
        sub.alert = _SLOT_COUNTS.get(props.lmt_id, 0) > 1 or props.lmt_id >= lmt.num_slots
        sub.prop(props, "lmt_id")
        sub = col.row(align=True)
        sub.prop(props, "num_frames")
        sub.operator("albam.lmt_frames_from_action", text="", icon="FILE_REFRESH")
        col.prop(props, "loop_frames")
        col.prop(props, "source_fps")


@blender_registry.register_blender_type
class ALBAM_PT_LmtRootMotionEnd(LmtPanelBase, bpy.types.Panel):
    bl_idname = "ALBAM_PT_LmtRootMotionEnd"
    bl_parent_id = "ALBAM_PT_AlbamActionSection"
    bl_label = "Root Motion End"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _active_action(context) is not None

    def draw(self, context):
        props = get_lmt_props(_active_action(context))
        col = self.layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(props, "end_pos")
        col.prop(props, "end_quat")


@blender_registry.register_blender_type
class ALBAM_PT_AlbamEventSection(LmtPanelBase, bpy.types.Panel):
    bl_idname = "ALBAM_PT_AlbamEventSection"
    bl_parent_id = "ALBAM_PT_AlbamActionSection"
    bl_label = "Events"

    @classmethod
    def poll(cls, context):
        return _active_action(context) is not None

    def draw(self, context):
        props = get_lmt_props(_active_action(context))
        row = self.layout.row()
        row.template_list(
            "ALBAM_UL_LmtEventList", "event", props, "event_markers", props, "active_event_index",
            sort_lock=True, rows=4,
        )
        col = row.column(align=True)
        col.operator("albam.add_event", icon="ADD", text="")
        col.operator("albam.remove_event", icon="REMOVE", text="")


@blender_registry.register_blender_type
class ALBAM_PT_AlbamIndexedEventSection(LmtPanelBase, bpy.types.Panel):
    bl_idname = "ALBAM_PT_AlbamIndexedEventSection"
    bl_parent_id = "ALBAM_PT_AlbamEventSection"
    bl_label = "Slots"

    @classmethod
    def poll(cls, context):
        return get_active_event(context) is not None

    def draw(self, context):
        action, event, marker = get_active_event(context)
        props = get_lmt_props(action)
        layout = self.layout

        row = layout.row()
        row.prop(event, "ev_type", expand=True)
        if marker is not None:
            row = layout.row()
            row.use_property_split = True
            row.use_property_decorate = False
            row.prop(marker, "frame", text="Frame")

        params = "events_params_01" if event.param_ev_type != "Sound" else "events_params_02"
        col = layout.column(align=True)
        for i in range(_animation().EVENT_SLOT_COUNT):
            row = col.row(align=True)
            row.prop(event, "slots", index=i, text=f"Slot {i + 1}", toggle=True)
            row.prop(props, params, index=i, text="")
        layout.label(text=f"Slot values are shared by all {event.param_ev_type or 'Hitbox'} events", icon="INFO")


@blender_registry.register_blender_type
class ALBAM_PT_AlbamHashedEventSection(LmtPanelBase, bpy.types.Panel):
    bl_idname = "ALBAM_PT_AlbamHashedEventSection"
    bl_parent_id = "ALBAM_PT_AlbamEventSection"
    bl_label = "Flags"

    @classmethod
    def poll(cls, context):
        return get_active_event(context) is not None

    def draw(self, context):
        _, event, _ = get_active_event(context)
        col = self.layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        group_hash = _animation().GroupHash
        for name in sorted(group_hash, key=lambda n: (group_hash[n], n)):
            col.prop(event, name)
        col.prop(event, "extra_bits")
        col.label(text=f"Event value: 0x{event.encode():08X}")


def _filter_lmt_armature(self, obj):
    return obj.type == "ARMATURE" and any(b.get("mtfw.anim_retarget") is not None for b in obj.data.bones)


@blender_registry.register_blender_type
class ALBAM_OT_LmtNew(bpy.types.Operator):
    """Create an empty LMT, to add animations to"""
    bl_idname = "albam.new_lmt"
    bl_label = "New LMT"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name="Name", default="new.lmt")
    armature: bpy.props.StringProperty(name="Armature", description="Armature of an imported model")

    def invoke(self, context, event):
        obj = context.active_object
        if obj is not None and _filter_lmt_armature(self, obj):
            self.armature = obj.name
        else:
            self.armature = next((o.name for o in context.scene.objects if _filter_lmt_armature(self, o)), "")
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "name")
        layout.prop_search(self, "armature", context.scene, "objects", icon="ARMATURE_DATA")

    def execute(self, context):
        armature = context.scene.objects.get(self.armature)
        if armature is None or not _filter_lmt_armature(self, armature):
            self.report({"ERROR"}, "Pick the armature of an imported model")
            return {"CANCELLED"}
        groups = context.scene.albam.lmt_groups
        lmt = groups.add(self.name)
        lmt.armature = armature
        groups.active_group_id = len(groups.anim_group) - 1
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_LmtRemove(bpy.types.Operator):
    """Remove the selected LMT from the list. Its actions are kept"""
    bl_idname = "albam.remove_lmt"
    bl_label = "Remove LMT"

    @classmethod
    def poll(cls, context):
        return get_active_lmt(context) is not None

    def execute(self, context):
        groups = context.scene.albam.lmt_groups
        groups.anim_group.remove(groups.active_group_id)
        groups.active_group_id = max(0, min(groups.active_group_id, len(groups.anim_group) - 1))
        return {"FINISHED"}


_ACTION_ITEMS = []  # Blender needs a reference to dynamic enum items


def _get_action_items(self, context):
    _ACTION_ITEMS.clear()
    lmt = get_active_lmt(context)
    in_lmt = {item.action for item in lmt.actions} if lmt else set()
    for i, action in enumerate(a for a in bpy.data.actions if a not in in_lmt):
        _ACTION_ITEMS.append((action.name, action.name, "", "ACTION", i))
    return _ACTION_ITEMS


def _action_length(action, context):
    """Length in game frames (60 fps, starting at 0), see animation.ExportTiming"""
    if action.fcurves:
        return _animation().game_length(action)
    scene = context.scene
    return int(round((scene.frame_end - scene.frame_start) * 60 / get_lmt_props(action).source_fps))


@blender_registry.register_blender_type
class ALBAM_OT_LmtAddAnim(bpy.types.Operator):
    """Add an animation to the LMT, in the first free slot"""
    bl_idname = "albam.add_anim"
    bl_label = "Add Animation"
    bl_options = {"REGISTER", "UNDO"}

    use_existing: bpy.props.BoolProperty(name="Use Existing Action")
    action_name: bpy.props.EnumProperty(items=_get_action_items, name="Action")
    name: bpy.props.StringProperty(name="Name", default="Anim")
    slot: bpy.props.IntProperty(name="Slot", min=0)

    @classmethod
    def poll(cls, context):
        return get_active_lmt(context) is not None

    def invoke(self, context, event):
        self.slot = get_active_lmt(context).free_slot()
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "use_existing")
        if self.use_existing:
            layout.prop(self, "action_name")
        else:
            layout.prop(self, "name")
        layout.prop(self, "slot")

    def execute(self, context):
        lmt = get_active_lmt(context)
        if self.use_existing:
            action = bpy.data.actions.get(self.action_name)
            if action is None:
                self.report({"ERROR"}, "Pick an action")
                return {"CANCELLED"}
        else:
            action = bpy.data.actions.new(self.name)
        action.albam_asset.app_id = "dmc4"
        action.use_fake_user = True

        props = get_lmt_props(action)
        if props.num_frames == 0:
            # not an action from an LMT before, set it up as a new animation
            render = context.scene.render
            props.source_fps = render.fps / render.fps_base
            props.num_frames = _action_length(action, context)
            props.loop_frames = -1
        props.lmt_id = self.slot
        lmt.num_slots = max(lmt.num_slots, self.slot + 1)

        lmt.add(action)
        lmt.active_id = len(lmt.actions) - 1
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_LmtRemoveAnim(bpy.types.Operator):
    """Remove the selected animation from the LMT. Its action is kept"""
    bl_idname = "albam.remove_anim"
    bl_label = "Remove Animation"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_anim(context) is not None

    def execute(self, context):
        lmt = get_active_lmt(context)
        lmt.actions.remove(lmt.active_id)
        lmt.active_id = max(0, min(lmt.active_id, len(lmt.actions) - 1))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_LmtFramesFromAction(bpy.types.Operator):
    """Set Frames to the length of the action"""
    bl_idname = "albam.lmt_frames_from_action"
    bl_label = "Frames From Action"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_action(context) is not None

    def execute(self, context):
        action = _active_action(context)
        get_lmt_props(action).num_frames = _action_length(action, context)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_LmtAddEvent(bpy.types.Operator):
    """Add an event at the current frame"""
    bl_idname = "albam.add_event"
    bl_label = "Add Event"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name="Name", description="Marker name. Leave empty for an automatic name")
    ev_type: bpy.props.EnumProperty(
        name="Type",
        items=[
            ("Hitbox", "Hitbox", "Hitbox event", "MESH_CUBE", 0),
            ("Sound", "Sound", "Sound event", "SPEAKER", 1),
        ],
        default="Hitbox",
    )

    @classmethod
    def poll(cls, context):
        return _active_action(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "ev_type", expand=True)
        layout.prop(self, "name")

    def execute(self, context):
        action = _active_action(context)
        link_legacy_events(action)
        props = get_lmt_props(action)
        frame = context.scene.frame_current
        prefix = "ev1" if self.ev_type == "Hitbox" else "ev2"
        marker = action.pose_markers.new(unique_marker_name(action, self.name or f"{prefix}_{frame}"))
        marker.frame = frame
        event = props.event_markers.add()
        event.setup(self.ev_type, 0)
        event.marker_name = marker.name
        props.active_event_index = len(props.event_markers) - 1
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_LmtRemoveEvent(bpy.types.Operator):
    """Remove the selected event and its marker"""
    bl_idname = "albam.remove_event"
    bl_label = "Remove Event"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_event(context) is not None

    def execute(self, context):
        action = _active_action(context)
        link_legacy_events(action)
        props = get_lmt_props(action)
        index = props.active_event_index
        marker_name = props.event_markers[index].marker_name
        props.event_markers.remove(index)
        marker = action.pose_markers.get(marker_name) if marker_name else None
        if marker is not None and not any(e.marker_name == marker_name for e in props.event_markers):
            action.pose_markers.remove(marker)
        props.active_event_index = max(0, min(index, len(props.event_markers) - 1))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_LmtExport(bpy.types.Operator):
    """Export the LMT with all its animations"""
    bl_idname = "albam.export_anim"
    bl_label = "Export LMT"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.lmt", options={"HIDDEN"})
    check_existing: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        lmt = get_active_lmt(context)
        return lmt is not None and len(lmt.actions) > 0

    def invoke(self, context, event):
        lmt = get_active_lmt(context)
        path = lmt.export_path or lmt.name
        if not path.lower().endswith(".lmt"):
            path += ".lmt"
        self.filepath = path
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):  # pragma: no cover
        lmt = get_active_lmt(context)
        try:
            self._execute(context, lmt)
        except Exception:
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
            return {"FINISHED"}
        lmt.export_path = self.filepath
        message = f"Exported {os.path.basename(self.filepath)}"
        if self.notes:
            # also in the console, the status bar only fits so much
            print(message + ":" + "".join("\n  " + note for note in self.notes))
            self.report({"WARNING"}, message + ". " + "; ".join(self.notes))
        else:
            self.report({"INFO"}, message)
        return {"FINISHED"}

    def _execute(self, context, lmt):
        for item in lmt.actions:
            if item.action:
                link_legacy_events(item.action)
        export_function = blender_registry.export_registry[("dmc4", "lmt")]
        self.notes = []
        data = export_function(lmt, self.notes)
        with open(self.filepath, "wb") as f:
            f.write(data)
