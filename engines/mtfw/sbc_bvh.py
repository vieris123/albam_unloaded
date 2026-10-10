"""DX9 DMC4 SBC1 (version 18) collision writer: groups of triangles, a BVH per group and a top-level BVH over the groups.

Pure Python (no bpy, no Kaitai) so it can be tested outside Blender. The layout rules below hold for all 67 unique DX9
game files (`Vibed/RE/sbc_dx9_format.md`):

- header 0x30, then boxes (80 bytes), groups (96), triangles (28), vertices (16), no padding.
- boxes[0:ntop] are the top-level tree over the groups (ntop = groups - 1, or 1 for a single group); each group's own
  tree follows at `start_boxes`, `triangles - 1` nodes (1 for a single triangle), in preorder, child indices relative
  to `start_boxes`, leaf indices relative to `start_tris` and numbered in leaf (DFS) order.
- node flags: 0x40 / 0x80 = child 0 / 1 is a leaf; bits 0-2 = child 0's min < child 1's min on x / y / z, bits 3-5 =
  child 0's max > child 1's max.
- group record i (< groups - 1) repeats top node i (child boxes, leaf child indices, 0 for inner children); the last
  group's copy is its own box twice with children (0, 0).
- max_parts_nest_count / max_nest_count = depth (in nodes) of the top tree / the deepest group tree.
- triangle vertex indices are relative to the group's `start_vertices`; `runtime_attr` is 0x3FFFFF00 in every file.
"""
import math
import struct

SBC1_MAGIC = b"SBC1"
SBC1_VERSION = 18
RUNTIME_ATTR = 0x3FFFFF00
GROUP_ID_NONE = 0xFFFFFFFF
MAX_INDEX = 0xFFFF            # u16 vertex indices, node / leaf indices and group count
LEAF0, LEAF1 = 0x40, 0x80

HEADER = struct.Struct("<4sHHHBBIII6f")
NODE = struct.Struct("<16fHHH10x")
GROUP = struct.Struct("<5I18fHH")
TRIANGLE = struct.Struct("<3HBBIIIII")
VERTEX = struct.Struct("<4f")


class SbcGroup:
    """One collision group: vertices in game space (cm, Y up), triangles as vertex index triples and one
    (type, special_attr, surface_attr, unk_00, unk_01) tuple per triangle."""

    def __init__(self, vertices, triangles, attributes, group_id=GROUP_ID_NONE, name=""):
        self.vertices = [tuple(float(c) for c in v) for v in vertices]
        self.triangles = [tuple(t) for t in triangles]
        self.attributes = [tuple(a) for a in attributes]
        self.group_id = group_id
        self.name = name


class SbcBuildError(ValueError):
    pass


def _bounds(points):
    return ([min(p[a] for p in points) for a in range(3)], [max(p[a] for p in points) for a in range(3)])


def _union(a, b):
    return ([min(a[0][i], b[0][i]) for i in range(3)], [max(a[1][i], b[1][i]) for i in range(3)])


def _flags(box0, box1):
    flags = 0
    for a in range(3):
        if box0[0][a] < box1[0][a]:
            flags |= 1 << a
        if box0[1][a] > box1[1][a]:
            flags |= 8 << a
    return flags


class _Node:
    __slots__ = ("boxes", "leaf", "child", "index")

    def __init__(self):
        self.boxes = [None, None]
        self.leaf = [False, False]
        self.child = [0, 0]      # leaf: item index; inner: _Node until numbered
        self.index = 0


