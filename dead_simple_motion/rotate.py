import bpy
from bpy.types import Operator
from mathutils import Matrix, Vector
from . import utils

MARKER = "dsm_rotate_marker"
CONTROL_PREFIX = "DSM_ROT_CTRL_"
LEGACY_ATTACH_CONSTRAINT = "DSM Rotate Attach"
LEGACY_SPIN_CONSTRAINT = "DSM Rotate Local Spin"


def _angle_expression(scene, speed, delay):
    settings = scene.dsm_settings
    start = int(settings.rotate_start) if settings.rotate_use_start else int(scene.frame_start)
    start += int(round(delay))

    if settings.rotate_use_end:
        end = max(start, int(settings.rotate_end))
        elapsed = f"max(min(frame, {end}) - {start}, 0)"
    else:
        elapsed = f"max(frame - {start}, 0)"

    return f"({elapsed}) * ({speed:.10f}) * 0.02"


def _resolve_rotate_child(obj):
    if not obj:
        return None

    if obj.get("dsm_rotate_control", False):
        return bpy.data.objects.get(obj.get("dsm_rotate_child", ""))

    if obj.get("dsm_rotate_helper_owner"):
        return bpy.data.objects.get(obj.get("dsm_rotate_helper_owner", ""))

    if obj.get("dsm_rotate_enabled", False):
        return obj

    return None


def _remove_constraint(obj, name):
    if not obj:
        return
    con = obj.constraints.get(name)
    if con:
        try:
            obj.constraints.remove(con)
        except Exception:
            pass


def _remove_legacy_helper(child):
    helper_name = child.get("dsm_rotate_helper", "")
    helper = bpy.data.objects.get(helper_name) if helper_name else None
    if helper:
        for index in range(4):
            utils.remove_owned_driver(helper, "rotation_quaternion", index, MARKER)
        try:
            bpy.data.objects.remove(helper, do_unlink=True)
        except Exception:
            pass


def _cleanup_old_rotate_data(child):
    """Remove rotate implementations from the early 0.1.x test builds."""
    _remove_constraint(child, LEGACY_ATTACH_CONSTRAINT)
    _remove_constraint(child, LEGACY_SPIN_CONSTRAINT)
    _remove_legacy_helper(child)

    for index in range(4):
        utils.remove_owned_driver(child, "rotation_quaternion", index, MARKER)

    for index in range(3):
        utils.remove_owned_driver(child, "delta_rotation_euler", index, MARKER)


def _control_display_size(obj):
    try:
        size = max(float(v) for v in obj.dimensions)
    except Exception:
        size = 1.0
    return max(1.0, min(size * 0.9, 8.0))


def _create_control(child, context, original_parent, original_parent_type, original_parent_bone):
    """Create the artist-facing axis Empty and put the object beneath it."""
    world = child.matrix_world.copy()
    location, rotation, scale = world.decompose()

    control = bpy.data.objects.new(f"{CONTROL_PREFIX}{child.name}", None)
    control.empty_display_type = 'ARROWS'
    control.empty_display_size = _control_display_size(child)
    control.show_in_front = True
    control.hide_render = True
    control.hide_select = False
    control["dsm_rotate_control"] = True
    control["dsm_rotate_child"] = child.name

    collection = child.users_collection[0] if child.users_collection else context.collection
    collection.objects.link(control)

    if original_parent:
        control.parent = original_parent
        try:
            control.parent_type = original_parent_type
        except Exception:
            pass
        if original_parent_type == 'BONE':
            try:
                control.parent_bone = original_parent_bone
            except Exception:
                pass

    # The control owns placement + orientation. Scale stays on the child.
    control.matrix_world = Matrix.LocRotScale(location, rotation, Vector((1.0, 1.0, 1.0)))

    # The child is deliberately neutral underneath the control. This makes
    # quaternion X/Y/Z spin unambiguously LOCAL to the visible axis Empty.
    child.parent = control
    child.parent_type = 'OBJECT'
    child.parent_bone = ""
    child.matrix_parent_inverse = Matrix.Identity(4)
    child.location = (0.0, 0.0, 0.0)
    child.rotation_mode = 'QUATERNION'
    child.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    child.scale = scale

    return control


