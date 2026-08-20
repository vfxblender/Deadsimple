bl_info = {
    "name": "Dead Simple Motion",
    "author": "VFXBlender",
    "version": (0, 3, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Dead Simple",
    "description": "Quick motion setup: Rotate, Orbit, Spawn/Looper, Follow, and FX",
    "category": "Animation",
}

if "properties" in locals():
    import importlib

    for _module in (properties, rotate, orbit, fx, spawn, follow, handlers, ui):
        importlib.reload(_module)
else:
    from . import properties, rotate, orbit, fx, spawn, follow, handlers, ui

_MODULES = (properties, rotate, orbit, fx, spawn, follow, ui)


def register():
    for module in _MODULES:
        module.register()
    handlers.ensure_handlers()


def unregister():
    handlers.remove_handlers()
    for module in reversed(_MODULES):
        module.unregister()
