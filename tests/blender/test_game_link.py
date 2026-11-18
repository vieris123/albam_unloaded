"""Game link client (blender_ui/game_link.py, 2026-11-18): the client of dmc4_hook's debug server
(Vibed/GameMCP/tools.md), against a stand-in server on a free port, so the game needn't run:
- Connect: status polled from the worker thread, results handed back by the timer function, version asked once;
- the panel's rows (room, mission, frame, load);
- a load_gen change reaches the listeners (the sdl tools drop their sync state there);
- errors: data.code kept, JSON-RPC -32601 = no_method;
- a port without a server: "Game not answering", retried; Disconnect stops the thread;
- the panel draws in every state (stub layout).
If the real game answers on 13350 (debug_server_enabled), its status is read too; otherwise that part is skipped."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402
import json, socket, threading, time, traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.blender_ui import game_link

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


STATE = {"load_gen": 1, "frame": 100, "calls": []}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method = body.get("method")
        STATE["calls"].append(method)
        if method == "status":
            STATE["frame"] += 1
            reply = {"result": {"frame": STATE["frame"], "area": True, "load_gen": STATE["load_gen"],
                                "layers": {"game": "Game", "mission": "Mission20", "room": "Room 502"},
                                "room": 502, "stage": 502, "mission": 20, "players": 1, "paused": False,
                                "stepping": 0}}
        elif method == "version":
            reply = {"result": {"server": "stand-in", "phase": "S5", "built": "today", "tools": []}}
        elif method == "sdl_layout":
            reply = {"error": {"code": -32000, "message": "no rScheduler 'x'", "data": {"code": "not_loaded"}}}
        else:
            reply = {"error": {"code": -32601, "message": "no method '%s'" % method}}
        data = json.dumps(dict(reply, jsonrpc="2.0", id=body.get("id"))).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
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
    """Run the timer function (timers don't run in -b) until `until()` or the time is up."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        game_link._tick()
        if until():
            return True
        time.sleep(0.02)
    return until()


class Layout:
    def __init__(self):
        self.texts = []
    def label(self, text="", icon="NONE"):
        self.texts.append(text)
    def operator(self, idname, **kw):
        self.texts.append(idname)
    def prop(self, data, name, **kw):
        self.texts.append(name)
    def row(self, **_):
        return self
    def column(self, **_):
        return self
    def split(self, **_):
        return self


def draw():
    layout = Layout()
    game_link.ALBAM_PT_GameLink.draw(type("P", (), {"layout": layout})(), bpy.context)
    return layout.texts


try:
    port = free_port()
    server = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    texts = draw()
    check("albam.game_link_connect" in texts and "port" in texts, "panel before Connect: the button and the port")

    bpy.context.scene.albam.game_link.port = port
    bpy.ops.albam.game_link_connect()
    check(pump(lambda: game_link.connected() and game_link.LINK.version is not None),
          "Connect: status and version come back through the worker thread (%s)" % game_link.LINK.state)
    rows = dict(game_link.status_lines(game_link.LINK.status))
    check(rows.get("Room", "").startswith("502") and rows.get("Mission") == "20" and rows.get("Load") == "1",
          "status rows: %s" % rows)
    check(STATE["calls"].count("version") == 1, "version asked once per connection")
    texts = draw()
    check("Connected" in texts and any(t.startswith("Server S5") for t in texts), "panel connected: %s" % texts[:4])

    frame = STATE["frame"]
    pump(lambda: STATE["frame"] >= frame + 2, 3.0)
    check(STATE["frame"] >= frame + 2, "status keeps being polled (%d more)" % (STATE["frame"] - frame))

    seen = []
    game_link.LOAD_GEN_LISTENERS.append(lambda old, new: seen.append((old, new)))
    STATE["load_gen"] = 2
    pump(lambda: seen, 3.0)
    check(seen == [(1, 2)], "a load_gen change reaches the listeners: %s" % seen)
    game_link.LOAD_GEN_LISTENERS.clear()

    answers = []
    game_link.call("sdl_layout", {"path": "x"}, lambda r, e: answers.append(e))
    game_link.call("nosuch", None, lambda r, e: answers.append(e))
    pump(lambda: len(answers) == 2, 3.0)
    codes = [getattr(e, "code", None) for e in answers]
    check(codes == ["not_loaded", "no_method"], "errors keep their codes: %s" % codes)

    bpy.ops.albam.game_link_disconnect()
    check(game_link.LINK.client is None and game_link._tick() is None, "Disconnect: no client, the timer ends")
    server.shutdown()

    bpy.context.scene.albam.game_link.port = free_port()
    bpy.ops.albam.game_link_connect()
    check(pump(lambda: game_link.LINK.state == "unreachable", 6.0), "no server: %s" % game_link.LINK.state)
    texts = draw()
    check("Game not answering" in texts, "panel unreachable: %s" % texts[:3])
    bpy.ops.albam.game_link_disconnect()

    # the real game, if it's running with the debug server on
    try:
        live = game_link.rpc(game_link.DEFAULT_PORT, "status", timeout=1.0)
    except game_link.LinkError as e:
        print("SKIPPED: no game on %d (%s)" % (game_link.DEFAULT_PORT, e.code))
        live = None
    if live is not None:
        check(isinstance(live.get("frame"), int), "the real game's status: frame %s, room %s"
              % (live.get("frame"), live.get("room")))

except Exception:
    traceback.print_exc()
    failures.append("exception")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
