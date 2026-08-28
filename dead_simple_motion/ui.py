import bpy
from bpy.types import Operator, Panel

from . import utils


def _apply_clear_row(layout, apply_id, clear_id, apply_text):
    row = layout.row(align=True)
    row.scale_y = 1.2
    row.operator(apply_id, text=apply_text, icon="PLAY")
    row.operator(clear_id, text="Clear", icon="X")


def _advanced_toggle(box, settings, prop_name):
    row = box.row()
    row.prop(settings, prop_name, text="Advanced", toggle=True, icon="PREFERENCES")


def _target_bone_ui(box, settings, target_attr, bone_attr):
    target = getattr(settings, target_attr)
    box.prop(settings, target_attr, text="Target")
    if target and target.type == "ARMATURE":
        box.prop_search(settings, bone_attr, target.data, "bones", text="Bone")


class DSM_OT_clear_all(Operator):
    bl_idname = "dsm.clear_all"
    bl_label = "Clear All Dead Simple Motion"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import follow, fx, orbit, rotate, spawn

        selected = utils.selected_objects(context)
        if not selected:
            self.report({"WARNING"}, "Select one or more objects")
            return {"CANCELLED"}

        owners = []
        seen = set()
        for item in selected:
            owner = utils.resolve_motion_owner(item)
            if owner and owner.name not in seen:
                seen.add(owner.name)
                owners.append(owner)

        count = 0
        for obj in owners:
            touched = False
            # Clear child-owned features before any control Empty is deleted.
            touched |= fx.clear_object(obj, restore=True)
            touched |= follow.clear_object(obj, restore=True)
            touched |= orbit.clear_object(obj, restore=True)
            touched |= spawn.clear_object(obj, restore=True)
            touched |= rotate.clear_object(obj, restore=True)
            if touched:
                count += 1

        self.report({"INFO"}, f"Dead Simple Motion cleared on {count} object(s)")
        return {"FINISHED"}


class DSM_PT_main(Panel):
    bl_label = "Dead Simple Motion"
    bl_idname = "DSM_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Dead Simple"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.dsm_settings

        tabs = layout.row(align=True)
        tabs.prop(settings, "tool", expand=True)
        layout.separator(factor=0.6)

        if settings.tool == "ROTATE":
            box = layout.box()
            row = box.row(align=True)
            row.label(text="Axis")
            row.prop(settings, "rotate_axis", expand=True)
            box.prop(settings, "rotate_speed", text="Speed")

            row = box.row(align=True)
            row.operator("dsm.rotate_key_in", text="Key In", icon="KEY_HLT")
            row.operator("dsm.rotate_key_out", text="Key Out", icon="KEY_DEHLT")
            row.operator("dsm.rotate_clear_range", text="Clear Range", icon="X")

            start = str(settings.rotate_start) if settings.rotate_use_start else "Scene Start"
            end = str(settings.rotate_end) if settings.rotate_use_end else "Forever"
            box.label(text=f"Range: {start} → {end}")

            _advanced_toggle(box, settings, "rotate_advanced")
            if settings.rotate_advanced:
                box.prop(settings, "rotate_variation", text="Variation")

            _apply_clear_row(box, "dsm.rotate_apply", "dsm.rotate_clear", "Apply Rotate")
            bake = box.row()
            bake.operator("dsm.rotate_bake", text="Bake Rotation", icon="KEYFRAME_HLT")

        elif settings.tool == "ORBIT":
            box = layout.box()
            _target_bone_ui(box, settings, "orbit_target", "orbit_bone")
            box.prop(settings, "orbit_shape", text="Shape")

            if settings.orbit_shape == "SPHERE":
                box.label(text="Plane: 3D / Rotating")
            else:
                row = box.row(align=True)
                row.label(text="Plane")
                row.prop(settings, "orbit_plane", expand=True)

            box.prop(settings, "orbit_speed", text="Speed")
            box.prop(settings, "orbit_orientation", text="Orientation")
            if settings.orbit_orientation != "NONE":
                box.prop(settings, "orbit_forward_axis", text="Forward Axis")

            _advanced_toggle(box, settings, "orbit_advanced")
            if settings.orbit_advanced:
                row = box.row(align=True)
                row.label(text="Behavior")
                row.prop(settings, "orbit_behavior", expand=True)
                box.prop(settings, "orbit_variation", text="Variation")
                if settings.orbit_shape == "SPHERE":
                    box.prop(settings, "orbit_sphere_axis_speed", text="Axis Speed")
                box.prop(settings, "orbit_fallback_radius", text="Fallback Radius")

            if settings.orbit_target is None:
                box.label(text="No target: uses the 3D Cursor as pivot")
            box.label(text="Cameras use a movable DSM focus Empty")
            _apply_clear_row(box, "dsm.orbit_apply", "dsm.orbit_clear", "Apply Orbit")

        elif settings.tool == "SPAWN":
            box = layout.box()
            row = box.row(align=True)
            row.label(text="Mode")
            row.prop(settings, "spawn_mode", expand=True)
            row = box.row(align=True)
            row.label(text="Axis")
            row.prop(settings, "spawn_axis", expand=True)
            box.prop(settings, "spawn_speed", text="Speed")
            box.prop(settings, "spawn_distance", text="Distance")

            _advanced_toggle(box, settings, "spawn_advanced")
            if settings.spawn_advanced:
                box.prop(settings, "spawn_fade_in_point", text="Fade In Point")
                box.prop(settings, "spawn_fade_out_point", text="Fade Out Point")
                box.prop(settings, "spawn_variation", text="Variation")

            if settings.spawn_mode == "LOOPER":
                box.label(text="Cameras get a movable focus Empty")
            _apply_clear_row(box, "dsm.spawn_apply", "dsm.spawn_clear", "Apply Spawn / Looper")

        elif settings.tool == "FOLLOW":
            box = layout.box()
            _target_bone_ui(box, settings, "follow_target", "follow_bone")
            box.prop(settings, "follow_delay", text="Delay", slider=True)
            box.label(text="0 = immediate • higher = more trailing lag")

            _advanced_toggle(box, settings, "follow_advanced")
            if settings.follow_advanced:
                box.prop(settings, "follow_drift", text="Drift")
                box.prop(settings, "follow_variation", text="Variation")

            box.label(text="Location follow only")
            _apply_clear_row(box, "dsm.follow_apply", "dsm.follow_clear", "Apply Follow")

        elif settings.tool == "FX":
            box = layout.box()
            box.prop(settings, "fx_preset", text="Preset")
            box.prop(settings, "fx_amount", text="Amount")
            box.prop(settings, "fx_speed", text="Speed")
            _advanced_toggle(box, settings, "fx_advanced")
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

        layout.separator(factor=0.8)
        clear = layout.row()
        clear.scale_y = 1.15
        clear.operator("dsm.clear_all", text="Clear All", icon="TRASH")


_CLASSES = (DSM_OT_clear_all, DSM_PT_main)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
