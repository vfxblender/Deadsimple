import bpy
from bpy.types import Operator
from mathutils import Matrix, Vector
from . import utils

DRIVER_MARKER = "dsm_rotate_marker"
CONTROL_PREFIX = "DSM_ROT_CTRL_"


def _axis_index(axis):
    return {"X": 0, "Y": 1, "Z": 2}[axis]


def _angle_expression(scene, speed, delay_frames):
    settings = scene.dsm_settings
    start = int(settings.rotate_start) if settings.rotate_use_start else int(scene.frame_start)
    start += int(round(delay_frames))

    if settings.rotate_use_end:
        end = max(start, int(settings.rotate_end))
        elapsed = f"max(min(frame, {end}) - {start}, 0)"
    else:
        elapsed = f"max(frame - {start}, 0)"

    return f"({elapsed}) * ({speed:.10f}) * 0.02"


def _resolve_child(obj):
    if not obj:
        return None
    if obj.get("dsm_rotate_control", False):
        return bpy.data.objects.get(obj.get("dsm_rotate_child", ""))
    if obj.get("dsm_rotate_enabled", False):
        return obj
    return None


def _remove_owned_rotation_drivers(obj):
    for index in range(3):
        utils.remove_owned_driver(obj, "rotation_euler", index, DRIVER_MARKER)

    # Cleanup for early alpha builds only.
    for index in range(3):
        utils.remove_owned_driver(obj, "delta_rotation_euler", index, DRIVER_MARKER)
    for index in range(4):
        utils.remove_owned_driver(obj, "rotation_quaternion", index, DRIVER_MARKER)


def _remove_old_helpers(obj):
    helper_name = obj.get("dsm_rotate_helper", "")
    helper = bpy.data.objects.get(helper_name) if helper_name else None
    if helper:
        try:
            bpy.data.objects.remove(helper, do_unlink=True)
        except Exception:
            pass

    for constraint_name in ("DSM Rotate Attach", "DSM Rotate Local Spin"):
        con = obj.constraints.get(constraint_name)
        if con:
            try:
                obj.constraints.remove(con)
            except Exception:
                pass


def _control_size(obj):
    try:
        size = max(abs(float(v)) for v in obj.dimensions)
    except Exception:
        size = 1.0
    return max(1.5, min(size * 1.25, 12.0))


def _create_control(obj, context):
    """Create a visible Empty that owns placement/orientation for the spinner."""
    world = obj.matrix_world.copy()
    location, rotation, scale = world.decompose()

    control = bpy.data.objects.new(f"{CONTROL_PREFIX}{obj.name}", None)
    control.empty_display_type = 'ARROWS'
    control.empty_display_size = _control_size(obj)
    control.show_in_front = True
    control.hide_render = True
    control.hide_select = False
    control["dsm_rotate_control"] = True
    control["dsm_rotate_child"] = obj.name

    collection = obj.users_collection[0] if obj.users_collection else context.collection
    collection.objects.link(control)

    original_parent = obj.parent
    original_parent_type = obj.parent_type if original_parent else 'OBJECT'
    original_parent_bone = obj.parent_bone if original_parent and obj.parent_type == 'BONE' else ""

    if original_parent:
        control.parent = original_parent
        control.parent_type = original_parent_type
        if original_parent_type == 'BONE':
            control.parent_bone = original_parent_bone

    # The Empty takes the object's world position + orientation.
    control.matrix_world = Matrix.LocRotScale(location, rotation, Vector((1.0, 1.0, 1.0)))

    # The mesh becomes a neutral local child. Its rotation channels are now a
    # pure local spin layer, while the Empty remains free for G/R transforms.
    obj.parent = control
    obj.parent_type = 'OBJECT'
    obj.parent_bone = ""
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_mode = 'XYZ'
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = scale

    return control


def _add_spin_driver(obj, axis, expression):
    index = _axis_index(axis)
    existing = utils.get_driver_fcurve(obj, "rotation_euler", index)
    if existing and not utils.driver_has_marker(existing, DRIVER_MARKER):
        return False

    fc = utils.add_owned_driver(
        obj,
        "rotation_euler",
        index,
        expression,
        DRIVER_MARKER,
    )
    return fc is not None


