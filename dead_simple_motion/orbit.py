import math
import bpy
from mathutils import Matrix, Quaternion, Vector
from bpy.types import Operator
from . import utils

FOCUS_PREFIX = "DSM_ORBIT_FOCUS_"
FOCUS_CONSTRAINT_NAME = "DSM Orbit Camera Focus"


def _plane_components(local, plane):
    if plane == 'XY':
        return local.x, local.y, local.z
    if plane == 'XZ':
        return local.x, local.z, local.y
    return local.y, local.z, local.x


def _plane_vector(u, v, normal, plane):
    if plane == 'XY':
        return Vector((u, v, normal))
    if plane == 'XZ':
        return Vector((u, normal, v))
    return Vector((normal, u, v))


def _target_for_object(obj):
    name = obj.get("dsm_orbit_target", "")
    return bpy.data.objects.get(name) if name else None


def _resolve_orbit_object(obj):
    if not obj:
        return None
    if obj.get("dsm_orbit_focus_owner"):
        return bpy.data.objects.get(obj.get("dsm_orbit_focus_owner", ""))
    if obj.get("dsm_orbit_enabled", False):
        return obj
    return None


def _set_world_rotation(obj, quaternion):
    try:
        location, _rotation, scale = obj.matrix_world.decompose()
        obj.matrix_world = Matrix.LocRotScale(location, quaternion, scale)
    except Exception:
        pass


def _remove_camera_focus(camera):
    if not camera:
        return

    con = camera.constraints.get(FOCUS_CONSTRAINT_NAME)
    if con:
        try:
            camera.constraints.remove(con)
        except Exception:
            pass

    focus_name = camera.get("dsm_orbit_focus_name", "")
    focus = bpy.data.objects.get(focus_name) if focus_name else None
    if focus:
        try:
            bpy.data.objects.remove(focus, do_unlink=True)
        except Exception:
            pass


def _create_camera_focus(camera, context, target, bone_name, pivot_world, radius):
    _remove_camera_focus(camera)

    focus = bpy.data.objects.new(f"{FOCUS_PREFIX}{camera.name}", None)
    focus.empty_display_type = 'SPHERE'
    focus.empty_display_size = max(0.35, min(float(radius) * 0.08, 2.0))
    focus.show_in_front = True
    focus.hide_render = True
    focus["dsm_orbit_focus_owner"] = camera.name

    collection = camera.users_collection[0] if camera.users_collection else context.collection
    collection.objects.link(focus)

    if target:
        focus.parent = target
        if target.type == 'ARMATURE' and bone_name:
            try:
                focus.parent_type = 'BONE'
                focus.parent_bone = bone_name
            except Exception:
                focus.parent_type = 'OBJECT'
        else:
            focus.parent_type = 'OBJECT'

    focus.matrix_world = Matrix.Translation(Vector(pivot_world))

    con = camera.constraints.new('DAMPED_TRACK')
    con.name = FOCUS_CONSTRAINT_NAME
    con.target = focus
    con.track_axis = 'TRACK_NEGATIVE_Z'

    camera["dsm_orbit_focus_name"] = focus.name
    return focus


def clear_object(obj, restore=True):
    child = _resolve_orbit_object(obj) or obj
    if not child or not child.get("dsm_orbit_enabled", False):
        return False

    seed = child.get("dsm_orbit_seed")

    if child.type == 'CAMERA':
        _remove_camera_focus(child)

    if restore:
        utils.set_world_location(
            child,
            utils.unpack_vector(child.get("dsm_orbit_start_world", (0.0, 0.0, 0.0))),
        )
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


def _sphere_basis(local, rng):
    radial = local.copy()
    if radial.length < 1e-5:
        radial = Vector((1.0, 0.0, 0.0))

    e1 = radial.normalized()
    trial = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
    if trial.length < 1e-5 or abs(trial.normalized().dot(e1)) > 0.95:
        trial = Vector((0.0, 0.0, 1.0)) if abs(e1.z) < 0.9 else Vector((0.0, 1.0, 0.0))

    e2 = (trial - e1 * trial.dot(e1)).normalized()
    radius = max(local.length, 1e-5)
    return e1, e2, radius


def _sphere_precession_axis(e1, e2, rng):
    plane_normal = e1.cross(e2)
    if plane_normal.length < 1e-5:
        plane_normal = Vector((0.0, 0.0, 1.0))
    else:
        plane_normal.normalize()

    for _ in range(12):
        axis = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
        if axis.length < 1e-5:
            continue
        axis.normalize()
        if abs(axis.dot(plane_normal)) < 0.80:
            return axis

    axis = e1 + plane_normal * 0.35
    if axis.length < 1e-5:
        axis = Vector((1.0, 0.0, 0.0))
    axis.normalize()
    return axis


