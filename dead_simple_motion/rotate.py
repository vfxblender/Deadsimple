import bpy
from bpy.types import Operator
from mathutils import Matrix, Vector

from . import utils

DRIVER_MARKER = "dsm_rotate_marker"
CONTROL_PREFIX = "DSM_ROT_CTRL_"
ROTATION_PATHS = {
    "rotation_euler",
    "rotation_quaternion",
    "rotation_axis_angle",
    "delta_rotation_euler",
    "delta_rotation_quaternion",
}


def _axis_index(axis):
    return {"X": 0, "Y": 1, "Z": 2}[axis]


def _resolve_child(obj):
    if not obj:
        return None
    if obj.get("dsm_rotate_control", False):
        return bpy.data.objects.get(obj.get("dsm_rotate_child", ""))
    if obj.get("dsm_rotate_enabled", False):
        return obj
    return None


def _selected_children(context):
    result = []
    seen = set()
    for item in utils.selected_objects(context):
        child = _resolve_child(item)
        if child and child.name not in seen:
            seen.add(child.name)
            result.append(child)
    return result


def _range(scene):
    settings = scene.dsm_settings
    start = int(settings.rotate_start) if settings.rotate_use_start else int(scene.frame_start)
    end = int(settings.rotate_end) if settings.rotate_use_end else int(scene.frame_end)
    if end <= start:
        end = start + 1
    return start, end


def _expression(scene, speed):
    settings = scene.dsm_settings
    start = int(settings.rotate_start) if settings.rotate_use_start else int(scene.frame_start)
    if settings.rotate_use_end:
        end = max(start, int(settings.rotate_end))
        elapsed = f"max(min(frame,{end})-{start},0)"
    else:
        elapsed = f"max(frame-{start},0)"
    return f"({elapsed})*({speed:.10f})*0.02"


def _control_size(obj):
    try:
        size = max(abs(float(v)) for v in obj.dimensions)
    except Exception:
        size = 1.0
    return max(0.45, min(size * 0.4, 2.5))


def _create_control(obj, context):
    world = obj.matrix_world.copy()
    location, rotation, scale = world.decompose()

    old_parent = obj.parent
    old_parent_type = obj.parent_type if old_parent else "OBJECT"
    old_parent_bone = obj.parent_bone if old_parent and obj.parent_type == "BONE" else ""

    control = bpy.data.objects.new(f"{CONTROL_PREFIX}{obj.name}", None)
    control.empty_display_type = "PLAIN_AXES"
    control.empty_display_size = _control_size(obj)
    control.show_in_front = False
    control.show_name = False
    control.hide_render = True
    control.hide_select = False
    control["dsm_rotate_control"] = True
    control["dsm_rotate_child"] = obj.name

    collection = obj.users_collection[0] if obj.users_collection else context.collection
    collection.objects.link(control)

    if old_parent:
        control.parent = old_parent
        control.parent_type = old_parent_type
        if old_parent_type == "BONE":
            control.parent_bone = old_parent_bone

    control.matrix_world = Matrix.LocRotScale(location, rotation, Vector((1.0, 1.0, 1.0)))

    obj.parent = control
    obj.parent_type = "OBJECT"
    obj.parent_bone = ""
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = scale
    obj.hide_select = False

    return control


def _remove_driver(obj):
    axis = _axis_index(obj.get("dsm_rotate_axis", "Z"))
    utils.remove_owned_driver(obj, "rotation_euler", axis, DRIVER_MARKER)
    marker_prop = f"{DRIVER_MARKER}_value"
    if marker_prop in obj:
        try:
            del obj[marker_prop]
        except Exception:
            pass


def _add_driver(obj, scene):
    axis = _axis_index(obj.get("dsm_rotate_axis", "Z"))
    speed = float(obj.get("dsm_rotate_speed", scene.dsm_settings.rotate_speed))
    return utils.add_owned_driver(
        obj,
        "rotation_euler",
        axis,
        _expression(scene, speed),
        DRIVER_MARKER,
    ) is not None


def _remove_bake_keys(obj):
    if not obj.get("dsm_rotate_baked", False):
        return

    axis = _axis_index(obj.get("dsm_rotate_axis", "Z"))
    records = (
        (obj.get("dsm_rotate_bake_start_frame"), obj.get("dsm_rotate_bake_start_value")),
        (obj.get("dsm_rotate_bake_end_frame"), obj.get("dsm_rotate_bake_end_value")),
    )
    for frame, value in records:
        if frame is None or value is None:
            continue
        utils.remove_matching_keyframe(obj, "rotation_euler", axis, float(frame), float(value))

    for key in (
        "dsm_rotate_baked",
        "dsm_rotate_bake_start_frame",
        "dsm_rotate_bake_start_value",
        "dsm_rotate_bake_end_frame",
        "dsm_rotate_bake_end_value",
    ):
        if key in obj:
            try:
                del obj[key]
            except Exception:
                pass