def clear_object(obj, restore=True):
    child = _resolve_child(obj)
    if not child or not child.get("dsm_rotate_enabled", False):
        return False

    control_name = child.get("dsm_rotate_control_name", "")
    control = bpy.data.objects.get(control_name) if control_name else None

    _remove_owned_rotation_drivers(child)
    _remove_old_helpers(child)

    try:
        child.rotation_mode = 'XYZ'
        child.rotation_euler = (0.0, 0.0, 0.0)
        bpy.context.view_layer.update()
    except Exception:
        pass

    world = child.matrix_world.copy()

    original_parent_name = child.get("dsm_rotate_original_parent", "")
    original_parent = bpy.data.objects.get(original_parent_name) if original_parent_name else None
    original_parent_type = child.get("dsm_rotate_original_parent_type", "OBJECT")
    original_parent_bone = child.get("dsm_rotate_original_parent_bone", "")
    original_rotation_mode = child.get("dsm_rotate_original_rotation_mode", "XYZ")

    child.parent = original_parent
    if original_parent:
        child.parent_type = original_parent_type
        if original_parent_type == 'BONE':
            child.parent_bone = original_parent_bone
    else:
        child.parent_type = 'OBJECT'
        child.parent_bone = ""

    child.matrix_parent_inverse = Matrix.Identity(4)
    child.matrix_world = world
    child.hide_select = False

    try:
        child.rotation_mode = original_rotation_mode
    except Exception:
        pass

    if control:
        try:
            bpy.data.objects.remove(control, do_unlink=True)
        except Exception:
            pass

    marker_prop = f"{DRIVER_MARKER}_value"
    if marker_prop in child:
        try:
            del child[marker_prop]
        except Exception:
            pass

    utils.clear_feature_props(child, "rotate")
    return True


def apply_object(obj, context):
    existing_child = _resolve_child(obj)
    if existing_child:
        obj = existing_child
        clear_object(obj, restore=True)

    scene = context.scene
    settings = scene.dsm_settings

    # Do not overwrite the artist's existing rotation animation.
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

    rng = utils.seeded_rng(obj, "rotate")
    speed_factor = utils.variation_factor(rng, settings.rotate_variation)
    delay = rng.uniform(0.0, settings.rotate_variation * 12.0)
    speed = settings.rotate_speed * speed_factor
    angle_expression = _angle_expression(scene, speed, delay)

    control = _create_control(obj, context)

    if not _add_spin_driver(obj, settings.rotate_axis, angle_expression):
        world = control.matrix_world.copy()
        obj.parent = original_parent
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_world = Matrix.LocRotScale(
            world.translation,
            world.to_quaternion(),
            obj.scale.copy(),
        )
        try:
            obj.rotation_mode = original_rotation_mode
        except Exception:
            pass
        try:
            bpy.data.objects.remove(control, do_unlink=True)
        except Exception:
            pass
        return False, "could not create local rotation driver", None

    obj["dsm_rotate_enabled"] = True
    obj["dsm_rotate_control_name"] = control.name
    obj["dsm_rotate_axis"] = settings.rotate_axis
    obj["dsm_rotate_speed_factor"] = float(speed_factor)
    obj["dsm_rotate_delay"] = float(delay)
    obj["dsm_rotate_original_parent"] = original_parent_name
    obj["dsm_rotate_original_parent_type"] = original_parent_type
    obj["dsm_rotate_original_parent_bone"] = original_parent_bone
    obj["dsm_rotate_original_rotation_mode"] = original_rotation_mode

    # Keep both the spinning mesh and the Empty selectable. The Empty is the
    # transform control for moving/reorienting the entire spinning rig.
    obj.hide_select = False

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
        selected = utils.selected_objects(context)
        if not selected:
            self.report({'WARNING'}, "Select one or more objects")
            return {'CANCELLED'}

        objects = []
        seen = set()
        for item in selected:
            child = _resolve_child(item) or item
            if child.name not in seen:
                seen.add(child.name)
                objects.append(child)

        controls = []
        skipped = []

        for obj in objects:
            ok, reason, control = apply_object(obj, context)
            if ok:
                controls.append(control)
            else:
                skipped.append(f"{obj.name}: {reason}")

        if controls:
            bpy.ops.object.select_all(action='DESELECT')
            for control in controls:
                control.select_set(True)
            context.view_layer.objects.active = controls[0]

        if skipped:
            self.report({'WARNING'}, "; ".join(skipped[:3]))
        self.report({'INFO'}, f"Rotate applied to {len(controls)} object(s)")
        return {'FINISHED'}


class DSM_OT_rotate_clear(Operator):
    bl_idname = "dsm.rotate_clear"
    bl_label = "Clear Rotate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = utils.selected_objects(context)
        count = 0
        seen = set()

        for item in selected:
            child = _resolve_child(item)
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
