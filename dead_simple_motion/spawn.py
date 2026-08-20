import bpy
from mathutils import Matrix, Vector
from bpy.types import Operator
from . import utils

CONTROL_PREFIX = "DSM_SPAWN_CTRL_"
FOCUS_PREFIX = "DSM_FOCUS_"
FOCUS_CONSTRAINT_NAME = "DSM Spawn Camera Focus"


def _resolve_spawn_object(obj):
    if not obj:
        return None
    if obj.get("dsm_spawn_control", False):
        return bpy.data.objects.get(obj.get("dsm_spawn_child", ""))
    if obj.get("dsm_spawn_focus_owner"):
        return bpy.data.objects.get(obj.get("dsm_spawn_focus_owner", ""))
    if obj.get("dsm_spawn_enabled", False):
        return obj
    return None


def _axis_vector(axis):
    if axis == 'Y':
        return Vector((0.0, 1.0, 0.0))
    if axis == 'Z':
        return Vector((0.0, 0.0, 1.0))
    return Vector((1.0, 0.0, 0.0))


def _control_size(obj):
    try:
        size = max(abs(float(v)) for v in obj.dimensions)
    except Exception:
        size = 1.0
    return max(1.0, min(size * 0.9, 10.0))


def _create_control(obj, context):
    """Create a movable path control and parent the moving object beneath it."""
    world = obj.matrix_world.copy()
    location, rotation, scale = world.decompose()

    original_parent = obj.parent
    original_parent_type = obj.parent_type if original_parent else 'OBJECT'
    original_parent_bone = obj.parent_bone if original_parent and obj.parent_type == 'BONE' else ""

    control = bpy.data.objects.new(f"{CONTROL_PREFIX}{obj.name}", None)
    control.empty_display_type = 'ARROWS'
    control.empty_display_size = _control_size(obj)
    control.show_in_front = True
    control.hide_render = True
    control["dsm_spawn_control"] = True
    control["dsm_spawn_child"] = obj.name

    collection = obj.users_collection[0] if obj.users_collection else context.collection
    collection.objects.link(control)

    if original_parent:
        control.parent = original_parent
        try:
            control.parent_type = original_parent_type
        except Exception:
            pass
        if original_parent_type == 'BONE':
            try:
                control.parent_bone = original_parent_bone
            except Exception:
                pass

    # World-axis motion by default. Rotate this Empty after Apply to rotate the
    # entire slider/spawn path in 3D.
    control.matrix_world = Matrix.Translation(location)

    # Preserve visible orientation/scale while making local location the motion layer.
    obj.parent = control
    obj.parent_type = 'OBJECT'
    obj.parent_bone = ""
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.matrix_basis = Matrix.LocRotScale(Vector((0.0, 0.0, 0.0)), rotation, scale)

    return control, original_parent, original_parent_type, original_parent_bone


def _create_camera_focus(camera, context, distance):
    """Create a world-space focus point and make the camera continuously look at it."""
    old = camera.constraints.get(FOCUS_CONSTRAINT_NAME)
    if old:
        try:
            camera.constraints.remove(old)
        except Exception:
            pass

    forward = camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
    if forward.length < 1e-5:
        forward = Vector((0.0, 0.0, -1.0))
    else:
        forward.normalize()

    focus = bpy.data.objects.new(f"{FOCUS_PREFIX}{camera.name}", None)
    focus.empty_display_type = 'SPHERE'
    focus.empty_display_size = max(0.35, min(distance * 0.06, 2.0))
    focus.show_in_front = True
    focus.hide_render = True
    focus["dsm_spawn_focus_owner"] = camera.name

    collection = camera.users_collection[0] if camera.users_collection else context.collection
    collection.objects.link(focus)
    focus.location = camera.matrix_world.translation + forward * max(2.0, distance * 0.5)

    con = camera.constraints.new('DAMPED_TRACK')
    con.name = FOCUS_CONSTRAINT_NAME
    con.target = focus
    con.track_axis = 'TRACK_NEGATIVE_Z'

    return focus


def _remove_camera_focus(obj):
    con = obj.constraints.get(FOCUS_CONSTRAINT_NAME)
    if con:
        try:
            obj.constraints.remove(con)
        except Exception:
            pass

    focus_name = obj.get("dsm_spawn_focus_name", "")
    focus = bpy.data.objects.get(focus_name) if focus_name else None
    if focus:
        try:
            bpy.data.objects.remove(focus, do_unlink=True)
        except Exception:
            pass


