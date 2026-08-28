import bpy
from bpy.types import Operator
from mathutils import Matrix, Vector

from . import utils

CONTROL_PREFIX = "DSM_SPAWN_CTRL_"
FOCUS_PREFIX = "DSM_LOOP_FOCUS_"
OLD_FOCUS_CONSTRAINT = "DSM Spawn Camera Focus"
ROTATION_PATHS = {
    "rotation_euler",
    "rotation_quaternion",
    "rotation_axis_angle",
    "delta_rotation_euler",
    "delta_rotation_quaternion",
}


def _resolve(obj):
    if not obj:
        return None
    if obj.get("dsm_spawn_control", False):
        return bpy.data.objects.get(obj.get("dsm_spawn_child", ""))
    owner = utils.resolve_focus_owner(obj, "spawn")
    if owner:
        return owner
    if obj.get("dsm_spawn_enabled", False):
        return obj
    return None


def _axis(axis):
    if axis == "Y":
        return Vector((0.0, 1.0, 0.0))
    if axis == "Z":
        return Vector((0.0, 0.0, 1.0))
    return Vector((1.0, 0.0, 0.0))


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
    control["dsm_spawn_control"] = True
    control["dsm_spawn_child"] = obj.name

    collection = obj.users_collection[0] if obj.users_collection else context.collection
    collection.objects.link(control)

    if old_parent:
        control.parent = old_parent
        control.parent_type = old_parent_type
        if old_parent_type == "BONE":
            control.parent_bone = old_parent_bone

    # The control owns placement and orientation of the entire path.
    control.matrix_world = Matrix.Translation(location)

    obj.parent = control
    obj.parent_type = "OBJECT"
    obj.parent_bone = ""
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.matrix_basis = Matrix.LocRotScale(Vector((0.0, 0.0, 0.0)), rotation, scale)
    obj.hide_select = False

    return control, old_parent, old_parent_type, old_parent_bone


def _create_focus(camera, context, distance):
    forward = camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
    if forward.length < 1e-5:
        forward = Vector((0.0, 0.0, -1.0))
    else:
        forward.normalize()

    location = camera.matrix_world.translation + forward * max(2.0, distance * 0.5)
    return utils.create_focus_empty(
        context,
        camera,
        "spawn",
        FOCUS_PREFIX,
        location,
        display_size=max(0.25, min(distance * 0.05, 1.0)),
    )


def _focus_for(obj):
    name = obj.get("dsm_spawn_focus_name", "")
    return bpy.data.objects.get(name) if name else None


def _ease(progress, fade_in, fade_out):
    p = max(0.0, min(1.0, float(progress)))
    fade_in = max(0.0, min(1.0, float(fade_in)))
    fade_out = max(0.0, min(1.0, float(fade_out)))

    if fade_out < fade_in:
        mid = (fade_in + fade_out) * 0.5
        fade_in = mid
        fade_out = mid

    if fade_in > 1e-6 and p < fade_in:
        s = p / fade_in
        return fade_in * (s * s * (2.0 - s))

    if fade_out < 1.0 - 1e-6 and p > fade_out:
        length = 1.0 - fade_out
        s = (p - fade_out) / length
        return fade_out + length * (-s * s * s + s * s + s)

    return p


def _capture_manual_offset(obj):
    last = utils.unpack_vector(obj.get("dsm_spawn_last_output", obj.location))
    current = Vector(obj.location)
    delta = current - last
    if delta.length <= 1e-6:
        return

    user = utils.unpack_vector(obj.get("dsm_spawn_user_offset", (0, 0, 0)))
    user += delta
    obj["dsm_spawn_user_offset"] = utils.pack_vector(user)