def _local_position_at_frame(obj, frame):
    speed = float(obj.get("dsm_orbit_speed", 1.0))
    phase = float(obj.get("dsm_orbit_phase", 0.0))
    t = float(frame) * speed * 0.02 + phase
    radius = float(obj.get("dsm_orbit_radius", 2.0))
    shape = obj.get("dsm_orbit_shape", "CIRCLE")

    if shape == 'SPHERE':
        e1 = utils.unpack_vector(obj.get("dsm_orbit_basis1", (1, 0, 0)))
        e2 = utils.unpack_vector(obj.get("dsm_orbit_basis2", (0, 1, 0)))
        circle_point = radius * (e1 * math.cos(t) + e2 * math.sin(t))

        precession_axis = utils.unpack_vector(obj.get("dsm_orbit_precession_axis", (0, 0, 1)))
        if precession_axis.length < 1e-5:
            precession_axis = Vector((0.0, 0.0, 1.0))
        else:
            precession_axis.normalize()

        axis_speed = float(obj.get("dsm_orbit_axis_speed", 0.35))
        axis_start = float(obj.get("dsm_orbit_axis_start_frame", frame))
        axis_angle = (float(frame) - axis_start) * axis_speed * 0.01
        return Quaternion(precession_axis, axis_angle) @ circle_point

    if shape == 'ELLIPSE':
        u, v = radius * math.cos(t), radius * 0.6 * math.sin(t)
    elif shape == 'INFINITY':
        u, v = radius * math.sin(t), radius * 0.5 * math.sin(2.0 * t)
    elif shape == 'SQUARE':
        su, sv = utils.square_orbit(t)
        u, v = radius * su, radius * sv
    else:
        u, v = radius * math.cos(t), radius * math.sin(t)

    normal = float(obj.get("dsm_orbit_normal", 0.0))
    return _plane_vector(u, v, normal, obj.get("dsm_orbit_plane", "XY"))


def _face_along_direction(obj, direction):
    if direction.length < 1e-7:
        return

    forward = obj.get("dsm_orbit_forward_axis", "Y")
    up = 'Y' if forward in {'Z', '-Z'} else 'Z'
    try:
        rotation = direction.normalized().to_track_quat(forward, up)
        _set_world_rotation(obj, rotation)
    except Exception:
        pass


def apply_object(obj, context, index=0, count=1):
    existing = _resolve_orbit_object(obj)
    if existing:
        obj = existing

    scene = context.scene
    settings = scene.dsm_settings

    from . import spawn, follow
    spawn.clear_object(obj, restore=True)
    follow.clear_object(obj, restore=True)
    clear_object(obj, restore=True)

    if utils.has_animation_path(obj, {"location"}):
        return False, "location already has animation or drivers", None

    face_direction = bool(settings.orbit_face_direction and obj.type != 'CAMERA')
    if face_direction and utils.has_animation_path(
        obj,
        {"rotation_euler", "rotation_quaternion", "rotation_axis_angle", "delta_rotation_euler", "delta_rotation_quaternion"},
    ):
        return False, "rotation already has animation or drivers; disable Face Direction", None

    target = settings.orbit_target
    bone = settings.orbit_bone.strip() if target and target.type == 'ARMATURE' else ""
    target_matrix = utils.get_target_matrix(target, bone)
    if target_matrix is None:
        target_matrix = Matrix.Translation(scene.cursor.location)

    pivot_world = target_matrix.translation.copy()
    world = utils.get_world_location(obj)
    start_rotation = obj.matrix_world.to_quaternion().copy()
    local = target_matrix.inverted() @ world

    rng = utils.seeded_rng(obj, "orbit")
    speed_factor = utils.variation_factor(rng, settings.orbit_variation)
    speed = settings.orbit_speed * speed_factor
    shape = settings.orbit_shape

    obj["dsm_orbit_enabled"] = True
    obj["dsm_orbit_start_world"] = utils.pack_vector(world)
    obj["dsm_orbit_start_rotation"] = [float(v) for v in start_rotation]
    obj["dsm_orbit_target"] = target.name if target else ""
    obj["dsm_orbit_bone"] = bone
    obj["dsm_orbit_pivot"] = utils.pack_vector(scene.cursor.location)
    obj["dsm_orbit_plane"] = settings.orbit_plane
    obj["dsm_orbit_shape"] = shape
    obj["dsm_orbit_speed"] = float(speed)
    obj["dsm_orbit_face_direction"] = face_direction
    obj["dsm_orbit_forward_axis"] = settings.orbit_forward_axis

    if shape == 'SPHERE':
        e1, e2, radius = _sphere_basis(local, rng)
        precession_axis = _sphere_precession_axis(e1, e2, rng)

        phase = -(scene.frame_current * speed * 0.02)
        if settings.orbit_behavior == 'OFFSET' and count > 1:
            phase += (2.0 * math.pi * index / count)
        elif settings.orbit_behavior == 'RANDOM':
            phase += rng.uniform(0.0, 2.0 * math.pi)

        axis_factor = utils.variation_factor(rng, settings.orbit_variation * 0.5)
        axis_speed = settings.orbit_sphere_axis_speed * axis_factor

        obj["dsm_orbit_basis1"] = utils.pack_vector(e1)
        obj["dsm_orbit_basis2"] = utils.pack_vector(e2)
        obj["dsm_orbit_precession_axis"] = utils.pack_vector(precession_axis)
        obj["dsm_orbit_axis_speed"] = float(axis_speed)
        obj["dsm_orbit_axis_start_frame"] = float(scene.frame_current)
        obj["dsm_orbit_radius"] = float(max(radius, settings.orbit_fallback_radius if radius < 1e-4 else radius))
        obj["dsm_orbit_phase"] = float(phase)
    else:
        u, v, normal = _plane_components(local, settings.orbit_plane)
        radius = math.hypot(u, v)
        if radius < 1e-4:
            radius = settings.orbit_fallback_radius
            angle = 0.0
        else:
            angle = math.atan2(v, u)

        phase = angle - (scene.frame_current * speed * 0.02)
        if settings.orbit_behavior == 'OFFSET' and count > 1:
            phase += (2.0 * math.pi * index / count)
        elif settings.orbit_behavior == 'RANDOM':
            phase += rng.uniform(0.0, 2.0 * math.pi)

        obj["dsm_orbit_radius"] = float(radius)
        obj["dsm_orbit_normal"] = float(normal)
        obj["dsm_orbit_phase"] = float(phase)

    focus = None
    if obj.type == 'CAMERA':
        radius_for_focus = float(obj.get("dsm_orbit_radius", max(local.length, 1.0)))
        focus = _create_camera_focus(
            obj,
            context,
            target,
            bone,
            pivot_world,
            radius_for_focus,
        )

    return True, "", focus


