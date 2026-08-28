import math
import time

import bpy
from bpy.types import Operator
from mathutils import Vector

from . import utils

_RUNTIME = {}
LOCATION_PATHS = {"location"}


def _target(obj):
    name = obj.get("dsm_follow_target", "")
    return bpy.data.objects.get(name) if name else None


def _target_world_position(target, bone_name=""):
    if target is None:
        return None

    if target.type == "ARMATURE" and bone_name:
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


def _organic_drift(obj, frame, amount):
    if amount <= 0.0:
        return Vector((0.0, 0.0, 0.0))

    px = float(obj.get("dsm_follow_phase_x", 0.0))
    py = float(obj.get("dsm_follow_phase_y", 0.0))
    pz = float(obj.get("dsm_follow_phase_z", 0.0))

    x = math.sin(frame * 0.017 + px) + 0.33 * math.sin(frame * 0.043 + py)
    y = math.sin(frame * 0.013 + py) + 0.29 * math.sin(frame * 0.037 + pz)
    z = math.sin(frame * 0.019 + pz) + 0.25 * math.sin(frame * 0.031 + px)
    return Vector((x, y, z)) * (amount / 1.33)


def _fps(scene):
    base = float(getattr(scene.render, "fps_base", 1.0) or 1.0)
    return max(1.0, float(scene.render.fps) / base)


def _runtime_state(obj, scene):
    state = _RUNTIME.get(obj.name)
    if state is None:
        state = {
            "last_frame": float(scene.frame_current),
            "last_time": time.monotonic(),
            "current": utils.get_world_location(obj),
        }
        _RUNTIME[obj.name] = state
    return state


def _time_step(state, scene, source):
    now = time.monotonic()
    frame = float(scene.frame_current)

    if source == "DEPSGRAPH":
        dt = max(1.0 / 240.0, min(now - float(state.get("last_time", now)), 0.25))
    else:
        frame_delta = abs(frame - float(state.get("last_frame", frame)))
        dt = frame_delta / _fps(scene)
        if frame_delta > 12.0:
            dt = min(dt, 0.5)

    state["last_time"] = now
    state["last_frame"] = frame
    return max(0.0, float(dt))


def clear_runtime(obj=None):
    if obj is None:
        _RUNTIME.clear()
    else:
        _RUNTIME.pop(obj.name, None)


def clear_object(obj, restore=True):
    if not obj or not obj.get("dsm_follow_enabled", False):
        return False

    if restore:
        start = utils.unpack_vector(obj.get("dsm_follow_start_world", (0, 0, 0)))
        utils.set_world_location(obj, start)

    clear_runtime(obj)
    utils.clear_feature_props(obj, "follow")
    obj.hide_select = False
    return True


def apply_object(obj, context):
    settings = context.scene.dsm_settings
    target = settings.follow_target
    bone = settings.follow_bone.strip() if target and target.type == "ARMATURE" else ""

    if not target:
        return False, "choose a follow target"

    target_position = _target_world_position(target, bone)
    if target_position is None:
        return False, "target or bone could not be read"

    from . import orbit, spawn

    orbit.clear_object(obj, restore=True)
    spawn.clear_object(obj, restore=True)
    clear_object(obj, restore=True)

    if utils.has_animation_path(obj, LOCATION_PATHS):
        return False, "location already has animation or drivers"

    world = utils.get_world_location(obj)
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
    obj.hide_select = False

    clear_runtime(obj)
    _runtime_state(obj, context.scene)
    return True, ""


def update_object(obj, scene, source="FRAME"):
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

    delay = max(0.0, float(obj.get("dsm_follow_delay", 35.0)))
    if delay <= 0.0:
        utils.set_world_location(obj, desired)
        state = _runtime_state(obj, scene)
        state["current"] = desired.copy()
        state["last_frame"] = frame
        state["last_time"] = time.monotonic()
        return

    state = _runtime_state(obj, scene)
    dt = _time_step(state, scene, source)
    if dt <= 0.0:
        return

    # Time-based exponential smoothing: the result depends on elapsed time,
    # not on how many depsgraph callbacks Blender happened to emit.
    tau = 0.04 + delay * 0.018
    alpha = 1.0 - math.exp(-dt / max(tau, 1e-5))
    current = utils.get_world_location(obj)
    new_location = current.lerp(desired, max(0.0, min(1.0, alpha)))

    if utils.set_world_location(obj, new_location):
        state["current"] = new_location.copy()


def update_all(scene, source="FRAME", updated_ids=None):
    for obj in bpy.data.objects:
        if not obj.get("dsm_follow_enabled", False):
            continue
        if updated_ids is not None:
            target = _target(obj)
            if not target or target.name not in updated_ids:
                continue
        update_object(obj, scene, source=source)


class DSM_OT_follow_apply(Operator):
    bl_idname = "dsm.follow_apply"
    bl_label = "Apply Follow"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = context.scene.dsm_settings.follow_target
        objects = utils.selected_objects(context, target)
        if not objects:
            self.report({"WARNING"}, "Select one or more followers")
            return {"CANCELLED"}

        success = 0
        skipped = []
        for obj in objects:
            ok, reason = apply_object(obj, context)
            if ok:
                success += 1
            else:
                skipped.append(f"{obj.name}: {reason}")

        update_all(context.scene, source="FRAME")

        if skipped:
            self.report({"WARNING"}, "; ".join(skipped[:3]))
        self.report({"INFO"}, f"Follow applied to {success} object(s)")
        return {"FINISHED"}


class DSM_OT_follow_clear(Operator):
    bl_idname = "dsm.follow_clear"
    bl_label = "Clear Follow"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = sum(1 for obj in utils.selected_objects(context) if clear_object(obj))
        self.report({"INFO"}, f"Follow cleared on {count} object(s)")
        return {"FINISHED"}


_CLASSES = (DSM_OT_follow_apply, DSM_OT_follow_clear)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    clear_runtime()
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