def _spin_expressions(axis, angle_expr):
    half = f"(({angle_expr}) * 0.5)"
    expressions = [f"cos({half})", "0.0", "0.0", "0.0"]
    axis_index = {'X': 1, 'Y': 2, 'Z': 3}[axis]
    expressions[axis_index] = f"sin({half})"
    return expressions


def clear_object(obj, restore=True):
    child = _resolve_rotate_child(obj)
    if not child or not child.get("dsm_rotate_enabled", False):
        return False

    control_name = child.get("dsm_rotate_control_name", "")
    control = bpy.data.objects.get(control_name) if control_name else None

    _cleanup_old_rotate_data(child)

    for index in range(4):
        utils.remove_owned_driver(child, "rotation_quaternion", index, MARKER)

    # Remove the spin before capturing the control's current placement.
    try:
        child.rotation_mode = 'QUATERNION'
        child.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        bpy.context.view_layer.update()
    except Exception:
        pass

    world = child.matrix_world.copy()

    original_parent_name = child.get("dsm_rotate_original_parent", "")
    original_parent = bpy.data.objects.get(original_parent_name) if original_parent_name else None
    original_parent_type = child.get("dsm_rotate_original_parent_type", "OBJECT")
    original_parent_bone = child.get("dsm_rotate_original_parent_bone", "")
    original_rotation_mode = child.get("dsm_rotate_original_rotation_mode", "XYZ")
    original_hide_select = bool(child.get("dsm_rotate_original_hide_select", False))

    child.parent = original_parent
    if original_parent:
        try:
            child.parent_type = original_parent_type
        except Exception:
            pass
        if original_parent_type == 'BONE':
            try:
                child.parent_bone = original_parent_bone
            except Exception:
                pass
    else:
        child.parent_type = 'OBJECT'
        child.parent_bone = ""

    child.matrix_parent_inverse = Matrix.Identity(4)
    child.matrix_world = world
    child.hide_select = original_hide_select

    try:
        child.rotation_mode = original_rotation_mode
    except Exception:
        pass

    if control:
        try:
            bpy.data.objects.remove(control, do_unlink=True)
        except Exception:
            pass

    marker_prop = f"{MARKER}_value"
    if marker_prop in child:
        try:
            del child[marker_prop]
        except Exception:
            pass

    utils.clear_feature_props(child, "rotate")
    return True


def apply_object(obj, context):
    existing_child = _resolve_rotate_child(obj)
    if existing_child:
        obj = existing_child
        clear_object(obj, restore=True)

    scene = context.scene
    settings = scene.dsm_settings

    # Never overwrite the artist's own rotation animation/drivers.
    if utils.has_animation_path(
        obj,
        {
            "rotation_euler",
            "rotation_quaternion",
            "rotation_axis_angle",
            "delta_rotation_euler",
            "delta_rotation_quaternion",
        },
    ):
        return False, "object already has rotation animation/drivers", None

    original_parent = obj.parent
    original_parent_name = original_parent.name if original_parent else ""
    original_parent_type = obj.parent_type if original_parent else "OBJECT"
    original_parent_bone = obj.parent_bone if original_parent and obj.parent_type == 'BONE' else ""
    original_rotation_mode = obj.rotation_mode
    original_hide_select = bool(obj.hide_select)

    rng = utils.seeded_rng(obj, "rotate")
    speed_factor = utils.variation_factor(rng, settings.rotate_variation)
    delay = rng.uniform(0.0, settings.rotate_variation * 12.0)
    speed = settings.rotate_speed * speed_factor
    angle_expr = _angle_expression(scene, speed, delay)

    control = _create_control(
        obj,
        context,
        original_parent,
        original_parent_type,
        original_parent_bone,
    )

    created = []
    for index, expression in enumerate(_spin_expressions(settings.rotate_axis, angle_expr)):
        fc = utils.add_owned_driver(obj, "rotation_quaternion", index, expression, MARKER)
        if not fc:
            for made_index in created:
                utils.remove_owned_driver(obj, "rotation_quaternion", made_index, MARKER)
            try:
                bpy.data.objects.remove(control, do_unlink=True)
            except Exception:
                pass
            return False, "could not create quaternion rotate driver", None
        created.append(index)

    obj["dsm_rotate_enabled"] = True
    obj["dsm_rotate_control_name"] = control.name
    obj["dsm_rotate_axis"] = settings.rotate_axis
    obj["dsm_rotate_speed_factor"] = float(speed_factor)
    obj["dsm_rotate_delay"] = float(delay)
    obj["dsm_rotate_original_parent"] = original_parent_name
    obj["dsm_rotate_original_parent_type"] = original_parent_type
    obj["dsm_rotate_original_parent_bone"] = original_parent_bone
    obj["dsm_rotate_original_rotation_mode"] = original_rotation_mode
    obj["dsm_rotate_original_hide_select"] = original_hide_select

    # Once rigged, the user manipulates the axis Empty, not the spinning mesh.
    obj.hide_select = True

    try:
        obj.update_tag()
        context.view_layer.update()
    except Exception:
        pass

    return True, "", control


