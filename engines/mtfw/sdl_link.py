"""Live `.sdl` edits and the scheduler clock over the game link (GameLink P2 / P3; protocol `Vibed\\GameMCP\\tools.md`,
owned by dmc4_hook's debug server; client `blender_ui/game_link.py`).

Live edits (Game Link panel > Live .sdl Edits): every imported `.sdl` (an `SDL_` root) whose game path the game has
loaded (`sdl_list`) is checked once against the game's layout (`sdl_layout` vs `sdl_live.layout` of the current
export; a different version of the file is never patched), then the game's copy takes Blender's values (every
timing / value array of the int / vector / float / bool tracks, `sdl_patch`). After that each edit (an object under
the root or its action changed: the depsgraph handler only marks the root, the timer does the rest) exports the
file in memory, diffs it against the bytes last synced and sends the differing runs. An edit that changes the file's
size or bytes outside those arrays (keys added or removed, new tracks, names, resources) isn't sent: the panel says
it needs export, deploy and a room reload. A new `load_gen` (the game loaded another room) drops all sync state.

Clock (Game Link panel > Clock, scene frame = scheduler frame): Follow Game polls `sdl_clock` and moves the playhead;
Drive Game pauses the scheduler and sets its frame to the playhead's (wrapped into a looping scheduler's length,
clamped otherwise), and lets it run again when turned off or the link closes.
"""
import time

import bpy
from bpy.app.handlers import persistent

from dmc4xml import sdl as sdl_codec

from albam.blender_ui import game_link
from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from . import sdl_live
from .scheduler import ROOT_PROP, build_sdl

LIST_EVERY = 1.0        # seconds between sdl_list calls
CLOCK_EVERY = 0.08      # seconds between clock calls
SETTLE = 0.15           # an edit is sent this long after the last change


class _Sync:
    def __init__(self):
        self.synced = None      # the bytes the game's image holds (as far as Albam knows)
        self.state = "waiting"
        self.message = ""
        self.pending = False
        self.dirty_at = None


SYNC = {}                       # SDL root name -> _Sync
FILES = {}                      # game path (lower case) -> sdl_list file entry
LIST = {"pending": False, "next": 0.0, "load_gen": None, "known": False}
CLOCK = {"pending": False, "next": 0.0, "mode": "OFF", "sent": None, "paused": None, "info": None, "message": ""}

STATE_TEXT = {
    "waiting": "waiting for the game",
    "not_loaded": "not loaded in the game",
    "checking": "checking...",
    "synced": "live",
    "sending": "sending...",
    "different": "a different file in the game",
    "needs_reload": "needs export + room reload",
    "error": "error",
}


def game_path(root):
    path = (root.albam_asset.relative_path or "").replace("/", "\\")
    if path.lower().endswith(".sdl"):
        path = path[:-4]
    return path


def sdl_roots(scene):
    return [ob for ob in scene.objects if ROOT_PROP in ob and ob.albam_asset.relative_path]


def root_bytes(root):
    sdl, _notes = build_sdl(root)
    return sdl_codec.write(sdl)


def _sync(root):
    s = SYNC.get(root.name)
    if s is None:
        s = SYNC[root.name] = _Sync()
    return s


def reset(*_args):
    """Forget everything synced (the game loaded another room, the link closed, the option was turned off)."""
    SYNC.clear()
    FILES.clear()
    LIST.update(pending=False, next=0.0, known=False)
    CLOCK.update(sent=None, info=None, message="")


def _changed():
    game_link.LINK.changed = True


# ---- sdl_list ----------------------------------------------------------------------------------------------------

def _on_list(result, error):
    LIST["pending"] = False
    LIST["next"] = time.monotonic() + LIST_EVERY
    if error is not None:
        CLOCK["message"] = str(error)
        _changed()
        return
    FILES.clear()
    for f in result.get("files") or []:
        FILES[str(f.get("path", "")).lower()] = f
    LIST["load_gen"] = result.get("load_gen")
    LIST["known"] = True
    _changed()


def file_of(root):
    return FILES.get(game_path(root).lower())


# ---- live edits --------------------------------------------------------------------------------------------------

def _fail(s, state, message):
    s.state, s.message, s.pending = state, message, False
    _changed()


def _check(root, s, f):
    """sdl_layout, then the first full push."""
    s.pending, s.state, s.message = True, "checking", ""
    name, path, gen = root.name, f["path"], LIST["load_gen"]

    def on_layout(result, error):
        root_now = bpy.data.objects.get(name)
        if root_now is None or SYNC.get(name) is not s:
            return
        if error is not None:
            return _fail(s, "not_loaded" if error.code == "not_loaded" else "error", str(error))
        try:
            data = root_bytes(root_now)
        except AlbamCheckFailure as e:
            return _fail(s, "error", "%s: %s" % (e, getattr(e, "details", "")))
        mine = sdl_live.layout(data)
        diffs = sdl_live.differences(mine, result)
        if diffs:
            return _fail(s, "different", "; ".join(diffs))
        runs = sdl_live.full_runs(data, sdl_live.ranges(mine))
        _send(s, path, gen, data, runs)

    game_link.call("sdl_layout", {"path": path}, on_layout)


