"""The DX9 morph-target files (2026-11-08; layouts and evidence in Vibed/RE/shape_morph.md). Pure Python.

- `.shp` = rShape: per model part (a mesh's idx_group) one map, a float texture W x H, and its targets, one texture of
  position deltas each (float4 (dx, dy, dz, 0), cm, game axes, rows packed). A vertex of a shape mesh holds its
  texel (column, row) in its part's map in TEXCOORD0.
- `.shw` = rShapeWeight: one weight curve per target (a Maya-style curve set). The game only turns a list on when it
  has at least as many curves as the .shp has targets, so `build_shw` writes one per target.

The vertex shader samples the map at TEXCOORD0 x (1 / (W - 1), 1 / (H - 1)) with point sampling. Columns and rows up to
W - 2 / H - 2 land on their own texel either way the texel is rounded, but the last column / row read at 1.0 exactly,
which clamps or wraps by the sampler's address mode: `texel` never uses them.
"""
import struct
from collections import namedtuple

D3DFMT_A32B32G32R32F = 116
MAP_WIDTH = 256
MAX_HALF_INT = 2048         # whole numbers above this aren't exact in a half float (TEXCOORD0 is half2)
MAX_ACTIVE_TARGETS = 15     # the blend pass sums at most 15 targets with a non-zero weight per map
MAX_PARTS = 0x200           # cShape.mTarget: 512 part bits
INTERP_STEP, INTERP_LINEAR = 1, 2
TEXEL_SIZE = 16

Map = namedtuple("Map", "part first count width height")
Target = namedtuple("Target", "map texels")        # texels: bytes, W x H float4, rows packed
Curve = namedtuple("Curve", "before keys")          # keys: [(frame (int), interpolation, value)]


def texel(n, width=MAP_WIDTH):
    """(column, row) of the n-th vertex of a part's map, the last column skipped"""
    return n % (width - 1), n // (width - 1)


def map_height(vertices, width=MAP_WIDTH):
    """rows a map of `vertices` texels needs: the last row stays unused, and the shader divides by H - 1"""
    return max(2, -(-vertices // (width - 1)) + 1)


def max_vertices(width=MAP_WIDTH):
    """vertices one part's map can address exactly (the row is a half float)"""
    return (width - 1) * MAX_HALF_INT


def build_shp(maps, targets):
    """`maps` = [(part, width, height)], `targets` = [Target(map index, texels)], each map's targets consecutive and in
    map order. The texels of a target may be short: the rest is zeros."""
    out = bytearray(b"SHP\0" + struct.pack("<HHHH", 2, len(maps), len(targets), 0))
    for index, (part, width, height) in enumerate(maps):
        mine = [k for k, t in enumerate(targets) if t.map == index]
        if mine and mine != list(range(mine[0], mine[0] + len(mine))):
            raise ValueError(f"the targets of map {index} aren't consecutive")
        out += struct.pack("<HHHHHHI", 0, part, len(mine), mine[0] if mine else 0, width, height, 0)
    for t in targets:
        width, height = maps[t.map][1:]
        out += struct.pack("<HH24xII", 0, t.map, D3DFMT_A32B32G32R32F, width * height * TEXEL_SIZE)
    for t in targets:
        width, height = maps[t.map][1:]
        size = width * height * TEXEL_SIZE
        if len(t.texels) > size:
            raise ValueError(f"target with {len(t.texels)} bytes of texels for a {width} x {height} map")
        out += t.texels
        out += bytes(size - len(t.texels))
    return bytes(out)


def parse_shp(data):
    """(maps [Map], targets [Target]) of a .shp"""
    if data[:4] != b"SHP\0":
        raise ValueError("not a .shp")
    version, num_maps, num_targets, _ = struct.unpack_from("<HHHH", data, 4)
    if version != 2:
        raise ValueError(f".shp version {version}")
    maps = []
    pos = 12
    for _ in range(num_maps):
        _, part, count, first, width, height, _ = struct.unpack_from("<HHHHHHI", data, pos)
        maps.append(Map(part, first, count, width, height))
        pos += 16
    headers = []
    for _ in range(num_targets):
        _, index, fmt, size = struct.unpack_from("<HH24xII", data, pos)
        headers.append((index, size))
        pos += 36
    targets = []
    for index, size in headers:
        targets.append(Target(index, bytes(data[pos:pos + size])))
        pos += size
    return maps, targets


def texel_delta(target, map_, column, row):
    """(dx, dy, dz) a target stores for a texel"""
    return struct.unpack_from("<3f", target.texels, (row * map_.width + column) * TEXEL_SIZE)


def build_shw(curves, frame_max, first_target=0):
    """a weight list with curve k for target first_target + k. `curves` = [Curve(before, keys)]; frame_max = the list's
    length in game frames (it loops over 0..frame_max)"""
    n = len(curves)
    out = bytearray(b"SHW\0" + struct.pack("<HHIII", 2, n, max(int(frame_max), 1), first_target,
                                          first_target + n - 1))
    out += struct.pack(f"<{n}i", *range(n))
    for c in curves:
        out += struct.pack("<IIf", 0, len(c.keys), c.before)
    for c in curves:
        for frame, interpolation, value in c.keys:
            out += struct.pack("<iIf24x", int(frame), interpolation, value)    # the frame is an s32 (cvtsi2ss)
    return bytes(out)


def parse_shw(data):
    """(frame_max, first target, [curve index per target], [Curve])"""
    if data[:4] != b"SHW\0":
        raise ValueError("not a .shw")
    version, n, frame_max, first, last = struct.unpack_from("<HHIII", data, 4)
    if version != 2:
        raise ValueError(f".shw version {version}")
    pos = 20
    count = last - first + 1
    index = list(struct.unpack_from(f"<{count}i", data, pos))
    pos += 4 * count
    heads = []
    for _ in range(n):
        _, keys, before = struct.unpack_from("<IIf", data, pos)
        heads.append((keys, before))
        pos += 12
    curves = []
    for keys, before in heads:
        out = []
        for _ in range(keys):
            out.append(struct.unpack_from("<iIf", data, pos))
            pos += 36
        curves.append(Curve(before, out))
    return frame_max, first, index, curves


def evaluate(curve, frame):
    """a curve's value at a game frame, for linear / step keys (sub_B1F580's cases 1 / 2)"""
    keys = curve.keys
    if not keys or frame < keys[0][0]:
        return curve.before
    for (f0, interpolation, v0), (f1, _, v1) in zip(keys, keys[1:]):
        if f0 <= frame < f1:
            if interpolation == INTERP_LINEAR:
                return v0 + (v1 - v0) * (frame - f0) / (f1 - f0)
            return v0
    return keys[-1][2]


def linear_keys(samples, tolerance=1e-4):
    """the fewest linear keys [(frame, value)] through `samples` (one value per game frame from 0) that stay within
    `tolerance` of every sample"""
    if not samples:
        return []
    keys = [0]
    anchor = 0
    for end in range(2, len(samples)):
        a, b = samples[anchor], samples[end]
        if any(abs(a + (b - a) * (k - anchor) / (end - anchor) - samples[k]) > tolerance
               for k in range(anchor + 1, end)):
            anchor = end - 1
            keys.append(anchor)
    if len(samples) > 1:
        keys.append(len(samples) - 1)
    return [(k, samples[k]) for k in keys]
