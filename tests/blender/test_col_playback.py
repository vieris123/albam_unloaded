""".col groups follow a playing LMT's hitbox events without crashing: Blender 5.4 crashed during playback
(deg_check_base_in_depsgraph) when the frame-change handler called hide_set, so the handler queues the visibility
change for a timer. Nero's body + Collision\\pl000.col + the Snatch (pl000_02 slot 30), whose grab groups turn on at
frames 9 / 10 / 11 and off at 17."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import traceback
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.engines.mtfw import animation, col_shapes

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


common.skip_unless(os.path.join(common.NERO, r"Collision\pl000.col"), os.path.join(common.NERO, r"motion\pl000\pl000_02.lmt"))
scene = bpy.context.scene


def op_import(suffix):
    rfs = scene.albam.rfs
    rfs.file_list_selected_index = next(k for k, i in enumerate(rfs.file_list) if i.name.lower().endswith(suffix))
    return bpy.ops.albam.import_real()


try:
    scene.albam.rfs.add_root_folder("dmc4", common.NERO)
    check(op_import("model::game::pl000::pl000.mod") == {"FINISHED"}, "pl000.mod imports")
    check(op_import("collision::pl000.col") == {"FINISHED"}, "Collision\\pl000.col imports")
    arm = bpy.data.objects["pl000.mod"]
    scene.albam.import_options_lmt.armature = arm
    check(op_import("motion::pl000::pl000_02.lmt") == {"FINISHED"}, "pl000_02.lmt imports")
    lmt = scene.albam.lmt_groups.anim_group[-1]
    lmt.active_id = next(i for i, r in enumerate(lmt.actions) if animation.get_lmt_props(r.action).lmt_id == 30)
    root = next(o for o in bpy.data.objects if col_shapes.is_col_root(o))

    shown = {}
    for frame in range(25):
        scene.frame_set(frame)      # crashed here on 5.4 before
        check_queued = col_shapes._visibility_pending[0]
        col_shapes._visibility_timer()   # timers don't run headless; the frame handler queued it
        if frame == 0:
            check(check_queued, "the frame-change handler queues the visibility update")
        shown[frame] = {ob.name for ob in col_shapes.members(root) if not ob.hide_get()}
    grab = shown[11] - shown[8]
    check(len(grab) > 0 and shown[17] == shown[8], f"grab groups show on frames 9-11 ({len(grab)} objects) and "
          "hide again at 17")
    check(len(shown[9]) < len(shown[10]) < len(shown[11]), "they turn on one frame after another")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