def update_object(obj, scene):
    if not obj.get("dsm_orbit_enabled", False):
        return

    target = _target_for_object(obj)
    bone = obj.get("dsm_orbit_bone", "")
    matrix = utils.get_target_matrix(target, bone)
    if matrix is None:
        matrix = Matrix.Translation(utils.unpack_vector(obj.get("dsm_orbit_pivot", (0, 0, 0))))

    frame = float(scene.frame_current)
    local = _local_position_at_frame(obj, frame)
    world = matrix @ local

    if (utils.get_world_location(obj) - world).length > 1e-6:
        utils.set_world_location(obj, world)

    if obj.get("dsm_orbit_face_direction", False) and obj.type != 'CAMERA':
        next_local = _local_position_at_frame(obj, frame + 0.05)
        next_world = matrix @ next_local
        _face_along_direction(obj, next_world - world)


def update_all(scene):
    for obj in bpy.data.objects:
        if obj.get("dsm_orbit_enabled", False):
            update_object(obj, scene)


class DSM_OT_orbit_apply(Operator):
    bl_idname = "dsm.orbit_apply"
    bl_label = "Apply Orbit"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        target = context.scene.dsm_settings.orbit_target
        selected = utils.selected_objects(context, target)
        if not selected:
            self.report({'WARNING'}, "Select one or more orbiting objects")
            return {'CANCELLED'}

        objects = []
        seen = set()
        for item in selected:
            obj = _resolve_orbit_object(item) or item
            if obj.name not in seen:
                seen.add(obj.name)
                objects.append(obj)

        success = 0
        skipped = []
        focus_empties = []
        total = len(objects)

        for index, obj in enumerate(objects):
            ok, reason, focus = apply_object(obj, context, index, total)
            if ok:
                success += 1
                if focus:
                    focus_empties.append(focus)
            else:
                skipped.append(f"{obj.name}: {reason}")

        update_all(context.scene)

        if len(objects) == 1 and focus_empties:
            try:
                bpy.ops.object.select_all(action='DESELECT')
                focus_empties[0].select_set(True)
                context.view_layer.objects.active = focus_empties[0]
            except Exception:
                pass

        if skipped:
            self.report({'WARNING'}, "; ".join(skipped[:3]))
        self.report({'INFO'}, f"Orbit applied to {success} object(s)")
        return {'FINISHED'}


class DSM_OT_orbit_clear(Operator):
    bl_idname = "dsm.orbit_clear"
    bl_label = "Clear Orbit"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = utils.selected_objects(context)
        count = 0
        seen = set()
        for item in selected:
            obj = _resolve_orbit_object(item)
            if obj and obj.name not in seen:
                seen.add(obj.name)
                if clear_object(obj):
                    count += 1
        self.report({'INFO'}, f"Orbit cleared on {count} object(s)")
        return {'FINISHED'}


_CLASSES = (DSM_OT_orbit_apply, DSM_OT_orbit_clear)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
