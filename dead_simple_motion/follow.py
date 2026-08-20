import math
import bpy
from mathutils import Vector
from bpy.types import Operator
from . import utils


def _target(obj):
    name = obj.get("dsm_follow_target", "")
    return bpy.data.objects.get(name) if name else None


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

    from . import orbit, spawn
    orbit.clear_object(obj, restore=True)
    spawn.clear_object(obj, restore=True)
    clear_object(obj, restore=True)

    if utils.has_animation_path(obj, {"location"}):
        return False, "location already has animation or drivers"

    target_matrix = utils.get_target_matrix(target, bone)
    if target_matrix is None:
        return False, "target or bone could not be read"

    world = utils.get_world_location(obj)
    offset = world - target_matrix.translation
    rng = utils.seeded_rng(obj, "follow")
    factor = utils.variation_factor(rng, settings.follow_variation)

    obj["dsm_follow_enabled"] = True
    obj["dsm_follow_start_world"] = utils.pack_vector(world)
    obj["dsm_follow_target"] = target.name
    obj["dsm_follow_bone"] = bone
    obj["dsm_follow_offset"] = utils.pack_vector(offset)
    obj["dsm_follow_smoothness"] = float(max(0.0, min(1.0, settings.follow_smoothness * factor)))
    obj["dsm_follow_drift"] = float(settings.follow_drift * factor)
    obj["dsm_follow_phase_x"] = rng.uniform(0.0, math.tau)
    obj["dsm_follow_phase_y"] = rng.uniform(0.0, math.tau)
    obj["dsm_follow_phase_z"] = rng.uniform(0.0, math.tau)
    return True, ""


def update_object(obj, scene):
    if not obj.get("dsm_follow_enabled", False):
        return
    target = _target(obj)
    if not target:
        return
    bone = obj.get("dsm_follow_bone", "")
    matrix = utils.get_target_matrix(target, bone)
    if matrix is None:
        return

    offset = utils.unpack_vector(obj.get("dsm_follow_offset", (0, 0, 0)))
    drift = float(obj.get("dsm_follow_drift", 0.0))
    f = float(scene.frame_current)
    drift_vec = Vector((
        math.sin(f * 0.027 + float(obj.get("dsm_follow_phase_x", 0.0))),
        math.sin(f * 0.021 + float(obj.get("dsm_follow_phase_y", 0.0))),
        math.sin(f * 0.031 + float(obj.get("dsm_follow_phase_z", 0.0))),
    )) * drift
    desired = matrix.translation + offset + drift_vec

    smooth = float(obj.get("dsm_follow_smoothness", 0.55))
    alpha = max(0.04, min(1.0, 1.0 - smooth * 0.92))
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