def _bake(obj, scene):
    child = _resolve_child(obj) or obj
    if not child or not child.get("dsm_rotate_enabled", False):
        return False

    start, end = _range(scene)
    axis = _axis_index(child.get("dsm_rotate_axis", "Z"))
    speed = float(child.get("dsm_rotate_speed", scene.dsm_settings.rotate_speed))
    start_value = 0.0
    end_value = (end - start) * speed * 0.02

    _remove_bake_keys(child)
    _remove_driver(child)

    current = int(scene.frame_current)
    try:
        child.rotation_mode = "XYZ"
        child.rotation_euler[axis] = start_value
        child.keyframe_insert(
            data_path="rotation_euler",
            index=axis,
            frame=float(start),
            group="Dead Simple Rotate",
        )
        child.rotation_euler[axis] = end_value
        child.keyframe_insert(
            data_path="rotation_euler",
            index=axis,
            frame=float(end),
            group="Dead Simple Rotate",
        )
    except Exception:
        _add_driver(child, scene)
        return False

    utils.set_matching_keyframes_linear(
        child,
        "rotation_euler",
        axis,
        ((float(start), float(start_value)), (float(end), float(end_value))),
    )
    child["dsm_rotate_baked"] = True
    child["dsm_rotate_bake_start_frame"] = float(start)
    child["dsm_rotate_bake_start_value"] = float(start_value)
    child["dsm_rotate_bake_end_frame"] = float(end)
    child["dsm_rotate_bake_end_value"] = float(end_value)

    try:
        scene.frame_set(current)
    except Exception:
        pass
    return True


def _refresh(obj, scene):
    child = _resolve_child(obj) or obj
    if not child or not child.get("dsm_rotate_enabled", False):
        return False

    if child.get("dsm_rotate_baked", False):
        return _bake(child, scene)

    axis = _axis_index(child.get("dsm_rotate_axis", "Z"))
    fc = utils.get_driver_fcurve(child, "rotation_euler", axis)
    if not fc or not utils.driver_has_marker(fc, DRIVER_MARKER):
        return False

    speed = float(child.get("dsm_rotate_speed", scene.dsm_settings.rotate_speed))
    fc.driver.expression = f"({_expression(scene, speed)}) + ({DRIVER_MARKER} * 0.0)"
    try:
        child.update_tag()
    except Exception:
        pass
    return True


def _refresh_selected(context):
    count = sum(1 for obj in _selected_children(context) if _refresh(obj, context.scene))
    try:
        context.view_layer.update()
    except Exception:
        pass
    return count


def clear_object(obj, restore=True):
    child = _resolve_child(obj)
    if not child or not child.get("dsm_rotate_enabled", False):
        return False

    control_name = child.get("dsm_rotate_control_name", "")
    control = bpy.data.objects.get(control_name) if control_name else None

    _remove_bake_keys(child)
    _remove_driver(child)

    if restore:
        try:
            child.rotation_mode = "XYZ"
            child.rotation_euler = (0.0, 0.0, 0.0)
            bpy.context.view_layer.update()
        except Exception:
            pass

    world = child.matrix_world.copy()
    parent_name = child.get("dsm_rotate_original_parent", "")
    parent = bpy.data.objects.get(parent_name) if parent_name else None
    parent_type = child.get("dsm_rotate_original_parent_type", "OBJECT")
    parent_bone = child.get("dsm_rotate_original_parent_bone", "")
    rotation_mode = child.get("dsm_rotate_original_rotation_mode", "XYZ")

    child.parent = parent
    if parent:
        child.parent_type = parent_type
        if parent_type == "BONE":
            child.parent_bone = parent_bone
    else:
        child.parent_type = "OBJECT"
        child.parent_bone = ""

    child.matrix_parent_inverse = Matrix.Identity(4)
    child.matrix_world = world
    child.hide_select = False

    try:
        child.rotation_mode = rotation_mode
    except Exception:
        pass

    if control:
        try:
            bpy.data.objects.remove(control, do_unlink=True)
        except Exception:
            pass

    utils.clear_feature_props(child, "rotate")
    return True


