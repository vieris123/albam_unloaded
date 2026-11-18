"""Albam <-> game link: the client of dmc4_hook's debug server.

The protocol belongs to the game side: `Vibed\\GameMCP\\tools.md` (HTTP JSON-RPC 2.0 on 127.0.0.1, POST /mcp, plain
calls `{"method": "<tool>", "params": {...}}`). Albam never blocks on it: calls go to one worker thread
(`Client`), their results come back on the main thread through a `bpy.app.timers` timer (`_tick`), never through
depsgraph or frame handlers (GameLink decision G6).

v1 (2026-11-18): connect / disconnect, a status poll (`status` every POLL seconds, `version` once per connection) and
the Game Link panel. The live `.sdl` tools (sdl_list / sdl_layout / sdl_patch / sdl_clock) come next, once the game
side has built them; `on_load_gen` is where their sync state is dropped when the game loads another room.
"""
import json
import queue
import threading
import time
import traceback
import urllib.error
import urllib.request

import bpy

from albam.registry import blender_registry

DEFAULT_PORT = 13350
POLL = 0.5            # seconds between status calls while connected
RETRY = 2.0           # seconds between tries while the game doesn't answer
TIMEOUT = 4.0         # per HTTP call; the game thread takes up to 3 s before it answers game_busy
TICK = 0.1            # the timer's period


class LinkError(Exception):
    """A call that failed. `code` is the server's stable code (`data.code`, tools.md), else one of ours:
    `unreachable` (no server on the port), `no_method` (JSON-RPC -32601), `protocol` (an answer we can't read)."""

    def __init__(self, message, code="failed", data=None):
        super().__init__(message)
        self.code = code
        self.data = data or {}


def rpc(port, method, params=None, timeout=TIMEOUT):
    """One plain call, blocking. The result, or LinkError."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    request = urllib.request.Request(
        "http://127.0.0.1:%d/mcp" % port, json.dumps(body).encode(),
        {"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        raise LinkError("HTTP %d from the game" % e.code, "protocol") from None
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise LinkError("no answer on port %d (%s)" % (port, reason), "unreachable") from None
    try:
        answer = json.loads(raw)
    except ValueError:
        raise LinkError("the game's answer isn't JSON", "protocol") from None
    if not isinstance(answer, dict):
        raise LinkError("unexpected answer", "protocol")
    error = answer.get("error")
    if error is not None:
        data = error.get("data") if isinstance(error.get("data"), dict) else {}
        code = data.get("code") or ("no_method" if error.get("code") == -32601 else "failed")
        raise LinkError(str(error.get("message", "error")), code, data)
    return answer.get("result")


class Client:
    """A worker thread that makes the calls one after another. `call` queues one; `poll` (main thread) runs the
    callbacks of the finished ones: callback(result, error), one of them None."""

    def __init__(self, port):
        self.port = port
        self._requests = queue.Queue()
        self._results = queue.Queue()
        self._stop = threading.Event()
        self._pending = 0
        self._thread = threading.Thread(target=self._run, name="albam-game-link", daemon=True)
        self._thread.start()

    def call(self, method, params=None, callback=None):
        self._pending += 1
        self._requests.put((method, params, callback))

    @property
    def pending(self):
        return self._pending

    def poll(self):
        while True:
            try:
                callback, result, error = self._results.get_nowait()
            except queue.Empty:
                return
            self._pending -= 1
            if callback is not None:
                callback(result, error)

    def stop(self):
        """Calls queued before this still go out (their callbacks don't run), then the thread ends."""
        self._stop.set()
        self._requests.put(None)

    def _run(self):
        while True:
            item = self._requests.get()
            if item is None:
                return
            method, params, callback = item
            try:
                result, error = rpc(self.port, method, params), None
            except LinkError as e:
                result, error = None, e
            except Exception as e:   # never let the thread die silently
                result, error = None, LinkError("%s: %s" % (type(e).__name__, e))
            self._results.put((callback, result, error))


# ---------------------------------------------------------------------------------------------------------------
# link state (runtime only: nothing of it is saved in the .blend)

class _Link:
    def __init__(self):
        self.client = None
        self.state = "off"          # off / connecting / connected / unreachable
        self.message = ""
        self.version = None         # the `version` result of this connection
        self.status = None          # the last `status` result
        self.load_gen = None
        self.next_status = 0.0
        self.status_pending = False
        self.changed = False


LINK = _Link()
LOAD_GEN_LISTENERS = []   # callables(old, new): the game loaded another room / area; drop what was synced to it
TICK_LISTENERS = []       # callables(): every timer tick while connected (main thread); queue calls from here
DISCONNECT_LISTENERS = [] # callables(): just before the link closes; calls queued here still go out


def connected():
    return LINK.state == "connected"


def call(method, params=None, callback=None):
    """Queue a call on the open link (callback(result, error) runs on the main thread). False if there's no link."""
    if LINK.client is None:
        return False
    LINK.client.call(method, params, callback)
    return True


def connect(port):
    disconnect()
    LINK.client = Client(port)
    LINK.state, LINK.message = "connecting", ""
    LINK.version = LINK.status = LINK.load_gen = None
    LINK.next_status = 0.0
    LINK.status_pending = False
    LINK.changed = True
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.0, persistent=True)


