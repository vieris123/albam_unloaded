"""Approximate particle simulation of one EFL record, ported from the DX9 runtime (efl_import_plan.md M2).

Pure Python. Positions are in the generator's local frame at spawn, game units (cm, Y-up), one step per game
frame (60 fps). Whether particles then follow the generator or stay in the world is `emission_space(record)`.
Sources (DX9):
    emission   uknGenBehaviorFunc1 0x9DDCB0: wait WaitFrame; then bursts of LoopNum frames, each spawning
               SetNum (0xA8, or its keyframe 0x1D0) particles per frame; pause SetFrame frames; BurstNum (0xAC)
               bursts, 0 = forever
    spawn      sub_999040 (RangeType shapes on Range[3]), scaled by UknRangeThing[1..3]; with RangeStripPath, placed
               on the .efs strip by serial / RangeDivideNum (sub_99B270: vertex for type 0, else segment + t)
    collision  moveParticlePosCollision 0x99A210, against a ground plane (the stage collision isn't available):
               bounce = reflect * |d| * BounceRate while bounces remain, then CollType 0 kill / 1 stop / 2 continue
    direction  calcDir 0x9DEC60: axis (move RotAxisType) rotated by move Rot (RotOrder), blended toward the spawn
               offset for RangeDirType diffuse/converge by UknRangeThing[0]
    motion     moveParticleMoveAdd/Mul: pos += vel - (0, fall, 0); Add: speed += Acceleration, fall += Gravity;
               Mul: speed *= SpeedCoef. Move keyframes (Rot, Speed, FallSpeed) replace those per frame.
    space      moveParticleMoveNone 0x995E60 re-places None particles from the current generator matrix (follow);
               Add/Mul integrate in world space; MoveOptionFlag 8 (ALWAYS_CORRECT) with the generator's 0x4000
               flag adds the generator's translation delta every frame (moveParticleMoveVel 0x99BEA0)
    life       initParticleLifeFrame 0x9729B0 / moveParticleLifeFrame 0x998C30: Appear / Keep / Vanish frames, each
               s + rand % (r + 1); alpha ramps in, holds, ramps out; HoldUntilEffectEnds holds Keep until released
    flipbook   sub_961DB0: pattern += PatSpeed per frame when AnimFlag MOVE; LOOP wraps, FINISH kills, else holds;
               sequence = SeqNoMin + rand % (SeqNoRange + 1); a PatNo keyframe gives the pattern (or the speed when
               DrawFlags_0x41 bit 0 is set); AnimFlag 0x400 / 0x800 flip each particle's U / V with probability
               1/2 (getAnimFlag 0x980140)
    paths      move types 3-6 (initParticleMovePath* 0x9739D0.., moveParticleMovePath* 0x996D60..): the particle
               rides a path in generator space (it follows the generator) until its release timer runs out, then
               continues as an Add particle in world space. 5 PathKeyframe: keyframed offset; 6 PathLine:
               distance along the rotated axis, clamped to PathLength; 3 PathStrip: distance along an .efs curve;
               4 PathChain: approximated as PathLine without a clamp (the game uses a trailing rope)
    lines      Polyline (1) / Line (4): LineOfsNum points per particle by LineType (move sub_98E3E0): FOLLOW = the
               particle's last N positions, FIX_END = that trail pulled toward the spawn point (t^2), LENGTH = a
               rigid stick along the rotated axis, FIX = points stored in the file, CHAIN = approximated as FOLLOW.
               Width HeadSize -> PlaceSize and colour -> PlaceColor along the strip (calc_color_gradient 0x9B52A0).
               CHAIN uses the rope below. Texline (3) uses the same points.
    cloth      ClothPolyline/Texline/Line (12-14) always run as cloth, by ClothType: 0 CHAIN = a rope from the
               particle (P0) to the tail P1 = generator . SubOfs under a constant pull (dir . Acceleration), with
               rest shape + PreUpdateLoopNum steps at spawn, ConstOff end release and keyframed / distance-driven
               length; 1 CURVE = P0 -> P1 bent by CurveCoef (sine or two Hermite halves); 2 ZIGZAG = the curve plus
               random per-vertex jitter. World-fixed pulls (OptionFlag 1/2) use the world axes measured at import
    rope       moveChain 0x994C20 / initChain 0x984350: per-node velocity, one root-to-tip pass per frame with an
               exact segment-length constraint fed back into velocity; pull = Acceleration along calcDir(Rot), blended
               toward BlendRot by BlendRate; FrameInf damps, VertexInf springs. CHAIN trails root at the particle;
               PathChain (move 4) particles ride a generator-owned rope by distance (calcParticleMovePathChainPos)
    model      Model (5): one mesh per particle, the first with idx_group == PartsNoMin + rand % (PartsNoRange+1),
               advanced by AnimSpeed when ModelAnimFlag & 1; ModelScale/Rot (+Add or keyframes) as PrimModel
    light      Light (10): AttenuateStart/End (+Add per frame) x scale; colour x intensity; linear falloff
    strip      PolygonStrip (15, sword trail): the last LineOfsNum edge pairs P +/- axis*Width (pivot WidthPlaceRate),
               axis rotated by Rot(+RotAdd) and scaled by the particle scale (buildPolygonStripEdgeVert 0x98D240)
    keyframes  efl/keyframe.py; per-particle random rates drawn at spawn; a keyed value is absolute (its *Add is
               ignored); InitOnly keys are evaluated once at spawn and the *Add field applies after that
    shape      Polygon (2): Width / Height half-extents (+Add, or keyframes clamped >= 0; <= 0 kills when not keyed);
               PrimModel (6): Radius0/1, Height0/1 (+Add, or keyframes), rebuilt per frame in the game (sub_990310)
    uv scroll  Model (5) with ModelAnimFlag 0x10: offset += ScrollU/V (or their keyframes) per frame, wrapped to [-1, 1]
    range key  generator 0x1D4 keyframe: replaces Range (s and r) at spawn with the generator timer (sub_999640)
    rope keys  EFL_PARAM_CHAIN Length (total), Rot / BlendRot (direction recomputed per frame), BlendRate keyframes;
               PathChain ropes use the generator timer, CHAIN trails the particle timer (moveChain 0x994C20)
    colour     rgb * Intensity (clamped 0..127) as in the XfPrim vertex shader
Not modelled: collision with real stage geometry, the game's RNG table, LoopFrameDist/SetFrameDist fractional
spreading, external wind on ropes and cloth, rope and cloth response to emitter motion (they live in generator space),
world-fixed rope pulls (ChainOptionFlag 1/2), hermite/spline .efs interpolation (linear here), the keyed spawn path's
skipped burst smear, Polygon DivideNum strips (same look), the ZIGZAG ease-in weight (0x100).
"""
from __future__ import annotations

import math
import random
import struct
from dataclasses import dataclass, field

from . import keyframe as kfm
from .efs import Polyline
from .schema import bgra_to_rgba

ANIM_MOVE, ANIM_LOOP, ANIM_REVERSE, ANIM_FINISH = 1, 2, 4, 8
NO_LIFE_FRAMES = 120          # records without a life block: show particles this long
MAX_PARTICLES = 4000          # per record, to keep previews responsive
INTENSITY_MAX = 127.0         # initParticleBillboard / the shader clamp intensity to [0, 127]
REFRACT_FLAG = 0x10           # ParticleOptionFlag: refraction (initGeneratorParam 0x96B612 -> prim ATTR_REFRACT)
OCCLUSION_FLAG = 0x2          # CullingFlag OCCLUSION, checked first (0x96B603), so it disables refraction


COLOR_BLEND_BITS = ((2, 0x1), (1, 0x2), (0, 0x4), (3, 0x8))   # (BGRA byte, nEffect::COLOR_FLAG bit), the game's order
COLOR_EACH_RANDOM = 0x10


CULL_PER_PARTICLE, CULL_ANGLE = 0x4, 0x80          # culling block CullingFlag (rEffectList::CULLING_FLAG)
CULL_BOTH_DIR, CULL_ANGLE_RANGE, CULL_OVERLAP = 0x1, 0x800, 0x1000   # CullingOptionFlag (CULLING_OPTION_FLAG)
CULL_DIST, CULL_NEAR_CLIP, CULL_FAR_CLIP = 0x2000, 0x4000, 0x8000


def culling_params(block):
    """The culling block of a particle block, for culling_fade, or None (CullingFlag bit 0 off / no block)."""
    if block is None or not block.has("CullingFlag") or not block.get("CullingFlag") & 1:
        return None
    sub = next((s for s in block.subblocks() if s.kind == "culling"), None)
    if sub is None:
        return None
    f = sub.fields()
    word = f["CullingFlags"]
    direction = rotate(_AXES.get(word >> 8 & 0xF, (0, 0, 1)), f["CullingRot"], word >> 12 & 0xF)
    return {"flags": word & 0xFF, "option": word >> 16 & 0xFFFF, "dir": list(direction),
            "near": [f["CullingDistNearStart"], f["CullingDistNearEnd"]],
            "far": [f["CullingDistFarStart"], f["CullingDistFarEnd"]],
            "angle": [f["CullingAngleStart"], f["CullingAngleEnd"]], "rate": f["CullingRate"]}


def _angle_fade(c, cosine):
    a = math.acos(min(max(cosine, -1.0), 1.0))
    start, end = c["angle"]
    if c["option"] & CULL_ANGLE_RANGE:
        if start >= a:
            return 1.0
        return 1.0 - (a - start) / c["rate"] if a < end and c["rate"] else 0.0
    return 1.0 - a / end if end > a else 0.0


def culling_fade(c, to_camera, direction):
    """uEffectVFR::calc_culling_fade 0x963BD0: alpha factor from the distance to the camera and the angle between
    the culling direction and the way to the camera. to_camera = camera - position (game cm), direction = the
    culling direction (calcDir(CullingRot) turned into world space)."""
    d = math.sqrt(sum(v * v for v in to_camera))
    fade = 1.0
    if c["option"] & CULL_DIST:
        (near_start, near_end), (far_start, far_end) = c["near"], c["far"]
        if near_start >= d or d >= far_end:
            return 0.0
        if d < near_end:
            if c["option"] & CULL_NEAR_CLIP:
                return 0.0
            fade = (d - near_start) / (near_end - near_start)
        elif d > far_start:
            if c["option"] & CULL_FAR_CLIP:
                return 0.0
            fade = 1.0 - (d - far_start) / (far_end - far_start)
    if c["flags"] & CULL_ANGLE:
        v = tuple(x / d for x in to_camera) if d >= 1.1920929e-07 else tuple(to_camera)
        cosine = sum(a * b for a, b in zip(direction, v))
        angle = _angle_fade(c, cosine)
        if c["option"] & CULL_BOTH_DIR:
            other = _angle_fade(c, -cosine)
            angle = min(angle, other) if c["option"] & CULL_OVERLAP else max(angle, other)
        fade *= angle
    return fade


def _random_flips(anim_flag, rng):
    """uEffectVFR::getAnimFlag 0x980140: VFLIP_RAND (0x800) then HFLIP_RAND (0x400) each add their flip with
    probability 1/2. Returns only the flips the record's AnimFlag doesn't already have."""
    flip = 0
    if anim_flag & 0x800 and rng.random() < 0.5:
        flip |= 0x200
    if anim_flag & 0x400 and rng.random() < 0.5:
        flip |= 0x100
    return flip & ~anim_flag


