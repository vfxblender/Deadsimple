import bpy
from bpy.types import Operator
from mathutils import Matrix, Vector
from . import utils

MARKER = "dsm_rotate_marker"
CONTROL_PREFIX = "DSM_ROT_CTRL_"
LEGACY_HELPER_PREFIX = "DSM_ROT_"
LEGACY_ATTACH_CONSTRAINT = "DSM Rotate Attach"
LEGACY_SPIN_CONSTRAINT = "DSM Rotate Local Spin"


def _angle_expression(scene, speed, delay):
    start = int(scene.frame_start)
    if scene.dsm_settings.rotate_use_start:
        start = int(scene.dsm_settings.rotate_start)
    start += int(delay)

    end = int(scene.dsm_settings.rotate_end) if scene.dsm_settings.rotate_use_end else None
    if end is not None:
        if end < start:
            end = start
        elapsed = f"max(min(frame, {end}) - {start}, 0)"
    else:
        elapsed = f"max(frame - {start}, 0)"

    return f"({elapsed}) * ({speed:.10f}) * 0.02"


def _resolve_rotate_child(obj):
    if not obj:
        return None

    if obj.get("dsm_rotate_control", False):
        return bpy.data.objects.get(obj.get("dsm_rotate_child", ""))

    # 0.1.1 / 0.1.2 quaternion helper migration.
    if obj.get("dsm_rotate_helper_owner"):
        return bpy.data.objects.get(obj.get("dsm_rotate_helper_owner", ""))

    if obj.get("dsm_rotate_enabled", False):
        return obj

    return None


def _remove_constraint(obj, name):
    if not obj:
        return
    con = obj.constraints.get(name)
    if con:
        try:
            obj.constraints.remove(con)
        except Exception:
            pass


def _remove_legacy_helper(child):
    helper_name = child.get("dsm_rotate_helper", "")
    helper = bpy.data.objects.get(helper_name) if helper_name else None
    if helper:
        for index in range(4):
            utils.remove_owned_driver(helper, "rotation_quaternion", index, MARKER)
        try:
            bpy.data.objects.remove(helper, do_unlink=True)
        except Exception:
            pass


def _clear_legacy_rotate(child):
    _remove_constraint(child, LEGACY_ATTACH_CONSTRAINT)
    _remove_constraint(child, LEGACY_SPIN_CONSTRAINT)
    _remove_legacy_helper(child)

    axis = int(child.get("dsm_rotate_axis_index", 2))
    utils.remove_owned_driver(child, "delta_rotation_euler", axis, MARKER)
    if "dsm_rotate_base_delta" in child:
        try:
            child.delta_rotation_euler = child.get("dsm_rotate_base_delta", [0.0, 0.0, 0.0])
        except Exception:
            pass


def _control_matrix_from_world(world_matrix):
    location, rotation, _scale = world_matrix.decompose()
    return Matrix.LocRotScale(location, rotation, Vector((1.0, 1.0, 1.0)))


def _create_control(child, context, original_parent, original_parent_type, original_parent_bone):
    world = child.matrix_world.copy()
    control = bpy.data.objects.new(f"{CONTROL_PREFIX}{child.name}", None)
    control.empty_display_type = 'PLAIN_AXES'
    control.empty_display_size = 0.65
    control.show_in_front = True
    control.hide_render = True
    control["dsm_rotate_control"] = True
    control["dsm_rotate_child"] = child.name

    collection = child.users_collection[0] if child.users_collection else context.collection
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

    # The control represents placement/orientation only. Scale stays on child.
    control.matrix_world = _control_matrix_from_world(world)

    # Reparent the real object while preserving the exact visible transform.
    child.parent = control
    child.parent_type = 'OBJECT'
    child.parent_bone = ""
    child.matrix_parent_inverse = Matrix.Identity(4)
    child.matrix_world = world

    return control


