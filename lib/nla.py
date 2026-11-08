"""The NLA as Blender evaluates it, for the previews that read an object's animation themselves (2026-11-04).

The .col groups following LMT events and the foot IK fade read the events of the animation playing on an armature,
and the foot IK ghost has to play exactly what the armature plays. Reading only `animation_data.action` missed
animations that live in NLA strips. `playing` lists the actions animating an object at a frame with the action frame
each one is at (Blender's strip time mapping: scale, repeat, reverse, hold, animated strip time), `state` is a value
that changes with any of it (cache keys), `mirror` copies it to another object and `paused` switches it off for a
while (foot IK calibration).

Followed from Blender's anim_sys / nla code (nlastrips_ctime_get_strip, nlastrip_get_frame_actionclip,
nlastrip_get_influence): a muted track or strip plays nothing, a solo track plays alone, while a strip is tweaked its
track and the ones above are off (Tab, lower stack: the full-stack flag isn't in the Python API) and the tweaked action
plays in the strip's time. Transition and meta strips are skipped.
"""
import contextlib
import math

from albam.lib import blender_compat as compat

EPS = 1e-6


def _value(strip, prop, frame):
    """a strip's influence / strip_time at a scene frame: its F-curve when animated, else the stored value"""
    fc = strip.fcurves.find(prop)
    return fc.evaluate(frame) if fc is not None else getattr(strip, prop)


def strip_frame(strip, frame):
    """the action frame a clip strip plays at scene frame `frame` (within the strip; holds pass its start / end)"""
    start, end = strip.action_frame_start, strip.action_frame_end
    length = (end - start) or 1.0
    if strip.use_animated_time:
        t = _value(strip, "strip_time", frame)
        if strip.use_animated_time_cyclic:
            t = start + math.fmod(t - start, length) + (length if t < start else 0.0)
        return t
    scale = abs(strip.scale) or 1.0
    whole = abs(strip.repeat - math.floor(strip.repeat)) < EPS
    at_end = abs(frame - strip.frame_end) < EPS and whole
    offset = math.fmod(frame - strip.frame_start, length * scale) / scale
    if strip.use_reverse:
        return start if at_end else end - offset
    return end if at_end else start + offset


def strip_influence(strip, frame):
    """how much a strip counts at scene frame `frame`: its animated influence, else its blend in / out ramp"""
    if strip.use_animated_influence:
        return _value(strip, "influence", frame)
    blend_in, blend_out = abs(strip.blend_in), abs(strip.blend_out)
    if blend_in > EPS and frame <= strip.frame_start + blend_in:
        return abs(frame - strip.frame_start) / blend_in
    if blend_out > EPS and frame >= strip.frame_end - blend_out:
        return abs(strip.frame_end - frame) / blend_out
    return 1.0


def track_strip(track, frame):
    """(strip, scene frame it's evaluated at) for what a track plays at `frame`, holds included, or None"""
    strips = list(track.strips)
    found, at = None, frame
    for i, strip in enumerate(strips):
        if strip.frame_start - EPS <= frame <= strip.frame_end + EPS:
            found = strip
            break
        if frame < strip.frame_start:
            if i == 0:
                found = strip if strip.extrapolation == "HOLD" else None
                at = strip.frame_start
            else:
                previous = strips[i - 1]
                found = previous if previous.extrapolation != "NOTHING" else None
                at = previous.frame_end
            break
        if i == len(strips) - 1:
            found = strip if strip.extrapolation != "NOTHING" else None
            at = strip.frame_end
    if found is None or found.mute or found.type != "CLIP" or found.action is None:
        return None
    return found, at


def tweaked(ad):
    """(track, strip) being tweaked, or None. Entering tweak mode from Python doesn't mark the strip active, so
    without that flag it's the active track's selected strip playing the tweaked action (or the first one)"""
    if not ad.use_tweak_mode:
        return None
    track = next((t for t in ad.nla_tracks if t.active), None)
    if track is None:
        return None
    strips = list(track.strips)
    strip = next((s for s in strips if s.active), None) \
        or next((s for s in strips if s.select and s.action == ad.action), None) \
        or next((s for s in strips if s.action == ad.action), None)
    return track, strip


