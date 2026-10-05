"""Approximate particle simulation of one EFL record, ported from the DX9 runtime (efl_import_plan.md M2).

Pure Python. Positions are in the generator's local frame, game units (cm, Y-up), one step per game frame (60 fps).
Sources (DX9):
    emission   uknGenBehaviorFunc1 0x9DDCB0: wait WaitFrame; then bursts of LoopNum frames, each spawning
               SetNum (0xA8) particles per frame; pause SetFrame frames; burst count = 0xAC (0 = forever)
    spawn      sub_999040 (RangeType shapes on Range[3]), scaled by UknRangeThing[1..3]
    direction  calcDir 0x9DEC60: axis (move RotAxisType) rotated by move Rot (RotOrder), blended toward the spawn
               offset for RangeDirType diffuse/converge by UknRangeThing[0]
    motion     moveParticleMoveAdd/Mul: pos += vel - (0, fall, 0); Add: vel += dir * Acceleration;
               Mul: vel *= SpeedCoef; fall += Gravity (Add only)
    life       sub_9729B0: Appear / Keep / Vanish frames, each s + rand % (r + 1); alpha ramps in, holds, ramps out
    flipbook   sub_961DB0: pattern += PatSpeed per frame when AnimFlag MOVE; LOOP wraps, FINISH kills, else holds
Not modelled: keyframe curves, path move types (3-6), collision, emitter motion after spawn (particles here follow
the generator), the game's RNG table, LoopFrameDist/SetFrameDist fractional spreading.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

ANIM_MOVE, ANIM_LOOP, ANIM_REVERSE, ANIM_FINISH = 1, 2, 4, 8
NO_LIFE_FRAMES = 120          # records without a life block: show particles this long
MAX_PARTICLES = 4000          # per record, to keep previews responsive

_AXES = {0: (1, 0, 0), 1: (-1, 0, 0), 2: (0, 1, 0), 3: (0, -1, 0), 4: (0, 0, 1), 5: (0, 0, -1), 6: (0, 0, 1)}
# setMatFromAngle 0x95FF60: RotOrder enum -> order the axes are applied in
ROT_ORDERS = ("ZYX", "ZXY", "YZX", "YXZ", "XZY", "XYZ")


def _rf(rng, pair):
    s, r = pair
    return s + rng.random() * r


def _ru(rng, pair):
    s, r = pair
    return s + (rng.randrange(r + 1) if r else 0)


def _rotate(vec, angles, order):
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


@dataclass
class Particle:
    birth: int
    pos: tuple
    vel: tuple
    accel: tuple
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
    pattern: float
    pat_speed: float
    pat_count: int
    anim_flag: int

    def lifetime(self):
        return sum(self.life) if self.life else NO_LIFE_FRAMES


@dataclass
class ParticleState:
    pos: tuple
    alpha: float
    scale: float
    angle: float
    rot: tuple
    model_scale: tuple
    pattern: int


def emission_schedule(gen, rng, max_frames):
    """[(frame, count)] following the generator state machine."""
    out = []
    frame = _ru(rng, gen.get("WaitFrame"))
    bursts = _ru(rng, gen.get("BurstNum"))   # 0 = repeat until max_frames
    done = 0
    while frame < max_frames:
        length = max(_ru(rng, gen.get("LoopNum")), 1)
        for f in range(frame, min(frame + length, max_frames)):
            count = _ru(rng, gen.get("SetNum"))
            if count:
                out.append((f, count))
        frame += length + _ru(rng, gen.get("SetFrame"))
        done += 1
        if bursts and done >= bursts:
            break
    return out


def spawn_offset(gen, rng, t):
    """sub_999040: point on the RangeType shape; t is the burst position in [0, 1)."""
    (xs, xr), (ys, yr), (zs, zr) = gen.get("Range")
    kind = gen.get("RangeType")
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
    scale = [_rf(rng, r) for r in gen.get("UknRangeThing")[1:]]
    return x * scale[0], y * scale[1], z * scale[2]


def _direction(gen, move, rng, offset):
    if move is None or not move.has("Rot"):
        return (0.0, 1.0, 0.0)
    angles = [_rf(rng, r) for r in move.get("Rot")]
    d = _rotate(_AXES.get(move.get("RotAxisType"), (0, 1, 0)), angles, move.get("RotOrder"))
    dir_type = gen.get("RangeDirType")
    if dir_type in (1, 2) and any(offset):
        target = _normalize(offset if dir_type == 1 else tuple(-c for c in offset))
        f = min(max(_rf(rng, gen.get("UknRangeThing")[0]), 0.0), 1.0)
        d = _normalize(tuple(a * (1 - f) + b * f for a, b in zip(d, target)))
    return d


def spawn(record, rng, birth, t, pat_count=1):
    gen, ptcl, life, move = record.gen, record.ptcl, record.life, record.move
    offset = spawn_offset(gen, rng, t)
    d = _direction(gen, move, rng, offset)
    speed = accel = coef = gravity = 0.0
    if move is not None and move.type in (1, 2):
        speed = _rf(rng, move.get("Speed"))
        if move.type == 1:
            accel = _rf(rng, move.get("Acceleration"))
            gravity = _rf(rng, move.get("Gravity"))
        else:
            coef = _rf(rng, move.get("SpeedCoef"))
    life_frames = None
    if life is not None and life.type in (1, 2):
        life_frames = tuple(_ru(rng, life.get(k)) for k in ("AppearFrame", "KeepFrame", "VanishFrame"))
        if not any(life_frames):
            life_frames = (0, 1, 0)

    def has(name):
        return ptcl is not None and ptcl.has(name)

    scale = _rf(rng, ptcl.get("Scale")) if has("Scale") else 1.0
    scale_add = _rf(rng, ptcl.get("ScaleAdd")) if has("ScaleAdd") else 0.0
    angle = _rf(rng, ptcl.get("Angle")) if has("Angle") else 0.0
    angle_add = _rf(rng, ptcl.get("AngleAdd")) if has("AngleAdd") else 0.0
    rot = tuple(_rf(rng, r) for r in ptcl.get("Rot")) if has("Rot") else (0.0, 0.0, 0.0)
    rot_add = tuple(_rf(rng, r) for r in ptcl.get("RotAdd")) if has("RotAdd") else (0.0, 0.0, 0.0)
    if has("ModelScale"):
        model_scale = tuple(_rf(rng, r) for r in ptcl.get("ModelScale"))
        model_scale_add = tuple(_rf(rng, r) for r in ptcl.get("ModelScaleAdd"))
    else:
        model_scale, model_scale_add = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    pattern, pat_speed, anim_flag = 0.0, 0.0, 0
    if has("PatSpeed"):
        anim_flag = ptcl.get("AnimFlag")
        pat_speed = ptcl.get("PatSpeed") if anim_flag & ANIM_MOVE else 0.0
        pattern = float(min(_ru(rng, (ptcl.get("PatNoMin"), ptcl.get("PatNoRange"))), max(pat_count - 1, 0)))
    return Particle(birth, offset, tuple(c * speed for c in d), tuple(c * accel for c in d), coef, gravity,
                    life_frames, scale, scale_add, angle, angle_add, rot, rot_add, model_scale, model_scale_add,
                    pattern, pat_speed, max(pat_count, 1), anim_flag)


def simulate(record, seed=0, max_frames=300, pat_count=1):
    """All particles a record emits in max_frames game frames."""
    if record.gen is None:
        return []
    rng = random.Random(seed)
    particles = []
    divide = record.gen.get("RangeDivideNum")
    serial = 0
    for frame, count in emission_schedule(record.gen, rng, max_frames):
        for i in range(count):
            if divide:
                t = (serial % (divide + 1)) / divide
            else:
                t = rng.random()
            serial += 1
            particles.append(spawn(record, rng, frame, t, pat_count))
            if len(particles) >= MAX_PARTICLES:
                return particles
    return particles


def state_at(p, frame):
    """ParticleState at a game frame, or None if the particle isn't alive."""
    n = frame - p.birth
    if n < 0 or n >= p.lifetime():
        return None
    # position: n steps of pos += vel - (0, fall, 0)
    if p.coef and abs(p.coef - 1.0) > 1e-6:
        k = (1 - p.coef ** n) / (1 - p.coef)
        pos = [p.pos[i] + p.vel[i] * k for i in range(3)]
    else:
        tri = n * (n - 1) / 2
        pos = [p.pos[i] + p.vel[i] * n + p.accel[i] * tri for i in range(3)]
    pos[1] -= p.gravity * n * (n - 1) / 2
    alpha = 1.0
    if p.life:
        appear, keep, vanish = p.life
        if n < appear:
            alpha = (n + 1) / (appear + 1)
        elif n >= appear + keep:
            alpha = max(0.0, 1.0 - (n - appear - keep + 1) / (vanish + 1))
    scale = p.scale + p.scale_add * n
    if scale <= 0:
        return None
    pattern = p.pattern
    if p.pat_speed:
        step = p.pat_speed * n
        pattern = pattern - step if p.anim_flag & ANIM_REVERSE else pattern + step
        if pattern >= p.pat_count or pattern < 0:
            if p.anim_flag & ANIM_LOOP:
                pattern %= p.pat_count
            elif p.anim_flag & ANIM_FINISH:
                return None
            else:
                pattern = min(max(pattern, 0.0), p.pat_count - 1)
    return ParticleState(
        tuple(pos), alpha, scale, p.angle + p.angle_add * n,
        tuple(r + a * n for r, a in zip(p.rot, p.rot_add)),
        tuple(max(s + a * n, 0.0) for s, a in zip(p.model_scale, p.model_scale_add)),
        int(pattern))