def _spin_quaternion_expressions(base_q, axis, angle_expr):
    bw, bx, by, bz = [float(v) for v in base_q]
    c = f"cos((({angle_expr}) * 0.5))"
    s = f"sin((({angle_expr}) * 0.5))"

    if axis == 'X':
        return [
            f"({bw:.12f})*({c}) - ({bx:.12f})*({s})",
            f"({bw:.12f})*({s}) + ({bx:.12f})*({c})",
            f"({by:.12f})*({c}) + ({bz:.12f})*({s})",
            f"-({by:.12f})*({s}) + ({bz:.12f})*({c})",
        ]

    if axis == 'Y':
        return [
            f"({bw:.12f})*({c}) - ({by:.12f})*({s})",
            f"({bx:.12f})*({c}) - ({bz:.12f})*({s})",
            f"({bw:.12f})*({s}) + ({by:.12f})*({c})",
            f"({bx:.12f})*({s}) + ({bz:.12f})*({c})",
        ]

    return [
        f"({bw:.12f})*({c}) - ({bz:.12f})*({s})",
        f"({bx:.12f})*({c}) + ({by:.12f})*({s})",
        f"-({bx:.12f})*({s}) + ({by:.12f})*({c})",
        f"({bw:.12f})*({s}) + ({bz:.12f})*({c})",
    ]


def clear_object(obj, restore=True):
    child = _resolve_rotate_child(obj)
    if not child or not child.get("dsm_rotate_enabled", False):
        return False

    # Clean previous experimental implementations as well.
    _clear_legacy_rotate(child)

    control_name = child.get("dsm_rotate_control_name", "")
    control = bpy.data.objects.get(control_name) if control_name else None

    for index in range(4):
        utils.remove_owned_driver(child, "rotation_quaternion", index, MARKER)

    base_q = child.get("dsm_rotate_base_quaternion")
    if base_q:
        try:
            child.rotation_mode = 'QUATERNION'
            child.rotation_quaternion = tuple(float(v) for v in base_q)
        except Exception:
            pass

    try:
        bpy.context.view_layer.update()
    except Exception:
        pass

    # With spin removed, this is the artist-controlled, unspun world transform.
    world = child.matrix_world.copy()

    original_parent_name = child.get("dsm_rotate_original_parent", "")
    original_parent = bpy.data.objects.get(original_parent_name) if original_parent_name else None
    original_parent_type = child.get("dsm_rotate_original_parent_type", "OBJECT")
    original_parent_bone = child.get("dsm_rotate_original_parent_bone", "")
    original_rotation_mode = child.get("dsm_rotate_original_rotation_mode", "XYZ")

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

    try:
        child.rotation_mode = original_rotation_mode
    except Exception:
        pass

    if control:
        try:
            bpy.data.objects.remove(control, do_unlink=True)
        except Exception:
            pass

    marker_prop = f"{MARKER}_value"
    if marker_prop in child:
        try:
            del child[marker_prop]
        except Exception:
            pass

    utils.clear_feature_props(child, "rotate")
    return True


def apply_object(obj, context):
    # Reapplying from the control updates its child rather than rigging the Empty.
    existing_child = _resolve_rotate_child(obj)
    if existing_child:
        obj = existing_child
        clear_object(obj, restore=True)

    scene = context.scene
    settings = scene.dsm_settings

    # Dead Simple must never destroy an artist's existing rotation animation.
    if utils.has_animation_path(
        obj,
        {
            "rotation_euler",
            "rotation_quaternion",
            "rotation_axis_angle",
            "delta_rotation_euler",
            "delta_rotation_quaternion",
        },
    ):
        return False, "object already has rotation animation/drivers", None

    original_parent = obj.parent
    original_parent_name = original_parent.name if original_parent else ""
    original_parent_type = obj.parent_type if original_parent else "OBJECT"
    original_parent_bone = obj.parent_bone if original_parent and obj.parent_type == 'BONE' else ""
    original_rotation_mode = obj.rotation_mode

    rng = utils.seeded_rng(obj, "rotate")
    speed_factor = utils.variation_factor(rng, settings.rotate_variation)
    delay = rng.uniform(0.0, settings.rotate_variation * 12.0)
    speed = settings.rotate_speed * speed_factor
    angle_expr = _angle_expression(scene, speed, delay)

    control = _create_control(
        obj,
        context,
        original_parent,
        original_parent_type,
        original_parent_bone,
    )

    # Child is now underneath an aligned control, so its own rotation is the
    # true local spin layer. Quaternion multiplication keeps that spin local.
    obj.rotation_mode = 'QUATERNION'
    base_q = obj.rotation_quaternion.copy()
    expressions = _spin_quaternion_expressions(base_q, settings.rotate_axis, angle_expr)

    created = []
    for index, expression in enumerate(expressions):
        fc = utils.add_owned_driver(obj, "rotation_quaternion", index, expression, MARKER)
        if not fc:
            for made_index in created:
                utils.remove_owned_driver(obj, "rotation_quaternion", made_index, MARKER)
            try:
                bpy.data.objects.remove(control, do_unlink=True)
            except Exception:
                pass
            obj.parent = original_parent
            obj.rotation_mode = original_rotation_mode
            return False, "could not create quaternion rotate driver", None
        created.append(index)

    obj["dsm_rotate_enabled"] = True
    obj["dsm_rotate_control_name"] = control.name
    obj["dsm_rotate_base_quaternion"] = [float(v) for v in base_q]
    obj["dsm_rotate_axis"] = settings.rotate_axis
    obj["dsm_rotate_speed_factor"] = float(speed_factor)
    obj["dsm_rotate_delay"] = float(delay)
    obj["dsm_rotate_original_parent"] = original_parent_name
    obj["dsm_rotate_original_parent_type"] = original_parent_type
    obj["dsm_rotate_original_parent_bone"] = original_parent_bone
    obj["dsm_rotate_original_rotation_mode"] = original_rotation_mode

    try:
        obj.update_tag()
    except Exception:
        pass

    return True, "", control