def disconnect():
    if LINK.client is not None:
        if LINK.state == "connected":
            for listener in list(DISCONNECT_LISTENERS):
                try:
                    listener()
                except Exception as e:
                    print("Albam game link: disconnect listener failed:", e)
        LINK.client.stop()
    LINK.client = None
    LINK.state, LINK.message = "off", ""
    LINK.status_pending = False
    LINK.changed = True


def _on_version(result, error):
    if error is None and isinstance(result, dict):
        LINK.version = result
        LINK.changed = True


def _on_status(result, error):
    LINK.status_pending = False
    now = time.monotonic()
    if error is not None:
        if error.code == "unreachable":
            LINK.state = "unreachable"
            LINK.status = LINK.version = None
            _set_load_gen(None)
        LINK.message = str(error)
        LINK.next_status = now + (RETRY if error.code == "unreachable" else POLL)
        LINK.changed = True
        return
    if LINK.state != "connected":
        LINK.state = "connected"
        call("version", None, _on_version)
    LINK.message = ""
    LINK.status = result if isinstance(result, dict) else {}
    _set_load_gen(LINK.status.get("load_gen"))
    LINK.next_status = now + POLL
    LINK.changed = True


def _set_load_gen(value):
    old = LINK.load_gen
    LINK.load_gen = value
    if old != value and old is not None:
        for listener in list(LOAD_GEN_LISTENERS):
            try:
                listener(old, value)
            except Exception as e:   # one listener's bug mustn't stop the link
                print("Albam game link: load_gen listener failed:", e)


def _tick():
    """bpy.app.timers: hand results back, keep the status poll going, redraw the panel when something changed."""
    client = LINK.client
    if client is None:
        _redraw()
        return None
    client.poll()
    if LINK.client is client and not LINK.status_pending and time.monotonic() >= LINK.next_status:
        LINK.status_pending = True
        client.call("status", None, _on_status)
    if LINK.client is client and LINK.state == "connected":
        for listener in list(TICK_LISTENERS):
            try:
                listener()
            except Exception as e:   # one feature's bug mustn't stop the link
                traceback.print_exc()
                LINK.message = "%s: %s" % (type(e).__name__, e)
                LINK.changed = True
    if LINK.changed:
        _redraw()
    return TICK


def _redraw():
    LINK.changed = False
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# ---------------------------------------------------------------------------------------------------------------
# Blender side

