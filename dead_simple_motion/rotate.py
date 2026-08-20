import bpy
from bpy.types import Operator
from . import utils

MARKER = "dsm_rotate_marker"
ATTACH_CONSTRAINT_NAME = "DSM Rotate Attach"
SPIN_CONSTRAINT_NAME = "DSM Rotate Local Spin"
HELPER_PREFIX = "DSM_ROT_"


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


def _remove_constraint(obj, name):
    con = obj.constraints.get(name)
    if con:
        try:
            obj.constraints.remove(con)
        except Exception:
            pass


def _remove_helper(obj):
    helper_name = obj.get("dsm_rotate_helper", "")
    helper = bpy.data.objects.get(helper_name) if helper_name else None
    if helper:
        for index in range(4):
            utils.remove_owned_driver(helper, "rotation_quaternion", index, MARKER)
        try:
            bpy.data.objects.remove(helper, do_unlink=True)
        except Exception:
            pass


def _clear_legacy_delta_rotate(obj, restore=True):
    """Remove the 0.1.0 delta-Euler implementation if present."""
    axis = int(obj.get("dsm_rotate_axis_index", 2))
    utils.remove_owned_driver(obj, "delta_rotation_euler", axis, MARKER)
    if restore and "dsm_rotate_base_delta" in obj:
        try:
            obj.delta_rotation_euler = obj.get("dsm_rotate_base_delta", [0.0, 0.0, 0.0])
        except Exception:
            pass


def clear_object(obj, restore=True):
    if not obj or not obj.get("dsm_rotate_enabled", False):
        return False

    _remove_constraint(obj, SPIN_CONSTRAINT_NAME)
    _remove_constraint(obj, ATTACH_CONSTRAINT_NAME)
    _remove_helper(obj)
    _clear_legacy_delta_rotate(obj, restore=restore)

    marker_prop = f"{MARKER}_value"
    if marker_prop in obj:
        try:
            del obj[marker_prop]
        except Exception:
            pass

    utils.clear_feature_props(obj, "rotate")
    return True


def _apply_attach_constraint(obj, target, bone_name):
    _remove_constraint(obj, ATTACH_CONSTRAINT_NAME)
    if not target:
        return

    target_matrix = utils.get_target_matrix(target, bone_name)
    if target_matrix is None:
        return

    con = obj.constraints.new('CHILD_OF')
    con.name = ATTACH_CONSTRAINT_NAME
    con.target = target
    if target.type == 'ARMATURE' and bone_name:
        con.subtarget = bone_name

    try:
        con.inverse_matrix = target_matrix.inverted()
    except Exception:
        pass


def _create_spin_helper(obj, context, axis, angle_expr):
    helper = bpy.data.objects.new(f"{HELPER_PREFIX}{obj.name}", None)
    helper.empty_display_type = 'PLAIN_AXES'
    helper.empty_display_size = 0.001
    helper.rotation_mode = 'QUATERNION'
    helper.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    helper.hide_render = True
    helper.hide_select = True
    helper["dsm_rotate_helper_owner"] = obj.name

    collection = obj.users_collection[0] if obj.users_collection else context.collection
    collection.objects.link(helper)

    # IMPORTANT: do not call hide_set(True) or hide_viewport here.
    # A Copy Rotation constraint depends on this object being evaluated by the
    # active view layer. The helper is made tiny/unselectable instead.
    try:
        helper.hide_set(False)
        helper.hide_viewport = False
    except Exception:
        pass

    half_angle = f"(({angle_expr}) * 0.5)"
    expressions = [f"cos({half_angle})", "0.0", "0.0", "0.0"]
    axis_index = {'X': 1, 'Y': 2, 'Z': 3}[axis]
    expressions[axis_index] = f"sin({half_angle})"

    for index, expression in enumerate(expressions):
        fc = utils.add_owned_driver(
            helper,
            "rotation_quaternion",
            index,
            expression,
            MARKER,
        )
        if not fc:
            try:
                bpy.data.objects.remove(helper, do_unlink=True)
            except Exception:
                pass
            return None

    return helper


def _apply_local_spin_constraint(obj, helper):
    _remove_constraint(obj, SPIN_CONSTRAINT_NAME)
    con = obj.constraints.new('COPY_ROTATION')
    con.name = SPIN_CONSTRAINT_NAME
    con.target = helper
    con.use_x = True
    con.use_y = True
    con.use_z = True
    con.invert_x = False
    con.invert_y = False
    con.invert_z = False
    con.target_space = 'LOCAL'
    con.owner_space = 'LOCAL'
    con.mix_mode = 'AFTER'
    return con


def apply_object(obj, context):
    scene = context.scene
    settings = scene.dsm_settings

    clear_object(obj, restore=True)

    rng = utils.seeded_rng(obj, "rotate")
    speed_factor = utils.variation_factor(rng, settings.rotate_variation)
    delay = rng.uniform(0.0, settings.rotate_variation * 12.0)
    speed = settings.rotate_speed * speed_factor
    angle_expr = _angle_expression(scene, speed, delay)

    helper = _create_spin_helper(obj, context, settings.rotate_axis, angle_expr)
    if helper is None:
        return False, "could not create quaternion spin helper"

    target = settings.rotate_target
    bone = settings.rotate_bone.strip() if target and target.type == 'ARMATURE' else ""

    _apply_attach_constraint(obj, target, bone)
    _apply_local_spin_constraint(obj, helper)

    obj["dsm_rotate_enabled"] = True
    obj["dsm_rotate_helper"] = helper.name
    obj["dsm_rotate_axis"] = settings.rotate_axis
    obj["dsm_rotate_speed_factor"] = float(speed_factor)
    obj["dsm_rotate_delay"] = float(delay)
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


_CLASSES = (
    DSM_OT_rotate_apply,
    DSM_OT_rotate_clear,
    DSM_OT_rotate_key_in,
    DSM_OT_rotate_key_out,
    DSM_OT_rotate_clear_range,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
