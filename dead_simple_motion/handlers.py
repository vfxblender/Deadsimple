import bpy
from bpy.app.handlers import persistent

_UPDATING = False


@persistent
def dsm_update_handler(scene, depsgraph=None):
    global _UPDATING
    if _UPDATING:
        return
    _UPDATING = True
    try:
        from . import orbit, spawn, follow
        orbit.update_all(scene)
        spawn.update_all(scene)
        follow.update_all(scene)
    finally:
        _UPDATING = False


def ensure_handlers():
    if dsm_update_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(dsm_update_handler)
    if dsm_update_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(dsm_update_handler)


def remove_handlers():
    for collection in (bpy.app.handlers.frame_change_post, bpy.app.handlers.depsgraph_update_post):
        while dsm_update_handler in collection:
            collection.remove(dsm_update_handler)