def _send(s, path, gen, data, runs):
    if not runs:
        s.synced, s.state, s.pending = data, "synced", False
        _changed()
        return
    s.pending, s.state = True, "sending"
    params = {"path": path, "runs": [{"offset": o, "bytes": sdl_live.hex_bytes(b)} for o, b in runs]}
    if gen is not None:
        params["load_gen"] = gen

    def on_patch(result, error):
        if SYNC.get(_name_of(s)) is not s:
            return
        if error is None:
            s.synced, s.state, s.message, s.pending = data, "synced", "", False
            _changed()
            return
        if error.code in ("stale", "not_loaded"):
            s.synced = None
            return _fail(s, "waiting" if error.code == "stale" else "not_loaded", str(error))
        s.synced = None
        _fail(s, "error", "%s (run %s)" % (error, error.data.get("run")) if "run" in error.data else str(error))

    game_link.call("sdl_patch", params, on_patch)


def _name_of(s):
    for name, other in SYNC.items():
        if other is s:
            return name
    return None


def _send_edit(root, s, f):
    s.dirty_at = None
    try:
        data = root_bytes(root)
    except AlbamCheckFailure as e:
        return _fail(s, "error", "%s: %s" % (e, getattr(e, "details", "")))
    if data == s.synced:
        if s.state == "needs_reload":
            s.state, s.message = "synced", ""
            _changed()
        return
    if len(data) != len(s.synced):
        return _fail(s, "needs_reload", "the file's size changes (keys or tracks added or removed)")
    spans = sdl_live.ranges(sdl_live.layout(s.synced))
    runs, outside = sdl_live.diff_runs(s.synced, data, spans)
    if outside:
        return _fail(s, "needs_reload", "%d bytes change outside the key arrays (names, resources, track table)"
                     % outside)
    if s.state == "needs_reload":
        s.state, s.message = "synced", ""
    _send(s, f["path"], LIST["load_gen"], data, runs)


def _tick_live(scene, now):
    names = set()
    for root in sdl_roots(scene):
        names.add(root.name)
        s = _sync(root)
        if s.pending:
            continue
        f = file_of(root)
        if f is None:
            if LIST["known"] and s.state != "not_loaded":
                s.synced = None
                _fail(s, "not_loaded", "")
            continue
        if s.synced is None:
            if s.state in ("different", "error") and s.dirty_at is None:
                continue            # wait for an edit (or a new room) before asking again
            s.dirty_at = None
            _check(root, s, f)
        elif s.dirty_at is not None and now - s.dirty_at >= SETTLE:
            _send_edit(root, s, f)
    for name in [n for n in SYNC if n not in names]:
        del SYNC[name]


def mark_dirty(root_name):
    s = SYNC.get(root_name)
    if s is not None:
        s.dirty_at = time.monotonic()


def _root_of(ob):
    while ob is not None:
        if ROOT_PROP in ob:
            return ob
        ob = ob.parent
    return None


@persistent
def _on_depsgraph(scene, depsgraph):
    """Read-only: mark the SDL roots whose objects or actions changed; the timer sends the edit."""
    if not SYNC or game_link.LINK.state != "connected":
        return
    actions = None
    for update in depsgraph.updates:
        idb = getattr(update.id, "original", update.id)
        if isinstance(idb, bpy.types.Object):
            root = _root_of(idb)
            if root is not None:
                mark_dirty(root.name)
        elif isinstance(idb, bpy.types.Action):
            if actions is None:
                actions = {}
                for ob in scene.objects:
                    ad = ob.animation_data
                    if ad is not None and ad.action is not None:
                        root = _root_of(ob)
                        if root is not None:
                            actions.setdefault(ad.action.name, set()).add(root.name)
            for name in actions.get(idb.name, ()):
                mark_dirty(name)


# ---- clock -------------------------------------------------------------------------------------------------------

def _scheduler_of(root):
    f = file_of(root) if root is not None else None
    schedulers = (f or {}).get("schedulers") or []
    return schedulers[0] if schedulers else None


def _playing():
    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        if window.screen and window.screen.is_animation_playing:
            return True
    return False


def _on_clock(result, error):
    CLOCK["pending"] = False
    if error is not None:
        CLOCK["message"] = str(error)
        CLOCK["info"] = None
        _changed()
        return
    CLOCK["info"], CLOCK["message"] = result, ""
    if CLOCK["mode"] == "FOLLOW" and not _playing():
        scene = bpy.context.scene
        frame = int(result.get("frame", 0))
        if scene.frame_current != frame:
            scene.frame_current = frame
    _changed()


def game_frame(frame, info):
    """The scheduler frame for a playhead frame: wrapped into a looping scheduler, clamped into another."""
    length = int((info or {}).get("length") or 0)
    if length <= 0:
        return max(0, frame)
    if (info or {}).get("loop"):
        return frame % length
    return min(max(0, frame), length)


