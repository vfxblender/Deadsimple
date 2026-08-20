import bpy
from bpy.types import Operator, Panel
from . import utils


def _apply_clear_row(layout, apply_id, clear_id, apply_text):
    row = layout.row(align=True)
    row.scale_y = 1.25
    row.operator(apply_id, text=apply_text, icon='PLAY')
    row.operator(clear_id, text="Clear", icon='X')


def _target_bone_ui(box, settings, target_attr, bone_attr):
    target = getattr(settings, target_attr)
    box.prop(settings, target_attr, text="Target")
    if target and target.type == 'ARMATURE':
        box.prop_search(settings, bone_attr, target.data, "bones", text="Bone")


class DSM_OT_clear_all(Operator):
    bl_idname = "dsm.clear_all"
    bl_label = "Clear All Dead Simple Motion"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from . import rotate, orbit, fx, spawn, follow
        objects = utils.selected_objects(context)
        if not objects:
            self.report({'WARNING'}, "Select one or more objects")
            return {'CANCELLED'}
        count = 0
        for obj in objects:
            touched = False
            touched |= rotate.clear_object(obj, restore=True)
            touched |= orbit.clear_object(obj, restore=True)
            touched |= fx.clear_object(obj, restore=True)
            touched |= spawn.clear_object(obj, restore=True)
            touched |= follow.clear_object(obj, restore=True)
            if touched:
                count += 1
        self.report({'INFO'}, f"Dead Simple Motion cleared on {count} object(s)")
        return {'FINISHED'}


class DSM_PT_main(Panel):
    bl_label = "Dead Simple Motion"
    bl_idname = "DSM_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Dead Simple'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.dsm_settings

        tabs = layout.row(align=True)
        tabs.prop(settings, "tool", expand=True)
        layout.separator(factor=0.6)

        if settings.tool == 'ROTATE':
            box = layout.box()
            row = box.row(align=True)
            row.label(text="Axis")
            row.prop(settings, "rotate_axis", expand=True)
            box.prop(settings, "rotate_speed", text="Speed")
            box.prop(settings, "rotate_variation", text="Variation")

            range_row = box.row(align=True)
            range_row.operator("dsm.rotate_key_in", text="Key In", icon='KEY_HLT')
            range_row.operator("dsm.rotate_key_out", text="Key Out", icon='KEY_DEHLT')
            range_row.operator("dsm.rotate_clear_range", text="Clear", icon='X')

            if settings.rotate_use_start or settings.rotate_use_end:
                start = str(settings.rotate_start) if settings.rotate_use_start else "Start"
                end = str(settings.rotate_end) if settings.rotate_use_end else "Forever"
                box.label(text=f"Range: {start} → {end}")
            else:
                box.label(text="Range: Forever")

            _apply_clear_row(box, "dsm.rotate_apply", "dsm.rotate_clear", "Apply Rotate")

        elif settings.tool == 'ORBIT':
            box = layout.box()
            _target_bone_ui(box, settings, "orbit_target", "orbit_bone")
            row = box.row(align=True)
            row.label(text="Plane")
            row.prop(settings, "orbit_plane", expand=True)
            box.prop(settings, "orbit_shape", text="Shape")
            row = box.row(align=True)
            row.label(text="Behavior")
            row.prop(settings, "orbit_behavior", expand=True)
            box.prop(settings, "orbit_speed", text="Speed")
            box.prop(settings, "orbit_variation", text="Variation")
            if settings.orbit_target is None:
                box.label(text="No target: uses the 3D Cursor as pivot", icon='PIVOT_CURSOR')
            _apply_clear_row(box, "dsm.orbit_apply", "dsm.orbit_clear", "Apply Orbit")

        elif settings.tool == 'FX':
            box = layout.box()
            box.prop(settings, "fx_preset", text="Preset")
            box.prop(settings, "fx_amount", text="Amount")
            box.prop(settings, "fx_speed", text="Speed")
            box.prop(settings, "fx_advanced", text="Advanced", toggle=True, icon='PREFERENCES')
            if settings.fx_advanced:
                box.prop(settings, "fx_variation", text="Variation")
                box.prop(settings, "fx_float", text="Float")
                box.prop(settings, "fx_wobble", text="Wobble")
                box.prop(settings, "fx_scale", text="Scale Pulse")
                box.prop(settings, "fx_bob", text="Bob")
                row = box.row(align=True)
                row.label(text="Bob Axis")
                row.prop(settings, "fx_bob_axis", expand=True)
                box.prop(settings, "fx_shake", text="Shake")
                box.prop(settings, "fx_shake_speed", text="Shake Speed")
            _apply_clear_row(box, "dsm.fx_apply", "dsm.fx_clear", "Apply FX")

        elif settings.tool == 'SPAWN':
            box = layout.box()
            row = box.row(align=True)
            row.label(text="Mode")
            row.prop(settings, "spawn_mode", expand=True)
            row = box.row(align=True)
            row.label(text="Axis")
            row.prop(settings, "spawn_axis", expand=True)
            box.prop(settings, "spawn_speed", text="Speed")
            box.prop(settings, "spawn_distance", text="Distance")
            box.prop(settings, "spawn_variation", text="Variation")
            _apply_clear_row(box, "dsm.spawn_apply", "dsm.spawn_clear", "Apply Spawn / Looper")

        elif settings.tool == 'FOLLOW':
            box = layout.box()
            _target_bone_ui(box, settings, "follow_target", "follow_bone")
            box.prop(settings, "follow_delay", text="Delay")
            box.prop(settings, "follow_drift", text="Drift")
            box.prop(settings, "follow_variation", text="Variation")
            box.label(text="Location follow only; bone rotation will not orbit", icon='CAMERA_DATA')
            _apply_clear_row(box, "dsm.follow_apply", "dsm.follow_clear", "Apply Follow")

        layout.separator(factor=0.8)
        clear = layout.row()
        clear.scale_y = 1.2
        clear.operator("dsm.clear_all", text="Clear All", icon='TRASH')


_CLASSES = (DSM_OT_clear_all, DSM_PT_main)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
