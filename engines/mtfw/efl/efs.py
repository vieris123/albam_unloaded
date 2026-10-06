"""DMC4 .efs (rEffectStrip) curves, used by PathStrip moves (move type 3) and generator RangeStripPath.

Layout (DX9 loader sub_AD9810):
    0x00 'EFS\\0'  0x04 version 0x20060725  0x08 data size  0x0C 0  0x10 part count  0x14 joint count (?)
    0x18 total vertex count  0x1C 0
    0x20 body: u32 offset per part (relative to the body); each part = u32 vertex count, u32 0, then 32-byte
         vertices: f32 pos[3] (cm), u8 joints[4], f32[4] (normal/up)
Only positions are used here.
"""
from __future__ import annotations

import math
import struct

MAGIC = b"EFS\0"
HEADER_SIZE = 0x20
VERTEX_SIZE = 32


class EfsError(Exception):
    pass


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


class Polyline:
    """Arc-length lookup on a list of points (linear segments; the game also has hermite/spline modes)."""

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
