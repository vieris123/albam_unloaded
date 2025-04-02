import bpy

from albam.registry import blender_registry

@blender_registry.register_blender_type
class ALBAM_UL_LmtList(bpy.types.UIList):

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name)


@blender_registry.register_blender_type
class ALBAM_PT_LmtSection(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_LmtSection"
    bl_label = "LMT"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_context = 'action'
    bl_region_type = "UI"

    def draw(self, context):
        row = self.layout.row()
        row.template_list(
            "ALBAM_UL_LmtList",
            "lmt",
            context.scene.albam.lmt_groups,
            "anim_group",
            context.scene.albam.lmt_groups,
            "active_group_id",
            sort_lock=True,
            rows=1,
            maxrows=3,
        )
        index = context.scene.albam.lmt_groups.active_group_id
        item = context.scene.albam.lmt_groups.anim_group[index]

        for k in item.__annotations__:
            self.layout.prop(item, k)

@blender_registry.register_blender_type
class ALBAM_PT_AlbamActionMakeActive(bpy.types.Operator):
    bl_idname = "albam.make_active"
    bl_label = "Make Active"

    def execute(self, context):
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action
        #context.space_data.action = action
        lmt_item.armature.animation_data.action = action
        return {"FINISHED"}

@blender_registry.register_blender_type
class ALBAM_PT_AlbamActionAddAnim(bpy.types.Operator):
    bl_idname = "albam.add_anim"
    bl_label = "Add Animation"


    def get_actions(self, context):
        action_names = bpy.data.actions.keys()
        action_list = zip(action_names, action_names, ['']*len(action_names), range(len(action_names)))
        return action_list
    
    name: bpy.props.StringProperty(name='Anim Name')
    action_list: bpy.props.EnumProperty(items=get_actions,name='Actions')
    use_existing: bpy.props.BoolProperty(name = 'Use existing animation')

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)
    
    def execute(self, context):
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]

        if self.use_existing:
            new_action = bpy.data.actions[bpy.data.actions.find(str(self.action_list))]
            new_anim = lmt_item.add(self.name)
            new_anim.action = new_action
        else:
            new_action = bpy.data.actions.new(self.name)
            new_anim = lmt_item.add(self.name)
            new_anim.action = new_action
        new_action.albam_asset.app_id = 'dmc4'

        custom_property = new_action.albam_custom_properties.get_custom_properties_for_appid('dmc4')
        return {"FINISHED"}

    def draw(self, context):
        self.layout.prop(self, 'name')
        self.layout.prop(self, 'use_existing')
        if self.use_existing:
            self.layout.prop(self, 'action_list')


@blender_registry.register_blender_type
class ALBAM_PT_AlbamActionRemoveAnim(bpy.types.Operator):
    bl_idname = "albam.remove_anim"
    bl_label = "Remove Animation"

    def execute(self, context):
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action
        lmt_item.actions.remove(lmt_item.active_id)
        bpy.data.actions.remove(action)
        return {"FINISHED"}

@blender_registry.register_blender_type
class ALBAM_PT_AlbamActionReorgFcurve(bpy.types.Operator):
    bl_idname = "albam.reorganize_fcurves"
    bl_label = "Reorganize F-Curves"
    bl_description = "Clean up F-Curves for exporting. Use this for new animations before exporting"
    def execute(self, context):
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action
        for group in action.groups:
            action.groups.remove(group)
        for f in action.fcurves:
            data_path = f.data_path
            bone_name = data_path[data_path.find('[\"')+2:data_path.find('\"]')]
            action_type = data_path.split('.')[-1]
            group_name = f'{bone_name}.{action_type}'
            group = action.groups.get(group_name) or action.groups.new(group_name)
            f.group = group
        return {"FINISHED"}
    

@blender_registry.register_blender_type
class ALBAM_PT_AlbamActionSection(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_AlbamActionSection"
    bl_label = "Albam Action"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_context = 'action'
    bl_region_type = "UI"

    def draw(self, context):
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]

        box = self.layout.box()
        row = box.row()
        col = row.column()
        col.operator('albam.add_anim',icon='ADD',text='')
        col.operator('albam.remove_anim',icon='REMOVE',text='')
        row.template_list(
            "ALBAM_UL_LmtList",
            "action",
            lmt_item,
            "actions",
            lmt_item,
            "active_id",
            sort_lock=True,
            rows=1,
            maxrows=5,
        )
        box.operator('albam.make_active')
        box.operator('albam.reorganize_fcurves')
        action = lmt_item.actions[lmt_item.active_id].action
        #lmt_item.armature.animation_data.action = action
        #context.space_data.action = action
        app_id = action.albam_asset.app_id
        custom_properties = action.albam_custom_properties.get_custom_properties_for_appid(app_id)

        self.layout.prop(custom_properties, 'lmt_id')
        self.layout.prop(custom_properties, 'num_frames')
        self.layout.prop(custom_properties, 'loop_frames')
        self.layout.prop(custom_properties, 'end_pos')
        self.layout.prop(custom_properties, 'end_quat')
        self.layout.operator('albam.export_anim', text='Export')
        # for i in range(8):
        #     self.layout.prop(custom_properties, f'events_params_01[{i}]')
        #self.layout.prop_with_menu(custom_properties, 'events_params_02')
        # for k in custom_properties.__annotations__:
        #     self.layout.prop(custom_properties, k)