def _src_color(ptcl, rng):
    """A particle's start colour, BGRA bytes (uEffectVFR::calcSrcColor 0x9801B0): Color0, with each channel whose
    COLOR_FLAG blend bit (R 0x1, G 0x2, B 0x4, A 0x8) is set mixed toward Color1 by one random t, re-rolled after
    every channel with EACH_RANDOM (0x10). CHOICE (0x20) isn't handled by DX9."""
    c0 = list(ptcl.get("Color0"))
    flag = ptcl.get("ColorFlag") if ptcl.has("ColorFlag") else 0
    if not flag & 0xF or not ptcl.has("Color1"):
        return c0
    c1 = list(ptcl.get("Color1"))
    out, t = list(c0), rng.random()
    for byte, bit in COLOR_BLEND_BITS:
        if flag & bit:
            out[byte] = int((1.0 - t) * c1[byte] + c0[byte] * t)
            if flag & COLOR_EACH_RANDOM and bit != 0x8:
                t = rng.random()
    return out


def refracts(ptcl):
    """True for particles drawn with the refraction shader (XfPrim PRIM_EX_REFRACT): the screen behind them, offset by
    (BaseMap.rg - 0.5) x Intensity / 100, times the particle colour; Intensity doesn't tint them."""
    return ptcl is not None and ptcl.has("ParticleOptionFlag") and bool(ptcl.get("ParticleOptionFlag") & REFRACT_FLAG)         and not (ptcl.has("CullingFlag") and ptcl.get("CullingFlag") & OCCLUSION_FLAG)

SPACE_FOLLOW = "follow"                   # re-placed from the generator every frame (move None)
SPACE_WORLD = "world"                     # stays where it was emitted
SPACE_FOLLOW_TRANSLATION = "translation"  # world space, but carried along by the generator's translation
PATH_TYPES = (3, 4, 5, 6)

_AXES = {0: (1, 0, 0), 1: (-1, 0, 0), 2: (0, 1, 0), 3: (0, -1, 0), 4: (0, 0, 1), 5: (0, 0, -1), 6: (0, 0, 1)}
# setMatFromAngle 0x95FF70: RotOrder enum -> MtMatrix::setRotate<name> (ROT_ORDER_NAMES). The names don't give the
# order the axes are applied in: emulating the six functions (2026-10-09) shows RotOrder 0-5 apply the axes in the
# order of ROT_ORDERS (alphabetical), which is also Blender's Euler order string (first letter applied first).
ROT_ORDER_NAMES = ("ZYX", "ZXY", "YZX", "YXZ", "XZY", "XYZ")
ROT_ORDERS = ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX")

# block field -> particle property it drives
_PTCL_KEYS = {
    "KeyframeIntensityParamOffset": "intensity", "KeyframeScaleParamOffset": "scale",
    "KeyframeColorParamOffset": "color", "KeyframePatNoParamOffset": "pattern",
    "KeyframeAngleParamOffset": "angle", "KeyframeRotParamOffset": "rot",
    "KeyframeModelScaleParamOffset": "model_scale",
    "KeyframeRadius0ParamOffset": "shape0", "KeyframeRadius1ParamOffset": "shape1",
    "KeyframeHeight0ParamOffset": "shape2", "KeyframeHeight1ParamOffset": "shape3",
    "KeyframeWidthParamOffset": "shape0", "KeyframeHeightParamOffset": "shape2",
    "KeyframeScrollUParamOffset": "scroll_u", "KeyframeScrollVParamOffset": "scroll_v",
}
_ROPE_KEYS = {"KeyframeLengthParamOffset": "length", "KeyframeChainRotParamOffset": "rot",
              "KeyframeBlendRotParamOffset": "blend_rot", "KeyframeBlendRateParamOffset": "blend_rate"}
_MOVE_KEYS = {"KeyframeRotParamOffset": "move_rot", "KeyframeSpeedParamOffset": "speed",
              "KeyframeFallSpeedParamOffset": "fall"}
_GEN_KEY_FIELDS = ("KeyframeScaleParamOffset", "KeyframeSetNumParamOffset", "KeyframeRangeParamOffset",
                   "KeyframePosParamOffset", "KeyframeRotParamOffset")


def _rf(rng, pair):
    s, r = pair
    return s + rng.random() * r


def _ru(rng, pair):
    s, r = pair
    return s + (rng.randrange(r + 1) if r else 0)


def rotate(vec, angles, order):
    x, y, z = vec
    for axis in ROT_ORDERS[order] if 0 <= order < len(ROT_ORDERS) else "XYZ":
        a = angles["XYZ".index(axis)]
        c, s = math.cos(a), math.sin(a)
        if axis == "X":
            y, z = y * c - z * s, y * s + z * c
        elif axis == "Y":
            x, z = x * c + z * s, -x * s + z * c
        else:
            x, y = x * c - y * s, x * s + y * c
    return x, y, z


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v) if n > 1e-7 else v


def keyframes_of(block, mapping):
    """{property: Keyframe} for the keyframe sub-blocks of a block."""
    out = {}
    if block is None:
        return out
    for sub in block.subblocks():
        if sub.kind == "kf" and sub.field.name in mapping:
            try:
                kf = kfm.read(sub)
            except Exception:
                continue
            if kf.frames:
                out[mapping[sub.field.name]] = kf
    return out


def emission_space(record):
    """SPACE_* for a record's particles after spawn."""
    move = record.move
    if move is None or move.type == 0:
        return SPACE_FOLLOW
    if move.type in PATH_TYPES:   # per-particle anchors: on the path = follow, released = world
        return SPACE_WORLD
    option = move.get("MoveOptionFlag")
    gen = record.gen
    corrected = bool(option & 4) or (gen is not None and any(gen.get(f) for f in _GEN_KEY_FIELDS))
    if corrected and option & 8:
        return SPACE_FOLLOW_TRANSLATION
    return SPACE_WORLD


@dataclass
class Particle:
    birth: int
    pos: tuple
    dir: tuple
    speed: float
    accel: float
    coef: float
    gravity: float
    life: tuple           # (appear, keep, vanish) frames, or None
    scale: float
    scale_add: float
    angle: float
    angle_add: float
    rot: tuple
    rot_add: tuple
    model_scale: tuple
    model_scale_add: tuple
    color: tuple          # rgba 0..255
    intensity: float
    aspect: float
    sequence: int
    pattern: float
    pat_speed: float
    pat_count: int
    anim_flag: int
    pat_key_is_speed: bool = False
    rot_axis: tuple = (0.0, 1.0, 0.0)
    rot_order: int = 5
    keys: dict = field(default_factory=dict)     # property -> (Keyframe, rates)
    path: dict = None                            # move types 3-6
    line: dict = None                            # Polyline / Line particles
    strip: dict = None                           # PolygonStrip particles
    light: dict = None                           # Light particles
    coll: dict = None                            # ground-plane collision state
    shape: dict = None                           # Polygon / PrimModel size parameters
    scroll: dict = None                          # Model UV scroll
    _rope: list = None
    _path: list = None
    _track: list = None
    end: int = None       # birth + lifetime, set by callers that filter by life window
    refract: bool = False  # refraction shader: the colour isn't multiplied by intensity
    flip: int = 0          # AnimFlag 0x100 / 0x200 rolled from the _RAND bits that the record doesn't set itself

    def lifetime(self):
        return sum(self.life) if self.life else NO_LIFE_FRAMES

    def keyed(self, name, age):
        """Keyframe value for a property at a particle age, or None if the property isn't keyed."""
        entry = self.keys.get(name)
        if entry is None:
            return None
        kf, rates = entry
        if kf.init_only:
            age = 0
        timer = age if kf.uses_particle_age else self.birth + age
        return kfm.evaluate(kf, timer, rates)

    def keyed_or(self, name, age, base, add):
        """A property with an *Add field: the keyframe (absolute) if keyed, else base + add * age. InitOnly keys
        are evaluated at spawn and then the Add applies."""
        entry = self.keys.get(name)
        if entry is None:
            return _linear(base, add, age)
        kf, rates = entry
        if kf.init_only:
            value = kfm.evaluate(kf, 0 if kf.uses_particle_age else self.birth, rates)
            return _linear(tuple(value) if isinstance(value, (list, tuple)) else value, add, age)
        value = kfm.evaluate(kf, age if kf.uses_particle_age else self.birth + age, rates)
        return tuple(value) if isinstance(value, (list, tuple)) else value

    def is_keyed(self, name):
        entry = self.keys.get(name)
        return entry is not None and not entry[0].init_only

    def placement(self, n):
        if self.coll is not None and self.path is None:
            if self._track is None:
                self._track = [(q, 0) for q in _coll_track(self)]
            return self._track[n] if n < len(self._track) else (None, None)
        return self._placement(n)

    def _placement(self, n):
        """(position, anchor age) after n frames, or (None, None) once the particle has died on its path.
        anchor None = generator space of the current frame (riding a path); otherwise the age whose generator
        frame the position is expressed in (0 = spawn)."""
        if self.path is None:
            return self.position(n), 0
        if self._track is None:
            self._track = _path_track(self)
        if n >= len(self._track):
            return None, None
        return self._track[n]

    def position(self, n):
        """Offset from the spawn frame's generator origin after n frames (cm, generator axes at spawn)."""
        if not any(name in self.keys for name in ("move_rot", "speed", "fall")):
            if self.coef and abs(self.coef - 1.0) > 1e-6:
                k = self.speed * (1 - self.coef ** n) / (1 - self.coef)
            else:
                k = self.speed * n + self.accel * n * (n - 1) / 2
            pos = [self.pos[i] + self.dir[i] * k for i in range(3)]
            pos[1] -= self.gravity * n * (n - 1) / 2
            return tuple(pos)
        if self._path is None:   # step-integrate once, cache the whole lifetime
            path, pos = [self.pos], list(self.pos)
            speed, fall = self.speed, 0.0
            for age in range(self.lifetime()):
                rot = self.keyed("move_rot", age)
                d = rotate(self.rot_axis, rot, self.rot_order) if rot is not None else self.dir
                keyed_speed = self.keyed("speed", age)
                if keyed_speed is not None:
                    speed = keyed_speed
                keyed_fall = self.keyed("fall", age)
                if keyed_fall is not None:
                    fall = keyed_fall
                pos = [pos[0] + d[0] * speed, pos[1] + d[1] * speed - fall, pos[2] + d[2] * speed]
                path.append(tuple(pos))
                if keyed_speed is None:
                    speed = speed * self.coef if self.coef else speed + self.accel
                if keyed_fall is None:
                    fall += self.gravity
            self._path = path
        return self._path[min(n, len(self._path) - 1)]


def _linear(base, add, age):
    if isinstance(base, tuple):
        return tuple(b + a * age for b, a in zip(base, add))
    return base + add * age


@dataclass
class ParticleState:
    pos: tuple
    alpha: float
    scale: float
    aspect: float
    angle: float
    rot: tuple
    model_scale: tuple
    color: tuple          # rgba 0..1, rgb multiplied by intensity
    sequence: int
    pattern: int
    anchor: int = None    # game frame whose generator matrix places pos; None = the current frame
    line: list = None     # Polyline / Line: [(pos, anchor, half width cm, rgba)] head first
    strip: tuple = None   # PolygonStrip: ([(A, B, anchor)] newest first, head rgba, tail rgba, spline subdivisions)
    light: tuple = None   # Light: (start cm, end cm)
    shape: tuple = None   # Polygon (W, 0, H, 0) half-extents / PrimModel (Radius0, Radius1, Height0, Height1), cm
    uv_scroll: tuple = None   # Model: (u, v) offset in UV units
    flip: int = 0         # extra flipbook flips (AnimFlag 0x100 / 0x200) on top of the record's own


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return (tuple(c / n for c in v), n) if n >= 1.19e-7 else (tuple(v), n)


