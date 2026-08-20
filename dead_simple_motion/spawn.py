import bpy
from mathutils import Vector
from bpy.types import Operator
from . import utils


def clear_object(obj, restore=True):
    if not obj or not obj.get("dsm_spawn_enabled", False):
        return False
    if restore:
        start = utils.unpack_vector(obj.get("dsm_spawn_start_world", (0, 0, 0)))
        utils.set_world_location(obj, start)
    obj.hide_viewport = bool(obj.get("dsm_spawn_original_hide_viewport", False))
    obj.hide_render = bool(obj.get("dsm_spawn_original_hide_render", False))
    utils.clear_feature_props(obj, "spawn")
    return True


def apply_object(obj, context):
    scene = context.scene
    settings = scene.dsm_settings
    from . import orbit, follow
    orbit.clear_object(obj, restore=True)
    follow.clear_object(obj, restore=True)
    clear_object(obj, restore=True)

    if utils.has_animation_path(obj, {"location"}):
        return False, "location already has animation or drivers"

    rng = utils.seeded_rng(obj, "spawn")
    factor = utils.variation_factor(rng, settings.spawn_variation)
    distance = max(0.001, settings.spawn_distance)
    phase_distance = rng.uniform(0.0, distance)

    obj["dsm_spawn_enabled"] = True
    obj["dsm_spawn_start_world"] = utils.pack_vector(utils.get_world_location(obj))
    obj["dsm_spawn_mode"] = settings.spawn_mode
    obj["dsm_spawn_axis"] = settings.spawn_axis
    obj["dsm_spawn_speed"] = float(settings.spawn_speed * factor)
    obj["dsm_spawn_distance"] = float(distance)
    obj["dsm_spawn_phase_distance"] = float(phase_distance)
    obj["dsm_spawn_original_hide_viewport"] = bool(obj.hide_viewport)
    obj["dsm_spawn_original_hide_render"] = bool(obj.hide_render)
    return True, ""


def update_object(obj, scene):
    if not obj.get("dsm_spawn_enabled", False):
        return
    start = utils.unpack_vector(obj.get("dsm_spawn_start_world", (0, 0, 0)))
    distance = max(0.001, float(obj.get("dsm_spawn_distance", 10.0)))
    speed = float(obj.get("dsm_spawn_speed", 0.1))
    phase = float(obj.get("dsm_spawn_phase_distance", 0.0))
    travel = ((scene.frame_current - scene.frame_start) * speed) + phase
    mode = obj.get("dsm_spawn_mode", "SPAWN")

    if mode == 'LOOPER':
        wrapped = travel % (2.0 * distance)
        offset = wrapped if wrapped <= distance else (2.0 * distance - wrapped)
        hidden = False
    else:
        wrapped = travel % distance
        offset = wrapped
        hidden = wrapped >= (distance * 0.965)

    axis = obj.get("dsm_spawn_axis", "X")
    direction = Vector((1.0, 0.0, 0.0))
    if axis == 'Y':
        direction = Vector((0.0, 1.0, 0.0))
    elif axis == 'Z':
        direction = Vector((0.0, 0.0, 1.0))

    utils.set_world_location(obj, start + direction * offset)
    if mode == 'SPAWN':
        obj.hide_viewport = hidden
        obj.hide_render = hidden


def update_all(scene):
    for obj in bpy.data.objects:
        if obj.get("dsm_spawn_enabled", False):
            update_object(obj, scene)


class DSM_OT_spawn_apply(Operator):
    bl_idname = "dsm.spawn_apply"
    bl_label = "Apply Spawn / Looper"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects = utils.selected_objects(context)
        if not objects:
            self.report({'WARNING'}, "Select one or more objects")
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
        self.report({'INFO'}, f"{context.scene.dsm_settings.spawn_mode.title()} applied to {success} object(s)")
        return {'FINISHED'}


class DSM_OT_spawn_clear(Operator):
    bl_idname = "dsm.spawn_clear"
    bl_label = "Clear Spawn / Looper"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = sum(1 for obj in utils.selected_objects(context) if clear_object(obj))
        self.report({'INFO'}, f"Spawn / Looper cleared on {count} object(s)")
        return {'FINISHED'}


_CLASSES = (DSM_OT_spawn_apply, DSM_OT_spawn_clear)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