class DSM_OT_rotate_apply(Operator):
    bl_idname = "dsm.rotate_apply"
    bl_label = "Apply Rotate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects = utils.selected_objects(context)
        if not objects:
            self.report({'WARNING'}, "Select one or more objects")
            return {'CANCELLED'}

        success = 0
        skipped = []
        controls = []

        # A selected rotate control stands in for its child.
        unique_objects = []
        seen = set()
        for obj in objects:
            child = _resolve_rotate_child(obj) or obj
            if child.name not in seen:
                seen.add(child.name)
                unique_objects.append(child)

        for obj in unique_objects:
            ok, reason, control = apply_object(obj, context)
            if ok:
                success += 1
                if control:
                    controls.append(control)
            else:
                skipped.append(f"{obj.name}: {reason}")

        # The control is intentionally what the artist manipulates after Apply.
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
        self.report({'INFO'}, f"Rotate applied to {success} object(s)")
        return {'FINISHED'}


class DSM_OT_rotate_clear(Operator):
    bl_idname = "dsm.rotate_clear"
    bl_label = "Clear Rotate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects = utils.selected_objects(context)
        count = 0
        seen = set()
        for obj in objects:
            child = _resolve_rotate_child(obj)
            if child and child.name not in seen:
                seen.add(child.name)
                if clear_object(child):
                    count += 1
        self.report({'INFO'}, f"Rotate cleared on {count} object(s)")
        return {'FINISHED'}


class DSM_OT_rotate_key_in(Operator):
    bl_idname = "dsm.rotate_key_in"
    bl_label = "Key In"
    bl_options = {'UNDO'}

    def execute(self, context):
        s = context.scene.dsm_settings
        s.rotate_use_start = True
        s.rotate_start = context.scene.frame_current
        return {'FINISHED'}


class DSM_OT_rotate_key_out(Operator):
    bl_idname = "dsm.rotate_key_out"
    bl_label = "Key Out"
    bl_options = {'UNDO'}

    def execute(self, context):
        s = context.scene.dsm_settings
        s.rotate_use_end = True
        s.rotate_end = context.scene.frame_current
        return {'FINISHED'}


class DSM_OT_rotate_clear_range(Operator):
    bl_idname = "dsm.rotate_clear_range"
    bl_label = "Clear Range"
    bl_options = {'UNDO'}

    def execute(self, context):
        s = context.scene.dsm_settings
        s.rotate_use_start = False
        s.rotate_use_end = False
        return {'FINISHED'}


_CLASSES = (
    DSM_OT_rotate_apply,
    DSM_OT_rotate_clear,
    DSM_OT_rotate_key_in,
    DSM_OT_rotate_key_out,
    DSM_OT_rotate_clear_range,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