def _path_track(p):
    """[(local pos, anchor age)] per age for a path particle (generator-space while on the path)."""
    P = p.path
    kind, opt, release_type = P["kind"], P["option"], P["release_type"]
    timer, d, speed, accel = P["release_timer"], P["d0"], P["speed"], P["accel"]
    track, prev = [], None
    on_path, anchor = True, None
    vel = acc = (0.0, 0.0, 0.0)
    grav = fall = 0.0
    pos = None
    for age in range(p.lifetime()):
        if not on_path:   # released: Add motion in the release frame's space
            pos = (pos[0] + vel[0], pos[1] + vel[1] - fall, pos[2] + vel[2])
            vel = tuple(v + a for v, a in zip(vel, acc))
            fall += grav
            track.append((pos, anchor))
            continue
        rot = p.keyed("move_rot", age)
        rot = rot if rot is not None else P["rot"]
        end = False
        if kind == 5:
            kf, rates = P["ofs_key"]
            timer_frame = age if kf.uses_particle_age else p.birth + age
            value = kfm.evaluate(kf, timer_frame, rates) or (0.0, 0.0, 0.0)
            end = not kf.loop and timer_frame >= kf.frames[-1]
            offset = tuple(v * s for v, s in zip(value, P["scale3"]))
        else:
            if age > 0:
                keyed_speed = p.keyed("speed", age)
                if keyed_speed is not None:
                    speed = keyed_speed
                d += speed
                speed += accel
            if kind == 4 and P["rope"] is not None:
                nodes = P["rope"].at(p.birth + age)
                total, point, end = 0.0, nodes[-1], True
                for a, b in zip(nodes, nodes[1:]):
                    seg = math.dist(a, b)
                    if seg > 0 and d < total + seg:
                        f = (d - total) / seg
                        point, end = tuple(x + (y - x) * f for x, y in zip(a, b)), False
                        break
                    total += seg
                if d < 0:
                    point, end = nodes[0], True
                spawn_off = rotate(P["spawn"], rot, P["order"]) if any(rot) else P["spawn"]
                local = tuple(x + y for x, y in zip(point, spawn_off))
                offset = None
            elif kind == 3 and P["strip"] is not None:
                point, end = P["strip"].at(d, P["strip_loop"])
                offset = tuple(v * s for v, s in zip(point, P["scale3"]))
            else:
                if kind == 6:
                    end = d < 0 or d > P["max_d"]
                    if end and not (release_type and opt & 1):
                        d = min(max(d, 0.0), P["max_d"])
                offset = tuple(c * d for c in P["axis"])
        if offset is not None:
            r = rotate(offset, rot, P["order"]) if any(rot) else offset
            local = tuple(a + b for a, b in zip(P["spawn"], r))
        if age > 0:
            if end and opt & 2:          # KILL_PATH_END
                break
            if release_type:
                if end and opt & 1:      # RELEASE_PATH_END
                    timer = 0
                if timer > 0:
                    timer -= 1
                else:
                    direction, length = _unit(tuple(a - b for a, b in zip(local, prev)))
                    if kind == 5:
                        keyed_speed = p.keyed("speed", age)
                        spd = keyed_speed if keyed_speed is not None else \
                            length if release_type == 1 else P["fresh_speed"] if release_type == 2 else 0.0
                        vel = tuple(c * spd for c in direction)
                        acc = tuple(c * P["fresh_accel"] for c in direction)
                    else:
                        vel = (tuple(a - b for a, b in zip(local, prev)) if release_type == 1 else
                               tuple(c * speed for c in direction) if release_type == 2 else (0.0, 0.0, 0.0))
                        acc = tuple(c * accel for c in direction)
                    grav = P["gravity"]
                    keyed_fall = p.keyed("fall", age)
                    fall = keyed_fall if keyed_fall is not None else 0.0
                    on_path, anchor, pos = False, age, local
                    track.append((local, anchor))
                    prev = local
                    continue
        track.append((local, None))
        prev = local
    return track


def emission_schedule(gen, rng, max_frames):
    """[(frame, count)] following the generator state machine."""
    out = []
    set_num_key = keyframes_of(gen, {"KeyframeSetNumParamOffset": "set_num"}).get("set_num")
    set_num_rates = kfm.draw_rates(set_num_key, rng) if set_num_key else None
    frame = _ru(rng, gen.get("WaitFrame"))
    bursts = _ru(rng, gen.get("BurstNum"))   # 0 = repeat until max_frames
    done = 0
    while frame < max_frames:
        length = max(_ru(rng, gen.get("LoopNum")), 1)
        for f in range(frame, min(frame + length, max_frames)):
            if set_num_key is not None:
                count = int(kfm.evaluate(set_num_key, f, set_num_rates) or 0)
            else:
                count = _ru(rng, gen.get("SetNum"))
            if count > 0:
                out.append((f, count))
        frame += length + _ru(rng, gen.get("SetFrame"))
        done += 1
        if bursts and done >= bursts:
            break
    return out


def strip_point(gen, strip_parts, rng, serial):
    """Spawn point on the generator's .efs strip (RangeStripPath), unscaled cm, or None."""
    if not strip_parts:
        return None
    flags, kind = gen.get("RangeStripFlag"), gen.get("RangeStripType")
    divide = gen.get("RangeDivideNum")
    spread = None
    if flags & 0x20 and divide and kind != 0:   # ALL_PARTS + RangeDivideNum: the slots run across every part
        k = serial % divide if flags & 0x01 else (divide - 1 - serial % divide if flags & 0x02 else rng.randrange(divide))
        x = k * len(strip_parts) / divide
        part_no, spread = int(x), x - int(x)
    elif flags & 0x20:   # sub_99B270: a random part
        part_no = rng.randrange(len(strip_parts))
    else:
        part_no = min(max(gen.get("RangeStripPartsNo"), 0), len(strip_parts) - 1)
    pts = strip_parts[part_no]
    if not pts:
        return None
    n = len(pts)

    def pick(count):
        if flags & 0x01:
            return serial % count
        if flags & 0x02:
            return count - 1 - serial % count
        return rng.randrange(count)

    if kind == 0 or n == 1:
        return pts[pick(n)]
    closed = bool(flags & 0x08)
    segs = n if closed else n - 1
    if spread is not None:
        x = spread * segs
        seg, t = min(int(x), segs - 1), x - min(int(x), segs - 1)
    elif divide:
        k = pick(divide)
        x = k * n / divide if closed else (k * (n - 1) / (divide - 1) if divide > 1 else 0.0)
        seg, t = int(x), x - int(x)
        if seg >= segs:
            seg, t = segs - 1, 1.0
    else:
        seg = pick(segs)
        t = 0.5 if flags & 0x10 else rng.random()
    a, b = pts[seg], pts[(seg + 1) % n]
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def spawn_offset(gen, rng, t, ranges=None):
    """sub_999040: point on the RangeType shape; t is the burst position in [0, 1). ranges overrides Range."""
    x, y, z = _shape_point(ranges or gen.get("Range"), gen.get("RangeType"), rng, t)
    scale = [_rf(rng, r) for r in gen.get("UknRangeThing")[1:]]
    return x * scale[0], y * scale[1], z * scale[2]


def _shape_point(ranges, kind, rng, t):
    """sub_999040 on (base, rand) extents: RangeType box faces 1-3, rings 4-6, spheres 7-8, else the origin."""
    (xs, xr), (ys, yr), (zs, zr) = ranges
    k = 1.0 - math.sin(rng.random() * math.pi / 2)   # radial falloff: 1 - sin(rand * pi/2)
    if kind in (1, 2, 3):
        u = [2 * rng.random() - 1 for _ in range(3)]
        u[kind - 1] = 2 * t - 1
        x, y, z = u[0] * xs, u[1] * ys, u[2] * zs
    elif kind == 4:
        a = t * 2 * math.pi
        x, y, z = rng.random() * xr + xs, (yr * k + ys) * math.cos(a), (zr * k + zs) * math.sin(a)
    elif kind == 5:
        a = t * 2 * math.pi
        x, y, z = (xr * k + xs) * math.sin(a), rng.random() * yr + ys, (zr * k + zs) * math.cos(a)
    elif kind == 6:
        a = t * 2 * math.pi
        x, y, z = (xr * k + xs) * math.cos(a), (yr * k + ys) * math.sin(a), rng.random() * zr + zs
    elif kind in (7, 8):
        polar = t * (math.pi if kind == 7 else math.pi / 2)
        az = rng.random() * 2 * math.pi
        x = (xr * k + xs) * math.sin(az) * math.sin(polar)
        y = (rng.random() * yr + ys) * math.cos(polar)
        z = (zr * k + zs) * math.cos(az) * math.sin(polar)
    else:
        x = y = z = 0.0
    return x, y, z


def _direction(gen, move, rng, offset, keys):
    if move is None or not move.has("Rot"):
        return (0.0, 1.0, 0.0), (0.0, 1.0, 0.0), 5
    axis = _AXES.get(move.get("RotAxisType"), (0, 1, 0))
    order = move.get("RotOrder")
    if "move_rot" in keys:
        kf, rates = keys["move_rot"]
        angles = kfm.evaluate(kf, 0, rates)
    else:
        angles = [_rf(rng, r) for r in move.get("Rot")]
    d = rotate(axis, angles, order)
    dir_type = gen.get("RangeDirType")
    if dir_type in (1, 2) and any(offset):
        target = _normalize(offset if dir_type == 1 else tuple(-c for c in offset))
        f = min(max(_rf(rng, gen.get("UknRangeThing")[0]), 0.0), 1.0)
        d = _normalize(tuple(a * (1 - f) + b * f for a, b in zip(d, target)))
    return d, axis, order


class _Template:
    """Per-record data shared by all its particles (keyframes parsed once)."""

    def __init__(self, record, rng=None, strip_points=None, range_strip=None, ground_y=None, world_axes=None):
        self.record = record
        self.max_frames = 300   # simulated range (simulate() sets it): held particles last until its end
        self.world_axes = world_axes        # game world -> generator space at import (row-major 3x3), or None
        self.range_strip = range_strip      # generator RangeStripPath .efs parts (cm)
        self.ground_y = ground_y            # ground plane height in generator space (cm) for collision
        self.collision = _collision_params(record.move)
        self.ptcl_keys = keyframes_of(record.ptcl, _PTCL_KEYS)
        self.move_keys = keyframes_of(record.move, {**_MOVE_KEYS, "KeyframeReleaseFrameParamOffset": "release"})
        self.path_ofs = keyframes_of(record.move, {"KeyframeOfsParamOffset": "ofs"}).get("ofs")
        self.range_key = keyframes_of(record.gen, {"KeyframeRangeParamOffset": "range"}).get("range")
        self.keep_key = keyframes_of(record.life, {"KeyframeKeepFrameParamOffset": "keep"}).get("keep")
        self.line_ext = _line_extension(record.ptcl)
        self.cloth_ext = _cloth_extension(record.ptcl)
        self.line_keys = keyframes_of(record.ptcl, {"KeyframeHeadSizeParamOffset": "head_size",
                                                    "KeyframePlaceSizeParamOffset": "place_size"})
        self.strip = Polyline(strip_points) if strip_points else None
        # Path3DScale / PathLengthScale: rolled once per generator start (initGeneratorParam 0x96B9C3)
        self.path_scale3, self.path_length_scale = (1.0, 1.0, 1.0), 1.0
        move = record.move
        if rng is not None and move is not None and move.type in PATH_TYPES and move.has("Path3DScaleX"):
            scale3 = tuple(_rf(rng, move.get(f"Path3DScale{a}")) for a in "XYZ")
            self.path_length_scale = _rf(rng, move.get("PathLengthScale"))
            self.path_scale3 = tuple(c * self.path_length_scale for c in scale3)
        self.path_rope = None
        if rng is not None and move is not None and move.type == 4 and move.has("ChainPosNum"):
            nodes = max(move.get("ChainPosNum"), 2)
            self.path_rope = GeneratorRope(Rope(_chain_params(move.data, 0x80, rng, nodes), nodes,
                                                self.path_length_scale, _rope_keys(move, rng), birth=None))


