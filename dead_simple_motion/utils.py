import math
import random

import bpy
from mathutils import Matrix, Vector

PREFIX = "dsm_"


def selected_objects(context, target=None):
    objects = [obj for obj in context.selected_objects if obj is not None]
    if not objects and context.object:
        objects = [context.object]
    if target:
        objects = [obj for obj in objects if obj != target]
    return objects


def feature_key(feature, suffix):
    return f"dsm_{feature}_{suffix}"


def clear_feature_props(obj, feature, preserve_seed=True):
    """Remove only custom properties owned by one DSM feature.

    Seeds are preserved by default so re-applying a feature does not reshuffle
    deterministic per-object variation.
    """
    prefix = f"dsm_{feature}_"
    seed_key = feature_key(feature, "seed")
    seed_value = obj.get(seed_key) if preserve_seed else None

    for key in list(obj.keys()):
        if key.startswith(prefix):
            try:
                del obj[key]
            except Exception:
                pass

    if preserve_seed and seed_value is not None:
        obj[seed_key] = int(seed_value)


def ensure_seed(obj, feature):
    key = feature_key(feature, "seed")
    if key not in obj:
        obj[key] = random.randint(1, 2_000_000_000)
    return int(obj[key])


def seeded_rng(obj, feature):
    return random.Random(ensure_seed(obj, feature))


def variation_factor(rng, amount):
    amount = max(0.0, min(float(amount), 1.0))
    return 1.0 + rng.uniform(-amount, amount)


def pack_vector(vec):
    return [float(vec[0]), float(vec[1]), float(vec[2])]


def unpack_vector(value, fallback=(0.0, 0.0, 0.0)):
    try:
        return Vector((float(value[0]), float(value[1]), float(value[2])))
    except Exception:
        return Vector(fallback)


def pack_matrix(matrix):
    return [float(v) for row in matrix for v in row]


def unpack_matrix(value):
    try:
        values = [float(v) for v in value]
        if len(values) != 16:
            return Matrix.Identity(4)
        return Matrix((values[0:4], values[4:8], values[8:12], values[12:16]))
    except Exception:
        return Matrix.Identity(4)


def get_target_matrix(target, bone_name=""):
    if target is None:
        return None
    if target.type == "ARMATURE" and bone_name:
        pose = getattr(target, "pose", None)
        if pose:
            pose_bone = pose.bones.get(bone_name)
            if pose_bone:
                return target.matrix_world @ pose_bone.matrix
    return target.matrix_world.copy()


def set_world_location(obj, location, epsilon=1e-7):
    location = Vector(location)
    if (obj.matrix_world.translation - location).length <= epsilon:
        return False
    matrix = obj.matrix_world.copy()
    matrix.translation = location
    obj.matrix_world = matrix
    return True


def get_world_location(obj):
    return obj.matrix_world.translation.copy()


def set_world_rotation(obj, quaternion, epsilon=1e-7):
    try:
        location, current, scale = obj.matrix_world.decompose()
        if abs(current.rotation_difference(quaternion).angle) <= epsilon:
            return False
        obj.matrix_world = Matrix.LocRotScale(location, quaternion, scale)
        return True
    except Exception:
        return False


def aim_camera_at(camera, focus):
    if not camera or not focus:
        return False
    direction = focus.matrix_world.translation - camera.matrix_world.translation
    if direction.length < 1e-7:
        return False
    try:
        quat = direction.normalized().to_track_quat("-Z", "Y")
    except Exception:
        return False
    return set_world_rotation(camera, quat)


def _channelbag_for_object(obj):
    ad = getattr(obj, "animation_data", None)
    if not ad or not getattr(ad, "action", None):
        return None
    try:
        from bpy_extras.anim_utils import animdata_get_channelbag_for_assigned_slot
        return animdata_get_channelbag_for_assigned_slot(ad)
    except Exception:
        return None


def iter_action_fcurves(obj):
    """Yield assigned Action FCurves on Blender 4.2 legacy and 4.4+/5.x."""
    ad = getattr(obj, "animation_data", None)
    action = getattr(ad, "action", None) if ad else None
    if not action:
        return

    seen = set()

    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None:
        try:
            for fc in fcurves:
                token = id(fc)
                if token not in seen:
                    seen.add(token)
                    yield fc
        except Exception:
            pass

    bag = _channelbag_for_object(obj)
    if bag:
        try:
            for fc in bag.fcurves:
                token = id(fc)
                if token not in seen:
                    seen.add(token)
                    yield fc
        except Exception:
            pass


def find_action_fcurve(obj, data_path, index):
    for fc in iter_action_fcurves(obj) or ():
        if fc.data_path == data_path and fc.array_index == index:
            return fc
    return None


def remove_action_fcurve(obj, fc):
    if fc is None:
        return False

    ad = getattr(obj, "animation_data", None)
    action = getattr(ad, "action", None) if ad else None
    if action:
        fcurves = getattr(action, "fcurves", None)
        if fcurves is not None:
            try:
                if fc in fcurves:
                    fcurves.remove(fc)
                    return True
            except Exception:
                pass

    bag = _channelbag_for_object(obj)
    if bag:
        try:
            if fc in bag.fcurves:
                bag.fcurves.remove(fc)
                return True
        except Exception:
            pass
    return False


def has_animation_path(obj, data_paths):
    ad = getattr(obj, "animation_data", None)
    if not ad:
        return False

    try:
        for fc in ad.drivers:
            if fc.data_path in data_paths:
                return True
    except Exception:
        pass

    for fc in iter_action_fcurves(obj) or ():
        if fc.data_path in data_paths:
            return True
    return False


