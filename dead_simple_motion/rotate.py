import bpy
from bpy.types import Operator
from . import utils

MARKER = "dsm_rotate_marker"
CONSTRAINT_NAME = "DSM Rotate Attach"


def _axis_index(axis):
    return {'X': 0, 'Y': 1, 'Z': 2}[axis]


def _angle_expression(scene, speed, delay):
    start = int(scene.frame_start)
    if scene.dsm_settings.rotate_use_start:
        start = int(scene.dsm_settings.rotate_start)
    start += int(delay)
    end = int(scene.dsm_settings.rotate_end) if scene.dsm_settings.rotate_use_end else None
    if end is not None:
        if end < start:
            end = start
        elapsed = f"max(min(frame, {end}) - {start}, 0)"
    else:
        elapsed = f"max(frame - {start}, 0)"
    return f"({elapsed}) * ({speed:.10f}) * 0.02"


def _remove_attach_constraint(obj):
    con = obj.constraints.get(CONSTRAINT_NAME)
    if con:
        try:
            obj.constraints.remove(con)
        except Exception:
            pass


def clear_object(obj, restore=True):
    if not obj or not obj.get("dsm_rotate_enabled", False):
        return False
    axis = int(obj.get("dsm_rotate_axis_index", 2))
    utils.remove_owned_driver(obj, "delta_rotation_euler", axis, MARKER)
    if restore:
        try:
            obj.delta_rotation_euler = obj.get("dsm_rotate_base_delta", [0.0, 0.0, 0.0])
        except Exception:
            pass
    _remove_attach_constraint(obj)
    marker_prop = f"{MARKER}_value"
    if marker_prop in obj:
        del obj[marker_prop]
    utils.clear_feature_props(obj, "rotate")
    return True


def _apply_attach_constraint(obj, target, bone_name):
    _remove_attach_constraint(obj)
    if not target:
        return
    target_matrix = utils.get_target_matrix(target, bone_name)
    if target_matrix is None:
        return
    con = obj.constraints.new('CHILD_OF')
    con.name = CONSTRAINT_NAME
    con.target = target
    if target.type == 'ARMATURE' and bone_name:
        con.subtarget = bone_name
    try:
        con.inverse_matrix = target_matrix.inverted()
    except Exception:
        pass


def apply_object(obj, context):
    scene = context.scene
    settings = scene.dsm_settings
    clear_object(obj, restore=True)
    axis = _axis_index(settings.rotate_axis)
    existing = utils.get_driver_fcurve(obj, "delta_rotation_euler", axis)
    if existing and not utils.driver_has_marker(existing, MARKER):
        return False, "delta rotation channel already has a driver"

    rng = utils.seeded_rng(obj, "rotate")
    speed_factor = utils.variation_factor(rng, settings.rotate_variation)
    delay = rng.uniform(0.0, settings.rotate_variation * 12.0)
    speed = settings.rotate_speed * speed_factor
    expr = _angle_expression(scene, speed, delay)

    obj["dsm_rotate_enabled"] = True
    obj["dsm_rotate_axis_index"] = axis
    obj["dsm_rotate_base_delta"] = utils.pack_vector(obj.delta_rotation_euler)
    obj["dsm_rotate_speed_factor"] = float(speed_factor)
    obj["dsm_rotate_delay"] = float(delay)

    base = float(obj.delta_rotation_euler[axis])
    fc = utils.add_owned_driver(obj, "delta_rotation_euler", axis, f"{base:.10f} + ({expr})", MARKER)
    if not fc:
        utils.clear_feature_props(obj, "rotate")
        return False, "could not create rotate driver"

    target = settings.rotate_target
    bone = settings.rotate_bone.strip() if target and target.type == 'ARMATURE' else ""
    _apply_attach_constraint(obj, target, bone)
    obj["dsm_rotate_target"] = target.name if target else ""
    obj["dsm_rotate_bone"] = bone
    return True, ""


class DSM_OT_rotate_apply(Operator):
    bl_idname = "dsm.rotate_apply"
    bl_label = "Apply Rotate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        target = context.scene.dsm_settings.rotate_target
        objects = utils.selected_objects(context, target)
        if not objects:
            self.report({'WARNING'}, "Select one or more objects")
            return {'CANCELLED'}
        success = 0
        skipped = []
        for obj in objects:
            ok, reason = apply_object(obj, context)
            if ok:
                success += 1
            else:
                skipped.append(f"{obj.name}: {reason}")
        if skipped:
            self.report({'WARNING'}, "; ".join(skipped[:3]))
        self.report({'INFO'}, f"Rotate applied to {success} object(s)")
        return {'FINISHED'}


class DSM_OT_rotate_clear(Operator):
    bl_idname = "dsm.rotate_clear"
    bl_label = "Clear Rotate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = sum(1 for obj in utils.selected_objects(context) if clear_object(obj))
        self.report({'INFO'}, f"Rotate cleared on {count} object(s)")
        return {'FINISHED'}


class DSM_OT_rotate_key_in(Operator):
    bl_idname = "dsm.rotate_key_in"
    bl_label = "Key In"
    bl_options = {'UNDO'}

    def execute(self, context):
        s = context.scene.dsm_settings
        s.rotate_use_start = True
        s.rotate_start = context.scene.frame_current
        return {'FINISHED'}


class DSM_OT_rotate_key_out(Operator):
    bl_idname = "dsm.rotate_key_out"
    bl_label = "Key Out"
    bl_options = {'UNDO'}

    def execute(self, context):
        s = context.scene.dsm_settings
        s.rotate_use_end = True
        s.rotate_end = context.scene.frame_current
        return {'FINISHED'}


class DSM_OT_rotate_clear_range(Operator):
    bl_idname = "dsm.rotate_clear_range"
    bl_label = "Clear Range"
    bl_options = {'UNDO'}

    def execute(self, context):
        s = context.scene.dsm_settings
        s.rotate_use_start = False
        s.rotate_use_end = False
        return {'FINISHED'}


_CLASSES = (DSM_OT_rotate_apply, DSM_OT_rotate_clear, DSM_OT_rotate_key_in, DSM_OT_rotate_key_out, DSM_OT_rotate_clear_range)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