def spawn(template, rng, birth, t, pat_counts=(1,), serial=0):
    """One particle; pat_counts = pattern count per flipbook sequence."""
    record = template.record
    gen, ptcl, life, move = record.gen, record.ptcl, record.life, record.move
    keys = {name: (kf, kfm.draw_rates(kf, rng)) for name, kf in {**template.ptcl_keys, **template.move_keys}.items()
            if name != "release"}
    ranges = None
    if template.range_key is not None:   # keyed spawn extents: key base = Range.s, key range = Range.r
        kf = template.range_key
        timer = max(birth - 1, 0) if kf.ref_type == 1 else birth
        s = kfm.evaluate(kf, timer, (0.0, 0.0, 0.0))
        sr = kfm.evaluate(kf, timer, (1.0, 1.0, 1.0))
        if s is not None:
            ranges = [(a, b - a) for a, b in zip(s, sr)]
    offset = spawn_offset(gen, rng, t, ranges)
    on_strip = strip_point(gen, template.range_strip, rng, serial)
    if on_strip is not None:
        scale = [_rf(rng, r) for r in gen.get("UknRangeThing")[1:]]
        offset = tuple(o + p * s for o, p, s in zip(offset, on_strip, scale))
    d, axis, order = _direction(gen, move, rng, offset, keys)
    speed = accel = coef = gravity = 0.0
    path = None
    if move is not None and move.type in PATH_TYPES:
        path = _path_init(template, move, rng, offset, keys, axis, order)
    elif move is not None and move.type in (1, 2):
        speed = _rf(rng, move.get("Speed"))
        if move.type == 1:
            accel = _rf(rng, move.get("Acceleration"))
            gravity = _rf(rng, move.get("Gravity"))
        else:
            coef = _rf(rng, move.get("SpeedCoef"))
    if move is None or move.type == 0:
        for name in ("move_rot", "speed", "fall"):
            keys.pop(name, None)
    life_frames = None
    if life is not None and life.type in (1, 2):
        life_frames = tuple(_ru(rng, life.get(k)) for k in ("AppearFrame", "KeepFrame", "VanishFrame"))
        if template.keep_key is not None:   # the keyframe replaces KeepFrame, evaluated once at spawn
            kf = template.keep_key
            timer = 0 if kf.ref_type in (0, 5, 6, 7) else (max(birth - 1, 0) if kf.ref_type == 1 else birth)
            keep = kfm.evaluate(kf, timer, kfm.draw_rates(kf, rng))
            if keep is not None:
                life_frames = (life_frames[0], max(int(keep), 0), life_frames[2])
        if life.get("HoldUntilEffectEnds"):   # the Keep phase waits for the effect to end (moveParticleLifeFrame)
            appear, _keep, vanish = life_frames
            limit = life.get("HoldFrameLimit")   # runs out -> straight to Vanish; 0 = no limit
            # nothing ends the effect in the preview: hold until the end of the simulated range (path-end and
            # collision releases aren't modelled)
            life_frames = (appear, limit or max(template.max_frames - birth - appear, 1), vanish)
        if not any(life_frames):
            life_frames = (0, 1, 0)

    def has(name):
        return ptcl is not None and ptcl.has(name)

    scale = _rf(rng, ptcl.get("Scale")) if has("Scale") else 1.0
    scale_add = _rf(rng, ptcl.get("ScaleAdd")) if has("ScaleAdd") else 0.0
    intensity = _rf(rng, ptcl.get("Intensity")) if has("Intensity") else 1.0
    color = bgra_to_rgba(_src_color(ptcl, rng)) if has("Color0") else (255, 255, 255, 255)
    aspect = _rf(rng, ptcl.get("AspectRatio")) if has("AspectRatio") else 1.0
    angle = _rf(rng, ptcl.get("Angle")) if has("Angle") else 0.0
    angle_add = _rf(rng, ptcl.get("AngleAdd")) if has("AngleAdd") else 0.0
    rot = tuple(_rf(rng, r) for r in ptcl.get("Rot")) if has("Rot") else (0.0, 0.0, 0.0)
    rot_add = tuple(_rf(rng, r) for r in ptcl.get("RotAdd")) if has("RotAdd") else (0.0, 0.0, 0.0)
    if has("ModelScale"):
        model_scale = tuple(_rf(rng, r) for r in ptcl.get("ModelScale"))
        model_scale_add = tuple(_rf(rng, r) for r in ptcl.get("ModelScaleAdd"))
    else:
        model_scale, model_scale_add = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    sequence, pattern, pat_speed, anim_flag, pat_count, key_is_speed, flip = 0, 0.0, 0.0, 0, 1, False, 0
    if has("ModelFlags"):   # Model: the "pattern" is the mesh part number
        pat_count = max(pat_counts[0], 1) if pat_counts else 1
        pattern = float(_ru(rng, (ptcl.get("PartsNoMin"), ptcl.get("PartsNoRange"))))
        anim_flag = ptcl.get("ModelAnimFlag") & 0xF
        pat_speed = ptcl.get("AnimSpeed") if anim_flag & ANIM_MOVE else 0.0
    elif has("PatSpeed"):
        anim_flag = ptcl.get("AnimFlag")
        flip = _random_flips(anim_flag, rng)
        sequence =min(_ru(rng, (ptcl.get("SeqNoMin"), ptcl.get("SeqNoRange"))), len(pat_counts) - 1)
        pat_count = max(pat_counts[sequence], 1)
        pattern = float(min(_ru(rng, (ptcl.get("PatNoMin"), ptcl.get("PatNoRange"))), pat_count - 1))
        pat_speed = ptcl.get("PatSpeed")
        key_is_speed = bool(ptcl.get("DrawFlags_0x41") & 1)
        if "pattern" in keys:
            anim_flag |= ANIM_MOVE
        elif not anim_flag & ANIM_MOVE:
            pat_speed = 0.0
    line = _line_init(template, rng, ptcl, keys, serial) if ptcl is not None and ptcl.has("LineFlags") else None
    shape = scroll = None
    if ptcl is not None and ptcl.type == 6 and ptcl.has("Radius"):
        radius, radius_add = ptcl.get("Radius"), ptcl.get("RadiusAdd")
        height, height_add = ptcl.get("Height"), ptcl.get("HeightAdd")
        shape = {"kind": "prim",
                 "base": tuple(_rf(rng, r) for r in (radius[0], radius[1], height[0], height[1])),
                 "add": tuple(_rf(rng, r) for r in (radius_add[0], radius_add[1], height_add[0], height_add[1]))}
    elif ptcl is not None and ptcl.type == 2 and ptcl.has("Width"):
        shape = {"kind": "polygon",
                 "base": (_rf(rng, ptcl.get("Width")), 0.0, _rf(rng, ptcl.get("Height")), 0.0),
                 "add": (_rf(rng, ptcl.get("WidthAdd")), 0.0, _rf(rng, ptcl.get("HeightAdd")), 0.0)}
    if ptcl is not None and ptcl.type == 5 and ptcl.has("ScrollU") and ptcl.get("ModelAnimFlag") & 0x10:
        scroll = {"speed": (_rf(rng, ptcl.get("ScrollU")), _rf(rng, ptcl.get("ScrollV"))), "offsets": None}
    light = None
    if ptcl is not None and ptcl.type == 10 and ptcl.has("AttenuateStart"):
        light = {name: _rf(rng, ptcl.get(field)) for name, field in (
            ("start", "AttenuateStart"), ("start_add", "AttenuateStartAdd"),
            ("end", "AttenuateEnd"), ("end_add", "AttenuateEndAdd"))}
    strip = None
    if ptcl is not None and ptcl.type == 15 and ptcl.has("Width"):
        strip = _strip_init(rng, ptcl, keys)
        for name, field_name in (("strip_rot", "KeyframeRotParamOffset"), ("strip_width", "KeyframeWidthParamOffset")):
            kf = keyframes_of(ptcl, {field_name: name}).get(name)
            if kf is not None:
                keys[name] = (kf, kfm.draw_rates(kf, rng))
    particle = Particle(birth, offset, d, speed, accel, coef, gravity, life_frames, scale, scale_add, angle, angle_add,
                    rot, rot_add, model_scale, model_scale_add, color, intensity, aspect, sequence, pattern,
                    pat_speed, pat_count, anim_flag, key_is_speed, axis, order, keys, path, line, strip, light,
                    shape=shape, scroll=scroll, refract=refracts(ptcl), flip=flip)
    if line is not None and line.get("rope") is not None:
        line["rope"].birth = birth   # generator-timer rope keys run from the particle's birth frame
    c = template.collision
    if c is not None and template.ground_y is not None and path is None and \
            not any(name in keys for name in ("move_rot", "speed", "fall")):
        r = c["CollRadius"]
        particle.coll = {
            "ground": template.ground_y, "radius": max(r[0], 0.0), "type": c["CollType"],
            "timer": c["CollCancelFrame"] | (c["member_0x3"] << 8),
            "bounces": c["BounceNumBase"] + (rng.randrange(c["BounceNumRange"] + 1) if c["BounceNumRange"] else 0),
            "rate": _rf(rng, c["BounceRate"]),
        }
    return particle


def _collision_params(move):
    """EFL_PARAM_COLLISION fields for a move block with CollParamOffset, or None."""
    if move is None or move.type not in (1, 2) or not move.get("CollParamOffset"):
        return None
    for sub in move.subblocks():
        if sub.kind == "collision":
            try:
                return sub.fields()
            except Exception:
                return None
    return None


def _coll_track(p):
    """Stepped positions with ground-plane collision; ends early when the particle is killed."""
    c = p.coll
    pos, track = p.pos, [p.pos]
    vel = tuple(x * p.speed for x in p.dir)
    acc = tuple(x * p.accel for x in p.dir)
    fall, timer, bounces = 0.0, c["timer"], c["bounces"]
    frozen = colliding = False
    for _age in range(1, p.lifetime()):
        if frozen:
            track.append(pos)
            continue
        new = (pos[0] + vel[0], pos[1] + vel[1] - fall, pos[2] + vel[2])
        vel = tuple(v * p.coef for v in vel) if p.coef else tuple(v + a for v, a in zip(vel, acc))
        fall += p.gravity
        if timer > 0:
            timer -= 1
        elif not colliding and new[1] < c["ground"] + c["radius"] <= pos[1] + 1e-6:
            timer = 1
            if bounces > 0:
                d = tuple(a - b for a, b in zip(new, pos))
                length = math.sqrt(sum(x * x for x in d)) or 1.0
                unit = tuple(x / length for x in d)
                reflected = (unit[0], -unit[1], unit[2])
                vel = tuple(x * length * c["rate"] for x in reflected)
                fall, bounces = 0.0, bounces - 1
                new = (new[0], c["ground"] + c["radius"] + 0.1, new[2])
            elif c["type"] == 0:   # KILL
                break
            elif c["type"] == 1:   # MOVE_STOP
                new, frozen = (new[0], c["ground"] + c["radius"], new[2]), True
            else:                   # COLL_STOP: keep moving, collision off
                colliding = True
        pos = new
        track.append(pos)
    return track


