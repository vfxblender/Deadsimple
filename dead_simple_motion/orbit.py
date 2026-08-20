import math
import bpy
from mathutils import Matrix, Quaternion, Vector
from bpy.types import Operator
from . import utils

FOCUS_PREFIX = "DSM_ORBIT_FOCUS_"
LEGACY_FOCUS_CONSTRAINT = "DSM Orbit Camera Focus"


def _plane_components(local, plane):
    if plane == "XY":
        return local.x, local.y, local.z
    if plane == "XZ":
        return local.x, local.z, local.y
    return local.y, local.z, local.x


def _plane_vector(u, v, normal, plane):
    if plane == "XY":
        return Vector((u, v, normal))
    if plane == "XZ":
        return Vector((u, normal, v))
    return Vector((normal, u, v))


def _target_for(obj):
    name = obj.get("dsm_orbit_target", "")
    return bpy.data.objects.get(name) if name else None


def _resolve(obj):
    if not obj:
        return None
    if obj.get("dsm_orbit_focus_owner"):
        return bpy.data.objects.get(obj.get("dsm_orbit_focus_owner", ""))
    if obj.get("dsm_orbit_enabled", False):
        return obj
    return None


def _set_world_rotation(obj, quat):
    location, _rot, scale = obj.matrix_world.decompose()
    obj.matrix_world = Matrix.LocRotScale(location, quat, scale)


def _remove_focus(camera):
    if not camera:
        return
    con = camera.constraints.get(LEGACY_FOCUS_CONSTRAINT)
    if con:
        try:
            camera.constraints.remove(con)
        except Exception:
            pass

    name = camera.get("dsm_orbit_focus_name", "")
    focus = bpy.data.objects.get(name) if name else None
    if focus:
        try:
            bpy.data.objects.remove(focus, do_unlink=True)
        except Exception:
            pass


def _create_focus(camera, context, target, bone, pivot, radius):
    _remove_focus(camera)

    focus = bpy.data.objects.new(f"{FOCUS_PREFIX}{camera.name}", None)
    focus.empty_display_type = "SPHERE"
    focus.empty_display_size = max(0.35, min(float(radius) * 0.08, 2.0))
    focus.show_in_front = True
    focus.hide_render = True
    focus["dsm_orbit_focus_owner"] = camera.name

    collection = camera.users_collection[0] if camera.users_collection else context.collection
    collection.objects.link(focus)

    if target:
        focus.parent = target
        if target.type == "ARMATURE" and bone:
            try:
                focus.parent_type = "BONE"
                focus.parent_bone = bone
            except Exception:
                focus.parent_type = "OBJECT"
        else:
            focus.parent_type = "OBJECT"
        focus.matrix_world = Matrix.Translation(Vector(pivot))
    else:
        focus.location = Vector(pivot)

    camera["dsm_orbit_focus_name"] = focus.name
    return focus


def _aim_camera(camera):
    name = camera.get("dsm_orbit_focus_name", "")
    focus = bpy.data.objects.get(name) if name else None
    if not focus:
        return
    direction = focus.matrix_world.translation - camera.matrix_world.translation
    if direction.length < 1e-7:
        return
    try:
        quat = direction.normalized().to_track_quat("-Z", "Y")
        _set_world_rotation(camera, quat)
    except Exception:
        pass


def _sphere_basis(local, rng):
    radial = local.copy()
    if radial.length < 1e-5:
        radial = Vector((1.0, 0.0, 0.0))
    e1 = radial.normalized()

    trial = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
    if trial.length < 1e-5 or abs(trial.normalized().dot(e1)) > 0.95:
        trial = Vector((0.0, 0.0, 1.0)) if abs(e1.z) < 0.9 else Vector((0.0, 1.0, 0.0))
    e2 = (trial - e1 * trial.dot(e1)).normalized()
    return e1, e2, max(local.length, 1e-5)


def _precession_axis(e1, e2, rng):
    normal = e1.cross(e2)
    if normal.length < 1e-5:
        normal = Vector((0.0, 0.0, 1.0))
    else:
        normal.normalize()

    for _ in range(12):
        axis = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
        if axis.length < 1e-5:
            continue
        axis.normalize()
        if abs(axis.dot(normal)) < 0.8:
            return axis

    axis = e1 + normal * 0.35
    if axis.length < 1e-5:
        axis = Vector((1.0, 0.0, 0.0))
    axis.normalize()
    return axis