def _release():
    """Let a scheduler Drive Game paused run again."""
    if CLOCK["paused"] is not None:
        game_link.call("sdl_clock", {"id": CLOCK["paused"], "pause": False})
        CLOCK["paused"] = None
    CLOCK["sent"] = None


def _tick_clock(scene, settings, now):
    mode = settings.clock_mode
    sched = _scheduler_of(settings.clock_target)
    if mode != CLOCK["mode"] or (CLOCK["paused"] is not None and (sched is None or sched["id"] != CLOCK["paused"])):
        if CLOCK["mode"] == "DRIVE" or CLOCK["paused"] is not None:
            _release()
        CLOCK["mode"] = mode
        _changed()
    if mode == "OFF" or CLOCK["pending"] or now < CLOCK["next"]:
        return
    if sched is None:
        msg = "pick a scheduler" if settings.clock_target is None else "not playing in the game"
        if CLOCK["message"] != msg:
            CLOCK["message"], CLOCK["info"] = msg, None
            _changed()
        return
    CLOCK["next"] = now + CLOCK_EVERY
    if mode == "FOLLOW":
        CLOCK["pending"] = True
        game_link.call("sdl_clock", {"id": sched["id"]}, _on_clock)
        return
    frame = game_frame(scene.frame_current, CLOCK["info"] or sched)
    if CLOCK["paused"] != sched["id"]:
        CLOCK["pending"], CLOCK["paused"], CLOCK["sent"] = True, sched["id"], frame
        game_link.call("sdl_clock", {"id": sched["id"], "pause": True, "frame": frame}, _on_clock)
    elif frame != CLOCK["sent"]:
        CLOCK["pending"], CLOCK["sent"] = True, frame
        game_link.call("sdl_clock", {"id": sched["id"], "frame": frame}, _on_clock)


# ---- the tick ----------------------------------------------------------------------------------------------------

def tick():
    scene = bpy.context.scene
    settings = scene.albam.game_link
    if not settings.sdl_live and settings.clock_mode == "OFF" and CLOCK["mode"] == "OFF":
        if SYNC:
            reset()
        return
    now = time.monotonic()
    if not LIST["pending"] and now >= LIST["next"]:
        LIST["pending"] = True
        game_link.call("sdl_list", {}, _on_list)
    if settings.sdl_live:
        _tick_live(scene, now)
    elif SYNC:
        SYNC.clear()
        _changed()
    _tick_clock(scene, settings, now)


def _on_load_gen(old, new):
    reset()
    CLOCK["paused"] = None          # that scheduler is gone with the room


def _on_disconnect():
    _release()
    CLOCK["mode"] = "OFF"
    reset()


# ---- panel -------------------------------------------------------------------------------------------------------

@blender_registry.register_blender_type
class ALBAM_PT_GameLinkSdl(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_GameLinkSdl"
    bl_label = "Schedulers (.sdl)"
    bl_parent_id = "ALBAM_PT_GameLink"
    bl_region_type = "UI"
    bl_space_type = "VIEW_3D"

    @classmethod
    def poll(cls, context):
        return game_link.connected()

    def draw(self, context):
        layout = self.layout
        settings = context.scene.albam.game_link
        layout.prop(settings, "sdl_live")
        if settings.sdl_live:
            roots = sdl_roots(context.scene)
            col = layout.column(align=True)
            if not roots:
                col.label(text="No imported .sdl in this scene", icon="INFO")
            for root in roots:
                s = SYNC.get(root.name)
                state = s.state if s else "waiting"
                icon = {"synced": "CHECKMARK", "different": "ERROR", "needs_reload": "ERROR",
                        "error": "ERROR"}.get(state, "DOT")
                split = col.split(factor=0.45)
                split.label(text=root.name[4:] if root.name.startswith("SDL_") else root.name)
                split.label(text=STATE_TEXT.get(state, state), icon=icon)
                if s and s.message and state in ("different", "needs_reload", "error"):
                    col.label(text=s.message)
        box = layout.box()
        box.prop(settings, "clock_target")
        box.row().prop(settings, "clock_mode", expand=True)
        info = CLOCK["info"]
        if settings.clock_mode != "OFF":
            if info:
                box.label(text="Game frame %.1f of %s%s%s" % (info.get("frame", 0), info.get("length", "?"),
                                                             ", looping" if info.get("loop") else "",
                                                             ", paused" if info.get("pause") else ""))
            elif CLOCK["message"]:
                box.label(text=CLOCK["message"], icon="INFO")


def register_handlers():
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    for lst, fn in ((game_link.TICK_LISTENERS, tick), (game_link.LOAD_GEN_LISTENERS, _on_load_gen),
                    (game_link.DISCONNECT_LISTENERS, _on_disconnect)):
        if fn not in lst:
            lst.append(fn)


def unregister_handlers():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    for lst, fn in ((game_link.TICK_LISTENERS, tick), (game_link.LOAD_GEN_LISTENERS, _on_load_gen),
                    (game_link.DISCONNECT_LISTENERS, _on_disconnect)):
        if fn in lst:
            lst.remove(fn)