def clear_object(obj, restore=True):
    child = _resolve(obj)
    if not child or not child.get("dsm_spawn_enabled", False):
        return False

    control_name = child.get("dsm_spawn_control_name", "")
    control = bpy.data.objects.get(control_name) if control_name else None
    utils.remove_named_constraint(child, OLD_FOCUS_CONSTRAINT)
    utils.remove_focus_empty(child, "spawn")

    user_offset = utils.unpack_vector(child.get("dsm_spawn_user_offset", (0, 0, 0)))
    if restore:
        child.location = user_offset
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass

    world = child.matrix_world.copy()

    parent_name = child.get("dsm_spawn_original_parent", "")
    parent = bpy.data.objects.get(parent_name) if parent_name else None
    parent_type = child.get("dsm_spawn_original_parent_type", "OBJECT")
    parent_bone = child.get("dsm_spawn_original_parent_bone", "")

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
    child.hide_viewport = bool(child.get("dsm_spawn_original_hide_viewport", False))
    child.hide_render = bool(child.get("dsm_spawn_original_hide_render", False))

    if control:
        try:
            bpy.data.objects.remove(control, do_unlink=True)
        except Exception:
            pass

    utils.clear_feature_props(child, "spawn")
    return True


def apply_object(obj, context):
    existing = _resolve(obj)
    if existing:
        obj = existing

    from . import follow, orbit

    orbit.clear_object(obj, restore=True)
    follow.clear_object(obj, restore=True)
    clear_object(obj, restore=True)

    if utils.has_animation_path(obj, {"location"}):
        return False, "location already has animation or drivers", None, None
    if obj.type == "CAMERA" and utils.has_animation_path(obj, ROTATION_PATHS):
        return False, "camera rotation already has animation or drivers", None, None

    settings = context.scene.dsm_settings
    original_hide_viewport = bool(obj.hide_viewport)
    original_hide_render = bool(obj.hide_render)

    rng = utils.seeded_rng(obj, "spawn")
    factor = utils.variation_factor(rng, settings.spawn_variation)
    distance = max(0.001, float(settings.spawn_distance))
    phase = 0.0 if obj.type == "CAMERA" else rng.uniform(0.0, distance) * float(settings.spawn_variation)

    control, old_parent, old_parent_type, old_parent_bone = _create_control(obj, context)

    obj["dsm_spawn_enabled"] = True
    obj["dsm_spawn_control_name"] = control.name
    obj["dsm_spawn_mode"] = settings.spawn_mode
    obj["dsm_spawn_axis"] = settings.spawn_axis
    obj["dsm_spawn_speed"] = float(settings.spawn_speed * factor)
    obj["dsm_spawn_distance"] = distance
    obj["dsm_spawn_phase_distance"] = float(phase)
    obj["dsm_spawn_fade_in_point"] = float(settings.spawn_fade_in_point)
    obj["dsm_spawn_fade_out_point"] = float(settings.spawn_fade_out_point)
    obj["dsm_spawn_user_offset"] = [0.0, 0.0, 0.0]
    obj["dsm_spawn_last_output"] = [0.0, 0.0, 0.0]
    obj["dsm_spawn_original_parent"] = old_parent.name if old_parent else ""
    obj["dsm_spawn_original_parent_type"] = old_parent_type
    obj["dsm_spawn_original_parent_bone"] = old_parent_bone
    obj["dsm_spawn_original_hide_viewport"] = original_hide_viewport
    obj["dsm_spawn_original_hide_render"] = original_hide_render

    focus = _create_focus(obj, context, distance) if obj.type == "CAMERA" else None
    return True, "", control, focus