def _local_at(obj, frame):
    speed = float(obj.get("dsm_orbit_speed", 1.0))
    phase = float(obj.get("dsm_orbit_phase", 0.0))
    t = float(frame) * speed * 0.02 + phase
    radius = float(obj.get("dsm_orbit_radius", 2.0))
    shape = obj.get("dsm_orbit_shape", "CIRCLE")

    if shape == "SPHERE":
        e1 = utils.unpack_vector(obj.get("dsm_orbit_basis1", (1, 0, 0)))
        e2 = utils.unpack_vector(obj.get("dsm_orbit_basis2", (0, 1, 0)))
        point = radius * (e1 * math.cos(t) + e2 * math.sin(t))
        axis = utils.unpack_vector(obj.get("dsm_orbit_precession_axis", (0, 0, 1)))
        if axis.length < 1e-5:
            axis = Vector((0.0, 0.0, 1.0))
        else:
            axis.normalize()
        axis_speed = float(obj.get("dsm_orbit_axis_speed", 0.35))
        start = float(obj.get("dsm_orbit_axis_start_frame", frame))
        angle = (float(frame) - start) * axis_speed * 0.01
        return Quaternion(axis, angle) @ point

    if shape == "ELLIPSE":
        u, v = radius * math.cos(t), radius * 0.6 * math.sin(t)
    elif shape == "INFINITY":
        u, v = radius * math.sin(t), radius * 0.5 * math.sin(2.0 * t)
    elif shape == "SQUARE":
        su, sv = utils.square_orbit(t)
        u, v = radius * su, radius * sv
    else:
        u, v = radius * math.cos(t), radius * math.sin(t)

    normal = float(obj.get("dsm_orbit_normal", 0.0))
    return _plane_vector(u, v, normal, obj.get("dsm_orbit_plane", "XY"))


def clear_object(obj, restore=True):
    child = _resolve(obj) or obj
    if not child or not child.get("dsm_orbit_enabled", False):
        return False

    seed = child.get("dsm_orbit_seed")
    if child.type == "CAMERA":
        _remove_focus(child)

    if restore:
        utils.set_world_location(child, utils.unpack_vector(child.get("dsm_orbit_start_world", (0, 0, 0))))
        start_rot = child.get("dsm_orbit_start_rotation")
        if start_rot and len(start_rot) == 4:
            try:
                _set_world_rotation(child, Quaternion(tuple(float(v) for v in start_rot)))
            except Exception:
                pass

    utils.clear_feature_props(child, "orbit")
    if seed is not None:
        child["dsm_orbit_seed"] = int(seed)
    return True


def apply_object(obj, context, index=0, count=1):
    existing = _resolve(obj)
    if existing:
        obj = existing

    seed = obj.get("dsm_orbit_seed")

    from . import spawn, follow
    spawn.clear_object(obj, restore=True)
    follow.clear_object(obj, restore=True)
    clear_object(obj, restore=True)

    if seed is not None:
        obj["dsm_orbit_seed"] = int(seed)

    if utils.has_animation_path(obj, {"location"}):
        return False, "location already has animation or drivers", None

    scene = context.scene
    s = scene.dsm_settings
    target = s.orbit_target
    bone = s.orbit_bone.strip() if target and target.type == "ARMATURE" else ""
    matrix = utils.get_target_matrix(target, bone)
    if matrix is None:
        matrix = Matrix.Translation(scene.cursor.location)

    world = utils.get_world_location(obj)
    local = matrix.inverted() @ world
    pivot = matrix.translation.copy()
    start_rotation = obj.matrix_world.to_quaternion().copy()

    face = bool(s.orbit_face_direction and obj.type != "CAMERA")
    if face and utils.has_animation_path(obj, {"rotation_euler", "rotation_quaternion", "rotation_axis_angle", "delta_rotation_euler", "delta_rotation_quaternion"}):
        return False, "rotation already animated; disable Face Direction", None

    rng = utils.seeded_rng(obj, "orbit")
    speed_factor = utils.variation_factor(rng, s.orbit_variation)
    speed = float(s.orbit_speed * speed_factor)
    shape = s.orbit_shape

    obj["dsm_orbit_enabled"] = True
    obj["dsm_orbit_start_world"] = utils.pack_vector(world)
    obj["dsm_orbit_start_rotation"] = [float(v) for v in start_rotation]
    obj["dsm_orbit_target"] = target.name if target else ""
    obj["dsm_orbit_bone"] = bone
    obj["dsm_orbit_pivot"] = utils.pack_vector(scene.cursor.location)
    obj["dsm_orbit_plane"] = s.orbit_plane
    obj["dsm_orbit_shape"] = shape
    obj["dsm_orbit_speed"] = speed
    obj["dsm_orbit_face_direction"] = face
    obj["dsm_orbit_forward_axis"] = s.orbit_forward_axis

    if shape == "SPHERE":
        e1, e2, radius = _sphere_basis(local, rng)
        axis = _precession_axis(e1, e2, rng)
        phase = -(scene.frame_current * speed * 0.02)
        if s.orbit_behavior == "OFFSET" and count > 1:
            phase += 2.0 * math.pi * index / count
        elif s.orbit_behavior == "RANDOM":
            phase += rng.uniform(0.0, 2.0 * math.pi)

        obj["dsm_orbit_basis1"] = utils.pack_vector(e1)
        obj["dsm_orbit_basis2"] = utils.pack_vector(e2)
        obj["dsm_orbit_precession_axis"] = utils.pack_vector(axis)
        obj["dsm_orbit_axis_speed"] = float(s.orbit_sphere_axis_speed * utils.variation_factor(rng, s.orbit_variation * 0.5))
        obj["dsm_orbit_axis_start_frame"] = float(scene.frame_current)
        obj["dsm_orbit_radius"] = float(max(radius, s.orbit_fallback_radius if radius < 1e-4 else radius))
        obj["dsm_orbit_phase"] = float(phase)
    else:
        u, v, normal = _plane_components(local, s.orbit_plane)
        radius = math.hypot(u, v)
        if radius < 1e-4:
            radius = s.orbit_fallback_radius
            angle = 0.0
        else:
            angle = math.atan2(v, u)

        phase = angle - scene.frame_current * speed * 0.02
        if s.orbit_behavior == "OFFSET" and count > 1:
            phase += 2.0 * math.pi * index / count
        elif s.orbit_behavior == "RANDOM":
            phase += rng.uniform(0.0, 2.0 * math.pi)

        obj["dsm_orbit_radius"] = float(radius)
        obj["dsm_orbit_normal"] = float(normal)
        obj["dsm_orbit_phase"] = float(phase)

    focus = None
    if obj.type == "CAMERA":
        focus = _create_focus(obj, context, target, bone, pivot, float(obj.get("dsm_orbit_radius", max(local.length, 1.0))))

    return True, "", focus


