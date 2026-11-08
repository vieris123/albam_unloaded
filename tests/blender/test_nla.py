"""LMT animations in NLA strips reach the previews that read events (2026-11-04): lib/nla maps scene frames to action
frames as Blender does (checked against Blender's own evaluation: offset, scale, repeat, reverse, holds, blend in),
lists what plays on top (active action, tracks top down, mute, solo, tweak mode), the .col groups follow a Snatch that
plays only from a strip, the foot IK ghost mirrors the NLA (also built in tweak mode) and its fade reads the strip's
events, and the chain preview's cache key changes with the NLA. Nero's body + Collision\\pl000.col + pl000_02.lmt."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import traceback
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.engines.mtfw import animation, col_shapes, cns_chain_preview
from albam.blender_ui import foot_ik
from albam.lib import blender_compat as compat
from albam.lib import nla

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


def pose(ob):
    return [p.matrix.copy() for p in ob.pose.bones if not p.name.startswith(foot_ik.PREFIX)]


def differ(a, b):
    return max(max(abs(x - y) for ra, rb in zip(m, n) for x, y in zip(ra, rb)) for m, n in zip(a, b))


def names(f):
    return [(x[0].name[-4:], round(x[1], 2)) for x in nla.playing(arm, f)]


def at(frame):
    whole = int(frame // 1)
    scene.frame_set(whole, subframe=frame - whole)


def pose_of_action(arm, action, frame):
    """the pose `action` gives as the active action alone at action frame `frame`"""
    ad = arm.animation_data
    keep = ad.use_nla
    ad.use_nla = False
    compat.assign_action(arm, action)
    at(frame)
    out = pose(arm)
    compat.assign_action(arm, None)
    ad.use_nla = keep
    return out


try:
    scene.albam.rfs.add_root_folder("dmc4", common.NERO)
    check(op_import("model::game::pl000::pl000.mod") == {"FINISHED"}, "pl000.mod imports")
    check(op_import("collision::pl000.col") == {"FINISHED"}, "Collision\\pl000.col imports")
    arm = bpy.data.objects["pl000.mod"]
    scene.albam.import_options_lmt.armature = arm
    check(op_import("motion::pl000::pl000_02.lmt") == {"FINISHED"}, "pl000_02.lmt imports")
    lmt = scene.albam.lmt_groups.anim_group[-1]
    actions = {animation.get_lmt_props(r.action).lmt_id: r.action for r in lmt.actions if r.action}
    snatch = actions[30]
    others = [a for k, a in sorted(actions.items()) if k != 30]
    ad = arm.animation_data
    compat.assign_action(arm, None)

    # -- time mapping against Blender's own evaluation ------------------------------------------------------------
    track = ad.nla_tracks.new()
    a, b = others[0], others[1]
    s1 = track.strips.new("a", 20, a)
    s1.scale, s1.repeat = 2.0, 2.0
    s2 = track.strips.new("b", int(s1.frame_end) + 15, b)
    s2.use_reverse = True
    s2.extrapolation = "HOLD_FORWARD"
    s1.blend_in = 4.0
    worst = 0.0
    frames = [10, 20, 21.5, 22, 33, 47.25, s1.frame_end - 1, s1.frame_end, s1.frame_end + 7, s2.frame_start + 3.5,
              s2.frame_end, s2.frame_end + 30]
    for f in frames:
        playing = nla.playing(arm, f)
        at(f)
        blender = pose(arm)
        if not playing:
            continue
        action, af = playing[0]
        if action == a and f < s1.frame_start + s1.blend_in:
            continue        # blending in from the rest pose: not one action alone
        worst = max(worst, differ(blender, pose_of_action(arm, action, af)))
    check(worst < 1e-4, f"strip_frame matches Blender's evaluation (offset, scale, repeat, reverse, holds; "
          f"worst {worst:.2e})")
    check(nla.playing(arm, 20) == [], "a strip's first frame of blend in plays nothing (influence 0)")
    s1.blend_in = 0.0
    s1.extrapolation = "HOLD_FORWARD"
    check(nla.playing(arm, 5) == [], "nothing before a first strip that doesn't hold (HOLD on the first strip only)")
    s1.extrapolation = "HOLD"
    check([x[0] for x in nla.playing(arm, 5)] == [a], f"a first strip set to Hold plays before it {names(5)}")
    s1.extrapolation = "HOLD_FORWARD"

    # -- what plays on top ------------------------------------------------------------------------------------------
    below = nla.track_strip(track, 110)[0].action      # the lower track holds a strip there
    top = ad.nla_tracks.new()
    top.strips.new("snatch", 100, snatch)
    check([x[0] for x in nla.playing(arm, 110)] == [snatch, below],
          f"the top track first, then the tracks below {names(110)}")
    top.mute = True
    check([x[0] for x in nla.playing(arm, 110)] == [below], f"a muted track plays nothing {names(110)}")
    top.mute = False
    track.is_solo = True
    check([x[0] for x in nla.playing(arm, 110)] == [below], f"a solo track plays alone {names(110)}")
    track.is_solo = False
    mine = bpy.data.actions.new("not_an_lmt")
    compat.fcurve_new(mine, 'pose.bones["0"].location', 0, "0", owner=arm).keyframe_points.insert(0, 0.0)
    compat.assign_action(arm, mine)
    check([x[0] for x in nla.playing(arm, 110)] == [mine, snatch, below],
          f"the active action on top of the NLA {names(110)}")
    check(animation.playing_lmt(arm, 110) == (snatch, 10.0), "playing_lmt skips an action that isn't an LMT's")
    compat.assign_action(arm, None)

    # -- .col groups follow the Snatch from its strip ---------------------------------------------------------------
    root = next(o for o in bpy.data.objects if col_shapes.is_col_root(o))
    shown = {}
    for f in (108, 111, 117):
        scene.frame_set(f)
        col_shapes._visibility_timer()
        shown[f] = {ob.name for ob in col_shapes.members(root) if not ob.hide_get()}
    check(len(shown[111] - shown[108]) > 0 and shown[117] == shown[108],
          "grab groups show on the Snatch's frames 9-11 played from a strip at 100, and hide again at 17")

    # -- foot IK: the ghost mirrors the NLA, the fade reads the strip ---------------------------------------------
    ground = bpy.data.objects.new("ground", bpy.data.meshes.new("ground"))
    ground.data.from_pydata([(-50, -50, -5), (50, -50, -5), (50, 50, -5), (-50, 50, -5)], [], [(0, 1, 2, 3)])
    scene.collection.objects.link(ground)       # out of the ray window: the IK leaves the legs where they are
    foot_ik.build_rig(arm, ground)
    ghost = foot_ik.get_ghost(arm)
    check(ghost.animation_data.action is None and len(ghost.animation_data.nla_tracks) == 2,
          f"the ghost gets the armature's NLA ({len(ghost.animation_data.nla_tracks)} tracks)")
    scene.frame_set(60)
    check(differ(pose(ghost), pose(arm)) < 1e-4, "and poses like the armature (legs out of reach of the ground)")
    check(op_import("motion::pl000::pl000_01.lmt") == {"FINISHED"}, "pl000_01.lmt imports (foot IK events)")
    compat.assign_action(arm, None)
    flagged = next(((animation.get_lmt_props(r.action).lmt_id, r.action) for r in scene.albam.lmt_groups.anim_group[-1].actions
                    if r.action and any(e.right_foot_ik for e in animation.get_lmt_props(r.action).event_markers)), None)
    if flagged is not None:
        top.strips.new("ik", 300, flagged[1])
        foot_ik.update_rig(scene, arm)
        check(foot_ik._mirror_pending[0], "an NLA change queues a re-mirror")
        foot_ik._mirror_timer()
        check(len(ghost.animation_data.nla_tracks[-1].strips) == 2, "which copies the new strip")
        frame = 300 + 40
        want = foot_ik.foot_ik_weights(flagged[1], 40.0, scene.albam.foot_ik_preview.blend_speed)
        scene.frame_current = frame
        check(foot_ik.current_weights(scene, arm) == want, f"the IK fade reads the strip's events in its own time "
              f"(slot {flagged[0]}: {want})")
    else:
        check(False, "an animation of pl000_02 with right-foot IK events")

    # tweak mode: the ghost follows, and a rebuild leaves the tweak alone
    ad.nla_tracks.active = track
    track.select = True
    for s in track.strips:
        s.select = s == s1
    ad.use_tweak_mode = True
    check(ad.use_tweak_mode and ad.action == a and [x[0] for x in nla.playing(arm, 40)] == [a],
          f"the tweaked strip's action plays alone: its track and the ones above are off {names(40)}")
    foot_ik._mirror_timer()
    check(ghost.animation_data.use_tweak_mode and ghost.animation_data.action == a,
          f"the ghost tweaks the same strip ({ghost.animation_data.use_tweak_mode}, {ghost.animation_data.action})")
    foot_ik.build_rig(arm, ground)
    check(ad.use_tweak_mode and ad.action == a, f"building the rig in tweak mode keeps the tweak ({ad.use_tweak_mode}, "
          f"{ad.action})")
    ghost = foot_ik.get_ghost(arm)
    scene.frame_set(40)
    check(differ(pose(ghost), pose(arm)) < 1e-4, "and the rebuilt ghost poses like the armature")
    ad.use_tweak_mode = False
    foot_ik.remove_rig(arm)

    # -- the chain preview's cache follows the NLA --------------------------------------------------------------
    before = cns_chain_preview._animation_key(arm)
    top.mute = True
    check(cns_chain_preview._animation_key(arm) != before, "muting a track changes the chain cache key")
    top.mute = False
    check(cns_chain_preview._animation_key(arm) == before, "and unmuting it gives the same key back")
    s1.select = not s1.select
    check(cns_chain_preview._animation_key(arm) == before, "selecting a strip doesn't")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)
sys.exit(1 if failures else 0)