def build_tree(boxes):
    """Binary BVH over item boxes [(min, max)]. Returns (nodes in preorder, item order = leaf order, depth).
    Items are split at the median centroid along the longest centroid axis."""
    count = len(boxes)
    if count == 0:
        raise SbcBuildError("empty tree")
    centers = [[(b[0][a] + b[1][a]) * 0.5 for a in range(3)] for b in boxes]
    nodes, order = [], []

    def subtree(items):
        """-> (is_leaf, payload, box, depth)"""
        if len(items) == 1:
            return True, items[0], boxes[items[0]], 0
        lo = [min(centers[i][a] for i in items) for a in range(3)]
        hi = [max(centers[i][a] for i in items) for a in range(3)]
        axis = max(range(3), key=lambda a: hi[a] - lo[a])
        items = sorted(items, key=lambda i: (centers[i][axis], centers[i][(axis + 1) % 3], centers[i][(axis + 2) % 3], i))
        half = len(items) // 2
        node = _Node()
        node.index = len(nodes)
        nodes.append(node)
        depth = 0
        box = None
        for k, part in enumerate((items[:half], items[half:])):
            is_leaf, payload, child_box, child_depth = subtree(part)
            if is_leaf:
                node.leaf[k] = True
                node.child[k] = len(order)
                order.append(payload)
            else:
                node.child[k] = payload.index
            node.boxes[k] = child_box
            box = child_box if box is None else _union(box, child_box)
            depth = max(depth, child_depth)
        return False, node, box, depth + 1

    if count == 1:
        # one item: a single node whose two children are both that item
        node = _Node()
        node.boxes = [boxes[0], boxes[0]]
        node.leaf = [True, True]
        node.child = [0, 0]
        return [node], [0], 1
    _, _, _, depth = subtree(list(range(count)))
    return nodes, order, depth


def _node_bytes(node, flags=None):
    (min0, max0), (min1, max1) = node.boxes
    if flags is None:
        flags = (LEAF0 if node.leaf[0] else 0) | (LEAF1 if node.leaf[1] else 0) | _flags(node.boxes[0], node.boxes[1])
    return NODE.pack(*min0, 0.0, *max0, 0.0, *min1, 0.0, *max1, 0.0, flags, node.child[0], node.child[1])


def _check_group(index, group):
    label = group.name or f"group {index}"
    problems = []
    if not group.triangles:
        problems.append(f"{label} has no triangles")
    if len(group.vertices) > MAX_INDEX + 1:
        problems.append(f"{label} has {len(group.vertices)} vertices (65,536 at most)")
    if len(group.triangles) > MAX_INDEX + 1:
        problems.append(f"{label} has {len(group.triangles)} triangles (65,536 at most)")
    if len(group.attributes) != len(group.triangles):
        problems.append(f"{label}: {len(group.attributes)} attribute rows for {len(group.triangles)} triangles")
    if any(not math.isfinite(c) for v in group.vertices for c in v):
        problems.append(f"{label} has non-finite vertex coordinates")
    if any(len(set(t)) != 3 or max(t) >= len(group.vertices) or min(t) < 0 for t in group.triangles):
        problems.append(f"{label} has degenerate or out-of-range triangles")
    return problems


