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
class ALBAM_PT_AlbamActionSection(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_AlbamActionSection"
    bl_label = "Albam Action"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_context = 'action'
    bl_region_type = "UI"

    def draw(self, context):
        row = self.layout.row()

        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]

        row.template_list(
            "ALBAM_UL_LmtList",
            "action",
            lmt_item,
            "actions",
            lmt_item,
            "active_id",
            sort_lock=True,
            rows=1,
            maxrows=3,
        )

        action = lmt_item.actions[lmt_item.active_id].action
        #lmt_item.armature.animation_data.action = action
        context.space_data.action = action
        app_id = action.albam_asset.app_id
        self.layout.prop(action.albam_asset, 'lmt_index')
        custom_properties = action.albam_custom_properties.get_custom_properties_for_appid(app_id)

        self.layout.prop(custom_properties, 'num_frames')
        self.layout.prop(custom_properties, 'loop_frames')
        # for i in range(8):
        #     self.layout.prop(custom_properties, f'events_params_01[{i}]')
        #self.layout.prop_with_menu(custom_properties, 'events_params_02')
        # for k in custom_properties.__annotations__:
        #     self.layout.prop(custom_properties, k)

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
        row = self.layout.row()

        lmt_index = context.scene.albam.lmt_groups.active_group_id
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action
        app_id = context.scene.albam.apps.app_selected
        action_custom_prop = action.albam_custom_properties.get_custom_properties_for_appid(app_id)

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
        split = row.split(factor=0.3,align=True)

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
        app_id = context.scene.albam.apps.app_selected
        action_custom_prop = action.albam_custom_properties.get_custom_properties_for_appid(app_id)
        pose_marker = action.pose_markers.active
        ev_custom_properties = pose_marker.dmc4_event_props
        
        for k in ev_custom_properties.__annotations__:
            if k in ['slots', 'param_ev_type']:
                continue
            self.layout.prop(ev_custom_properties, k, slider=True)

class ActiveMarker(bpy.types.Operator):
    pass