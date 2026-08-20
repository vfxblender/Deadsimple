import math
import bpy
from bpy.types import Operator
from . import utils

MARKER = "dsm_fx_marker"
DELTA_PATHS = {"delta_location", "delta_rotation_euler", "delta_scale"}

PRESETS = {
    'SCIFI_DRONE': dict(float=0.22, wobble=0.045, scale=0.008, bob=0.10, shake=0.008, shake_speed=7.0),
    'SPACE_DEBRIS': dict(float=0.50, wobble=0.12, scale=0.015, bob=0.20, shake=0.004, shake_speed=4.0),
    'ENGINE': dict(float=0.02, wobble=0.018, scale=0.008, bob=0.01, shake=0.06, shake_speed=18.0),
    'BREATHING': dict(float=0.03, wobble=0.015, scale=0.055, bob=0.08, shake=0.0, shake_speed=4.0),
    'MAGIC_HOVER': dict(float=0.35, wobble=0.075, scale=0.02, bob=0.28, shake=0.01, shake_speed=6.0),
    'ALAKAZAM': dict(float=0.65, wobble=0.16, scale=0.07, bob=0.45, shake=0.05, shake_speed=13.0),
}


def apply_preset_to_settings(settings):
    data = PRESETS.get(settings.fx_preset, PRESETS['SCIFI_DRONE'])
    settings.fx_float = data['float']
    settings.fx_wobble = data['wobble']
    settings.fx_scale = data['scale']
    settings.fx_bob = data['bob']
    settings.fx_shake = data['shake']
    settings.fx_shake_speed = data['shake_speed']


def _owned_paths():
    return [("delta_location", i) for i in range(3)] + [("delta_rotation_euler", i) for i in range(3)] + [("delta_scale", i) for i in range(3)]


def clear_object(obj, restore=True):
    if not obj or not obj.get("dsm_fx_enabled", False):
        return False
    for path, index in _owned_paths():
        utils.remove_owned_driver(obj, path, index, MARKER)
    if restore:
        try:
            obj.delta_location = obj.get("dsm_fx_base_loc", [0.0, 0.0, 0.0])
            obj.delta_rotation_euler = obj.get("dsm_fx_base_rot", [0.0, 0.0, 0.0])
            obj.delta_scale = obj.get("dsm_fx_base_scale", [1.0, 1.0, 1.0])
        except Exception:
            pass
    marker_prop = f"{MARKER}_value"
    if marker_prop in obj:
        del obj[marker_prop]
    utils.clear_feature_props(obj, "fx")
    return True


def apply_object(obj, context):
    settings = context.scene.dsm_settings
    clear_object(obj, restore=True)
    for path, index in _owned_paths():
        fc = utils.get_driver_fcurve(obj, path, index)
        if fc and not utils.driver_has_marker(fc, MARKER):
            return False, f"{path} already has a driver"
    if utils.has_animation_path(obj, DELTA_PATHS):
        return False, "delta transforms already contain animation"

    rng = utils.seeded_rng(obj, "fx")
    factor = utils.variation_factor(rng, settings.fx_variation)
    speed = settings.fx_speed * factor
    amount = settings.fx_amount
    phases = [rng.uniform(0.0, math.tau) for _ in range(9)]

    base_loc = [float(v) for v in obj.delta_location]
    base_rot = [float(v) for v in obj.delta_rotation_euler]
    base_scale = [float(v) for v in obj.delta_scale]
    obj["dsm_fx_enabled"] = True
    obj["dsm_fx_base_loc"] = base_loc
    obj["dsm_fx_base_rot"] = base_rot
    obj["dsm_fx_base_scale"] = base_scale

    float_amt = settings.fx_float * amount
    wobble = settings.fx_wobble * amount
    scale_amt = settings.fx_scale * amount
    bob = settings.fx_bob * amount
    shake = settings.fx_shake * amount
    shake_speed = settings.fx_shake_speed
    bob_axis = {'X': 0, 'Y': 1, 'Z': 2}[settings.fx_bob_axis]

    for i in range(3):
        slow = f"sin(frame*{(0.022 + i*0.006)*speed:.10f}+{phases[i]:.10f})*{float_amt:.10f}"
        bob_expr = f" + sin(frame*{0.05*speed:.10f}+{phases[3]:.10f})*{bob:.10f}" if i == bob_axis else ""
        jitter = f" + sin(frame*{0.12*shake_speed*speed:.10f}+{phases[4+i]:.10f})*{shake:.10f}"
        utils.add_owned_driver(obj, "delta_location", i, f"{base_loc[i]:.10f} + {slow}{bob_expr}{jitter}", MARKER)

    for i in range(3):
        expr = f"{base_rot[i]:.10f} + sin(frame*{(0.018 + i*0.004)*speed:.10f}+{phases[6+i]:.10f})*{wobble:.10f}"
        utils.add_owned_driver(obj, "delta_rotation_euler", i, expr, MARKER)

    for i in range(3):
        expr = f"{base_scale[i]:.10f} + sin(frame*{0.035*speed:.10f}+{phases[(i+2)%9]:.10f})*{scale_amt:.10f}"
        utils.add_owned_driver(obj, "delta_scale", i, expr, MARKER)
    return True, ""


class DSM_OT_fx_apply(Operator):
    bl_idname = "dsm.fx_apply"
    bl_label = "Apply FX"
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
        if skipped:
            self.report({'WARNING'}, "; ".join(skipped[:3]))
        self.report({'INFO'}, f"FX applied to {success} object(s)")
        return {'FINISHED'}


class DSM_OT_fx_clear(Operator):
    bl_idname = "dsm.fx_clear"
    bl_label = "Clear FX"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = sum(1 for obj in utils.selected_objects(context) if clear_object(obj))
        self.report({'INFO'}, f"FX cleared on {count} object(s)")
        return {'FINISHED'}


_CLASSES = (DSM_OT_fx_apply, DSM_OT_fx_clear)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
