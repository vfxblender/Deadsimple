import math
import bpy
from mathutils import Matrix, Quaternion, Vector
from bpy.types import Operator
from . import utils


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


def clear_object(obj, restore=True):
    if not obj or not obj.get("dsm_orbit_enabled", False):
        return False
    if restore:
        utils.set_world_location(obj, utils.unpack_vector(obj.get("dsm_orbit_start_world", (0.0, 0.0, 0.0))))
    utils.clear_feature_props(obj, "orbit")
    return True


def _sphere_basis(local, rng):
    """Build a great-circle plane that passes through the object's start point."""
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
    """Choose a stable 3D axis that actually changes the orbital plane."""
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
        # If the axis is too close to the plane normal, the plane would mostly
        # spin around itself and would not visibly precess in 3D.
        if abs(axis.dot(plane_normal)) < 0.80:
            return axis

    # Deterministic fallback that is not parallel to the plane normal.
    axis = e1 + plane_normal * 0.35
    if axis.length < 1e-5:
        axis = Vector((1.0, 0.0, 0.0))
    axis.normalize()
    return axis


def apply_object(obj, context, index=0, count=1):
    scene = context.scene
    settings = scene.dsm_settings

    from . import spawn, follow
    spawn.clear_object(obj, restore=True)
    follow.clear_object(obj, restore=True)
    clear_object(obj, restore=True)

    if utils.has_animation_path(obj, {"location"}):
        return False, "location already has animation or drivers"

    target = settings.orbit_target
    bone = settings.orbit_bone.strip() if target and target.type == 'ARMATURE' else ""
    target_matrix = utils.get_target_matrix(target, bone)
    if target_matrix is None:
        target_matrix = Matrix.Translation(scene.cursor.location)

    world = utils.get_world_location(obj)
    local = target_matrix.inverted() @ world

    rng = utils.seeded_rng(obj, "orbit")
    speed_factor = utils.variation_factor(rng, settings.orbit_variation)
    speed = settings.orbit_speed * speed_factor
    shape = settings.orbit_shape

    obj["dsm_orbit_enabled"] = True
    obj["dsm_orbit_start_world"] = utils.pack_vector(world)
    obj["dsm_orbit_target"] = target.name if target else ""
    obj["dsm_orbit_bone"] = bone
    obj["dsm_orbit_pivot"] = utils.pack_vector(scene.cursor.location)
    obj["dsm_orbit_plane"] = settings.orbit_plane
    obj["dsm_orbit_shape"] = shape
    obj["dsm_orbit_speed"] = float(speed)

    if shape == 'SPHERE':
        # Sphere is a true 3D precessing orbit. The object first travels in a
        # great-circle plane, then that entire plane rotates around a second 3D
        # axis over time. This creates the electron / atom style motion.
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

    return True, ""


def update_object(obj, scene):
    if not obj.get("dsm_orbit_enabled", False):
        return

    target = _target_for_object(obj)
    bone = obj.get("dsm_orbit_bone", "")
    matrix = utils.get_target_matrix(target, bone)
    if matrix is None:
        matrix = Matrix.Translation(utils.unpack_vector(obj.get("dsm_orbit_pivot", (0, 0, 0))))

    speed = float(obj.get("dsm_orbit_speed", 1.0))
    phase = float(obj.get("dsm_orbit_phase", 0.0))
    t = scene.frame_current * speed * 0.02 + phase
    radius = float(obj.get("dsm_orbit_radius", 2.0))
    shape = obj.get("dsm_orbit_shape", "CIRCLE")

    if shape == 'SPHERE':
        e1 = utils.unpack_vector(obj.get("dsm_orbit_basis1", (1, 0, 0)))
        e2 = utils.unpack_vector(obj.get("dsm_orbit_basis2", (0, 1, 0)))

        # First orbit in the object's local great-circle plane.
        circle_point = radius * (e1 * math.cos(t) + e2 * math.sin(t))

        # Then rotate that entire plane around a second 3D axis. This is the
        # precession layer that turns a flat orbit into an atom/electron path.
        precession_axis = utils.unpack_vector(obj.get("dsm_orbit_precession_axis", (0, 0, 1)))
        if precession_axis.length < 1e-5:
            precession_axis = Vector((0.0, 0.0, 1.0))
        else:
            precession_axis.normalize()

        axis_speed = float(obj.get("dsm_orbit_axis_speed", 0.35))
        axis_start = float(obj.get("dsm_orbit_axis_start_frame", scene.frame_current))
        axis_angle = (float(scene.frame_current) - axis_start) * axis_speed * 0.01
        precession = Quaternion(precession_axis, axis_angle)
        local = precession @ circle_point
    else:
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
        local = _plane_vector(u, v, normal, obj.get("dsm_orbit_plane", "XY"))

    world = matrix @ local
    if (utils.get_world_location(obj) - world).length > 1e-6:
        utils.set_world_location(obj, world)


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
        objects = utils.selected_objects(context, target)
        if not objects:
            self.report({'WARNING'}, "Select one or more orbiting objects")
            return {'CANCELLED'}

        success = 0
        skipped = []
        total = len(objects)

        for index, obj in enumerate(objects):
            ok, reason = apply_object(obj, context, index, total)
            if ok:
                success += 1
            else:
                skipped.append(f"{obj.name}: {reason}")

        update_all(context.scene)

        if skipped:
            self.report({'WARNING'}, "; ".join(skipped[:3]))
        self.report({'INFO'}, f"Orbit applied to {success} object(s)")
        return {'FINISHED'}


class DSM_OT_orbit_clear(Operator):
    bl_idname = "dsm.orbit_clear"
    bl_label = "Clear Orbit"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = sum(1 for obj in utils.selected_objects(context) if clear_object(obj))
        self.report({'INFO'}, f"Orbit cleared on {count} object(s)")
        return {'FINISHED'}


_CLASSES = (DSM_OT_orbit_apply, DSM_OT_orbit_clear)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