def _evaluated_tracks(ad):
    """the tracks Blender evaluates, top first"""
    if not ad.use_nla:
        return []
    tracks = list(ad.nla_tracks)
    if ad.use_tweak_mode:
        active = next((i for i, t in enumerate(tracks) if t.active), None)
        if active is not None:
            tracks = tracks[:active]
    if any(t.is_solo for t in tracks):
        tracks = [t for t in tracks if t.is_solo]
    return [t for t in reversed(tracks) if not t.mute]


def _active_plays(ad):
    if ad.action is None or ad.action_influence <= EPS:
        return False
    return compat.LEGACY_ACTIONS or getattr(ad, "action_slot", None) is not None


def playing(ob, frame):
    """[(action, action frame)] animating `ob` at scene frame `frame`, the one on top first: the active action (or
    the strip being tweaked, in that strip's time), then the strip of each evaluated track from the top down.
    Strips at zero influence (the first frame of a blend in) are left out."""
    ad = ob.animation_data
    if ad is None:
        return []
    out = []
    if _active_plays(ad):
        at = ad.nla_tweak_strip_time_to_scene(frame, invert=True) if ad.use_tweak_mode else frame
        out.append((ad.action, at))
    for track in _evaluated_tracks(ad):
        found = track_strip(track, frame)
        if found is None:
            continue
        strip, at = found
        if strip_influence(strip, at) > EPS:
            out.append((strip.action, strip_frame(strip, at)))
    return out


# not `influence` / `strip_time`: playback writes their animated values back every frame (the F-curves count instead)
_STRIP_PROPS = ("frame_start", "frame_end", "action_frame_start", "action_frame_end", "scale", "repeat", "blend_type",
                "extrapolation", "blend_in", "blend_out", "use_auto_blend", "use_reverse", "mute",
                "use_animated_influence", "use_animated_time", "use_animated_time_cyclic", "type")


def _strip_key(strip):
    return (strip.action.as_pointer() if strip.action else 0,
            getattr(strip.action_slot, "identifier", "") if hasattr(strip, "action_slot") else "",
            tuple(getattr(strip, p) for p in _STRIP_PROPS),
            tuple((fc.data_path, tuple(tuple(k.co) for k in fc.keyframe_points)) for fc in strip.fcurves))


def state(ob):
    """a value that changes when what animates `ob` changes: the active action and its settings, tweak mode (with the
    tweaked track), every evaluated track's strips (cache keys; muted tracks are read for their flag only)"""
    ad = ob.animation_data
    if ad is None:
        return None
    parts = [ad.action.as_pointer() if ad.action else 0, ad.action_blend_type, round(ad.action_influence, 6),
             ad.action_extrapolation, ad.use_nla, ad.use_tweak_mode,
             getattr(ad.action_slot, "identifier", "") if hasattr(ad, "action_slot") else ""]
    tracks = _evaluated_tracks(ad)
    if ad.use_tweak_mode:
        tracks += [t for t in ad.nla_tracks if t.active]
    for track in tracks:
        parts.append(tuple(_strip_key(strip) for strip in track.strips))
    return repr(parts)


def _copy_fcurve(src_strip, dst_strip, prop):
    src = src_strip.fcurves.find(prop)
    dst = dst_strip.fcurves.find(prop)
    if src is None or dst is None:
        return
    dst.keyframe_points.clear()
    dst.keyframe_points.add(len(src.keyframe_points))
    for a, b in zip(src.keyframe_points, dst.keyframe_points):
        b.co, b.interpolation = a.co, a.interpolation
        b.handle_left_type, b.handle_right_type = a.handle_left_type, a.handle_right_type
        b.handle_left, b.handle_right = a.handle_left, a.handle_right
    dst.update()