def _chain_params(data, base, rng, nodes):
    """EFL_PARAM_CHAIN at data[base:] rolled for one rope (draw order as initChain 0x984350)."""
    def rangef(off):
        return _rf(rng, struct.unpack_from("<2f", data, base + off))

    option, = struct.unpack_from("<H", data, base)
    pre, = struct.unpack_from("<H", data, base + 6)
    rot_byte, blend_byte = data[base + 4], data[base + 5]
    segs = max(nodes - 1, 1)
    c = {"option": option, "pre": pre}
    c["length"] = max(0.0, rangef(0x08)) / segs
    c["length_add"] = rangef(0x10) / segs
    c["acc"], c["frame_inf"], c["vertex_inf"] = rangef(0x20), rangef(0x28), rangef(0x30)
    if option & 0x10:
        c["force_rate"], c["force_atten"] = rangef(0x68), rangef(0x70) / segs
    else:
        c["force_rate"] = c["force_atten"] = 0.0
    c["blend_rate"] = rangef(0x18)
    c["rot_byte"], c["blend_byte"], c["segs"] = rot_byte, blend_byte, segs
    rot = [rangef(0x38 + 8 * i) for i in range(3)]
    axis = _AXES.get(rot_byte & 0xF, (0, 1, 0))
    c["dir"] = rotate(axis, rot, rot_byte >> 4)
    blend_rot = [rangef(0x50 + 8 * i) for i in range(3)]
    c["blend_dir"] = _blend_dir(c, blend_rot)
    return c


def _blend_dir(c, angles):
    byte = c["blend_byte"]
    bdir = rotate(_AXES.get(byte & 0xF, (0, 1, 0)), angles, byte >> 4)
    if c["option"] & 0x20:
        bdir = _shortest_arc_rotate(_AXES.get(c["rot_byte"] & 0xF, (0, 1, 0)), c["dir"], bdir)
    return bdir


def _rope_keys(block, rng):
    """{length / rot / blend_rot / blend_rate: (Keyframe, rates)} of an EFL_PARAM_CHAIN's keyframes."""
    return {name: (kf, kfm.draw_rates(kf, rng)) for name, kf in keyframes_of(block, _ROPE_KEYS).items()}


def _shortest_arc_rotate(a, d, v):
    """Rotate v by the rotation that takes unit axis a onto direction d."""
    d, _ = _unit(d)
    dot = sum(x * y for x, y in zip(a, d))
    if dot < -0.999:   # 180 degrees about any perpendicular axis
        perp = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)
        k = _unit((a[1] * perp[2] - a[2] * perp[1], a[2] * perp[0] - a[0] * perp[2], a[0] * perp[1] - a[1] * perp[0]))[0]
        return tuple(2 * sum(x * y for x, y in zip(k, v)) * kc - vc for kc, vc in zip(k, v))
    cross = (a[1] * d[2] - a[2] * d[1], a[2] * d[0] - a[0] * d[2], a[0] * d[1] - a[1] * d[0])
    s = math.sqrt(2 * (1 + dot))
    q = (s / 2, cross[0] / s, cross[1] / s, cross[2] / s)   # (w, x, y, z)
    w, x, y, z = q
    # v' = q v q*
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + y * tz - z * ty, v[1] + w * ty + z * tx - x * tz, v[2] + w * tz + x * ty - y * tx)


class Rope:
    """moveChain 0x994C20: nodes relative to the root, in the frame the root moves in."""

    def __init__(self, params, nodes, scale, keys=None, birth=0):
        """keys: rope keyframes; birth: the owner's birth frame (particle ropes, particle timer) or None for a
        generator-owned rope (generator timer = the rope's own frame count)."""
        self.p, self.n, self.scale = dict(params), nodes, scale
        self.keys, self.birth, self.age = keys or {}, birth, 0
        self.length = params["length"]
        self._apply_keys(initial=True)
        segs = nodes - 1
        unit_dir, _ = _unit(self.p["dir"])
        seg = self.length * scale
        self.vel = [(0.0, 0.0, 0.0)] * nodes
        if not self.p["blend_rate"]:
            self.pos = [tuple(c * seg * i for c in unit_dir) for i in range(nodes)]
        else:
            unit_blend, _ = _unit(self.p["blend_dir"])
            pos, acc = [(0.0, 0.0, 0.0)], (0.0, 0.0, 0.0)
            for k in range(segs):
                wa = self._weight(k / segs)
                acc = tuple(a + u * seg * wa + b * seg * (1 - wa) for a, u, b in zip(acc, unit_dir, unit_blend))
                pos.append(acc)
            self.pos = pos
        for _ in range(params["pre"]):
            self._step()

    def _weight(self, t):
        br = self.p["blend_rate"]
        if br < 0.5:
            return (1 - 2 * br) * t + (1 - t)
        if br > 0.5:
            return 1 - ((br - 0.5) * 2 * (1 - t) + t)
        return 1 - t

    def _timer(self, kf):
        if self.birth is None or not kf.uses_particle_age:
            return (self.birth or 0) + self.age
        return self.age

    def _apply_keys(self, initial=False):
        """Rope keyframes (moveChain 0x994C20): Length = total length, Rot / BlendRot = angles (the pull direction
        is recomputed), BlendRate; InitOnly keys only at the start."""
        for name, (kf, rates) in self.keys.items():
            if kf.init_only and not initial:
                continue
            value = kfm.evaluate(kf, self._timer(kf), rates)
            if value is None:
                continue
            if name == "length":
                self.length = max(value, 0.0) / self.p["segs"]
            elif name == "rot":
                byte = self.p["rot_byte"]
                self.p["dir"] = rotate(_AXES.get(byte & 0xF, (0, 1, 0)), value, byte >> 4)
            elif name == "blend_rot":
                self.p["blend_dir"] = _blend_dir(self.p, value)
            elif name == "blend_rate":
                self.p["blend_rate"] = value

    def _accel(self, i):
        a = tuple(c * self.p["acc"] for c in self.p["dir"])
        if not self.p["blend_rate"]:
            return a
        b = tuple(c * self.p["acc"] for c in self.p["blend_dir"])
        wa = self._weight(i / (self.n - 1))
        return tuple(x * wa + y * (1 - wa) for x, y in zip(a, b))

    def _step(self):
        seg = self.length * self.scale
        frame_inf, vertex_inf = self.p["frame_inf"], self.p["vertex_inf"]
        pos, vel = list(self.pos), list(self.vel)
        for i in range(1, self.n):
            acc = self._accel(i)
            v = tuple(x * frame_inf + a for x, a in zip(vel[i], acc))
            d = tuple(a - b for a, b in zip(pos[i - 1], pos[i]))
            length = math.sqrt(sum(c * c for c in d))
            if length > seg and length > 1e-8:
                v = tuple(x + c * ((length - seg) / length) * vertex_inf for x, c in zip(v, d))
            q = tuple(a + b for a, b in zip(pos[i], v))
            d = tuple(a - b for a, b in zip(pos[i - 1], q))
            length = math.sqrt(sum(c * c for c in d))
            if length > 1e-8:
                k = (length - seg) / length
                q = tuple(a + c * k for a, c in zip(q, d))
                v = tuple(x + c * k * vertex_inf for x, c in zip(v, d))
            pos[i], vel[i] = q, v
        self.pos, self.vel = pos, vel

    def advance(self, root_delta):
        """One frame: the root moved by root_delta; returns node offsets from the new root."""
        self.age += 1
        if self.keys:
            self._apply_keys()
        keyed_length = "length" in self.keys and not self.keys["length"][0].init_only
        if self.p["length_add"] and not keyed_length:
            self.length = max(0.0, self.length + self.p["length_add"])
        self.pos[0] = root_delta
        self._step()
        root = self.pos[0]
        self.pos = [tuple(a - b for a, b in zip(q, root)) for q in self.pos]
        return list(self.pos)

    def total_length(self):
        return sum(math.dist(a, b) for a, b in zip(self.pos, self.pos[1:]))


class GeneratorRope:
    """PathChain: one rope per generator, rooted at the generator origin (static in generator space)."""

    def __init__(self, rope):
        self.rope, self.frames = rope, []

    def at(self, frame):
        while len(self.frames) <= frame:
            self.frames.append(self.rope.advance((0.0, 0.0, 0.0)))
        return self.frames[max(frame, 0)]


def _particle_rope(p, n):
    """CHAIN trail: rope node offsets at age n, stepped from spawn with the particle as the moving root."""
    if p._rope is None:
        p._rope = []
    rope = p.line["rope"]
    while len(p._rope) <= n:
        age = len(p._rope)
        if age == 0:
            p._rope.append(list(rope.pos))
            continue
        here, _ = p.placement(age)
        before, _ = p.placement(age - 1)
        delta = tuple(a - b for a, b in zip(here, before)) if here is not None and before is not None else (0.0, 0.0, 0.0)
        p._rope.append(rope.advance(delta))
    return p._rope[n]


def _strip_init(rng, ptcl, keys):
    pair = [bgra_to_rgba(c) for c in ptcl.get("PlaceColor")]
    t = rng.random()
    s = {
        "count": max(ptcl.get("LineOfsNum"), 2), "spline_div": max(ptcl.get("SplineDivideNum"), 1),
        "axis": _AXES.get(ptcl.get("RotAxisType"), (1, 0, 0)), "order": ptcl.get("RotOrder"),
        "rot": tuple(_rf(rng, r) for r in ptcl.get("Rot")), "rot_add": tuple(_rf(rng, r) for r in ptcl.get("RotAdd")),
        "width": _rf(rng, ptcl.get("Width")), "width_add": _rf(rng, ptcl.get("WidthAdd")),
        "pivot": ptcl.get("WidthPlaceRate"), "place_tail": ptcl.get("ColorPlaceType") != 0,
        "place_color": tuple(a + (b - a) * t for a, b in zip(*pair)),
    }
    return s


def _strip_edges(p, n, scale_at, rgba, intensity):
    S = p.strip
    width_now = p.keyed("strip_width", n)
    width_now = width_now if width_now is not None else S["width"] + S["width_add"] * n
    if width_now <= 0:
        return None
    edges = []
    for k in range(S["count"]):
        age = max(n - k, 0)
        pos, anchor = p.placement(age)
        if pos is None:
            continue
        rot = p.keyed("strip_rot", age)
        rot = rot if rot is not None else tuple(r + a * age for r, a in zip(S["rot"], S["rot_add"]))
        width = p.keyed("strip_width", age)
        width = width if width is not None else S["width"] + S["width_add"] * age
        a = rotate(tuple(c * scale_at(age) for c in S["axis"]), rot, S["order"])
        r = S["pivot"]
        edges.append((tuple(c + x * width * (1 - r) for c, x in zip(pos, a)),
                      tuple(c - x * width * r for c, x in zip(pos, a)),
                      None if anchor is None else p.birth + anchor))
    tail = rgba
    if S["place_tail"]:
        pc = S["place_color"]
        tail = (pc[0] / 255 * intensity, pc[1] / 255 * intensity, pc[2] / 255 * intensity, pc[3] / 255)
    return edges, rgba, tail, S["spline_div"]