@blender_registry.register_blender_type
class ALBAM_PT_AlbamAddEvent(bpy.types.Operator):
    bl_idname = 'albam.add_event'
    bl_label = 'Add event at current frame'
    name: bpy.props.StringProperty(name = 'Event Name')
    ev_type_enum = bpy.props.EnumProperty(
        name = 'Event Type',
        description = 'Define indexed parameters type',
        items = [
            ('Hitbox', 'Hitbox', 'Hitbox indices', 0),
            ('Sound', 'Sound', 'Sound indices', 1)
        ],
        default = 'Hitbox'
    )
    ev_type: ev_type_enum

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def execute(self, context):
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action
        app_id = context.scene.albam.apps.app_selected
        action_custom_prop = action.albam_custom_properties.get_custom_properties_for_appid(app_id)

        pose_marker = action.pose_markers.new(self.name)
        pose_marker.frame = context.scene.frame_current
        pose_marker.dmc4_event_props.setup(self.ev_type, 0)
        pose_marker.dmc4_event_props.action = lmt_item.actions[lmt_item.active_id]

        return {"FINISHED"}

    def draw(self, context):
        self.layout.prop(self, 'name')
        self.layout.prop(self, 'ev_type')

@blender_registry.register_blender_type
class ALBAM_PT_AlbamRemoveEvent(bpy.types.Operator):
    bl_idname = 'albam.remove_event'
    bl_label = 'Remove Event'

    def execute(self, context):
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action
        pose_marker = action.pose_markers.active
        action.pose_markers.remove(pose_marker)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_PT_AlbamEventSection(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_AlbamEventSection"
    bl_label = "Albam Events"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_context = 'action'
    bl_region_type = "UI"

    def draw(self, context):
        # self.layout.use_property_split = True
        # self.layout.use_property_decorate = False
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action

        row = self.layout.row()
        col = row.column()
        col.operator('albam.add_event',icon='ADD',text='')
        col.operator('albam.remove_event',icon='REMOVE',text='')
        row.template_list(
            "ALBAM_UL_LmtList",
            "event",
            action,
            "pose_markers",
            action.pose_markers,
            "active_index",
            sort_lock=True,
            rows=1,
            maxrows=3,
        )

@blender_registry.register_blender_type
class ALBAM_PT_AlbamIndexedEventSection(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_AlbamIndexedEventSection"
    bl_parent_id = 'ALBAM_PT_AlbamEventSection'
    bl_label = "Indexed Events"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_context = 'action'
    bl_region_type = "UI"

    def draw(self, context):
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action
        app_id = context.scene.albam.apps.app_selected
        action_custom_prop = action.albam_custom_properties.get_custom_properties_for_appid(app_id)
        pose_marker = action.pose_markers.active
        ev_custom_properties = pose_marker.dmc4_event_props

        row = self.layout.row(align=True)
        split = row.split(factor=0.5,align=True)

        row_toggle = split.row()
        col = row_toggle.column(align=True)
        for i in range(8):
            col.label(text=f'Event {i+1}')
        col = row_toggle.column()    
        col.prop(pose_marker.dmc4_event_props, 'slots', text='', toggle=0)

        split = split.split()
        col = split.column()
        if ev_custom_properties.param_ev_type == 'Hitbox':
            col.prop(action_custom_prop, 'events_params_01', text='', slider=True)
        else:
            col.prop(action_custom_prop, 'events_params_02', text='', slider=True)
        self.layout.prop(ev_custom_properties, 'param_ev_type')

    @classmethod
    def poll(self, context):
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action
        return action.pose_markers.active

@blender_registry.register_blender_type
class ALBAM_PT_AlbamHashedEventSection(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_AlbamHashedEventSection"
    bl_parent_id = 'ALBAM_PT_AlbamEventSection'
    bl_label = "Hashed Events"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_context = 'action'
    bl_region_type = "UI"

    def draw(self, context):
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action
        pose_marker = action.pose_markers.active
        ev_custom_properties = pose_marker.dmc4_event_props
        
        for k in ev_custom_properties.__annotations__:
            if k in ['slots', 'param_ev_type']:
                continue
            self.layout.prop(ev_custom_properties, k, slider=True)
    
    @classmethod
    def poll(self, context):
        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action
        return action.pose_markers.active


@blender_registry.register_blender_prop_albam(name="anim_exp_settings")
class AnimExportSettings(bpy.types.PropertyGroup):
    path: bpy.props.StringProperty()

@blender_registry.register_blender_type
class ExportAnimation(bpy.types.Operator):
    bl_idname = "albam.export_anim"
    bl_label = "Export Animations"
    filepath: bpy.props.StringProperty()

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):  # pragma: no cover
        index = context.scene.albam.lmt_groups.active_group_id
        item = context.scene.albam.lmt_groups.anim_group[index]
        try:
            self._execute(context, item)
        except Exception:
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
        return {"FINISHED"}

    def _execute(self, context, item):
        export_function = blender_registry.export_registry[('dmc4', 'lmt')]
        data = export_function(item)
        with open(self.filepath,'wb') as f:
            f.write(data)

class ActiveMarker(bpy.types.Operator):
    pass