def get_driver_fcurve(obj, data_path, index):
    ad = getattr(obj, "animation_data", None)
    if not ad:
        return None
    try:
        for fc in ad.drivers:
            if fc.data_path == data_path and fc.array_index == index:
                return fc
    except Exception:
        pass
    return None


def driver_has_marker(fc, marker_name):
    if not fc or not getattr(fc, "driver", None):
        return False
    try:
        return any(var.name == marker_name for var in fc.driver.variables)
    except Exception:
        return False


def remove_owned_driver(obj, data_path, index, marker_name):
    fc = get_driver_fcurve(obj, data_path, index)
    if not driver_has_marker(fc, marker_name):
        return False
    try:
        obj.driver_remove(data_path, index)
        return True
    except Exception:
        return False


def add_owned_driver(obj, data_path, index, expression, marker_name):
    existing = get_driver_fcurve(obj, data_path, index)
    if existing and not driver_has_marker(existing, marker_name):
        return None
    if existing:
        try:
            obj.driver_remove(data_path, index)
        except Exception:
            return None

    marker_prop = f"{marker_name}_value"
    obj[marker_prop] = 1.0

    try:
        fc = obj.driver_add(data_path, index)
    except Exception:
        return None

    driver = fc.driver
    driver.type = "SCRIPTED"
    variable = driver.variables.new()
    variable.name = marker_name
    variable.type = "SINGLE_PROP"
    variable.targets[0].id = obj
    variable.targets[0].data_path = f'["{marker_prop}"]'
    driver.expression = f"({expression}) + ({marker_name} * 0.0)"
    return fc


def remove_matching_keyframe(obj, data_path, index, frame, value, tolerance=1e-5):
    """Remove only the exact DSM bake point we recorded.

    If an artist edits that point later, the value no longer matches and Clear
    leaves it alone instead of deleting unrelated/modified animation.
    """
    fc = find_action_fcurve(obj, data_path, index)
    if not fc:
        return False

    removed = False
    for point in list(fc.keyframe_points):
        if abs(float(point.co.x) - float(frame)) <= tolerance and abs(float(point.co.y) - float(value)) <= tolerance:
            try:
                fc.keyframe_points.remove(point)
                removed = True
            except Exception:
                pass

    if removed:
        try:
            fc.update()
        except Exception:
            pass
        try:
            if len(fc.keyframe_points) == 0 and len(fc.modifiers) == 0:
                remove_action_fcurve(obj, fc)
        except Exception:
            pass
    return removed


def set_matching_keyframes_linear(obj, data_path, index, records, tolerance=1e-5):
    """Set interpolation only on the DSM points supplied in records."""
    fc = find_action_fcurve(obj, data_path, index)
    if not fc:
        return False

    matched = 0
    try:
        for key in fc.keyframe_points:
            for frame, value in records:
                if abs(float(key.co.x) - float(frame)) <= tolerance and abs(float(key.co.y) - float(value)) <= tolerance:
                    key.interpolation = "LINEAR"
                    matched += 1
                    break
        if matched and len(fc.keyframe_points) == matched:
            fc.extrapolation = "CONSTANT"
        fc.update()
    except Exception:
        pass
    return matched > 0


def remove_named_constraint(obj, name):
    """Remove one exact DSM-owned constraint by name."""
    if not obj:
        return False
    constraint = obj.constraints.get(name)
    if not constraint:
        return False
    try:
        obj.constraints.remove(constraint)
        return True
    except Exception:
        return False


def create_focus_empty(context, owner, feature, prefix, world_location, display_size=0.5):
    remove_focus_empty(owner, feature)

    focus = bpy.data.objects.new(f"{prefix}{owner.name}", None)
    focus.empty_display_type = "SPHERE"
    focus.empty_display_size = max(0.2, float(display_size))
    focus.show_in_front = False
    focus.show_name = True
    focus.hide_render = True
    focus.hide_select = False
    focus[feature_key(feature, "focus_owner")] = owner.name

    collection = owner.users_collection[0] if owner.users_collection else context.collection
    collection.objects.link(focus)
    focus.matrix_world = Matrix.Translation(Vector(world_location))
    owner[feature_key(feature, "focus_name")] = focus.name
    return focus


def remove_focus_empty(owner, feature):
    if not owner:
        return False
    name = owner.get(feature_key(feature, "focus_name"), "")
    focus = bpy.data.objects.get(name) if name else None
    if not focus:
        return False
    try:
        bpy.data.objects.remove(focus, do_unlink=True)
        return True
    except Exception:
        return False


def resolve_focus_owner(obj, feature):
    if not obj:
        return None
    owner_name = obj.get(feature_key(feature, "focus_owner"), "")
    return bpy.data.objects.get(owner_name) if owner_name else None


def resolve_motion_owner(obj):
    """Resolve a DSM control/focus Empty to the animated object it belongs to."""
    if not obj:
        return None

    child_name = obj.get("dsm_rotate_child", "") if obj.get("dsm_rotate_control", False) else ""
    if not child_name and obj.get("dsm_spawn_control", False):
        child_name = obj.get("dsm_spawn_child", "")
    if child_name:
        child = bpy.data.objects.get(child_name)
        if child:
            return child

    for feature in ("orbit", "spawn"):
        owner = resolve_focus_owner(obj, feature)
        if owner:
            return owner

    return obj


def square_orbit(t):
    p = (t / (2.0 * math.pi)) % 1.0
    s = p * 4.0
    if s < 1.0:
        return 1.0, -1.0 + 2.0 * s
    if s < 2.0:
        s -= 1.0
        return 1.0 - 2.0 * s, 1.0
    if s < 3.0:
        s -= 2.0
        return -1.0, 1.0 - 2.0 * s
    s -= 3.0
    return -1.0 + 2.0 * s, -1.0
