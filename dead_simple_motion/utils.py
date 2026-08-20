import math
import random
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


def clear_feature_props(obj, feature):
    prefix = f"dsm_{feature}_"
    for key in list(obj.keys()):
        if key.startswith(prefix):
            try:
                del obj[key]
            except Exception:
                pass


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
    if target.type == 'ARMATURE' and bone_name:
        pose = getattr(target, "pose", None)
        if pose and bone_name in pose.bones:
            return target.matrix_world @ pose.bones[bone_name].matrix
    return target.matrix_world.copy()


def set_world_location(obj, location):
    matrix = obj.matrix_world.copy()
    matrix.translation = Vector(location)
    obj.matrix_world = matrix


def get_world_location(obj):
    return obj.matrix_world.translation.copy()


def has_animation_path(obj, data_paths):
    ad = getattr(obj, "animation_data", None)
    if not ad:
        return False
    if ad.drivers:
        for fc in ad.drivers:
            if fc.data_path in data_paths:
                return True
    action = getattr(ad, "action", None)
    fcurves = getattr(action, "fcurves", None) if action else None
    if fcurves:
        for fc in fcurves:
            if fc.data_path in data_paths:
                return True
    return False


def get_driver_fcurve(obj, data_path, index):
    ad = getattr(obj, "animation_data", None)
    if not ad or not ad.drivers:
        return None
    for fc in ad.drivers:
        if fc.data_path == data_path and fc.array_index == index:
            return fc
    return None


def driver_has_marker(fc, marker_name):
    if not fc or not getattr(fc, "driver", None):
        return False
    return any(var.name == marker_name for var in fc.driver.variables)


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
            pass
    marker_prop = f"{marker_name}_value"
    obj[marker_prop] = 1.0
    fc = obj.driver_add(data_path, index)
    driver = fc.driver
    driver.type = 'SCRIPTED'
    variable = driver.variables.new()
    variable.name = marker_name
    variable.type = 'SINGLE_PROP'
    variable.targets[0].id = obj
    variable.targets[0].data_path = f'["{marker_prop}"]'
    driver.expression = f"({expression}) + ({marker_name} * 0.0)"
    return fc


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