def _line_extension(ptcl):
    """Per-LineType extension after the Polyline/Line struct (raw bytes; offsets from the block start)."""
    if ptcl is None or not ptcl.has("LineFlags"):
        return None
    data, base = ptcl.data, ptcl.struct.base_size
    line_type, count = ptcl.get("LineType"), ptcl.get("LineOfsNum")

    def rangef(off):
        return struct.unpack_from("<2f", data, base + off)

    def key(off, vtype):
        rel = struct.unpack_from("<i", data, base + off)[0]
        if not rel or not 0 < rel + 4 <= len(data):
            return None
        try:
            hdr = struct.unpack_from("<I", data, rel)[0]
            fake = type("Sub", (), {})()
            fake.block, fake.offset, fake.value_type = ptcl, rel, vtype
            kf = kfm.read(fake)
            return kf if kf.frames else None
        except Exception:
            return None

    if line_type == 4 and base + 0x50 <= len(data):
        word = struct.unpack_from("<I", data, base + 0x30)[0]
        return {"rot": [rangef(i * 8) for i in range(3)], "rot_add": [rangef(0x18 + i * 8) for i in range(3)],
                "axis": _AXES.get(word & 0xF, (0, 1, 0)), "order": word >> 4 & 0xF,
                "length": rangef(0x38), "length_add": rangef(0x40),
                "rot_key": key(0x48, "vec3"), "length_key": key(0x4C, "f32")}
    if line_type == 3 and base + 0x90 <= len(data):
        return {"chain_base": base}
    if line_type == 1 and base + 0x70 + 16 * count <= len(data):
        word = struct.unpack_from("<I", data, base + 0x60)[0]
        return {"model_scale": [rangef(i * 8) for i in range(3)],
                "model_scale_add": [rangef(0x18 + i * 8) for i in range(3)],
                "rot": [rangef(0x30 + i * 8) for i in range(3)], "rot_add": [rangef(0x48 + i * 8) for i in range(3)],
                "order": word >> 4 & 0xF,
                "points": [struct.unpack_from("<3f", data, base + 0x70 + 16 * i) for i in range(count)]}
    return {}


def _line_init(template, rng, ptcl, keys, serial=0):
    ext = template.line_ext or {}
    line_type = ptcl.get("LineType")
    pair = [bgra_to_rgba(c) for c in ptcl.get("PlaceColor")]
    t = rng.random()
    place_color = tuple(a + (b - a) * t for a, b in zip(*pair))
    line = {
        "type": line_type, "count": max(ptcl.get("LineOfsNum"), 2),
        "color_place": (ptcl.get("ColorPlaceType"), ptcl.get("ColorPlaceInpType"), ptcl.get("ColorPlaceNo")),
        "place_color": place_color,
        "size_place": ((ptcl.get("SizePlaceType"), ptcl.get("SizePlaceInpType"), ptcl.get("SizePlaceNo"))
                       if ptcl.has("SizePlaceFlags") else (0, 0, 0)),
        "head": _rf(rng, ptcl.get("HeadSize")) if ptcl.has("HeadSize") else 0.0,
        "head_add": _rf(rng, ptcl.get("HeadSizeAdd")) if ptcl.has("HeadSizeAdd") else 0.0,
        "place": _rf(rng, ptcl.get("PlaceSize")) if ptcl.has("PlaceSize") else 0.0,
        "place_add": _rf(rng, ptcl.get("PlaceSizeAdd")) if ptcl.has("PlaceSizeAdd") else 0.0,
        "keys": {name: (kf, kfm.draw_rates(kf, rng)) for name, kf in template.line_keys.items()},
    }
    if line_type == 4 and ext:
        line.update(rot=tuple(_rf(rng, r) for r in ext["rot"]), rot_add=tuple(_rf(rng, r) for r in ext["rot_add"]),
                    axis=ext["axis"], order=ext["order"], length=_rf(rng, ext["length"]),
                    length_add=_rf(rng, ext["length_add"]))
        for name in ("rot_key", "length_key"):
            if ext.get(name) is not None:
                line["keys"][name] = (ext[name], kfm.draw_rates(ext[name], rng))
    elif line_type == 1 and ext:
        line.update(model_scale=tuple(_rf(rng, r) for r in ext["model_scale"]),
                    model_scale_add=tuple(_rf(rng, r) for r in ext["model_scale_add"]),
                    rot=tuple(_rf(rng, r) for r in ext["rot"]), rot_add=tuple(_rf(rng, r) for r in ext["rot_add"]),
                    order=ext["order"], points=ext["points"])
    elif line_type == 3 and ext:
        gen_scale = template.record.gen.get("ParticleScale")[0] or 1.0 if template.record.gen else 1.0
        line["rope"] = Rope(_chain_params(ptcl.data, ext["chain_base"], rng, line["count"]), line["count"], gen_scale,
                            _rope_keys(ptcl, rng), birth=0)
    elif line_type in (1, 3, 4):
        line["type"] = 0   # extension missing: draw as a trail
    if template.cloth_ext is not None:
        line["cloth"] = _cloth_init(template, rng, ptcl, line["count"], serial)
    return line


def _gradient(i, last, place_type, inp_type, place_no):
    """calc_color_gradient 0x9B52A0: blend factor toward the 'place' value for point i."""
    if place_type == 0 or last <= 0:
        return 0.0
    p = min(max(place_no, 0), last)
    if place_type == 1:
        t = i / last
    elif place_type == 2:
        t = (i / p if p else 1.0) if i < p else ((last - i) / (last - p) if last > p else 1.0) if i > p else 1.0
    elif place_type == 3:
        t = 0.0 if i <= p else (i - p) / (last - p)
    elif place_type == 4:
        t = i / p if i < p and p else 1.0
    else:
        t = i / last
    if inp_type == 1:
        return math.sin(math.pi * t / 2)
    if inp_type == 2:
        return 1.0 - math.cos(math.pi * t / 2)
    if inp_type == 3:
        return (1.0 - math.cos(math.pi * t)) / 2
    return t


def _line_keyed(p, name, age):
    entry = p.line["keys"].get(name)
    if entry is None:
        return None
    kf, rates = entry
    timer = (0 if kf.init_only else age) if kf.uses_particle_age else p.birth + (0 if kf.init_only else age)
    return kfm.evaluate(kf, timer, rates)


def _line_points(p, n, pos, anchor, scale, rgba, intensity):
    """[(pos, anchor, half width, rgba)] for a Polyline/Line particle at age n; None if it died."""
    L = p.line
    count, last = L["count"], L["count"] - 1
    head = _line_keyed(p, "head_size", n)
    head = head if head is not None else L["head"] + L["head_add"] * n
    place = _line_keyed(p, "place_size", n)
    place = place if place is not None else L["place"] + L["place_add"] * n
    if head <= 0 and L["size_place"][0] == 0:
        return None
    place_rgba = (L["place_color"][0] / 255 * intensity, L["place_color"][1] / 255 * intensity,
                  L["place_color"][2] / 255 * intensity, L["place_color"][3] / 255)
    if L["type"] == 4 and "axis" in L:     # LENGTH: rigid stick
        length = _line_keyed(p, "length_key", n)
        length = length if length is not None else L["length"] + L["length_add"] * n
        if length <= 0 and L["length_add"]:
            return None
        rot = _line_keyed(p, "rot_key", n)
        rot = rot if rot is not None else tuple(r + a * n for r, a in zip(L["rot"], L["rot_add"]))
        points = [(tuple(c + o for c, o in zip(pos, rotate(tuple(a * length * scale * i / last for a in L["axis"]),
                                                             rot, L["order"]))), anchor) for i in range(count)]
    elif L["type"] == 1 and "points" in L:  # FIX: stored points
        rot = tuple(r + a * n for r, a in zip(L["rot"], L["rot_add"]))
        ms = tuple(m + a * n for m, a in zip(L["model_scale"], L["model_scale_add"]))
        points = [(tuple(c + o for c, o in zip(pos, rotate(tuple(v * scale * m for v, m in zip(pt, ms)),
                                                             rot, L["order"]))), anchor) for pt in L["points"]]
    elif "cloth" in L:                       # cloth: the vertices of cClothVertex, head = the particle
        points = [(q, anchor) for q in _cloth_points(p, n)]
    elif L["type"] == 3 and "rope" in L:     # CHAIN: rope rooted at the particle
        offsets = _particle_rope(p, n)
        points = [(tuple(c + o for c, o in zip(pos, off)), anchor) for off in offsets]
    else:                                   # FOLLOW: the last N positions; FIX_END pulls toward the spawn
        points = []
        for k in range(count):
            q, a = p.placement(max(n - k, 0))
            if q is None:
                q, a = pos, anchor
            points.append((q, a))
        if L["type"] == 2:
            end = p.pos
            points = [(tuple(h * (1 - t * t) + e * t * t for h, e in zip(q, end)), None)
                      for q, t in ((q, k / last) for k, (q, _a) in enumerate(points))]
    out = []
    for i, (q, a) in enumerate(points):
        fs = _gradient(i, last, *L["size_place"])
        fc = _gradient(i, last, *L["color_place"])
        width = (head + (place - head) * fs) * scale
        color = tuple(h + (pl - h) * fc for h, pl in zip(rgba, place_rgba))
        out.append((q, a, width, color))
    return out


# -- cloth (ClothPolyline 12 / ClothTexline 13 / ClothLine 14) ---------------------------------------------------
# initParticlePolyline switches on ClothType (0x176): 0 CHAIN init 0x981530 / move 0x992EC0 / vertices 0x9DFFE0,
# 1 CURVE 0x9820D0 / 0x993560 / 0x9E1B80, 2 ZIGZAG 0x983330 / 0x9944D0 / 0x9E2570. The gatherer sub_9B32E0 draws
# cClothVertex[mSetNo].p[0..N-1]: point 0 is the particle (P0), point N-1 the tail P1 = generator . SubOfs.

CLOTH_TYPES = (12, 13, 14)
_CLOTH_EXT_SIZE = {0: 0xC0, 1: 0x60, 2: 0x90}