class DSM_OT_rotate_apply(Operator):
    bl_idname = "dsm.rotate_apply"
    bl_label = "Apply Rotate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects = utils.selected_objects(context)
        if not objects:
            self.report({'WARNING'}, "Select one or more objects")
            return {'CANCELLED'}

        unique_objects = []
        seen = set()
        for obj in objects:
            child = _resolve_rotate_child(obj) or obj
            if child.name not in seen:
                seen.add(child.name)
                unique_objects.append(child)

        success = 0
        skipped = []
        controls = []

        for obj in unique_objects:
            ok, reason, control = apply_object(obj, context)
            if ok:
                success += 1
                controls.append(control)
            else:
                skipped.append(f"{obj.name}: {reason}")

        if controls:
            try:
                bpy.ops.object.select_all(action='DESELECT')
                for control in controls:
                    control.hide_select = False
                    control.select_set(True)
                context.view_layer.objects.active = controls[0]
            except Exception:
                pass

        if skipped:
            self.report({'WARNING'}, "; ".join(skipped[:3]))
        self.report({'INFO'}, f"Rotate applied to {success} object(s)")
        return {'FINISHED'}


class DSM_OT_rotate_clear(Operator):
    bl_idname = "dsm.rotate_clear"
    bl_label = "Clear Rotate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects = utils.selected_objects(context)
        count = 0
        seen = set()

        for obj in objects:
            child = _resolve_rotate_child(obj)
            if child and child.name not in seen:
                seen.add(child.name)
                if clear_object(child):
                    count += 1

        self.report({'INFO'}, f"Rotate cleared on {count} object(s)")
        return {'FINISHED'}


class DSM_OT_rotate_key_in(Operator):
    bl_idname = "dsm.rotate_key_in"
    bl_label = "Key In"
    bl_options = {'UNDO'}

    def execute(self, context):
        settings = context.scene.dsm_settings
        settings.rotate_use_start = True
        settings.rotate_start = context.scene.frame_current
        return {'FINISHED'}


class DSM_OT_rotate_key_out(Operator):
    bl_idname = "dsm.rotate_key_out"
    bl_label = "Key Out"
    bl_options = {'UNDO'}

    def execute(self, context):
        settings = context.scene.dsm_settings
        settings.rotate_use_end = True
        settings.rotate_end = context.scene.frame_current
        return {'FINISHED'}


class DSM_OT_rotate_clear_range(Operator):
    bl_idname = "dsm.rotate_clear_range"
    bl_label = "Clear Range"
    bl_options = {'UNDO'}

    def execute(self, context):
        settings = context.scene.dsm_settings
        settings.rotate_use_start = False
        settings.rotate_use_end = False
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
