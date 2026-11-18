"""Live .sdl edits and the scheduler clock over the game link (engines/mtfw/sdl_link.py + sdl_live.py, 2026-11-18),
against a stand-in debug server that holds st405 blade01.sdl's image like the game (Vibed/GameMCP/tools.md):
- sdl_live.layout matches the game's numbers for blade01 (38 tracks, mAngle values at 992, 48 bytes, size 2078);
- Live .sdl Edits: the layout is checked, then the game's copy takes Blender's values (a value the game had
  differently is overwritten);
- an edited mAngle key reaches the image through the depsgraph handler; only mAngle's value bytes change;
- an edit that changes the size (a new key) isn't sent ("needs export + room reload"); undoing it is live again;
- a new load_gen re-checks and pushes again; a different file in the game (another track count) is never patched;
- Clock: Follow Game moves the playhead to the scheduler's frame; Drive Game pauses it and sets the frame
  (wrapped into the 60-frame loop); Off and Disconnect let it run again."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402
import json, socket, threading, time, traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.blender_ui import game_link
from albam.engines.mtfw import scheduler, sdl_link, sdl_live
from albam.lib import blender_compat as compat

REL = r"scr\st405\data\blade01.sdl"
PATH = os.path.join(common.ARCTOOL, "st405", REL)
common.skip_unless(PATH)
SOURCE = open(PATH, "rb").read()
GAME_PATH = r"scr\st405\data\blade01"

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


GAME = {"image": bytearray(SOURCE), "load_gen": 1, "patches": 0, "sched": {"id": "0x1000", "frame": 0.0, "prev": 0.0,
        "length": 60, "loop": 1, "pause": 0, "speed": 1.0}, "layout_override": None, "clock_sets": []}
LOCK = threading.Lock()


def answer(method, p):
    if method == "status":
        return {"frame": 1, "area": True, "load_gen": GAME["load_gen"], "players": 1, "room": 405, "stage": 405}
    if method == "version":
        return {"server": "stand-in", "phase": "S5", "built": "today", "tools": []}
    if method == "sdl_list":
        return {"load_gen": GAME["load_gen"], "files": [{"path": GAME_PATH, "rsrc": "0x2000", "size": len(GAME["image"]),
                                                          "schedulers": [dict(GAME["sched"], frames_since_move=0)]}]}
    if method == "sdl_layout":
        if p.get("path", "").lower() != GAME_PATH.lower():
            raise LookupError("not_loaded")
        lay = GAME["layout_override"] or sdl_live.layout(GAME["image"])
        return dict(lay, path=GAME_PATH, load_gen=GAME["load_gen"])
    if method == "sdl_patch":
        if p.get("load_gen") is not None and p["load_gen"] != GAME["load_gen"]:
            raise LookupError("stale")
        spans = sdl_live.ranges(sdl_live.layout(GAME["image"]))
        runs = [(int(r["offset"]), bytes.fromhex(r["bytes"])) for r in p["runs"]]
        for i, (o, b) in enumerate(runs):
            if not any(s <= o and o + len(b) <= e for s, e, _t, _w in spans):
                raise LookupError("outside_value_array", i)
        for o, b in runs:
            GAME["image"][o:o + len(b)] = b
        GAME["patches"] += 1
        return {"applied": len(runs), "schedulers_rekeyed": 1}
    if method == "sdl_clock":
        s = GAME["sched"]
        if p.get("id") != s["id"]:
            raise LookupError("not_found")
        if "frame" in p or "pause" in p:
            GAME["clock_sets"].append(dict(p))
        if "frame" in p:
            s["frame"], s["prev"] = float(p["frame"]), -1.0
        if "pause" in p:
            s["pause"] = int(bool(p["pause"]))
        return {k: s[k] for k in ("id", "frame", "prev", "length", "loop", "pause", "speed")}
    raise KeyError(method)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with LOCK:
            try:
                reply = {"result": answer(body.get("method"), body.get("params") or {})}
            except LookupError as e:
                data = {"code": e.args[0]}
                if len(e.args) > 1:
                    data["run"] = e.args[1]
                reply = {"error": {"code": -32000, "message": e.args[0], "data": data}}
            except KeyError as e:
                reply = {"error": {"code": -32601, "message": "no method %s" % e}}
        data = json.dumps(dict(reply, jsonrpc="2.0", id=body.get("id"))).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def pump(until, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        game_link._tick()
        if until():
            return True
        time.sleep(0.02)
    return until()


def state():
    s = sdl_link.SYNC.get(root.name)
    return s.state if s else None


def edited():
    """Run the depsgraph so the handler sees the change (as Blender does after an edit)."""
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()


try:
    lay = sdl_live.layout(SOURCE)
    angle = lay["tracks"][4]
    check(lay["track_count"] == 38 and lay["size"] == 2078 and angle["name"] == "mAngle"
          and angle["data_offset"] == 992 and angle["keys"] == 3,
          "layout as the game reports it: 38 tracks, size 2078, mAngle values at 992 (3 keys)")

    asset = SimpleNamespace(app_id="dmc4", relative_path=REL, extension="sdl")
    root = scheduler.build_sdl_objects(SOURCE, "blade01", asset, bpy.context)
    check(sdl_link.game_path(root) == GAME_PATH, "game path %s" % sdl_link.game_path(root))
    # the game holds another value in mAngle's last key (a file deployed before), and Live overwrites it
    GAME["image"][1030] ^= 0x40

    port = free_port()
    server = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    settings = bpy.context.scene.albam.game_link
    settings.port = port
    bpy.ops.albam.game_link_connect()
    check(pump(game_link.connected), "connected")
    settings.sdl_live = True
    check(pump(lambda: state() == "synced"), "Live .sdl Edits: blade01 is live (%s)" % state())
    check(bytes(GAME["image"]) == SOURCE, "the game's copy took Blender's values (the stray value overwritten)")

    unit = next(o for o in bpy.data.objects if o.get("sdl_track") and json.loads(o["sdl_track"])["name"] == "blade01")
    fc = next(c for c in compat.fcurves_of(unit.animation_data.action, unit)
              if c.data_path == '["mAngle"]' and c.array_index == 1)
    fc.keyframe_points[1].co.y += 1.0
    fc.update()
    edited()
    before = GAME["patches"]
    check(pump(lambda: GAME["patches"] > before), "an edited mAngle key is sent")
    changed = [i for i in range(len(SOURCE)) if GAME["image"][i] != SOURCE[i]]
    check(changed and 992 <= changed[0] and changed[-1] < 1040,
          "only mAngle's value bytes changed (%s..%s)" % (changed[:1], changed[-1:]))
    data = sdl_link.root_bytes(root)
    check(bytes(GAME["image"]) == data, "the game's copy equals the export")

    # a new key changes the size: not sent
    fc.keyframe_points.insert(45, 0.5)
    fc.update()
    edited()
    patches = GAME["patches"]
    check(pump(lambda: state() == "needs_reload", 3.0), "a new key: %s" % state())
    check(GAME["patches"] == patches and bytes(GAME["image"]) == data, "nothing sent for it")
    fc.keyframe_points.remove(next(k for k in fc.keyframe_points if abs(k.co.x - 45) < 1e-3))
    fc.update()
    edited()
    check(pump(lambda: state() == "synced", 3.0), "the key removed again: live (%s)" % state())

    # another room loaded (the same file again): checked and pushed again
    GAME["image"] = bytearray(SOURCE)
    GAME["load_gen"] = 2
    check(pump(lambda: state() == "synced" and bytes(GAME["image"]) == data, 5.0),
          "new load_gen: pushed again (%s)" % state())

    # a different version of the file in the game: never patched
    other = sdl_live.layout(SOURCE)
    other["track_count"] = 39
    GAME["layout_override"] = other
    GAME["image"] = bytearray(SOURCE)
    GAME["load_gen"] = 3
    check(pump(lambda: state() == "different", 5.0), "a different file in the game: %s (%s)"
          % (state(), sdl_link.SYNC[root.name].message))
    check(bytes(GAME["image"]) == SOURCE, "nothing patched into it")
    GAME["layout_override"] = None

    # clock
    settings.clock_target = root
    GAME["sched"]["frame"] = 30.0
    settings.clock_mode = "FOLLOW"
    check(pump(lambda: bpy.context.scene.frame_current == 30, 3.0),
          "Follow Game: playhead at the scheduler's frame (%d)" % bpy.context.scene.frame_current)
    settings.clock_mode = "DRIVE"
    bpy.context.scene.frame_current = 75
    check(pump(lambda: GAME["sched"]["pause"] == 1 and GAME["sched"]["frame"] == 15.0, 3.0),
          "Drive Game: paused, frame 75 wrapped to %s" % GAME["sched"]["frame"])
    bpy.context.scene.frame_current = 20
    check(pump(lambda: GAME["sched"]["frame"] == 20.0, 3.0), "Drive Game follows the playhead")
    settings.clock_mode = "OFF"
    check(pump(lambda: GAME["sched"]["pause"] == 0, 3.0), "Off: the scheduler runs again")
    settings.clock_mode = "DRIVE"
    check(pump(lambda: GAME["sched"]["pause"] == 1, 3.0), "Drive again: paused")
    bpy.ops.albam.game_link_disconnect()
    time.sleep(0.5)
    check(GAME["sched"]["pause"] == 0, "Disconnect lets it run again")
    server.shutdown()

    # the panel draws
    class Layout:
        def __getattr__(self, name):
            return lambda *a, **k: self
    sdl_link.ALBAM_PT_GameLinkSdl.draw(type("P", (), {"layout": Layout()})(), bpy.context)
    check(True, "panel draws")

except Exception:
    traceback.print_exc()
    failures.append("exception")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
