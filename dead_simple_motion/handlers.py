import bpy
from bpy.app.handlers import persistent

_UPDATING = False


def _run_updates(scene, source, updated_ids=None):
    global _UPDATING
    if _UPDATING:
        return
    _UPDATING = True
    try:
        from . import follow, orbit, spawn

        orbit.update_all(scene, updated_ids=updated_ids)
        spawn.update_all(scene, updated_ids=updated_ids)
        follow.update_all(scene, source=source, updated_ids=updated_ids)
    finally:
        _UPDATING = False


@persistent
def dsm_frame_change_handler(scene, depsgraph=None):
    _run_updates(scene, "FRAME")


@persistent
def dsm_depsgraph_handler(scene, depsgraph=None):
    if depsgraph is None:
        return

    updated_ids = set()
    try:
        for update in depsgraph.updates:
            item = getattr(update, "id", None)
            name = getattr(item, "name", None)
            if name:
                updated_ids.add(name)
    except Exception:
        return

    if updated_ids:
        _run_updates(scene, "DEPSGRAPH", updated_ids=updated_ids)


@persistent
def dsm_render_pre_handler(scene):
    _run_updates(scene, "RENDER")


def _is_dsm_handler(fn):
    name = getattr(fn, "__name__", "")
    module = getattr(fn, "__module__", "")
    return name in {
        "dsm_update_handler",
        "dsm_frame_change_handler",
        "dsm_depsgraph_handler",
        "dsm_render_pre_handler",
    } and (module.endswith(".handlers") or module == __name__)


def _remove_stale(collection):
    for fn in list(collection):
        if _is_dsm_handler(fn):
            try:
                collection.remove(fn)
            except Exception:
                pass


def ensure_handlers():
    # Remove stale function objects left by module reloads, then install one
    # canonical handler per event type.
    _remove_stale(bpy.app.handlers.frame_change_post)
    _remove_stale(bpy.app.handlers.depsgraph_update_post)
    _remove_stale(bpy.app.handlers.render_pre)

    bpy.app.handlers.frame_change_post.append(dsm_frame_change_handler)
    bpy.app.handlers.depsgraph_update_post.append(dsm_depsgraph_handler)
    bpy.app.handlers.render_pre.append(dsm_render_pre_handler)


def remove_handlers():
    _remove_stale(bpy.app.handlers.frame_change_post)
    _remove_stale(bpy.app.handlers.depsgraph_update_post)
    _remove_stale(bpy.app.handlers.render_pre)