def _copy_strip(src, track):
    """a copy of clip strip `src` on `track` (None when Blender refuses it)"""
    try:
        new = track.strips.new(src.name, int(math.floor(src.frame_start)), src.action)
    except RuntimeError:
        return None
    if hasattr(src, "action_slot") and src.action_slot is not None and new.action_slot != src.action_slot:
        new.action_slot = src.action_slot
    new.use_sync_length = False
    if src.action_frame_start > new.action_frame_end:
        new.action_frame_end = src.action_frame_end
        new.action_frame_start = src.action_frame_start
    else:
        new.action_frame_start = src.action_frame_start
        new.action_frame_end = src.action_frame_end
    new.scale = src.scale
    new.repeat = src.repeat
    new.frame_start_ui = src.frame_start
    if abs(new.frame_end - src.frame_end) > EPS:
        new.frame_end_raw = src.frame_end
    for prop in ("blend_type", "extrapolation", "use_auto_blend", "blend_in", "blend_out", "use_reverse",
                 "influence", "strip_time"):
        setattr(new, prop, getattr(src, prop))
    for flag, prop in (("use_animated_influence", "influence"), ("use_animated_time", "strip_time")):
        if getattr(src, flag):
            setattr(new, flag, True)
            _copy_fcurve(src, new, prop)
    new.use_animated_time_cyclic = src.use_animated_time_cyclic
    return new


def mirror(src, dst):
    """give `dst` what animates `src`: its active action (slot, blend, influence, extrapolation), the tracks Blender
    evaluates and tweak mode. dst's own tracks are replaced. For the foot IK ghost, which shares src's armature data
    and has to pose like it."""
    sad = src.animation_data
    dad = dst.animation_data or dst.animation_data_create()
    if dad.use_tweak_mode:
        dad.use_tweak_mode = False
    for track in list(dad.nla_tracks):
        dad.nla_tracks.remove(track)
    if sad is None:
        compat.assign_action(dst, None)
        return
    tweak = tweaked(sad)
    compat.assign_action(dst, None if tweak else sad.action)
    if not tweak and sad.action is not None and hasattr(sad, "action_slot") and dad.action_slot != sad.action_slot:
        dad.action_slot = sad.action_slot
    dad.action_blend_type = sad.action_blend_type
    dad.action_influence = sad.action_influence
    dad.action_extrapolation = sad.action_extrapolation
    dad.use_nla = sad.use_nla
    tracks = list(sad.nla_tracks)
    solo = any(t.is_solo for t in tracks)
    target = None
    for track in tracks:
        is_tweaked = tweak is not None and track == tweak[0]
        if not is_tweaked and (track.mute or (solo and not track.is_solo)):
            continue
        new = dad.nla_tracks.new()
        new.name, new.mute = track.name, track.mute or (solo and not track.is_solo)
        for strip in track.strips:
            if strip.type != "CLIP" or strip.action is None:
                continue
            copy = _copy_strip(strip, new)
            if copy is not None and is_tweaked and strip == tweak[1]:
                target = (new, copy)
    if target is not None:
        _tweak(dad, *target)


def _tweak(ad, track, strip):
    """enter tweak mode on `strip` (Blender takes the active track's active or selected strip)"""
    ad.nla_tracks.active = track
    track.select = True
    if strip is not None:
        for other in track.strips:
            other.select = other == strip
    ad.use_tweak_mode = True


@contextlib.contextmanager
def paused(ob):
    """`ob` without its animation for a while (no action, NLA off, out of tweak mode), restored after"""
    ad = ob.animation_data
    if ad is None:
        yield
        return
    was_tweaked = tweaked(ad)
    if ad.use_tweak_mode:
        ad.use_tweak_mode = False
    action = ad.action
    slot = getattr(ad, "action_slot", None)
    use_nla = ad.use_nla
    compat.assign_action(ob, None)
    ad.use_nla = False
    try:
        yield
    finally:
        ad.use_nla = use_nla
        compat.assign_action(ob, action)
        if action is not None and slot is not None and ad.action_slot != slot:
            ad.action_slot = slot
        if was_tweaked is not None:
            _tweak(ad, *was_tweaked)