def build_sbc1(groups):
    """SbcGroup list -> SBC1 bytes. Raises SbcBuildError listing every problem."""
    problems = []
    if not groups:
        problems.append("no collision groups")
    if len(groups) > MAX_INDEX:
        problems.append(f"{len(groups)} groups (65,535 at most)")
    for i, g in enumerate(groups):
        problems += _check_group(i, g)
    if problems:
        raise SbcBuildError("\n".join(problems))

    group_trees = []
    group_boxes = []
    for g in groups:
        tri_boxes = [_bounds([g.vertices[i] for i in t]) for t in g.triangles]
        nodes, order, depth = build_tree(tri_boxes)
        if depth > 255:
            raise SbcBuildError(f"{g.name or 'group'}: tree depth {depth} doesn't fit a byte")
        group_trees.append((nodes, order, depth))
        box = tri_boxes[0]
        for tri_box in tri_boxes[1:]:
            box = _union(box, tri_box)
        group_boxes.append(box)

    ng = len(groups)
    if ng == 1:
        top = _Node()
        top.boxes = [([0.0] * 3, [0.0] * 3), group_boxes[0]]
        top.leaf = [False, True]
        top.child = [0, 0]
        top_nodes, top_depth = [top], 1
        top_flags = [LEAF1]
    else:
        top_nodes, top_order, top_depth = build_tree(group_boxes)
        if top_depth > 255:
            raise SbcBuildError(f"top tree depth {top_depth} doesn't fit a byte")
        # the tree numbers leaves in DFS order; point them at the real group indices instead
        for node in top_nodes:
            for k in range(2):
                if node.leaf[k]:
                    node.child[k] = top_order[node.child[k]]
        top_flags = [None] * len(top_nodes)

    ntop = len(top_nodes)
    num_tris = sum(len(g.triangles) for g in groups)
    num_verts = sum(len(g.vertices) for g in groups)
    num_boxes = ntop + sum(len(t[0]) for t in group_trees)
    # header bbox: every vertex, including unused ones (the game files' bbox equals the vertex bounds)
    vb = _bounds([v for g in groups for v in g.vertices])

    out = bytearray(HEADER.pack(SBC1_MAGIC, SBC1_VERSION, ng, ng - 1 if ng > 1 else 1, top_depth,
                                max(t[2] for t in group_trees), num_boxes, num_tris, num_verts, *vb[0], *vb[1]))
    for node, flags in zip(top_nodes, top_flags):
        out += _node_bytes(node, flags)
    for nodes, _, _ in group_trees:
        for node in nodes:
            out += _node_bytes(node)

    start_t = start_v = 0
    start_b = ntop
    for i, (g, (nodes, order, depth), box) in enumerate(zip(groups, group_trees, group_boxes)):
        if i < ng - 1:
            node = top_nodes[i]
            vmin = [node.boxes[0][0], node.boxes[1][0]]
            vmax = [node.boxes[0][1], node.boxes[1][1]]
            child = [node.child[k] if node.leaf[k] else 0 for k in range(2)]
        else:
            vmin, vmax, child = [box[0], box[0]], [box[1], box[1]], [0, 0]
        out += GROUP.pack(0, start_t, start_b, start_v, g.group_id & 0xFFFFFFFF, *box[0], *box[1],
                          *vmin[0], *vmin[1], *vmax[0], *vmax[1], *child)
        start_t += len(g.triangles)
        start_v += len(g.vertices)
        start_b += len(nodes)

    for g, (nodes, order, depth) in zip(groups, group_trees):
        for ti in order:
            a = g.attributes[ti]
            tri_type, special, surface = a[0], a[1], a[2]
            unk_00 = a[3] if len(a) > 3 else 0
            unk_01 = a[4] if len(a) > 4 else 0
            out += TRIANGLE.pack(*g.triangles[ti], unk_00 & 0xFF, unk_01 & 0xFF, RUNTIME_ATTR,
                                 tri_type & 0xFFFFFFFF, special & 0xFFFFFFFF, surface & 0xFFFFFFFF, 0)
    for g in groups:
        for v in g.vertices:
            out += VERTEX.pack(v[0], v[1], v[2], 0.0)
    return bytes(out)


def read_sbc1_groups(data):
    """SBC1 bytes -> SbcGroup list (the inverse of build_sbc1 up to triangle order and the trees)."""
    (magic, version, ng, _ngn, _pn, _n, nb, nf, nv, *_bbox) = HEADER.unpack_from(data, 0)
    if magic != SBC1_MAGIC:
        raise SbcBuildError(f"not an SBC1 file ({magic!r})")
    off_groups = HEADER.size + nb * NODE.size
    off_tris = off_groups + ng * GROUP.size
    off_verts = off_tris + nf * TRIANGLE.size
    heads = [GROUP.unpack_from(data, off_groups + i * GROUP.size) for i in range(ng)]
    groups = []
    for i, h in enumerate(heads):
        st, sv, gid = h[1], h[3], h[4]
        et = heads[i + 1][1] if i + 1 < ng else nf
        ev = heads[i + 1][3] if i + 1 < ng else nv
        verts = [VERTEX.unpack_from(data, off_verts + k * VERTEX.size)[:3] for k in range(sv, ev)]
        tris, attrs = [], []
        for k in range(st, et):
            a, b, c, u0, u1, _rt, tri_type, special, surface, _u2 = TRIANGLE.unpack_from(data, off_tris + k * TRIANGLE.size)
            tris.append((a, b, c))
            attrs.append((tri_type, special, surface, u0, u1))
        groups.append(SbcGroup(verts, tris, attrs, gid))
    return groups
