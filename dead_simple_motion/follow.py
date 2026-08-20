import math
import bpy
from mathutils import Vector
from bpy.types import Operator
from . import utils


def _target(obj):
    name = obj.get("dsm_follow_target", "")
    return bpy.data.objects.get(name) if name else None


def _target_world_position(target, bone_name=""):
    """Return only the target point in world space.

    Follow is deliberately LOCATION ONLY. For bones we use the pose bone head
    transformed into world space and never use the bone's rotation matrix to
    rotate the follower offset. That prevents a follower from orbiting when the
    bone rotates in place.
    """
    if target is None:
        return None

    if target.type == 'ARMATURE' and bone_name:
        pose = getattr(target, "pose", None)
        if not pose:
            return None
        pose_bone = pose.bones.get(bone_name)
        if pose_bone is None:
            return None
        try:
            return target.matrix_world @ pose_bone.head
        except Exception:
            return None

    return target.matrix_world.translation.copy()


def clear_object(obj, restore=True):
    if not obj or not obj.get("dsm_follow_enabled", False):
        return False

    if restore:
        start = utils.unpack_vector(obj.get("dsm_follow_start_world", (0, 0, 0)))
        utils.set_world_location(obj, start)

    utils.clear_feature_props(obj, "follow")
    return True


def apply_object(obj, context):
    settings = context.scene.dsm_settings
    target = settings.follow_target
    bone = settings.follow_bone.strip() if target and target.type == 'ARMATURE' else ""

    if not target:
        return False, "choose a follow target"

    target_position = _target_world_position(target, bone)
    if target_position is None:
        return False, "target or bone could not be read"

    from . import orbit, spawn
    orbit.clear_object(obj, restore=True)
    spawn.clear_object(obj, restore=True)
    clear_object(obj, restore=True)

    if utils.has_animation_path(obj, {"location"}):
        return False, "location already has animation or drivers"

    world = utils.get_world_location(obj)

    # The offset is stored in WORLD space. Bone rotation therefore never swings
    # the follower around the bone; only movement of the bone's position matters.
    offset = world - target_position

    rng = utils.seeded_rng(obj, "follow")
    factor = utils.variation_factor(rng, settings.follow_variation)

    obj["dsm_follow_enabled"] = True
    obj["dsm_follow_start_world"] = utils.pack_vector(world)
    obj["dsm_follow_target"] = target.name
    obj["dsm_follow_bone"] = bone
    obj["dsm_follow_offset"] = utils.pack_vector(offset)
    obj["dsm_follow_delay"] = float(max(0.0, settings.follow_delay * factor))
    obj["dsm_follow_drift"] = float(max(0.0, settings.follow_drift * factor))
    obj["dsm_follow_phase_x"] = rng.uniform(0.0, math.tau)
    obj["dsm_follow_phase_y"] = rng.uniform(0.0, math.tau)
    obj["dsm_follow_phase_z"] = rng.uniform(0.0, math.tau)
    return True, ""


def _organic_drift(obj, frame, amount):
    """Slow non-circular positional drift.

    Different mixed frequencies on each axis avoid the obvious elliptical path
    that a simple three-axis sine setup can look like.
    """
    if amount <= 0.0:
        return Vector((0.0, 0.0, 0.0))

    px = float(obj.get("dsm_follow_phase_x", 0.0))
    py = float(obj.get("dsm_follow_phase_y", 0.0))
    pz = float(obj.get("dsm_follow_phase_z", 0.0))

    x = math.sin(frame * 0.017 + px) + 0.33 * math.sin(frame * 0.043 + py)
    y = math.sin(frame * 0.013 + py) + 0.29 * math.sin(frame * 0.037 + pz)
    z = math.sin(frame * 0.019 + pz) + 0.25 * math.sin(frame * 0.031 + px)

    return Vector((x, y, z)) * (amount / 1.33)


def update_object(obj, scene):
    if not obj.get("dsm_follow_enabled", False):
        return

    target = _target(obj)
    if not target:
        return

    bone = obj.get("dsm_follow_bone", "")
    target_position = _target_world_position(target, bone)
    if target_position is None:
        return

    offset = utils.unpack_vector(obj.get("dsm_follow_offset", (0, 0, 0)))
    drift_amount = float(obj.get("dsm_follow_drift", 0.0))
    frame = float(scene.frame_current)
    desired = target_position + offset + _organic_drift(obj, frame, drift_amount)

    # Delay is a trailing-response control, not a literal frame buffer. This
    # keeps it responsive when the artist drags the target live in the viewport.
    # 0 = immediate lock. Higher values = slower catch-up and more visible lag.
    delay = max(0.0, float(obj.get("dsm_follow_delay", 35.0)))
    if delay <= 0.0:
        alpha = 1.0
    else:
        alpha = max(0.02, min(1.0, 1.0 / (1.0 + delay * 0.14)))

    current = utils.get_world_location(obj)
    new_location = current.lerp(desired, alpha)

    if (current - new_location).length > 1e-6:
        utils.set_world_location(obj, new_location)


def update_all(scene):
    for obj in bpy.data.objects:
        if obj.get("dsm_follow_enabled", False):
            update_object(obj, scene)


class DSM_OT_follow_apply(Operator):
    bl_idname = "dsm.follow_apply"
    bl_label = "Apply Follow"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        target = context.scene.dsm_settings.follow_target
        objects = utils.selected_objects(context, target)
        if not objects:
            self.report({'WARNING'}, "Select one or more followers")
            return {'CANCELLED'}

        success = 0
        skipped = []

        for obj in objects:
            ok, reason = apply_object(obj, context)
            if ok:
                success += 1
            else:
                skipped.append(f"{obj.name}: {reason}")

        update_all(context.scene)

        if skipped:
            self.report({'WARNING'}, "; ".join(skipped[:3]))
        self.report({'INFO'}, f"Follow applied to {success} object(s)")
        return {'FINISHED'}


class DSM_OT_follow_clear(Operator):
    bl_idname = "dsm.follow_clear"
    bl_label = "Clear Follow"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = sum(1 for obj in utils.selected_objects(context) if clear_object(obj))
        self.report({'INFO'}, f"Follow cleared on {count} object(s)")
        return {'FINISHED'}


_CLASSES = (DSM_OT_follow_apply, DSM_OT_follow_clear)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