def _ease_progress(progress, fade_in, fade_out):
    """Motion fade/ease mapping with zero velocity at the path ends.

    Fade In Point is where acceleration reaches normal path speed.
    Fade Out Point is where deceleration begins. This is especially useful for
    Looper cameras because the slider eases into both turnarounds instead of
    snapping direction instantly.
    """
    p = max(0.0, min(1.0, float(progress)))
    fade_in = max(0.0, min(1.0, float(fade_in)))
    fade_out = max(0.0, min(1.0, float(fade_out)))

    if fade_out < fade_in:
        mid = (fade_in + fade_out) * 0.5
        fade_in = mid
        fade_out = mid

    if fade_in > 1e-6 and p < fade_in:
        s = p / fade_in
        return fade_in * (s * s * (2.0 - s))

    if fade_out < 1.0 - 1e-6 and p > fade_out:
        length = 1.0 - fade_out
        s = (p - fade_out) / length
        return fade_out + length * (-s * s * s + s * s + s)

    return p


def clear_object(obj, restore=True):
    child = _resolve_spawn_object(obj)
    if not child or not child.get("dsm_spawn_enabled", False):
        return False

    control_name = child.get("dsm_spawn_control_name", "")
    control = bpy.data.objects.get(control_name) if control_name else None

    _remove_camera_focus(child)

    # Put the object back at the control origin before removing the path rig.
    if restore:
        try:
            child.location = (0.0, 0.0, 0.0)
            bpy.context.view_layer.update()
        except Exception:
            pass

    world = child.matrix_world.copy()

    original_parent_name = child.get("dsm_spawn_original_parent", "")
    original_parent = bpy.data.objects.get(original_parent_name) if original_parent_name else None
    original_parent_type = child.get("dsm_spawn_original_parent_type", "OBJECT")
    original_parent_bone = child.get("dsm_spawn_original_parent_bone", "")

    child.parent = original_parent
    if original_parent:
        try:
            child.parent_type = original_parent_type
        except Exception:
            pass
        if original_parent_type == 'BONE':
            try:
                child.parent_bone = original_parent_bone
            except Exception:
                pass
    else:
        child.parent_type = 'OBJECT'
        child.parent_bone = ""

    child.matrix_parent_inverse = Matrix.Identity(4)
    child.matrix_world = world

    child.hide_viewport = bool(child.get("dsm_spawn_original_hide_viewport", False))
    child.hide_render = bool(child.get("dsm_spawn_original_hide_render", False))

    if control:
        try:
            bpy.data.objects.remove(control, do_unlink=True)
        except Exception:
            pass

    seed = child.get("dsm_spawn_seed")
    utils.clear_feature_props(child, "spawn")
    if seed is not None:
        child["dsm_spawn_seed"] = int(seed)
    return True


def apply_object(obj, context):
    scene = context.scene
    settings = scene.dsm_settings

    existing = _resolve_spawn_object(obj)
    if existing:
        obj = existing

    # Preserve the stable seed across re-apply.
    seed = obj.get("dsm_spawn_seed")

    from . import orbit, follow
    orbit.clear_object(obj, restore=True)
    follow.clear_object(obj, restore=True)
    clear_object(obj, restore=True)

    if seed is not None:
        obj["dsm_spawn_seed"] = int(seed)

    if utils.has_animation_path(obj, {"location"}):
        return False, "location already has animation or drivers", None

    original_hide_viewport = bool(obj.hide_viewport)
    original_hide_render = bool(obj.hide_render)

    rng = utils.seeded_rng(obj, "spawn")
    factor = utils.variation_factor(rng, settings.spawn_variation)
    distance = max(0.001, float(settings.spawn_distance))

    # Variation controls phase variation. Cameras always begin at the slider start.
    if obj.type == 'CAMERA':
        phase_distance = 0.0
    else:
        phase_distance = rng.uniform(0.0, distance) * float(settings.spawn_variation)

    control, original_parent, original_parent_type, original_parent_bone = _create_control(obj, context)

    obj["dsm_spawn_enabled"] = True
    obj["dsm_spawn_control_name"] = control.name
    obj["dsm_spawn_mode"] = settings.spawn_mode
    obj["dsm_spawn_axis"] = settings.spawn_axis
    obj["dsm_spawn_speed"] = float(settings.spawn_speed * factor)
    obj["dsm_spawn_distance"] = distance
    obj["dsm_spawn_phase_distance"] = float(phase_distance)
    obj["dsm_spawn_fade_in_point"] = float(settings.spawn_fade_in_point)
    obj["dsm_spawn_fade_out_point"] = float(settings.spawn_fade_out_point)
    obj["dsm_spawn_original_parent"] = original_parent.name if original_parent else ""
    obj["dsm_spawn_original_parent_type"] = original_parent_type
    obj["dsm_spawn_original_parent_bone"] = original_parent_bone
    obj["dsm_spawn_original_hide_viewport"] = original_hide_viewport
    obj["dsm_spawn_original_hide_render"] = original_hide_render

    if obj.type == 'CAMERA':
        focus = _create_camera_focus(obj, context, distance)
        obj["dsm_spawn_focus_name"] = focus.name

    return True, "", control


