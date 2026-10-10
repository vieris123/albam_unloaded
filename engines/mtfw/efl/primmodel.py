"""PrimModel (particle type 6) geometry, ported from the DX9 builders.

    Ring / TexRing      buildPrimModelRing 0x9CD670 / buildPrimModelTexRing 0x9CEFC0
    Sphere / TexSphere  buildPrimModelSphere 0x9D11C0 / buildPrimModelTexSphere 0x9D4250
    Grid / TexGrid      buildPrimModelGrid 0x9D83C0 / buildPrimModelTexGrid 0x9D8C70 (approximated, see build)

Output is in the particle's local space with game axes and units (Y-up, centimetres), before the
particle matrix (ModelScale, Rot). Only the base value `s` of each range is used.

Colour gradient (every builder): row k of 0..HoriDivNum gets lerp(colour, colour B, calc_color_gradient(k)), colour B
= PlaceColor1/2 rolled like the colour (initParticlePrimModel 0x97BE70); PrimMesh.grad holds the factor per vertex.
Faces are wound so their normal points the way the game's rim-fade normal does (buildPrimModelRingAttenuate 0x9CDF70:
the frustum's outward normal, +axis for a flat ring; spheres: away from the centre).
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
    basis: list = field(default_factory=list)      # per vertex: 4 vectors, vertex = sum(basis[i] * shape[i])
    grad: list = field(default_factory=list)       # per vertex: colour gradient factor toward colour B (0 = colour)


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
          hori_div, hori_tex_div, hori_start, hori_end, edge_alpha=False, gradient=None):
    """
    shape = (Radius0, Radius1, Height0, Height1) base values:
        Ring:   two edge lines (r0, h0) and (r1, h1), rows lerped between them
        Sphere: (R, -, H, offset): latitude k*pi/M, ring radius sin*R, height cos*H + offset
        Grid:   (w0, w1, d0, d1): trapezoid between two edges (approximation)
    The draw ranges are inclusive cell indices, as in the game. gradient(k) = colour B factor of row k.
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

    zero = (0.0, 0.0, 0.0)

    def basis(j, k):
        """Corner between cells (column j, row k) as 4 vectors: the corner is linear in (r0, r1, h0, h1), so
        keyframed shapes can be rebuilt as sum(basis[i] * shape[i]) (the game rebuilds the mesh per frame)."""
        if family == 1:   # sphere: ring radius sin(theta) * r0, height cos(theta) * h0 + h1
            theta = k * math.pi / m
            phi = (j - (n >> 1)) * 2.0 * math.pi / n
            st = math.sin(theta)
            return (_place(axis, math.sin(phi) * st, math.cos(phi) * st, 0.0), zero,
                    _place(axis, 0.0, 0.0, math.cos(theta)), _place(axis, 0.0, 0.0, 1.0))
        t = k / m
        if family == 2:   # grid: width lerp(r0, r1), depth lerp(h0, h1)
            u = j / n - 0.5
            return (_place(axis, u * (1 - t), 0.0, 0.0), _place(axis, u * t, 0.0, 0.0),
                    _place(axis, 0.0, 1 - t, 0.0), _place(axis, 0.0, t, 0.0))
        phi = (j - (n >> 1)) * 2.0 * math.pi / n   # ring: radius lerp(r0, r1), height lerp(h0, h1)
        sp, cp = math.sin(phi), math.cos(phi)
        return (_place(axis, sp * (1 - t), cp * (1 - t), 0.0), _place(axis, sp * t, cp * t, 0.0),
                _place(axis, 0.0, 0.0, 1 - t), _place(axis, 0.0, 0.0, t))

    def point(j, k):
        vectors = basis(j, k)
        return tuple(sum(v[c] * w for v, w in zip(vectors, (r0, r1, h0, h1))) for c in range(3)), vectors

    mesh = PrimMesh()
    index = {}
    for k in range(hori_start, hori_end + 2):
        for j in range(rot_start, rot_end + 2):
            index[(j, k)] = len(mesh.vertices)
            vertex, vectors = point(j, k)
            mesh.vertices.append(vertex)
            mesh.basis.append(vectors)
            border = j in (rot_start, rot_end + 1) or k in (hori_start, hori_end + 1)
            mesh.alpha.append(0.0 if edge_alpha and border else 1.0)
            mesh.grad.append(gradient(k) if gradient is not None else 0.0)

    for k in range(hori_start, hori_end + 1):
        v0, v1 = _tex_range(k, hori_tex_div)
        for j in range(rot_start, rot_end + 1):
            u0, u1 = _tex_range(j, rot_tex_div)
            face = [index[(j, k)], index[(j + 1, k)], index[(j + 1, k + 1)], index[(j, k + 1)]]
            uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
            if _faces_inward(mesh, face, family, axis, (j + 0.5 - (n >> 1)) * 2.0 * math.pi / n, (r0, r1, h0, h1)):
                face.reverse()
                uvs.reverse()
            mesh.faces.append(tuple(face))
            mesh.uvs.extend(uvs)
    assert len(mesh.faces) == cols * rows
    return mesh


def _faces_inward(mesh, face, family, axis, phi, shape):
    """True if the face's winding normal points against the game's rim-fade normal."""
    pts = [mesh.vertices[i] for i in face]
    normal = [0.0, 0.0, 0.0]   # Newell
    for a, b in zip(pts, pts[1:] + pts[:1]):
        normal[0] += (a[1] - b[1]) * (a[2] + b[2])
        normal[1] += (a[2] - b[2]) * (a[0] + b[0])
        normal[2] += (a[0] - b[0]) * (a[1] + b[1])
    if family == 1:   # sphere: away from the centre
        centre = _place(axis, 0.0, 0.0, shape[3])
        mid = [sum(p[c] for p in pts) / 4 - centre[c] for c in range(3)]
        return sum(n * m for n, m in zip(normal, mid)) < 0
    if family == 2:   # grids have no rim fade
        return False
    r0, r1, h0, h1 = shape
    dr, dh = abs(r1 - r0), abs(h1 - h0)
    if dr < 0.01:
        game = _place(axis, math.sin(phi), math.cos(phi), 0.0)
    elif dh < 0.01:
        game = _place(axis, 0.0, 0.0, 1.0)
    else:
        a = dr * dr / dh * (-1.0 if r0 > r1 else 1.0) * (-1.0 if h1 > h0 else 1.0)
        game = _place(axis, math.sin(phi) * dr, math.cos(phi) * dr, a)
    return sum(n * g for n, g in zip(normal, game)) < 0


def build_from_block(block):
    """PrimMesh for an EFL_PARTICLE_PrimModel block (efl.model.Block)."""
    from .sim import _gradient
    shape = (block.get("Radius")[0][0], block.get("Radius")[1][0],
             block.get("Height")[0][0], block.get("Height")[1][0])
    edge_alpha = bool(block.get("ParticleOptionFlag") & 0x80000)
    place = (block.get("ColorPlaceType"), block.get("ColorPlaceInpType"), block.get("HoriColorPlaceNo"))
    last = block.get("HoriDivNum")
    gradient = (lambda k: _gradient(k, last, *place)) if place[0] else None
    return build(block.get("PrimModelType"), block.get("Axis"), shape,
                 block.get("RotDivNum"), block.get("RotTexDivNum"), block.get("RotDrawStart"), block.get("RotDrawEnd"),
                 block.get("HoriDivNum"), block.get("HoriTexDivNum"), block.get("HoriDrawStart"),
                 block.get("HoriDrawEnd"), edge_alpha, gradient)
