"""PrimModel (particle type 6) geometry, ported from the DX9 builders.

    Ring / TexRing      buildPrimModelRing 0x9CD670 / buildPrimModelTexRing 0x9CEFC0
    Sphere / TexSphere  buildPrimModelSphere 0x9D11C0 / buildPrimModelTexSphere 0x9D4250
    Grid / TexGrid      buildPrimModelGrid 0x9D83C0 / buildPrimModelTexGrid 0x9D8C70 (approximated, see build)

Output is in the particle's local space with game axes and units (Y-up, centimetres), before the
particle matrix (ModelScale, Rot). Only the base value `s` of each range is used.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

RING, TEX_RING, SPHERE, TEX_SPHERE, GRID, TEX_GRID = range(6)
TYPE_NAMES = ("Ring", "TexRing", "Sphere", "TexSphere", "Grid", "TexGrid")

# PrimFlags axis nibble (PRIM_MODEL_AXIS: 0 X, 1 Y, 2 Z) -> component indices for
# (sin * radius, cos * radius, height); identical in the ring and sphere builders.
_AXIS_COMPONENTS = {0: (2, 1, 0), 1: (0, 2, 1), 2: (1, 0, 2)}


@dataclass
class PrimMesh:
    vertices: list = field(default_factory=list)   # (x, y, z)
    faces: list = field(default_factory=list)      # vertex index quads
    uvs: list = field(default_factory=list)        # per face corner, same order as faces
    alpha: list = field(default_factory=list)      # per vertex: 0.0 on borders when edge alpha applies


def _place(axis, s, c, h):
    i_s, i_c, i_h = _AXIS_COMPONENTS.get(axis, _AXIS_COMPONENTS[1])
    p = [0.0, 0.0, 0.0]
    p[i_s], p[i_c], p[i_h] = s, c, h
    return tuple(p)


def _tex_range(index, tex_div):
    """UV span of one cell: the texture repeats every tex_div + 1 cells; 0 = whole texture per cell."""
    if not tex_div:
        return 0.0, 1.0
    step = 1.0 / (tex_div + 1)
    start = (index % (tex_div + 1)) * step
    return start, start + step


def build(prim_type, axis, shape, rot_div, rot_tex_div, rot_start, rot_end,
          hori_div, hori_tex_div, hori_start, hori_end, edge_alpha=False):
    """
    shape = (Radius0, Radius1, Height0, Height1) base values:
        Ring:   two edge lines (r0, h0) and (r1, h1), rows lerped between them
        Sphere: (R, -, H, offset): latitude k*pi/M, ring radius sin*R, height cos*H + offset
        Grid:   (w0, w1, d0, d1): trapezoid between two edges (approximation)
    The draw ranges are inclusive cell indices, as in the game.
    """
    n = max(int(rot_div), 1)
    m = max(int(hori_div), 1)
    rot_start, rot_end = int(rot_start), int(rot_end)
    hori_start, hori_end = int(hori_start), int(hori_end)
    if rot_end < rot_start or hori_end < hori_start:
        return PrimMesh()
    cols = rot_end - rot_start + 1     # cells around
    rows = hori_end - hori_start + 1   # cells along the axis
    r0, r1, h0, h1 = (float(v) for v in shape)
    family = prim_type // 2            # 0 ring, 1 sphere, 2 grid

    def point(j, k):
        """Corner between cells: column j (absolute), row k (absolute)."""
        if family == 1:
            theta = k * math.pi / m
            ring_r = math.sin(theta) * r0
            height = math.cos(theta) * h0 + h1
            phi = (j - (n >> 1)) * 2.0 * math.pi / n
            return _place(axis, math.sin(phi) * ring_r, math.cos(phi) * ring_r, height)
        t = k / m
        if family == 2:
            u = j / n - 0.5
            width = r0 + (r1 - r0) * t
            depth = h0 + (h1 - h0) * t
            return _place(axis, u * width, depth, 0.0)
        phi = (j - (n >> 1)) * 2.0 * math.pi / n
        radius = r0 + (r1 - r0) * t
        height = h0 + (h1 - h0) * t
        return _place(axis, math.sin(phi) * radius, math.cos(phi) * radius, height)

    mesh = PrimMesh()
    index = {}
    for k in range(hori_start, hori_end + 2):
        for j in range(rot_start, rot_end + 2):
            index[(j, k)] = len(mesh.vertices)
            mesh.vertices.append(point(j, k))
            border = j in (rot_start, rot_end + 1) or k in (hori_start, hori_end + 1)
            mesh.alpha.append(0.0 if edge_alpha and border else 1.0)

    for k in range(hori_start, hori_end + 1):
        v0, v1 = _tex_range(k, hori_tex_div)
        for j in range(rot_start, rot_end + 1):
            u0, u1 = _tex_range(j, rot_tex_div)
            mesh.faces.append((index[(j, k)], index[(j + 1, k)], index[(j + 1, k + 1)], index[(j, k + 1)]))
            mesh.uvs.extend(((u0, v0), (u1, v0), (u1, v1), (u0, v1)))
    assert len(mesh.faces) == cols * rows
    return mesh


def build_from_block(block):
    """PrimMesh for an EFL_PARTICLE_PrimModel block (efl.model.Block)."""
    shape = (block.get("Radius")[0][0], block.get("Radius")[1][0],
             block.get("Height")[0][0], block.get("Height")[1][0])
    edge_alpha = bool(block.get("ParticleOptionFlag") & 0x80000)
    return build(block.get("PrimModelType"), block.get("Axis"), shape,
                 block.get("RotDivNum"), block.get("RotTexDivNum"), block.get("RotDrawStart"), block.get("RotDrawEnd"),
                 block.get("HoriDivNum"), block.get("HoriTexDivNum"), block.get("HoriDrawStart"),
                 block.get("HoriDrawEnd"), edge_alpha)
