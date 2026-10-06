"""Effect keyframe curves (EFL_KEYFRAME_INDEX blocks), evaluated like the DX9 runtime.

Sources (DX9): getKeyframeTimer 0x963F10, KeyframeTag::calcTag 0xA9E820, calcKeyframeF32 0xA3C1C0 (Vector 0xA3C640,
U32 0xA3BAC0, Color 0xA9E9C0, FixAngle 0xA3D190), MtSpline::MtSpline 0x8D4390.
- Header: KeyframeNum bits 0-7, FixAngleFlag 8, SingleParamFlag 9 (unused in DX9), RefType 24-26, InpType 27-29,
  LoopFlag 30, InitOnlyFlag 31 (set: evaluated once at spawn and held).
- Keys: u32 Frame (absolute frame of the RefType timer) + a value range. Each particle draws its random rate(s) once
  at spawn: F32 s + r*rate; COLOR lerp(A, B, rate) per channel (bytes b, g, r, a); VECTOR3 three independent rates;
  U32 s + rnd % (r + 1); FixAngle (vector with FixAngleFlag) signed ints s + rnd % (r + 1), times 2*pi/4096.
- RefType: 0, 5-7 particle age; 1 generator timer; 2 effect timer; 3 parent effect timer; 4 global effect timer.
- InpType: 0 linear, 1 Hermite (tangents from neighbouring keys), 2 4-point Lagrange cubic; 3-7 give zero in DX9.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

FIX_ANGLE_UNIT = 2 * math.pi / 4096
REF_PARTICLE_AGE = (0, 5, 6, 7)

_KEY_FORMATS = {   # value type -> (struct format after the u32 frame, key size)
    "f32": ("<ff", 12), "u32": ("<HH", 8), "color": ("<4B4B", 12), "vec3": ("<6f", 28), "fixangle": ("<6i", 28),
}


@dataclass
class Keyframe:
    header: int
    vtype: str
    frames: list
    params: list        # per key, the raw range tuple

    @property
    def loop(self):
        return bool(self.header >> 30 & 1)

    @property
    def inp_type(self):
        return self.header >> 27 & 7

    @property
    def ref_type(self):
        return self.header >> 24 & 7

    @property
    def init_only(self):
        return bool(self.header >> 31 & 1)

    @property
    def uses_particle_age(self):
        return self.ref_type in REF_PARTICLE_AGE


def read(sub):
    """Keyframe for an efl.model.SubBlock of kind 'kf' (its field's sub says the value type)."""
    data = sub.block.data
    header = struct.unpack_from("<I", data, sub.offset)[0]
    vtype = sub.value_type or "f32"
    if vtype == "vec3" and header >> 8 & 1:
        vtype = "fixangle"
    fmt, size = _KEY_FORMATS[vtype]
    count = header & 0xFF
    frames, params = [], []
    for i in range(count):
        base = sub.offset + 4 + i * size
        if base + size > len(data):
            break
        frames.append(struct.unpack_from("<I", data, base)[0])
        params.append(struct.unpack_from(fmt, data, base + 4))
    return Keyframe(header, vtype, frames, params)


PARAM_COUNT = {"f32": 2, "u32": 2, "color": 8, "vec3": 6, "fixangle": 6}   # values per key
INTEGER_TYPES = ("u32", "color", "fixangle")


def encode(kf):
    """EFL_KEYFRAME_INDEX header (KeyframeNum = key count) + keys, padded to 16 bytes."""
    if len(kf.frames) > 0xFF:
        raise ValueError("at most 255 keys")
    fmt, _size = _KEY_FORMATS[kf.vtype]
    out = bytearray(struct.pack("<I", (kf.header & ~0xFF) | len(kf.frames)))
    for frame, param in zip(kf.frames, kf.params):
        out += struct.pack("<I", frame) + struct.pack(fmt, *param)
    out += bytes(-len(out) % 16)
    return bytes(out)


def draw_rates(kf, rng):
    """The per-particle random(s) a keyframe uses, drawn once at spawn."""
    if kf.vtype == "vec3":
        return (rng.random(), rng.random(), rng.random())
    if kf.vtype == "fixangle":
        return (rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(32))
    if kf.vtype == "u32":
        return rng.getrandbits(32)
    return rng.random()


def _key_value(kf, param, rates):
    if kf.vtype == "f32":
        s, r = param
        return s + r * rates
    if kf.vtype == "u32":
        s, r = param
        return float(s + (rates % (r + 1) if r else 0))
    if kf.vtype == "color":
        a, b = param[:4], param[4:]
        return tuple(x * (1 - rates) + y * rates for x, y in zip(a, b))
    if kf.vtype == "vec3":
        return tuple(param[2 * i] + param[2 * i + 1] * rates[i] for i in range(3))
    # fixangle: signed ints, integer random per axis
    return tuple(float(param[2 * i] + (rates[i] % (param[2 * i + 1] + 1) if param[2 * i + 1] > 0 else 0))
                 for i in range(3))


def _calc_tag(frame, frames, loop):
    n = len(frames)
    f0, fl = frames[0], frames[-1]
    if n < 2:
        return 2, 0, 0.0
    if loop:
        if frame in (f0, fl):
            return 2, 0, 0.0
        if fl > f0:
            if frame > fl:
                frame = f0 + (frame - fl) % (fl - f0)
            elif frame < f0:
                frame = fl - (f0 - frame) % (fl - f0)
    else:
        if frame <= f0:
            return 2, 0, 0.0
        if frame >= fl:
            return 3, n - 1, 0.0
    for i in range(1, n):
        if frame == frames[i]:
            return 1, i, 0.0
        if frame < frames[i]:
            return 0, i - 1, (frame - frames[i - 1]) / (frames[i] - frames[i - 1])
    return 3, n - 1, 0.0


_LAGRANGE = ((1.0, -11 / 6, 1.0, -1 / 6), (0.0, 3.0, -2.5, 0.5), (0.0, -1.5, 2.0, -0.5), (0.0, 1 / 3, -0.5, 1 / 6))


def _combine(weights_values):
    """Sum of w * v for scalars or tuples."""
    (w0, v0), *rest = weights_values
    if isinstance(v0, tuple):
        out = [w0 * c for c in v0]
        for w, v in rest:
            for i, c in enumerate(v):
                out[i] += w * c
        return tuple(out)
    return sum(w * v for w, v in weights_values)


def evaluate(kf, frame, rates):
    """Value at a timer frame (int). Scalars for f32/u32, tuples for color/vec3/fixangle; None if no keys."""
    n = len(kf.frames)
    if n == 0:
        return None
    status, i, t = _calc_tag(int(frame), kf.frames, kf.loop)

    def v(j):
        return _key_value(kf, kf.params[j], rates)

    if status:
        value = v(i)
    elif kf.inp_type == 0:
        j = 0 if kf.loop and i + 1 == n - 1 else i + 1
        value = _combine([(1 - t, v(i)), (t, v(j))])
    elif kf.inp_type == 1:
        if kf.loop:
            a = i + 1 if i < n - 2 else 0
            b = a + 1 if a < n - 2 else 0
        else:
            a, b = i + 1, i + 2
        if b >= n:
            value = _combine([(1 - t, v(i)), (t, v(a))])
        else:
            p0, p1, p2 = v(i), v(a), v(b)
            h00, h01 = 2 * t ** 3 - 3 * t ** 2 + 1, 3 * t ** 2 - 2 * t ** 3
            h10, h11 = t ** 3 - 2 * t ** 2 + t, t ** 3 - t ** 2
            # m0 = p1 - p0, m1 = p2 - p1
            value = _combine([(h00 - h10, p0), (h01 + h10 - h11, p1), (h11, p2)])
    elif kf.inp_type == 2 and n >= 4:
        if kf.loop:
            idx = ([n - 2, 0, 1, 2] if i == 0 else [i - 1, i, i + 1, 0] if i == n - 3 else
                   [i - 1, i, 0, 1] if i == n - 2 else [i - 1, i, i + 1, i + 2])
            u = t + 1
        elif i == 0:
            idx, u = [0, 1, 2, 3], t
        elif i == n - 2:
            idx, u = [n - 4, n - 3, n - 2, n - 1], t + 2
        else:
            idx, u = [i - 1, i, i + 1, i + 2], t + 1
        pts = [v(j) for j in idx]
        weights = [((c[3] * u + c[2]) * u + c[1]) * u + c[0] for c in _LAGRANGE]
        value = _combine(list(zip(weights, pts)))
    elif kf.inp_type == 2:
        # fewer than 4 keys: the game reads past the key array; fall back to linear
        j = min(i + 1, n - 1)
        value = _combine([(1 - t, v(i)), (t, v(j))])
    else:
        value = (0.0, 0.0, 0.0) if kf.vtype in ("vec3", "fixangle") else (0.0, 0.0, 0.0, 0.0) if kf.vtype == "color" else 0.0

    if kf.vtype == "u32":
        return float(int(value))
    if kf.vtype == "color":
        return tuple(min(max(c, 0.0), 255.0) for c in value)
    if kf.vtype == "fixangle":
        return tuple(c * FIX_ANGLE_UNIT for c in value)
    return value