def update_object(obj, scene):
    if not obj.get("dsm_spawn_enabled", False):
        return

    _capture_manual_offset(obj)

    distance = max(0.001, float(obj.get("dsm_spawn_distance", 10.0)))
    speed = float(obj.get("dsm_spawn_speed", 0.1))
    phase = float(obj.get("dsm_spawn_phase_distance", 0.0))
    travel = (float(scene.frame_current) - float(scene.frame_start)) * speed + phase
    mode = obj.get("dsm_spawn_mode", "SPAWN")
    fade_in = float(obj.get("dsm_spawn_fade_in_point", 0.15))
    fade_out = float(obj.get("dsm_spawn_fade_out_point", 0.85))

    if mode == "LOOPER":
        wrapped = travel % (2.0 * distance)
        progress = wrapped / distance if wrapped <= distance else (2.0 * distance - wrapped) / distance
        motion = _ease(progress, fade_in, fade_out) * distance
        hidden = False
    else:
        wrapped = travel % distance
        progress = wrapped / distance
        motion = _ease(progress, fade_in, fade_out) * distance
        hidden = progress >= 0.995

    user_offset = utils.unpack_vector(obj.get("dsm_spawn_user_offset", (0, 0, 0)))
    output = user_offset + _axis(obj.get("dsm_spawn_axis", "X")) * motion
    if (Vector(obj.location) - output).length > 1e-7:
        obj.location = output
    obj["dsm_spawn_last_output"] = utils.pack_vector(output)

    if mode == "SPAWN":
        obj.hide_viewport = hidden
        obj.hide_render = hidden
    else:
        obj.hide_viewport = bool(obj.get("dsm_spawn_original_hide_viewport", False))
        obj.hide_render = bool(obj.get("dsm_spawn_original_hide_render", False))

    if obj.type == "CAMERA":
        focus = _focus_for(obj)
        if focus:
            utils.aim_camera_at(obj, focus)


def update_all(scene, updated_ids=None):
    for obj in bpy.data.objects:
        if not obj.get("dsm_spawn_enabled", False):
            continue
        if updated_ids is not None:
            dependencies = {obj.name}
            control_name = obj.get("dsm_spawn_control_name", "")
            focus_name = obj.get("dsm_spawn_focus_name", "")
            if control_name:
                dependencies.add(control_name)
            if focus_name:
                dependencies.add(focus_name)
            if not dependencies.intersection(updated_ids):
                continue
        update_object(obj, scene)


class DSM_OT_spawn_apply(Operator):
    bl_idname = "dsm.spawn_apply"
    bl_label = "Apply Spawn / Looper"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected = utils.selected_objects(context)
        if not selected:
            self.report({"WARNING"}, "Select one or more objects")
            return {"CANCELLED"}

        objects = []
        seen = set()
        for item in selected:
            obj = _resolve(item) or item
            if obj.name not in seen:
                seen.add(obj.name)
                objects.append(obj)

        rigs = []
        skipped = []
        for obj in objects:
            ok, reason, control, focus = apply_object(obj, context)
            if ok:
                rigs.append((obj, control, focus))
            else:
                skipped.append(f"{obj.name}: {reason}")

        update_all(context.scene)

        if rigs:
            try:
                bpy.ops.object.select_all(action="DESELECT")
                for obj, control, focus in rigs:
                    obj.select_set(True)
                    control.select_set(True)
                    if focus:
                        focus.select_set(True)
                context.view_layer.objects.active = rigs[0][0]
            except Exception:
                pass

        if skipped:
            self.report({"WARNING"}, "; ".join(skipped[:3]))
        self.report({"INFO"}, f"{context.scene.dsm_settings.spawn_mode.title()} applied to {len(rigs)} object(s)")
        return {"FINISHED"}


class DSM_OT_spawn_clear(Operator):
    bl_idname = "dsm.spawn_clear"
    bl_label = "Clear Spawn / Looper"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = 0
        seen = set()
        for item in utils.selected_objects(context):
            obj = _resolve(item)
            if obj and obj.name not in seen:
                seen.add(obj.name)
                if clear_object(obj):
                    count += 1
        self.report({"INFO"}, f"Spawn / Looper cleared on {count} object(s)")
        return {"FINISHED"}


_CLASSES = (DSM_OT_spawn_apply, DSM_OT_spawn_clear)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
