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
            "active_group",
            sort_lock=True,
            rows=1,
            maxrows=3,
        )
        index = context.scene.albam.lmt_groups.active_group
        item = context.scene.albam.lmt_groups.anim_group[index]

        for k in item.__annotations__:
            self.layout.prop(item, k)

@blender_registry.register_blender_type
class ALBAM_PT_AlbamActionSection(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_AlbamActionSection"
    bl_label = "Albam action"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_context = 'action'
    bl_region_type = "UI"

    def draw(self, context):
        row = self.layout.row()

        lmt_index = context.scene.albam.lmt_groups.active_group
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

        for k in custom_properties.__annotations__:
            self.layout.prop(custom_properties, k)


@blender_registry.register_blender_type
class ALBAM_PT_AlbamEventSection(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_AlbamEventSection"
    bl_label = "Albam events"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_context = 'action'
    bl_region_type = "UI"

    def draw(self, context):
        row = self.layout.row()

        lmt_index = context.scene.albam.lmt_groups.active_group
        lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]
        action = lmt_item.actions[lmt_item.active_id].action
        pose_marker = action.pose_markers

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

        pose_marker = action.pose_markers.active

        custom_properties = pose_marker.dmc4_event_props
        for k in custom_properties.__annotations__:
            if k == 'slots':
                continue
            self.layout.prop(custom_properties, k)

        col = self.layout.column()
        for i, slot in enumerate(pose_marker.dmc4_event_props.slots):
            if pose_marker.param_ev_type == 'Hitbox':
                col.prop(pose_marker.action.coll_ev[i])
            else:
                col.prop(pose_marker.action.sfx_ev[i])
            col.prop(slot)


    # @classmethod
    # def poll(self, context):
    #     lmt_index = context.scene.albam.lmt_groups.active_group
    #     lmt_item = context.scene.albam.lmt_groups.anim_group[lmt_index]

    #     action = lmt_item.actions[lmt_item.active_id].action
    #     pose_marker = action.pose_markers.active

    #     return pose_marker