@blender_registry.register_blender_prop_albam(name="game_link")
class AlbamGameLinkSettings(bpy.types.PropertyGroup):
    port: bpy.props.IntProperty(
        name="Port", default=DEFAULT_PORT, min=1, max=65535,
        description="The port of dmc4_hook's debug server (dmc4_hook.cfg debug_server_port, 13350 unless changed). "
                    "Takes effect on the next Connect")
    sdl_live: bpy.props.BoolProperty(
        name="Live .sdl Edits", default=False,
        description="Send scheduler (.sdl) edits to the running game as you make them: key values and key timing of "
                    "int / float / bool / vector tracks, for every imported .sdl the game has loaded. When turned on, "
                    "the game's copy first takes Blender's values. Needs dmc4_hook's Dev tools (debug_server_dev_tools)")
    clock_target: bpy.props.PointerProperty(
        name="Scheduler", type=bpy.types.Object,
        poll=lambda self, ob: "sdl_root" in ob,
        description="The imported .sdl (its SDL_ root) whose clock the playhead follows or drives")
    clock_mode: bpy.props.EnumProperty(
        name="Clock", default="OFF",
        items=[("OFF", "Off", "The playhead and the game's scheduler run on their own"),
               ("FOLLOW", "Follow Game", "Blender's playhead follows the scheduler's frame in the game"),
               ("DRIVE", "Drive Game", "The scheduler in the game is paused and set to Blender's playhead; it runs "
                                       "on again when this is turned off or the link closes")],
        description="Tie Blender's playhead to the chosen scheduler's clock in the game (scene frame = scheduler "
                    "frame, 1/60 s)")


@blender_registry.register_blender_type
class ALBAM_OT_GameLinkConnect(bpy.types.Operator):
    """Connect to the running game through dmc4_hook's debug server (dmc4_hook.cfg: debug_server_enabled = true).
    Albam keeps asking every few seconds until the game answers"""
    bl_idname = "albam.game_link_connect"
    bl_label = "Connect to Game"

    def execute(self, context):
        connect(context.scene.albam.game_link.port)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_GameLinkDisconnect(bpy.types.Operator):
    """Stop talking to the game. Nothing in the game changes"""
    bl_idname = "albam.game_link_disconnect"
    bl_label = "Disconnect"

    def execute(self, context):
        disconnect()
        return {"FINISHED"}


STATE_TEXT = {
    "connecting": ("Connecting...", "SORTTIME"),
    "connected": ("Connected", "LINKED"),
    "unreachable": ("Game not answering", "UNLINKED"),
}


def status_lines(status):
    """(label, value) rows the panel shows for a `status` result."""
    rows = []
    layers = status.get("layers") or {}
    if status.get("room") is not None:
        rows.append(("Room", "%s (stage %s)" % (status["room"], status.get("stage", "?"))
                     + (", custom" if status.get("custom_room") else "")))
    elif layers.get("room"):
        rows.append(("Room layer", str(layers["room"])))
    if status.get("mission") is not None:
        rows.append(("Mission", str(status["mission"])))
    if not status.get("area"):
        rows.append(("Area", "none (title / loading)"))
    rows.append(("Frame", str(status.get("frame", "?"))
                 + ("  (paused)" if status.get("paused") else "")
                 + ("  (stepping %s)" % status["stepping"] if status.get("stepping") else "")))
    if status.get("players") is not None:
        rows.append(("Players", str(status["players"])))
    if status.get("load_gen") is not None:
        rows.append(("Load", str(status["load_gen"])))
    return rows


@blender_registry.register_blender_type
class ALBAM_PT_GameLink(bpy.types.Panel):
    bl_category = "Albam [Beta]"
    bl_idname = "ALBAM_PT_GameLink"
    bl_label = "Game Link"
    bl_region_type = "UI"
    bl_space_type = "VIEW_3D"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.albam.game_link
        if LINK.client is None:
            row = layout.row(align=True)
            row.operator("albam.game_link_connect", icon="LINKED")
            row.prop(settings, "port", text="")
            layout.label(text="Needs dmc4_hook's debug server on", icon="INFO")
            return
        text, icon = STATE_TEXT.get(LINK.state, (LINK.state, "QUESTION"))
        row = layout.row(align=True)
        row.label(text=text, icon=icon)
        row.operator("albam.game_link_disconnect", text="", icon="X")
        if LINK.state == "unreachable":
            col = layout.column(align=True)
            col.label(text="Is the game running with debug_server_enabled = true")
            col.label(text="in dmc4_hook.cfg, on port %d?" % LINK.client.port)
            return
        if LINK.message:
            layout.label(text=LINK.message, icon="ERROR")
        if LINK.status:
            col = layout.column(align=True)
            for label, value in status_lines(LINK.status):
                split = col.split(factor=0.35)
                split.label(text=label)
                split.label(text=value)
        if LINK.version:
            layout.label(text="Server %s, built %s" % (LINK.version.get("phase", "?"), LINK.version.get("built", "?")))


def unregister_link():
    disconnect()
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