def update_object(obj, scene):
    if not obj.get("dsm_orbit_enabled", False):
        return

    target = _target_for(obj)
    bone = obj.get("dsm_orbit_bone", "")
    matrix = utils.get_target_matrix(target, bone)
    if matrix is None:
        matrix = Matrix.Translation(utils.unpack_vector(obj.get("dsm_orbit_pivot", (0, 0, 0))))

    local = _local_at(obj, scene.frame_current)
    world = matrix @ local
    utils.set_world_location(obj, world)

    if obj.type == "CAMERA":
        _aim_camera(obj)
        return

    if obj.get("dsm_orbit_face_direction", False):
        next_local = _local_at(obj, float(scene.frame_current) + 0.25)
        next_world = matrix @ next_local
        direction = next_world - world
        if direction.length > 1e-7:
            try:
                forward = obj.get("dsm_orbit_forward_axis", "Y")
                up = "Y" if forward in {"Z", "-Z"} else "Z"
                _set_world_rotation(obj, direction.normalized().to_track_quat(forward, up))
            except Exception:
                pass


def update_all(scene):
    for obj in bpy.data.objects:
        if obj.get("dsm_orbit_enabled", False):
            update_object(obj, scene)


class DSM_OT_orbit_apply(Operator):
    bl_idname = "dsm.orbit_apply"
    bl_label = "Apply Orbit"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = context.scene.dsm_settings.orbit_target
        selected = utils.selected_objects(context, target)
        if not selected:
            self.report({"WARNING"}, "Select one or more orbiting objects")
            return {"CANCELLED"}

        objects = []
        seen = set()
        for item in selected:
            obj = _resolve(item) or item
            if obj.name not in seen:
                seen.add(obj.name)
                objects.append(obj)

        focus_empties = []
        skipped = []
        for index, obj in enumerate(objects):
            ok, reason, focus = apply_object(obj, context, index, len(objects))
            if ok and focus:
                focus_empties.append(focus)
            elif not ok:
                skipped.append(f"{obj.name}: {reason}")

        update_all(context.scene)

        if len(objects) == 1 and objects[0].type == "CAMERA":
            try:
                bpy.ops.object.select_all(action="DESELECT")
                objects[0].select_set(True)
                if focus_empties:
                    focus_empties[0].select_set(True)
                context.view_layer.objects.active = objects[0]
            except Exception:
                pass

        if skipped:
            self.report({"WARNING"}, "; ".join(skipped[:3]))
        self.report({"INFO"}, f"Orbit applied to {len(objects) - len(skipped)} object(s)")
        return {"FINISHED"}


class DSM_OT_orbit_clear(Operator):
    bl_idname = "dsm.orbit_clear"
    bl_label = "Clear Orbit"
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
        self.report({"INFO"}, f"Orbit cleared on {count} object(s)")
        return {"FINISHED"}


_CLASSES = (DSM_OT_orbit_apply, DSM_OT_orbit_clear)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
