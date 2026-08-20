import bpy
from bpy.types import Operator
from mathutils import Matrix, Vector
from . import utils

DRIVER_MARKER = "dsm_rotate_marker"
CONTROL_PREFIX = "DSM_ROT_CTRL_"


def _axis_index(axis):
    return {"X": 0, "Y": 1, "Z": 2}[axis]


def _effective_range(scene, obj=None):
    settings = scene.dsm_settings
    start = int(settings.rotate_start) if settings.rotate_use_start else int(scene.frame_start)
    end = int(settings.rotate_end) if settings.rotate_use_end else int(scene.frame_end)

    if obj is not None and not settings.rotate_use_start:
        start += int(round(float(obj.get("dsm_rotate_delay", 0.0))))

    if end <= start:
        end = start + 1
    return start, end


def _angle_expression(scene, speed, delay_frames):
    settings = scene.dsm_settings
    start = int(settings.rotate_start) if settings.rotate_use_start else int(scene.frame_start)
    if not settings.rotate_use_start:
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


def _selected_rotate_children(context):
    children = []
    seen = set()
    for item in utils.selected_objects(context):
        child = _resolve_child(item)
        if child and child.get("dsm_rotate_enabled", False) and child.name not in seen:
            seen.add(child.name)
            children.append(child)
    return children


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

    control.matrix_world = Matrix.LocRotScale(location, rotation, Vector((1.0, 1.0, 1.0)))

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


def _get_action_fcurve(obj, data_path, index):
    ad = getattr(obj, "animation_data", None)
    action = getattr(ad, "action", None) if ad else None
    if not action:
        return None, None

    # Blender 4.4+ / 5.x layered Actions.
    try:
        from bpy_extras.anim_utils import animdata_get_channelbag_for_assigned_slot
        bag = animdata_get_channelbag_for_assigned_slot(ad)
        if bag:
            fc = bag.fcurves.find(data_path, index=index)
            if fc:
                return fc, bag.fcurves
    except Exception:
        pass

    # Blender 4.2 legacy Actions.
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None:
        try:
            fc = fcurves.find(data_path, index=index)
            if fc:
                return fc, fcurves
        except Exception:
            try:
                for fc in fcurves:
                    if fc.data_path == data_path and fc.array_index == index:
                        return fc, fcurves
            except Exception:
                pass

    ensure = getattr(action, "fcurve_ensure_for_datablock", None)
    if ensure:
        try:
            return ensure(obj, data_path, index=index), None
        except Exception:
            pass
    return None, None


def _remove_baked_rotation_keys(obj):
    if not obj or not obj.get("dsm_rotate_baked", False):
        return

    axis = _axis_index(obj.get("dsm_rotate_axis", "Z"))
    frames = list(obj.get("dsm_rotate_bake_frames", []))

    for frame in frames:
        try:
            obj.keyframe_delete(data_path="rotation_euler", index=axis, frame=float(frame))
        except Exception:
            pass

    fc, collection = _get_action_fcurve(obj, "rotation_euler", axis)
    if fc and len(fc.keyframe_points) == 0 and len(fc.modifiers) == 0 and collection is not None:
        try:
            collection.remove(fc)
        except Exception:
            pass

    obj["dsm_rotate_baked"] = False
    if "dsm_rotate_bake_frames" in obj:
        try:
            del obj["dsm_rotate_bake_frames"]
        except Exception:
            pass


def _set_linear_bake_curve(obj, axis_index):
    fc, _collection = _get_action_fcurve(obj, "rotation_euler", axis_index)
    if not fc:
        return

    try:
        fc.extrapolation = 'CONSTANT'
    except Exception:
        pass

    for key in fc.keyframe_points:
        try:
            key.interpolation = 'LINEAR'
        except Exception:
            pass


def _bake_object_rotation(obj, scene):
    child = _resolve_child(obj) or obj
    if not child or not child.get("dsm_rotate_enabled", False):
        return False

    axis_name = child.get("dsm_rotate_axis", "Z")
    axis = _axis_index(axis_name)
    speed = float(child.get("dsm_rotate_speed", scene.dsm_settings.rotate_speed))
    start, end = _effective_range(scene, child)
    angle = (end - start) * speed * 0.02

    _remove_baked_rotation_keys(child)
    utils.remove_owned_driver(child, "rotation_euler", axis, DRIVER_MARKER)

    marker_prop = f"{DRIVER_MARKER}_value"
    if marker_prop in child:
        try:
            del child[marker_prop]
        except Exception:
            pass

    current_frame = int(scene.frame_current)

    try:
        child.rotation_mode = 'XYZ'
        child.rotation_euler[axis] = 0.0
        child.keyframe_insert(
            data_path="rotation_euler",
            index=axis,
            frame=float(start),
            group="Dead Simple Rotate",
        )

        child.rotation_euler[axis] = angle
        child.keyframe_insert(
            data_path="rotation_euler",
            index=axis,
            frame=float(end),
            group="Dead Simple Rotate",
        )
    except Exception:
        return False

    _set_linear_bake_curve(child, axis)
    child["dsm_rotate_baked"] = True
    child["dsm_rotate_bake_frames"] = [float(start), float(end)]

    try:
        scene.frame_set(current_frame)
    except Exception:
        pass
    return True