def apply_object(obj, context):
    existing = _resolve_child(obj)
    if existing:
        obj = existing

    if obj.get("dsm_rotate_enabled", False):
        clear_object(obj, restore=True)

    if utils.has_animation_path(obj, ROTATION_PATHS):
        return False, "object already has rotation animation or drivers", None

    scene = context.scene
    settings = scene.dsm_settings

    old_parent = obj.parent
    old_parent_name = old_parent.name if old_parent else ""
    old_parent_type = obj.parent_type if old_parent else "OBJECT"
    old_parent_bone = obj.parent_bone if old_parent and obj.parent_type == "BONE" else ""
    old_rotation_mode = obj.rotation_mode

    rng = utils.seeded_rng(obj, "rotate")
    speed_factor = utils.variation_factor(rng, settings.rotate_variation)
    speed = float(settings.rotate_speed * speed_factor)

    control = _create_control(obj, context)

    obj["dsm_rotate_enabled"] = True
    obj["dsm_rotate_control_name"] = control.name
    obj["dsm_rotate_axis"] = settings.rotate_axis
    obj["dsm_rotate_speed"] = speed
    obj["dsm_rotate_speed_factor"] = float(speed_factor)
    obj["dsm_rotate_original_parent"] = old_parent_name
    obj["dsm_rotate_original_parent_type"] = old_parent_type
    obj["dsm_rotate_original_parent_bone"] = old_parent_bone
    obj["dsm_rotate_original_rotation_mode"] = old_rotation_mode

    if not _add_driver(obj, scene):
        clear_object(obj, restore=True)
        return False, "could not create DSM rotation driver", None

    try:
        context.view_layer.update()
    except Exception:
        pass

    return True, "", control


class DSM_OT_rotate_apply(Operator):
    bl_idname = "dsm.rotate_apply"
    bl_label = "Apply Rotate"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected = utils.selected_objects(context)
        if not selected:
            self.report({"WARNING"}, "Select one or more objects")
            return {"CANCELLED"}

        objects = []
        seen = set()
        for item in selected:
            obj = _resolve_child(item) or item
            if obj.name not in seen:
                seen.add(obj.name)
                objects.append(obj)

        pairs = []
        skipped = []
        for obj in objects:
            ok, reason, control = apply_object(obj, context)
            if ok:
                pairs.append((obj, control))
            else:
                skipped.append(f"{obj.name}: {reason}")

        if pairs:
            try:
                bpy.ops.object.select_all(action="DESELECT")
                for obj, control in pairs:
                    obj.hide_select = False
                    obj.select_set(True)
                    control.select_set(True)
                context.view_layer.objects.active = pairs[0][0]
            except Exception:
                pass

        if skipped:
            self.report({"WARNING"}, "; ".join(skipped[:3]))
        self.report({"INFO"}, f"Rotate applied to {len(pairs)} object(s)")
        return {"FINISHED"}


class DSM_OT_rotate_bake(Operator):
    bl_idname = "dsm.rotate_bake"
    bl_label = "Bake Rotation"
    bl_description = "Convert the DSM rotation driver to two DSM-owned linear keyframes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        children = _selected_children(context)
        if not children:
            self.report({"WARNING"}, "Select a rotated object or its Rotate control")
            return {"CANCELLED"}
        count = sum(1 for child in children if _bake(child, context.scene))
        self.report({"INFO"}, f"Rotation baked on {count} object(s)")
        return {"FINISHED"}


class DSM_OT_rotate_clear(Operator):
    bl_idname = "dsm.rotate_clear"
    bl_label = "Clear Rotate"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = 0
        seen = set()
        for item in utils.selected_objects(context):
            child = _resolve_child(item)
            if child and child.name not in seen:
                seen.add(child.name)
                if clear_object(child):
                    count += 1
        self.report({"INFO"}, f"Rotate cleared on {count} object(s)")
        return {"FINISHED"}


class DSM_OT_rotate_key_in(Operator):
    bl_idname = "dsm.rotate_key_in"
    bl_label = "Key In"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = context.scene.dsm_settings
        settings.rotate_use_start = True
        settings.rotate_start = context.scene.frame_current
        count = _refresh_selected(context)
        self.report({"INFO"}, f"Key In {settings.rotate_start} updated on {count} rig(s)")
        return {"FINISHED"}


class DSM_OT_rotate_key_out(Operator):
    bl_idname = "dsm.rotate_key_out"
    bl_label = "Key Out"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = context.scene.dsm_settings
        settings.rotate_use_end = True
        settings.rotate_end = context.scene.frame_current
        count = _refresh_selected(context)
        self.report({"INFO"}, f"Key Out {settings.rotate_end} updated on {count} rig(s)")
        return {"FINISHED"}


class DSM_OT_rotate_clear_range(Operator):
    bl_idname = "dsm.rotate_clear_range"
    bl_label = "Clear Range"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = context.scene.dsm_settings
        settings.rotate_use_start = False
        settings.rotate_use_end = False
        count = _refresh_selected(context)
        self.report({"INFO"}, f"Rotate range cleared on {count} rig(s)")
        return {"FINISHED"}


_CLASSES = (
    DSM_OT_rotate_apply,
    DSM_OT_rotate_bake,
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
