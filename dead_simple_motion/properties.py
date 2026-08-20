import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


def _preset_update(self, context):
    try:
        from . import fx
        fx.apply_preset_to_settings(self)
    except Exception:
        pass


class DSM_Settings(PropertyGroup):
    tool: EnumProperty(
        name="Tool",
        items=[
            ('ROTATE', "Rotate", "Spin selected objects"),
            ('ORBIT', "Orbit", "Orbit around an object, bone, or 3D cursor"),
            ('SPAWN', "Spawn", "Spawn traffic or loop motion"),
            ('FOLLOW', "Follow", "Smooth live location follow"),
            ('FX', "FX", "Layered organic motion"),
        ],
        default='ROTATE',
    )

    rotate_axis: EnumProperty(name="Axis", items=[('X', 'X', ''), ('Y', 'Y', ''), ('Z', 'Z', '')], default='Z')
    rotate_speed: FloatProperty(name="Speed", default=1.0, min=-20.0, max=20.0)
    rotate_variation: FloatProperty(name="Variation", default=0.08, min=0.0, max=0.5, subtype='PERCENTAGE')
    rotate_target: PointerProperty(name="Target", type=bpy.types.Object)
    rotate_bone: StringProperty(name="Bone", default="")
    rotate_use_start: BoolProperty(name="Use Key In", default=False)
    rotate_use_end: BoolProperty(name="Use Key Out", default=False)
    rotate_start: IntProperty(name="Key In", default=1)
    rotate_end: IntProperty(name="Key Out", default=250)

    orbit_target: PointerProperty(name="Target", type=bpy.types.Object)
    orbit_bone: StringProperty(name="Bone", default="")
    orbit_plane: EnumProperty(name="Plane", items=[('XY', 'XY', ''), ('XZ', 'XZ', ''), ('YZ', 'YZ', '')], default='XY')
    orbit_shape: EnumProperty(name="Shape", items=[('CIRCLE', 'Circle', ''), ('ELLIPSE', 'Ellipse', ''), ('INFINITY', 'Infinity', ''), ('SQUARE', 'Square', ''), ('SPHERE', 'Sphere', '')], default='CIRCLE')
    orbit_behavior: EnumProperty(name="Behavior", items=[('NORMAL', 'Normal', 'Preserve current placement'), ('OFFSET', 'Offset', 'Evenly distribute selection'), ('RANDOM', 'Random', 'Randomize starting phase')], default='NORMAL')
    orbit_speed: FloatProperty(name="Speed", default=1.0, min=-20.0, max=20.0)
    orbit_variation: FloatProperty(name="Variation", default=0.08, min=0.0, max=0.5, subtype='PERCENTAGE')
    orbit_fallback_radius: FloatProperty(name="Radius", default=2.0, min=0.001)

    fx_preset: EnumProperty(name="Preset", items=[('SCIFI_DRONE', 'Sci-Fi Drone', ''), ('SPACE_DEBRIS', 'Space Debris', ''), ('ENGINE', 'Engine Vibration', ''), ('BREATHING', 'Breathing', ''), ('MAGIC_HOVER', 'Magic Hover', ''), ('ALAKAZAM', 'Alakazam!', '')], default='SCIFI_DRONE', update=_preset_update)
    fx_amount: FloatProperty(name="Amount", default=1.0, min=0.0, max=10.0)
    fx_speed: FloatProperty(name="Speed", default=1.0, min=0.0, max=20.0)
    fx_variation: FloatProperty(name="Variation", default=0.12, min=0.0, max=0.5, subtype='PERCENTAGE')
    fx_advanced: BoolProperty(name="Advanced", default=False)
    fx_float: FloatProperty(name="Float", default=0.35, min=0.0, max=10.0)
    fx_wobble: FloatProperty(name="Wobble", default=0.08, min=0.0, max=3.14159)
    fx_scale: FloatProperty(name="Scale Pulse", default=0.03, min=0.0, max=1.0)
    fx_bob: FloatProperty(name="Bob", default=0.15, min=0.0, max=10.0)
    fx_bob_axis: EnumProperty(name="Bob Axis", items=[('X', 'X', ''), ('Y', 'Y', ''), ('Z', 'Z', '')], default='Z')
    fx_shake: FloatProperty(name="Shake", default=0.02, min=0.0, max=5.0)
    fx_shake_speed: FloatProperty(name="Shake Speed", default=8.0, min=0.0, max=50.0)

    spawn_mode: EnumProperty(name="Mode", items=[('SPAWN', 'Spawn', 'Travel, hide/reset, and respawn'), ('LOOPER', 'Looper', 'Travel back and forth')], default='SPAWN')
    spawn_axis: EnumProperty(name="Axis", items=[('X', 'X', ''), ('Y', 'Y', ''), ('Z', 'Z', '')], default='X')
    spawn_speed: FloatProperty(name="Speed", default=0.1, min=-100.0, max=100.0)
    spawn_distance: FloatProperty(name="Distance", default=10.0, min=0.001)
    spawn_variation: FloatProperty(name="Variation", default=0.12, min=0.0, max=0.5, subtype='PERCENTAGE')

    follow_target: PointerProperty(name="Target", type=bpy.types.Object)
    follow_bone: StringProperty(name="Bone", default="")
    follow_smoothness: FloatProperty(name="Smoothness", default=0.55, min=0.0, max=1.0)
    follow_drift: FloatProperty(name="Drift", default=0.12, min=0.0, max=10.0)
    follow_variation: FloatProperty(name="Variation", default=0.08, min=0.0, max=0.5, subtype='PERCENTAGE')


_CLASSES = (DSM_Settings,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.dsm_settings = PointerProperty(type=DSM_Settings)


def unregister():
    if hasattr(bpy.types.Scene, "dsm_settings"):
        del bpy.types.Scene.dsm_settings
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