def _refresh_spin_driver(obj, scene):
    child = _resolve_child(obj) or obj
    if not child or not child.get("dsm_rotate_enabled", False):
        return False

    if child.get("dsm_rotate_baked", False):
        return _bake_object_rotation(child, scene)

    axis = child.get("dsm_rotate_axis", "Z")
    index = _axis_index(axis)
    fc = utils.get_driver_fcurve(child, "rotation_euler", index)
    if not fc or not utils.driver_has_marker(fc, DRIVER_MARKER):
        return False

    speed = float(child.get("dsm_rotate_speed", scene.dsm_settings.rotate_speed))
    delay = float(child.get("dsm_rotate_delay", 0.0))
    angle_expression = _angle_expression(scene, speed, delay)
    fc.driver.expression = f"({angle_expression}) + ({DRIVER_MARKER} * 0.0)"

    try:
        child.update_tag()
    except Exception:
        pass
    return True


def _refresh_selected_range(context):
    count = 0
    for child in _selected_rotate_children(context):
        if _refresh_spin_driver(child, context.scene):
            count += 1

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
    seed = child.get("dsm_rotate_seed")

    _remove_baked_rotation_keys(child)
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
    if seed is not None:
        child["dsm_rotate_seed"] = int(seed)
    return True


def apply_object(obj, context):
    existing_child = _resolve_child(obj)
    if existing_child:
        obj = existing_child

    seed = obj.get("dsm_rotate_seed")
    if obj.get("dsm_rotate_enabled", False):
        clear_object(obj, restore=True)
        if seed is not None:
            obj["dsm_rotate_seed"] = int(seed)

    scene = context.scene
    settings = scene.dsm_settings

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
    # When Key In is enabled, it is an exact start frame. Variation only changes speed.
    delay = 0.0 if settings.rotate_use_start else rng.uniform(0.0, settings.rotate_variation * 12.0)
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
    obj["dsm_rotate_speed"] = float(speed)
    obj["dsm_rotate_delay"] = float(delay)
    obj["dsm_rotate_original_parent"] = original_parent_name
    obj["dsm_rotate_original_parent_type"] = original_parent_type
    obj["dsm_rotate_original_parent_bone"] = original_parent_bone
    obj["dsm_rotate_original_rotation_mode"] = original_rotation_mode
    obj["dsm_rotate_baked"] = False
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


class DSM_OT_rotate_bake(Operator):
    bl_idname = "dsm.rotate_bake"
    bl_label = "Bake Rotation"
    bl_description = "Convert the DSM spin to two linear keyframes at Key In and Key Out"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        children = _selected_rotate_children(context)
        if not children:
            self.report({'WARNING'}, "Select a rotated object or its DSM Rotate control")
            return {'CANCELLED'}

        baked = sum(1 for child in children if _bake_object_rotation(child, context.scene))
        self.report({'INFO'}, f"Rotation baked on {baked} object(s)")
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
        count = _refresh_selected_range(context)
        self.report({'INFO'}, f"Key In set at frame {settings.rotate_start} on {count} Rotate rig(s)")
        return {'FINISHED'}


class DSM_OT_rotate_key_out(Operator):
    bl_idname = "dsm.rotate_key_out"
    bl_label = "Key Out"
    bl_options = {'UNDO'}

    def execute(self, context):
        settings = context.scene.dsm_settings
        settings.rotate_use_end = True
        settings.rotate_end = context.scene.frame_current
        count = _refresh_selected_range(context)
        self.report({'INFO'}, f"Key Out set at frame {settings.rotate_end} on {count} Rotate rig(s)")
        return {'FINISHED'}


class DSM_OT_rotate_clear_range(Operator):
    bl_idname = "dsm.rotate_clear_range"
    bl_label = "Clear Range"
    bl_options = {'UNDO'}

    def execute(self, context):
        settings = context.scene.dsm_settings
        settings.rotate_use_start = False
        settings.rotate_use_end = False
        count = _refresh_selected_range(context)
        self.report({'INFO'}, f"Rotate range cleared on {count} rig(s)")
        return {'FINISHED'}


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
