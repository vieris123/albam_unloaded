"""DMC4 .efs (rEffectStrip) curves, used by PathStrip moves (move type 3) and generator RangeStripPath.

Layout (DX9 loader sub_AD9810; names from the SE PDB, rEffectStrip::EFS_HEADER / PARTS_PARAM / VERTEX_PARAM /
INDEX_PARAM). DX9 (0x20060725, 53 files) and SE (0x20080912, 2 files) share it byte for byte apart from the
version:
    0x00 'EFS\\0'  0x04 Version  0x08 ParamBuffSize (file size - 0x20)  0x0C EfsHeader320c (0 in every file)
    0x10 PartsNum  0x14 JointNum (0 in every file)  0x18 TotalVertexNum  0x1C TotalIndexNum (0 in every file)
    0x20 body: u32 offset per part (relative to the body); each part = PARTS_PARAM (u32 VertexNum, u32 IndexNum),
         then VERTEX_PARAM[VertexNum], 32 bytes: f32 Pos[3] (cm), u8 BlendIndex0-3, f32 Norm[3] (unit length in
         every file), u8 BlendWeight0-3 (0 in every file); then INDEX_PARAM[IndexNum], 8 bytes: u16 VertexNo0-2,
         u16 reserved (triangles, for STRIP_TYPE_MODEL; no file has any).
STRIP_TYPE (SE enum): 0 VERTEX, 1 PATH_LINEAR, 2 PATH_HERMITE, 3 PATH_SPLINE, 4 MODEL. STRIP_FLAG: 0x1 ORDER,
0x2 REVERSE, 0x4 NORM_OFF, 0x8 PATH_LOOP, 0x10 CENTER_FIX, 0x20 ALL_PARTS, 0x40 SKINING.
curve_point / CurvePath evaluate the game's linear, hermite and 4-point spline curves (positions and normals).
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

MAGIC = b"EFS\0"
VERSION_DX9 = 0x20060725
VERSION_SE = 0x20080912
HEADER_SIZE = 0x20
VERTEX_SIZE = 32
INDEX_SIZE = 8


class EfsError(Exception):
    pass


@dataclass
class Vertex:
    pos: tuple                          # cm, game axes (Y up)
    norm: tuple = (0.0, 0.0, 1.0)       # unit length in every file
    blend_indices: tuple = (0, 0, 0, 0)
    blend_weights: tuple = (0, 0, 0, 0)


@dataclass
class Part:
    vertices: list = field(default_factory=list)
    indices: list = field(default_factory=list)   # (VertexNo0, VertexNo1, VertexNo2, reserved), STRIP_TYPE_MODEL only


@dataclass
class EffectStrip:
    version: int = VERSION_DX9
    parts: list = field(default_factory=list)
    header_320c: int = 0                # EfsHeader320c, 0 in every file
    joint_num: int = 0                  # JointNum, 0 in every file


def parse_strip(data):
    """Every field of an .efs, for editing (parse() gives only the positions)."""
    data = bytes(data)
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        raise EfsError("not an EFS file (bad magic)")
    version, size, h320c, parts, joints = struct.unpack_from("<5I", data, 4)
    if HEADER_SIZE + parts * 4 > len(data):
        raise EfsError("part table runs past the end of the file")
    strip = EffectStrip(version, [], h320c, joints)
    for i in range(parts):
        base = HEADER_SIZE + struct.unpack_from("<I", data, HEADER_SIZE + i * 4)[0]
        if base + 8 > len(data):
            raise EfsError(f"part {i} starts past the end of the file")
        vn, inn = struct.unpack_from("<II", data, base)
        start = base + 8
        if start + vn * VERTEX_SIZE + inn * INDEX_SIZE > len(data):
            raise EfsError(f"part {i}: its vertices / indices run past the end of the file")
        part = Part()
        for j in range(vn):
            o = start + j * VERTEX_SIZE
            pos = struct.unpack_from("<3f", data, o)
            bi = tuple(data[o + 12:o + 16])
            norm = struct.unpack_from("<3f", data, o + 16)
            bw = tuple(data[o + 28:o + 32])
            part.vertices.append(Vertex(pos, norm, bi, bw))
        o = start + vn * VERTEX_SIZE
        part.indices = [struct.unpack_from("<4H", data, o + k * INDEX_SIZE) for k in range(inn)]
        strip.parts.append(part)
    return strip


def to_bytes(strip):
    """.efs bytes: header, part offset table, then each part (PARTS_PARAM, vertices, indices) in order."""
    table = HEADER_SIZE and len(strip.parts) * 4
    blobs, offsets, at = [], [], table
    for part in strip.parts:
        out = bytearray(struct.pack("<II", len(part.vertices), len(part.indices)))
        for v in part.vertices:
            out += struct.pack("<3f", *v.pos) + bytes(v.blend_indices) + struct.pack("<3f", *v.norm) \
                + bytes(v.blend_weights)
        for idx in part.indices:
            out += struct.pack("<4H", *idx)
        offsets.append(at)
        at += len(out)
        blobs.append(bytes(out))
    body = b"".join(struct.pack("<I", o) for o in offsets) + b"".join(blobs)
    header = MAGIC + struct.pack("<7I", strip.version, len(body), strip.header_320c, len(strip.parts),
                                 strip.joint_num, sum(len(p.vertices) for p in strip.parts),
                                 sum(len(p.indices) for p in strip.parts))
    return header + body


def parse(data):
    """List of parts, each a list of (x, y, z) points in cm."""
    data = bytes(data)
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        raise EfsError("not an EFS file (bad magic)")
    parts = struct.unpack_from("<I", data, 0x10)[0]
    if HEADER_SIZE + parts * 4 > len(data):
        raise EfsError("part table runs past the end of the file")
    out = []
    for i in range(parts):
        base = HEADER_SIZE + struct.unpack_from("<I", data, HEADER_SIZE + i * 4)[0]
        if base + 8 > len(data):
            raise EfsError(f"part {i} starts past the end of the file")
        count = struct.unpack_from("<I", data, base)[0]
        start = base + 8
        if start + count * VERTEX_SIZE > len(data):
            raise EfsError(f"part {i}: {count} vertices run past the end of the file")
        out.append([struct.unpack_from("<3f", data, start + j * VERTEX_SIZE) for j in range(count)])
    return out


def parse_normals(data):
    """Per part, the unit normals of its points (game axes), parallel to parse()."""
    return [[v.norm for v in part.vertices] for part in parse_strip(data).parts]


STRIP_LINEAR, STRIP_HERMITE, STRIP_SPLINE = 1, 2, 3
# cubic through 4 points at u = 0, 1, 2, 3 (sub_8D40F0): coefficients of (1, u, u^2, u^3) per point
_LAGRANGE = ((1.0, -11.0 / 6.0, 1.0, -1.0 / 6.0), (0.0, 3.0, -2.5, 0.5), (0.0, -1.5, 2.0, -0.5),
             (0.0, 1.0 / 3.0, -0.5, 1.0 / 6.0))


def curve_point(pts, kind, seg, t, closed=False):
    """Point on segment seg (pts[seg] -> pts[seg + 1]) at t, as the game's strip samplers compute it (the RangeStrip
    samplers calcRangeStripLine / Curve3 / Curve4 0x99AAB0..; PathStrip calcParticleMovePathStripPos 0x975440):
    1 linear (sub_ADBD40); 2 hermite through seg, seg + 1 with tangents pts[seg + 1] - pts[seg] and
    pts[seg + 2] - pts[seg + 1] (sub_ADBED0; an open strip's last segment is linear); 3 the cubic through a window of
    4 points, evaluated at the segment's place in it (sub_ADC1E0: open strips use [seg - o .. seg - o + 3] with o = 0
    on the first segment, 2 on the last, else 1; closed ones wrap with o = 1). Works on normals the same way."""
    n = len(pts)
    a, b = pts[seg % n], pts[(seg + 1) % n]
    if kind == STRIP_HERMITE and n >= 3 and (closed or seg + 2 < n):
        c = pts[(seg + 2) % n]
        t2, t3 = t * t, t * t * t
        h00, h10, h01, h11 = 2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + t, 3 * t2 - 2 * t3, t3 - t2
        return tuple(h00 * p0 + h10 * (p1 - p0) + h01 * p1 + h11 * (p2 - p1) for p0, p1, p2 in zip(a, b, c))
    if kind == STRIP_SPLINE and n >= 4:
        if closed:
            offset = 1
        else:
            offset = 0 if seg == 0 else (2 if seg == n - 2 else 1)
        window = [pts[(seg - offset + k) % n] for k in range(4)]
        u = offset + t
        powers = (1.0, u, u * u, u * u * u)
        return tuple(sum(p[axis] * sum(c * w for c, w in zip(coef, powers)) for p, coef in zip(window, _LAGRANGE))
                     for axis in range(3))
    return tuple(x + (y - x) * t for x, y in zip(a, b))


class CurvePath:
    """Arc-length lookup on a PathStrip curve (calcPathStripLength 0x9DE470: a length table with PathCurveDivideNum
    steps per segment; sub_AE5100 turns a distance into a fractional step, which is evaluated on the curve).
    Linear paths are exact; closed (PATH_LOOP) paths include the segment back to the first point."""

    def __init__(self, points, kind=STRIP_LINEAR, divide=1, closed=False):
        self.points = list(points)
        self.kind, self.closed = kind, closed
        n = len(self.points)
        segments = n if closed and n > 1 else max(n - 1, 0)
        steps = 1 if kind not in (STRIP_HERMITE, STRIP_SPLINE) else max(int(divide), 1)
        self.params, self.lengths = [0.0], [0.0]
        prev = self.points[0] if self.points else (0.0, 0.0, 0.0)
        for seg in range(segments):
            for j in range(1, steps + 1):
                u = seg + j / steps
                point = self.point(u)
                self.params.append(u)
                self.lengths.append(self.lengths[-1] + math.dist(prev, point))
                prev = point

    def point(self, u):
        seg = min(int(u), max(len(self.points) - (1 if self.closed else 2), 0))
        return curve_point(self.points, self.kind, seg, u - seg, self.closed)

    @property
    def length(self):
        return self.lengths[-1]

    def at(self, d, loop=False):
        """(point, path_end) at arc length d."""
        if not self.points:
            return (0.0, 0.0, 0.0), True
        total = self.length
        end = False
        if total <= 0:
            return self.points[0], True
        if loop:
            d %= total
        elif d <= 0 or d >= total:
            end, d = True, min(max(d, 0.0), total)
        lo, hi = 0, len(self.lengths) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.lengths[mid] <= d:
                lo = mid
            else:
                hi = mid
        step = self.lengths[hi] - self.lengths[lo]
        f = (d - self.lengths[lo]) / step if step > 0 else 0.0
        return self.point(self.params[lo] + (self.params[hi] - self.params[lo]) * f), end


class Polyline:
    """Arc-length lookup on a list of points (linear segments; CurvePath follows the game's curve modes)."""

    def __init__(self, points):
        self.points = list(points)
        self.lengths = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.lengths.append(self.lengths[-1] + math.dist(a, b))

    @property
    def length(self):
        return self.lengths[-1]

    def at(self, d, loop=False):
        """(point, path_end) at arc length d."""
        if not self.points:
            return (0.0, 0.0, 0.0), True
        total = self.length
        end = False
        if total <= 0:
            return self.points[0], True
        if loop:
            d %= total
        elif d <= 0 or d >= total:
            end, d = True, min(max(d, 0.0), total)
        lo, hi = 0, len(self.lengths) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.lengths[mid] <= d:
                lo = mid
            else:
                hi = mid
        seg = self.lengths[hi] - self.lengths[lo]
        t = (d - self.lengths[lo]) / seg if seg > 0 else 0.0
        a, b = self.points[lo], self.points[hi]
        return tuple(x + (y - x) * t for x, y in zip(a, b)), end