def update_object(obj, scene):
    if not obj.get("dsm_spawn_enabled", False):
        return

    distance = max(0.001, float(obj.get("dsm_spawn_distance", 10.0)))
    speed = float(obj.get("dsm_spawn_speed", 0.1))
    phase = float(obj.get("dsm_spawn_phase_distance", 0.0))
    travel = ((float(scene.frame_current) - float(scene.frame_start)) * speed) + phase
    mode = obj.get("dsm_spawn_mode", "SPAWN")

    fade_in = float(obj.get("dsm_spawn_fade_in_point", 0.15))
    fade_out = float(obj.get("dsm_spawn_fade_out_point", 0.85))

    if mode == 'LOOPER':
        wrapped = travel % (2.0 * distance)
        progress = wrapped / distance if wrapped <= distance else (2.0 * distance - wrapped) / distance
        offset = _ease_progress(progress, fade_in, fade_out) * distance
        hidden = False
    else:
        wrapped = travel % distance
        progress = wrapped / distance
        offset = _ease_progress(progress, fade_in, fade_out) * distance
        # Keep the reset invisible for the tiny discontinuity at the loop seam.
        hidden = progress >= 0.995

    obj.location = _axis_vector(obj.get("dsm_spawn_axis", "X")) * offset

    if mode == 'SPAWN':
        obj.hide_viewport = hidden
        obj.hide_render = hidden
    else:
        obj.hide_viewport = bool(obj.get("dsm_spawn_original_hide_viewport", False))
        obj.hide_render = bool(obj.get("dsm_spawn_original_hide_render", False))


def update_all(scene):
    for obj in bpy.data.objects:
        if obj.get("dsm_spawn_enabled", False):
            update_object(obj, scene)


class DSM_OT_spawn_apply(Operator):
    bl_idname = "dsm.spawn_apply"
    bl_label = "Apply Spawn / Looper"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = utils.selected_objects(context)
        if not selected:
            self.report({'WARNING'}, "Select one or more objects")
            return {'CANCELLED'}

        objects = []
        seen = set()
        for item in selected:
            obj = _resolve_spawn_object(item) or item
            if obj.name not in seen:
                seen.add(obj.name)
                objects.append(obj)

        controls = []
        skipped = []
        for obj in objects:
            ok, reason, control = apply_object(obj, context)
            if ok:
                controls.append(control)
            else:
                skipped.append(f"{obj.name}: {reason}")

        update_all(context.scene)

        if controls:
            try:
                bpy.ops.object.select_all(action='DESELECT')
                for control in controls:
                    control.select_set(True)
                context.view_layer.objects.active = controls[0]
            except Exception:
                pass

        if skipped:
            self.report({'WARNING'}, "; ".join(skipped[:3]))
        self.report({'INFO'}, f"{context.scene.dsm_settings.spawn_mode.title()} applied to {len(controls)} object(s)")
        return {'FINISHED'}


class DSM_OT_spawn_clear(Operator):
    bl_idname = "dsm.spawn_clear"
    bl_label = "Clear Spawn / Looper"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = utils.selected_objects(context)
        count = 0
        seen = set()
        for item in selected:
            obj = _resolve_spawn_object(item)
            if obj and obj.name not in seen:
                seen.add(obj.name)
                if clear_object(obj):
                    count += 1
        self.report({'INFO'}, f"Spawn / Looper cleared on {count} object(s)")
        return {'FINISHED'}


_CLASSES = (DSM_OT_spawn_apply, DSM_OT_spawn_clear)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