def _vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vmul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _vlerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _vlen(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _block_key(block, at, vtype):
    """Keyframe whose rel32 offset (from the block start) is stored at block.data[at], or None."""
    data = block.data
    rel = struct.unpack_from("<i", data, at)[0]
    if not rel or not 0 < rel + 4 <= len(data):
        return None
    try:
        fake = type("Sub", (), {})()
        fake.block, fake.offset, fake.value_type = block, rel, vtype
        kf = kfm.read(fake)
        return kf if kf.frames else None
    except Exception:
        return None


def _cloth_extension(ptcl):
    """Raw cloth extension after the Polyline/Texline/Line struct, or None (layout in efl_import_plan.md)."""
    if ptcl is None or ptcl.type not in CLOTH_TYPES:
        return None
    kind = ptcl.get("ClothType") if ptcl.has("ClothType") else 0
    data, base = ptcl.data, ptcl.struct.base_size
    if kind not in _CLOTH_EXT_SIZE or base + _CLOTH_EXT_SIZE[kind] > len(data):
        return None

    def rangef(off):
        return struct.unpack_from("<2f", data, base + off)

    def u16(off):
        return struct.unpack_from("<H", data, base + off)[0]

    def key(off, vtype):
        return _block_key(ptcl, base + off, vtype)

    if kind == 0:   # CHAIN: EFL_PARAM_CHAIN (0x00-0x8F) + ConstOff / distance / SubRange
        return {
            "kind": 0, "option": u16(0), "rot_byte": data[base + 4], "blend_byte": data[base + 5], "pre": u16(6),
            "length": rangef(0x08), "length_add": rangef(0x10), "acc": rangef(0x20), "frame_inf": rangef(0x28),
            "vertex_inf": rangef(0x30), "rot": [rangef(0x38 + 8 * i) for i in range(3)],
            "blend_rot": [rangef(0x50 + 8 * i) for i in range(3)],
            "length_key": key(0x80, "f32"), "rot_key": key(0x84, "vec3"), "blend_rot_key": key(0x88, "vec3"),
            "const_off": (u16(0x90), u16(0x92)), "dist_conv": (u16(0x94), u16(0x96)), "dist_exp": rangef(0x98),
            "sub_range": [rangef(0xA0 + 8 * i) for i in range(3)],
            "sub_type": struct.unpack_from("<I", data, base + 0xB8)[0], "sub_div": u16(0xBC),
        }
    ext = {   # CURVE, shared by ZIGZAG
        "kind": kind, "rot": [rangef(8 * i) for i in range(3)], "rot_add": [rangef(0x18 + 8 * i) for i in range(3)],
        "rot_byte": data[base + 0x30], "dir_axis": data[base + 0x31] & 0xF, "curve_type": data[base + 0x31] >> 4,
        "flags": u16(0x32), "rot_key": key(0x34, "vec3"), "coef": rangef(0x38),
        "sub_range": [rangef(0x40 + 8 * i) for i in range(3)],
        "sub_type": struct.unpack_from("<I", data, base + 0x58)[0], "sub_div": u16(0x5C),
    }
    if kind == 2:
        ext.update(amp=[rangef(0x60 + 8 * i) for i in range(3)], update=(u16(0x78), u16(0x7A)))
    return ext


def _calc_dir(rot, rot_byte):
    """calcDir: AxisVector(low nibble) rotated by rot in Order (high nibble)."""
    return rotate(_AXES.get(rot_byte & 0xF, (0, 1, 0)), rot, rot_byte >> 4)


def _cloth_init(template, rng, ptcl, count, serial):
    e = template.cloth_ext
    gen = template.record.gen
    div = e["sub_div"]
    t = (serial % (div + 1)) / div if div else rng.random()
    particle_scale = (gen.get("ParticleScale")[0] or 1.0) if gen is not None else 1.0
    sub = _shape_point(e["sub_range"], e["sub_type"], rng, t)
    c = {"kind": e["kind"], "n": count, "sub_ofs": _vmul(sub, particle_scale), "world": template.world_axes,
         "keys": {}, "frames": [], "state": None}
    for name in ("length_key", "rot_key", "blend_rot_key"):
        if e.get(name) is not None:
            c["keys"][name] = (e[name], kfm.draw_rates(e[name], rng))
    if e["kind"] == 0:
        param = ptcl.get("ClothParam") if ptcl.has("ClothParam") else 0
        c.update(option=e["option"], param=param, pre=e["pre"], rot_byte=e["rot_byte"], blend_byte=e["blend_byte"],
                 length=max(_rf(rng, e["length"]), 0.0), length_add=_rf(rng, e["length_add"]),
                 acc=_rf(rng, e["acc"]), frame_inf=_rf(rng, e["frame_inf"]), vertex_inf=_rf(rng, e["vertex_inf"]),
                 dir0=_calc_dir([_rf(rng, r) for r in e["rot"]], e["rot_byte"]),
                 dir1=_calc_dir([_rf(rng, r) for r in e["blend_rot"]], e["blend_byte"]),
                 const_off=_ru(rng, e["const_off"]) if param & 3 else 0,
                 dist_rate=1.0 / (_ru(rng, e["dist_conv"]) + 1), dist_exp=_rf(rng, e["dist_exp"]))
    else:
        c.update(rot=tuple(_rf(rng, r) for r in e["rot"]), rot_add=tuple(_rf(rng, r) for r in e["rot_add"]),
                 rot_byte=e["rot_byte"], dir_axis=e["dir_axis"], curve_type=e["curve_type"], flags=e["flags"],
                 coef=_rf(rng, e["coef"]))
        if e["kind"] == 2:
            c.update(amp=e["amp"], update=e["update"], seed=rng.random())
    return c


def _cloth_keyed(p, c, name, age):
    entry = c["keys"].get(name)
    if entry is None:
        return None
    kf, rates = entry
    timer = (0 if kf.init_only else age) if kf.uses_particle_age else p.birth + (0 if kf.init_only else age)
    return kfm.evaluate(kf, timer, rates)


def _to_generator(c, d):
    """A world-fixed direction (game world axes) in generator space at import, if known."""
    W = c["world"]
    if W is None:
        return d
    return (W[0] * d[0] + W[1] * d[1] + W[2] * d[2], W[3] * d[0] + W[4] * d[1] + W[5] * d[2],
            W[6] * d[0] + W[7] * d[1] + W[8] * d[2])


class _ClothChain:
    """CHAIN cloth (0x992EC0 move + 0x9DFFE0 vertices): a rope from P0 to P1 under a constant pull.
    status 0x80 = tail pinned, 0x40 = head pinned as well; 0x80 clear = head only. Lengths are cm, unscaled."""

    def __init__(self, p, c, P0, P1, vel):
        self.p, self.c, self.n = p, c, c["n"]
        self.status, self.timer = 0xC0, c["const_off"]
        self.dir0 = self.dir1 = (0.0, 0.0, 0.0)
        self._directions(0, vel)
        keyed = _cloth_keyed(p, c, "length_key", 0)
        if keyed is not None:
            self.L = max(keyed, 0.0)
        elif c["param"] & 4:
            self.L = _vlen(_vsub(P0, P1)) + c["dist_exp"]
        else:
            self.L = c["length"]
        self._rest(P0, P1)
        for _ in range(c["pre"]):
            self._step(P0, P1)

    def _directions(self, age, vel):
        c = self.c
        for bit, src_bit, world_bit, key, base, byte in (
                (0x40, 4, 1, "rot_key", "dir0", "rot_byte"),
                (0x80, 8, 2, "blend_rot_key", "dir1", "blend_byte")):
            if not self.status & bit:
                continue
            if c["option"] & src_bit and _vlen(vel) > 1e-6:
                d = _unit(vel)[0]
            else:
                rot = _cloth_keyed(self.p, c, key, age)
                d = _calc_dir(rot, c[byte]) if rot is not None else c[base]
                if c["option"] & world_bit:
                    d = _to_generator(c, d)
            setattr(self, base, d)

    def _rest(self, P0, P1):
        n, acc = self.n, self.c["acc"]
        g0, g1 = _vmul(self.dir0, acc), _vmul(self.dir1, acc)
        P, V = [None] * n, [g0] * n
        if not self.status & 0x80:
            P[0], P[-1] = P0, _vadd(P0, _vmul(_unit(g0)[0], self.L))
            V[0] = (0.0, 0.0, 0.0)
        elif self.status & 0x40:
            P[0], P[-1] = P0, P1
            V = [_vlerp(g0, g1, k / (n - 1)) for k in range(n)]
            V[0] = V[-1] = (0.0, 0.0, 0.0)
        else:
            P[-1], P[0] = P1, _vadd(P1, _vmul(_unit(g1)[0], self.L))
            V = [g1] * n
            V[-1] = (0.0, 0.0, 0.0)
        for k in range(1, n - 1):
            P[k] = _vlerp(P[0], P[-1], k / (n - 1))
        self.P, self.V = P, V

    def _step(self, P0, P1):
        n, c = self.n, self.c
        seg = self.L / (n - 1)
        vertex_inf = c["vertex_inf"]
        P, V = list(self.P), [_vmul(v, c["frame_inf"]) for v in self.V]
        g0, g1 = _vmul(self.dir0, c["acc"]), _vmul(self.dir1, c["acc"])

        def relax(k, j, g):
            v = _vadd(V[k], g)
            d = _vsub(P[j], P[k])
            length = _vlen(d)
            if length > seg:
                v = _vadd(v, _vmul(d, (length - seg) / length * vertex_inf))
            q = _vadd(P[k], v)
            d = _vsub(P[j], q)
            length = _vlen(d)
            if length > 1e-8:
                corr = _vmul(d, (length - seg) / length)
                q = _vadd(q, corr)
                v = _vadd(v, _vmul(corr, vertex_inf))
            P[k], V[k] = q, v

        st = self.status
        if not st & 0x80:
            P[0] = P0
            for k in range(1, n):
                relax(k, k - 1, g0)
        elif st & 0x40:
            P[0], P[-1] = P0, P1
            for k in range(n - 2, 0, -1):
                relax(k, k + 1, g1)
            for k in range(1, n - 1):
                relax(k, k - 1, g0)
        else:
            P[-1] = P1
            for k in range(n - 2, -1, -1):
                relax(k, k + 1, g1)
        self.P, self.V = P, V

    def advance(self, age, P0, P1, vel):
        c = self.c
        if c["param"] & 3 and self.timer > 0:   # ConstOff: release one end
            self.timer -= 1
            if self.timer == 0:
                self.status &= ~0x40 if c["param"] & 1 else ~0x80
        keyed = _cloth_keyed(self.p, c, "length_key", age)
        if keyed is not None:
            self.L = max(keyed, 0.0)
        elif c["param"] & 4:
            if self.status & 0xC0 == 0xC0:
                D = _vlen(_vsub(P0, P1)) + c["dist_exp"]
                if D / (self.n - 1) > abs(D - self.L):
                    self.L = D
                else:
                    self.L += c["dist_rate"] * (D - self.L)
        elif c["length_add"]:
            self.L = max(self.L + c["length_add"], 0.0)
        self._directions(age, vel)
        self._step(P0, P1)
        return list(self.P)


def _cloth_curve(p, c, age, P0, P1, vel):
    """CURVE (0x993560 / 0x9E1B80): P0 -> P1 bent along dir by CurveCoef."""
    n = c["n"]
    rot = _cloth_keyed(p, c, "rot_key", age)
    rot = rot if rot is not None else tuple(r + a * age for r, a in zip(c["rot"], c["rot_add"]))
    axis = _AXES.get(c["rot_byte"] & 0xF, (0, 1, 0))
    d = rotate(axis, rot, c["rot_byte"] >> 4)
    if c["dir_axis"] != 6 and _vlen(vel) > 1e-6:   # aligned to the particle's velocity (approximate)
        d = _shortest_arc_rotate(axis, vel, d)
    span = _vsub(P1, P0)
    amp = c["coef"] * (_vlen(span) if c["flags"] & 1 else 1.0)
    out = []
    if c["curve_type"]:
        for k in range(n):
            u = k / (n - 1)
            out.append(_vadd(_vlerp(P0, P1, u), _vmul(d, amp * math.sin(math.pi * u))))
        return out
    M = _vadd(_vmul(_vadd(P0, P1), 0.5), _vmul(d, amp))
    half = _vmul(span, 0.5)

    def hermite(s, A, B, TA, TB):
        s2, s3 = s * s, s * s * s
        h = (2 * s3 - 3 * s2 + 1, s3 - 2 * s2 + s, 3 * s2 - 2 * s3, s3 - s2)
        return tuple(h[0] * a + h[1] * ta + h[2] * b + h[3] * tb for a, b, ta, tb in zip(A, B, TA, TB))

    for k in range(n):
        u = k / (n - 1)
        if u < 0.5:
            out.append(hermite(2 * u, P0, M, _vsub(M, P0), half))
        else:
            out.append(hermite(2 * u - 1, M, P1, half, _vsub(P1, M)))
    out[0], out[-1] = P0, P1
    return out


def _cloth_zigzag(c, age, points):
    """ZIGZAG (0x9944D0 / 0x9E2570): random per-vertex jitter, re-rolled every VertexUpdateFrame(+rand) frames
    (once with flag 0x400), in a frame whose +Z runs P[0] -> P[N-1]. The 0x100 ease-in weight isn't modelled."""
    if "jitter" not in c:   # the update schedule belongs to the particle: roll it once
        rng = random.Random(c["seed"])
        schedule, at = [], 0
        while at < 4096:
            amp = [_rf(rng, r) for r in c["amp"]]
            units = [(rng.random() - 0.5, rng.random() - 0.5, rng.random() - 0.5) for _ in range(c["n"])]
            schedule.append((at, amp, units))
            if c["flags"] & 0x400:
                break
            at += max(_ru(rng, c["update"]), 1)
        c["jitter"] = schedule
    current = None
    for at, amp, units in c["jitter"]:
        if at > age:
            break
        current = amp, units
    amp, units = current
    n = c["n"]
    span = _vsub(points[-1], points[0])
    if c["flags"] & 0x200:   # amplitude limited to the mean segment length
        mean = _vlen(span) / (n - 1)
        top = max(abs(a) for a in amp) or 1.0
        amp = [a * min(1.0, mean / top) for a in amp]
    axis = _unit(span)[0] if _vlen(span) > 1e-6 else (0.0, 0.0, 1.0)
    out = list(points)
    for k in range(1, n - 1):
        j = (units[k][0] * amp[0], units[k][1] * amp[1], units[k][2] * amp[2])
        out[k] = _vadd(out[k], _shortest_arc_rotate((0.0, 0.0, 1.0), axis, j))
    return out


def _cloth_points(p, n):
    """Cloth vertex positions at age n (in the particle's anchor space), head (the particle) first."""
    c = p.line["cloth"]
    frames = c["frames"]
    while len(frames) <= n:
        age = len(frames)
        P0, _ = p.placement(age)
        if P0 is None:
            frames.append(frames[-1] if frames else [(0.0, 0.0, 0.0)] * c["n"])
            continue
        before = p.placement(age - 1)[0] if age else None
        vel = _vsub(P0, before) if before is not None else (0.0, 0.0, 0.0)
        P1 = c["sub_ofs"]
        if c["kind"] == 0:
            if c["state"] is None:
                c["state"] = _ClothChain(p, c, P0, P1, vel)
                frames.append(list(c["state"].P))
            else:
                frames.append(c["state"].advance(age, P0, P1, vel))
        else:
            points = _cloth_curve(p, c, age, P0, P1, vel)
            frames.append(_cloth_zigzag(c, age, points) if c["kind"] == 2 else points)
    return frames[n]


def _path_init(template, move, rng, spawn_point, keys, axis, order):
    """Per-particle path state (initParticleMovePath*)."""
    kind = move.type
    if "move_rot" in keys:
        kf, rates = keys["move_rot"]
        rot = tuple(kfm.evaluate(kf, 0, rates))
    else:
        rot = tuple(_rf(rng, r) for r in move.get("Rot"))
    keyed_timer = template.move_keys.get("release")
    release_timer = (int(kfm.evaluate(keyed_timer, 0, kfm.draw_rates(keyed_timer, rng)) or 0) if keyed_timer
                     else _ru(rng, move.get("ReleaseFrame")))
    path = {
        "kind": kind, "spawn": spawn_point, "rot": rot, "order": order, "axis": axis,
        "option": move.get("PathOptionFlag"), "release_type": move.get("ReleaseType"),
        "release_timer": release_timer, "scale3": template.path_scale3,
        "speed": 0.0, "accel": 0.0, "d0": 0.0, "max_d": 0.0, "strip": None, "strip_loop": False,
        "gravity": _rf(rng, move.get("Gravity")),
        "fresh_speed": _rf(rng, move.get("Speed")), "fresh_accel": _rf(rng, move.get("Acceleration")),
    }
    if kind == 5:
        kf = template.path_ofs
        if kf is None:
            path["kind"] = 6   # no offset keys: degrade to a line of zero length
        else:
            path["ofs_key"] = (kf, kfm.draw_rates(kf, rng))
    if path["kind"] != 5:
        keyed_speed = keys.get("speed")
        path["speed"] = (kfm.evaluate(keyed_speed[0], 0, keyed_speed[1]) if keyed_speed else _rf(rng, move.get("Speed")))
        path["accel"] = _rf(rng, move.get("Acceleration"))
        path["d0"] = _rf(rng, move.get("Distance")) if move.has("Distance") else 0.0
        if move.has("PathLength"):
            path["max_d"] = move.get("PathLength") * template.path_length_scale
        if kind == 3:
            path["strip"] = template.strip
            path["strip_loop"] = bool(move.get("PathStripFlag") & 0x08)
    path["rope"] = template.path_rope if kind == 4 else None
    return path


def simulate(record, seed=0, max_frames=300, pat_counts=(1,), strip_points=None, range_strip=None, ground_y=None,
             world_axes=None):
    """All particles a record emits in max_frames game frames; pat_counts = patterns per flipbook sequence;
    strip_points = the .efs curve (cm) for PathStrip moves; world_axes = game world -> generator space (row-major
    3x3) for world-fixed cloth pulls."""
    if record.gen is None:
        return []
    rng = random.Random(seed)
    template = _Template(record, rng, strip_points, range_strip, ground_y, world_axes)
    template.max_frames = max_frames
    particles = []
    divide = record.gen.get("RangeDivideNum")
    # a particle's serial (openParticle 0x9DF333) picks its RangeDivideNum slot and ORDER strip index: the particle
    # count, or with RangeOptionFlags 1 EACH_FRAME the count of spawning frames (a frame's batch shares one slot)
    each_frame = bool(record.gen.get("RangeOptionFlags") & 1)
    serial = frames_done = 0
    for frame, count in emission_schedule(record.gen, rng, max_frames):
        for _ in range(count):
            number = frames_done if each_frame else serial
            t = (number % (divide + 1)) / divide if divide else rng.random()
            serial += 1
            particles.append(spawn(template, rng, frame, t, pat_counts or (1,), number))
            if len(particles) >= MAX_PARTICLES:
                return particles
        frames_done += 1
    return particles


def _shape_at(p, n):
    """Polygon (W, 0, H, 0) / PrimModel (r0, r1, h0, h1) at age n; None when a Polygon shrank to nothing."""
    S = p.shape
    values = []
    for i in range(4):
        name = f"shape{i}"
        value = p.keyed_or(name, n, S["base"][i], S["add"][i])
        if S["kind"] == "polygon" and i in (0, 2):
            if p.is_keyed(name):
                value = max(value, 0.0)
            elif S["add"][i] and value <= 0:   # sub_98EAA0: a shrinking polygon dies
                return None
        values.append(value)
    return tuple(values)


def _wrap_uv(x):
    return (x + 1.0) % 2.0 - 1.0


def _scroll_at(p, n):
    """Model UV offset at age n: += speed each frame (keyframes give the speed), wrapped to [-1, 1]."""
    S = p.scroll
    keyed = [p.is_keyed("scroll_u"), p.is_keyed("scroll_v")]
    if not any(keyed) and "scroll_u" not in p.keys and "scroll_v" not in p.keys:
        return tuple(_wrap_uv(v * n) for v in S["speed"])
    if S["offsets"] is None:
        S["offsets"] = [(0.0, 0.0)]
    offsets = S["offsets"]
    while len(offsets) <= n:
        age = len(offsets)
        u, v = offsets[-1]
        du = p.keyed_or("scroll_u", age, S["speed"][0], 0.0)
        dv = p.keyed_or("scroll_v", age, S["speed"][1], 0.0)
        offsets.append((_wrap_uv(u + du), _wrap_uv(v + dv)))
    return offsets[n]


def _pattern_at(p, n):
    keyed = p.keyed("pattern", n)
    if keyed is not None and not p.pat_key_is_speed:
        return min(max(keyed, 0.0), p.pat_count - 1), True
    if keyed is not None:   # the keyframe gives the speed: integrate it
        step = sum(p.keyed("pattern", a) for a in range(n))
    else:
        step = p.pat_speed * n
    if not step:
        return p.pattern, True
    pattern = p.pattern - step if p.anim_flag & ANIM_REVERSE else p.pattern + step
    if 0 <= pattern < p.pat_count:
        return pattern, True
    if p.anim_flag & ANIM_LOOP:
        return pattern % p.pat_count, True
    if p.anim_flag & ANIM_FINISH:
        return 0.0, False
    return min(max(pattern, 0.0), p.pat_count - 1), True


def state_at(p, frame):
    """ParticleState at a game frame, or None if the particle isn't alive."""
    n = frame - p.birth
    if n < 0 or n >= p.lifetime():
        return None
    alpha = 1.0
    if p.life:
        appear, keep, vanish = p.life
        if n < appear:
            alpha = (n + 1) / (appear + 1)
        elif n >= appear + keep:
            alpha = max(0.0, 1.0 - (n - appear - keep + 1) / (vanish + 1))
    scale = p.keyed_or("scale", n, p.scale, p.scale_add)
    if scale <= 0:
        return None
    pattern, alive = _pattern_at(p, n)
    if not alive:
        return None
    color = p.keyed("color", n)
    color = bgra_to_rgba(color) if color is not None else p.color
    intensity = p.keyed("intensity", n)
    intensity = min(max(intensity if intensity is not None else p.intensity, 0.0), INTENSITY_MAX)
    if p.refract:   # intensity only scales the refraction offset
        intensity = 1.0
    angle = p.keyed_or("angle", n, p.angle, p.angle_add)
    rot = tuple(p.keyed_or("rot", n, tuple(p.rot), tuple(p.rot_add)))
    model_scale = tuple(max(c, 0.0) for c in p.keyed_or("model_scale", n, tuple(p.model_scale),
                                                            tuple(p.model_scale_add)))
    rgba = (color[0] / 255 * intensity, color[1] / 255 * intensity, color[2] / 255 * intensity, color[3] / 255)
    pos, anchor_age = p.placement(n)
    if pos is None:
        return None
    anchor = None if anchor_age is None else p.birth + anchor_age
    line = strip = light = shape = uv_scroll = None
    if p.shape is not None:
        shape = _shape_at(p, n)
        if shape is None:
            return None
    if p.scroll is not None:
        uv_scroll = _scroll_at(p, n)
    if p.light is not None:
        L = p.light
        start = max(L["start"] + L["start_add"] * n, 0.0)
        end = max(L["end"] + L["end_add"] * n, 0.0)
        if start <= 0 and end <= 0:
            return None
        light = (start * scale, end * scale)
    if p.line is not None:
        line = _line_points(p, n, pos, anchor, scale, rgba, intensity)
        if line is None:
            return None
    if p.strip is not None:
        def scale_at(age):
            keyed = p.keyed("scale", age)
            return keyed if keyed is not None else p.scale + p.scale_add * age
        strip = _strip_edges(p, n, scale_at, rgba, intensity)
        if strip is None:
            return None
    return ParticleState(pos, alpha, scale, min(max(p.aspect, 0.0), 15.9375), angle, rot, model_scale,
                         rgba, p.sequence, int(pattern), anchor, line, strip, light, shape, uv_scroll, p.flip)
