"""dmc4_hook's chain solver in the chain preview: what the runner does for chains a ModelExtension `<physics>` entry
names, in place of the game's cCnsChain solve that cns_chain_preview.py replays for the others, and for `<cloth>`
sheets of such tendrils.

The reference both sides follow is Vibed/ModelExt/chain_solver.md (the runner's code is dmc4_hook
src/sdk/ChainSolver.cpp, whose structure this follows: a _Tendril per tendril, solve_set for one tendril or a sheet).
Blender's axes: game cm -> m, game Y up -> Blender Z up (so "y" in the note is z here), MT row matrices -> column
matrices (row i of a joint = column i of its bone matrix). The preview's matrices are rigid (cns_chain_preview._rigid),
so the note's row lengths are 1.

The game side runs once per drawn frame with T = the frame's length in 60 fps frames (at most 2 per frame: players
min(mDeltaTime, 2), other chains their t clamped to 2), so a scene frame here is one solve of T = 60 / fps, whatever
round(60 / fps) steps the game's solver takes in the preview.

`ground` casts a line per point at the scene's imported stage collision (.sbc meshes); without any it's skipped.
"""
import math

from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

SCALE = 0.01                    # game cm -> m
MAX_STEP = 2.0                  # one frame's time at most (ChainSolver on_move)
TELEPORT = 500.0 * SCALE        # a root jumping farther than this in a frame snaps the chain to the animation
UP = Vector((0.0, 0.0, 1.0))
DOWN = Vector((0.0, 0.0, -1.0))
TINY = 1e-6 * SCALE             # safe_normalize
SHORT = 1e-5 * SCALE            # a segment too short to have a direction
AXES = ("+x", "+y", "+z", "-x", "-y", "-z")     # axis codes 0-5


class Hook:
    """A chain's <physics> settings (movedef.ext_list.physics_values) over its file's (cns_chain_preview._settings),
    and the runner's per-tendril state (indexed by the tendril root's slot)."""

    def __init__(self, values, s):
        self.values = dict(values)
        self.substeps = values["substeps"]
        self.iterations = values["iterations"]
        self.stiffness = values["stiffness"]
        self.pin = values["pin"]
        local = s["pos_local"] or s["pos_local_y"] or s["rot_local"]
        self.inertia = values["inertia"] if values["inertia"] is not None else (0.0 if local else 1.0)
        self.limit = values["limit"]
        self.friction = values["friction"]
        self.radius = values["radius"] * SCALE if values["radius"] is not None else s["radius"]
        self.ground = values["ground"]
        self.self = values["self"]
        self.axis = values["axis"] if values["axis"] is not None else min(max(s["dir"], 0), 5)
        self.up = s["up"] % 3
        self.clear()

    def clear(self):
        self.seen = set()           # nodes with a previous animated place
        self.anim_prev = {}
        self.ref_prev = {}          # tendril root -> the reference frame at its last solve
        self.out = {}               # slot -> the joint's last result (world, rigid)


def frame_time(scene):
    """T of one scene frame, in 60 fps frames"""
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    return min(60.0 / fps, MAX_STEP) if fps > 0 else 1.0


def _unit(v, fallback):
    length = v.length
    return v / length if length > TINY else fallback.copy()


def _axis(m3, axis):
    """axis code 0-5 = +x +y +z -x -y -z: the joint's unit axis"""
    a = _unit(m3.col[axis % 3].copy(), UP)
    return -a if axis >= 3 else a


def _closest(p0, p1, q0, q1):
    """segment parameters (s, t) of the closest points of p0-p1 and q0-q1 (Ericson 5.1.9, as ChainSolver's)"""
    d1, d2, r = p1 - p0, q1 - q0, p0 - q0
    a, e, f = d1.length_squared, d2.length_squared, d2.dot(r)
    small = 1e-8 * SCALE * SCALE
    if a <= small and e <= small:
        return 0.0, 0.0
    if a <= small:
        return 0.0, min(max(f / e, 0.0), 1.0)
    c = d1.dot(r)
    if e <= small:
        return min(max(-c / a, 0.0), 1.0), 0.0
    b = d1.dot(d2)
    denom = a * e - b * b
    s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom > small * small else 0.0
    t = (b * s + f) / e
    if t < 0.0:
        t, s = 0.0, min(max(-c / a, 0.0), 1.0)
    elif t > 1.0:
        t, s = 1.0, min(max((b - c) / a, 0.0), 1.0)
    return s, t


def capsules(shapes):
    """cns_chain_preview._shapes' ("sphere", c, r) / ("capsule", a, b, r) as (a, b, r): a sphere is a = b"""
    return [(sh[1], sh[1], sh[2]) if sh[0] == "sphere" else (sh[1], sh[2], sh[3]) for sh in shapes]


def tendril(chain, slot):
    """(root, tip) slots of the tendril holding `slot`; its tail is the slot after the tip"""
    root, tip = slot, slot
    while root > 0 and chain.joints[root - 1] is not None:
        root -= 1
    while tip + 1 < len(chain.joints) and chain.joints[tip + 1] is not None:
        tip += 1
    return root, tip


def _rigid(m):
    out = m.to_3x3().normalized().to_4x4()
    out.translation = m.translation
    return out


def _per_step(rate, h):
    """a per-frame rate as a share per substep of h frames"""
    return 1.0 - (1.0 - min(max(rate, 0.0), 1.0)) ** h


class _Tendril:
    """One tendril being solved (ChainSolver's Tendril): steps 1-4 of the note on construction (the animated pose from
    a_root = the root's FK world, the reset, the points, the inertia carry), then the substep phases and the output.
    local_of(bone name) = the bone's animated local; shapes = [(a, b, radius)] in world space."""

    def __init__(self, chain, root, a_root, arm, local_of, T, shapes):
        hook, s = chain.hook, chain.s
        self.chain, self.hook, self.s, self.arm, self.local_of = chain, hook, s, arm, local_of
        self.root = root
        self.tip = tendril(chain, root)[1]
        self.tail = self.tip + 1
        self.axis, self.up = hook.axis, hook.up
        self.neighbours = []            # root slots of this chain's sheet neighbours (no self collision with them)
        root, tip, tail = self.root, self.tip, self.tail
        nodes = range(root, tail + 1)

        # 1. the animated pose, from the root's FK down the tendril's own locals; the tail along the aim axis
        A = {root: a_root}
        for k in range(root + 1, tip + 1):
            A[k] = _rigid(A[k - 1] @ local_of(chain.joints[k]))
        A[tail] = A[tip].copy()
        A[tail].translation = A[tip].translation + _axis(A[tip].to_3x3(), self.axis) * s["tail"]
        self.A = A
        self.a = a = {k: A[k].translation.copy() for k in nodes}
        self.L = {k: (a[k + 1] - a[k]).length for k in range(root, tail)}

        # 2. reset: the first solve, the game's reset state (cCnsChain::move still runs), or the root jumped
        self.reset = root not in hook.seen or chain.in_reset or (a[root] - hook.anim_prev[root]).length > TELEPORT
        # 3. points
        self.x, self.v = {}, {}
        for k in nodes:
            self.x[k] = a[k].copy() if self.reset else chain.mats[k].translation.copy()
            self.v[k] = Vector() if self.reset else chain.vel[k].copy()
            if self.reset or k not in hook.seen:
                hook.anim_prev[k] = a[k].copy()
            hook.seen.add(k)
        self.x[root] = a[root].copy()

        # 4. inertia: the part of the reference frame's motion the points are carried by
        ref = chain.parent
        self.ref_rot = ref.to_3x3()
        if not self.reset:
            carry = 1.0 - min(max(hook.inertia, 0.0), 1.0)
            prev = hook.ref_prev.get(root)
            if carry > 0.0 and prev is not None and T > 0.0:
                move = ref @ prev.inverted_safe()
                turn = move.to_3x3()
                for k in range(root + 1, tail + 1):
                    self.x[k] = self.x[k].lerp(move @ self.x[k], carry)
                    self.v[k] = self.v[k].lerp(turn @ self.v[k], carry)
        hook.ref_prev[root] = ref.copy()

        self.g = self.ref_rot @ s["gravity"] if s["gravity_local"] else s["gravity"].copy()
        self.wind = Vector() if s["mute_wind"] else chain.wind.copy()
        if s["wind_local"]:
            self.wind = self.ref_rot @ self.wind
        self.r = hook.radius
        self.shapes = [] if s["mute_collision"] else list(shapes)
        self.old, self.contact, self.touched, self.at = {}, {}, {}, {}
        self.planes, self.others = {}, []

    def nodes(self):
        return self.tail - self.root

    def weight(self, k):
        return 0.0 if k == self.root else 1.0

    def gather(self, ground):
        """before the substeps: the ground under each point, the other tendrils' segments (self)"""
        x, a = self.x, self.a
        self.planes = {}
        if self.hook.ground and ground is not None:
            for k in range(self.root + 1, self.tail + 1):
                top = max(x[k].z, a[k].z) + 50.0 * SCALE
                bottom = min(x[k].z, a[k].z) - 100.0 * SCALE
                hit = ground(Vector((x[k].x, x[k].y, top)), top - bottom)
                if hit is not None:
                    self.planes[k] = hit
        self.others = []
        if self.hook.self:
            chain = self.chain
            for k, name in enumerate(chain.joints):
                if name is None or self.root <= k <= self.tip or tendril(chain, k)[0] in self.neighbours:
                    continue
                self.others.append((chain.mats[k].translation.copy(), chain.mats[k + 1].translation.copy()))

    def begin_substep(self, h, f):
        hook, s, x, v, root = self.hook, self.s, self.x, self.v, self.root
        self.damp = min(max(s["damping"], 0.0), 1.0) ** h
        self.pin, self.stiff, self.fric = (_per_step(r, h) for r in (hook.pin, hook.stiffness, hook.friction))
        self.at = {k: hook.anim_prev[k].lerp(self.a[k], f) for k in range(root, self.tail + 1)}
        x[root] = self.at[root].copy()
        # root push: the root, a sphere of the chain's radius, out of every shape (the game keeps a root's push too;
        # Nero's coat roots _02 / _03 sit inside a body shape at bind and would hold their first segment in it)
        for ca, cb, cr in self.shapes:
            _, w = _closest(x[root], x[root], ca, cb)
            d = x[root] - ca.lerp(cb, w)
            pen = self.r + cr - d.length
            if pen > 0.0:
                x[root] = x[root] + _unit(d, UP) * pen
        for k in range(root + 1, self.tail + 1):
            v[k] = (v[k] + (self.g + self.wind) * h) * self.damp
            self.old[k] = x[k].copy()
            x[k] = x[k] + v[k] * h
            self.touched[k] = False

    def constrain(self, first):
        """one constraint pass up to the lengths (stiffness and pin in the first pass only)"""
        hook, s, x, at, r = self.hook, self.s, self.x, self.at, self.r
        root, tail = self.root, self.tail
        touched, contact = self.touched, self.contact
        if first and (self.pin > 0.0 or self.stiff > 0.0):
            for k in range(root + 1, tail + 1):
                if self.stiff > 0.0:        # stiffness
                    length = (x[k] - x[k - 1]).length
                    d = _unit(at[k] - at[k - 1], DOWN)
                    x[k] = x[k] + (x[k - 1] + d * length - x[k]) * self.stiff
                if self.pin > 0.0:          # pin
                    x[k] = x[k] + (at[k] - x[k]) * self.pin
        for k in range(root, tail):         # shapes: both ends pushed, weighted by u; the root doesn't move
            for ca, cb, cr in self.shapes:
                u, w = _closest(x[k], x[k + 1], ca, cb)
                p, q = x[k].lerp(x[k + 1], u), ca.lerp(cb, w)
                pen = r + cr - (p - q).length
                if pen <= 0.0:
                    continue
                n = _unit(p - q, _unit(x[k + 1] - ca, UP))
                wa, wb = (0.0 if k == root else 1.0 - u), u
                den = wa * wa + wb * wb
                if den < 1e-6:
                    continue
                lam = pen / den
                if k != root:
                    x[k] = x[k] + n * (lam * wa)
                    touched[k], contact[k] = True, n
                x[k + 1] = x[k + 1] + n * (lam * wb)
                touched[k + 1], contact[k + 1] = True, n
        if self.others:                     # self: the other tendrils, radius 2r, half the push
            for k in range(root, tail):
                for oa, ob in self.others:
                    u, w = _closest(x[k], x[k + 1], oa, ob)
                    p, q = x[k].lerp(x[k + 1], u), oa.lerp(ob, w)
                    dist = (p - q).length
                    pen = 2.0 * r - dist
                    if pen <= 0.0 or dist < SHORT:
                        continue
                    n = (p - q) / dist
                    wa, wb = (0.0 if k == root else 1.0 - u), u
                    den = wa * wa + wb * wb
                    if den < 1e-6:
                        continue
                    lam = 0.5 * pen / den
                    if k != root:
                        x[k] = x[k] + n * (lam * wa)
                    x[k + 1] = x[k + 1] + n * (lam * wb)
        for k in range(root + 1, tail + 1):     # ground plane, mFloorLevel
            if k in self.planes:
                n, p = self.planes[k]
                d = (x[k] - p).dot(n) - r
                if d < 0.0:
                    x[k] = x[k] - n * d
                    touched[k], contact[k] = True, n
            if s["floor_on"] and x[k].z < s["floor"] + r:
                x[k].z = s["floor"] + r
                touched[k], contact[k] = True, UP.copy()
        if hook.limit > 0.0:                # limit: within `limit` of the animated direction, length kept
            lim = math.radians(min(hook.limit, 180.0))
            cos_limit, sin_limit = math.cos(lim), math.sin(lim)
            for k in range(root + 1, tail + 1):
                seg = x[k] - x[k - 1]
                length = seg.length
                if length < SHORT:
                    continue
                d = _unit(at[k] - at[k - 1], seg / length)
                if (seg / length).dot(d) >= cos_limit:
                    continue
                side = _unit(seg - d * seg.dot(d), Vector())
                if side.length == 0.0:
                    continue
                x[k] = x[k - 1] + (d * cos_limit + side * sin_limit) * length

    def lengths(self, h):
        """lengths last, root to tail, each child moved onto its parent's sphere"""
        s, x, at, L = self.s, self.x, self.at, self.L
        spring = _per_step(s["spring"], h)
        for k in range(self.root, self.tail):
            d = x[k + 1] - x[k]
            length = d.length
            direction = d / length if length > SHORT else _unit(at[k + 1] - at[k], DOWN)
            want = L[k]
            if s["stretch"]:
                want = length + (L[k] - length) * spring if length > L[k] else length
                if s["stretch_limit"] >= 0.0:
                    want = min(want, L[k] * s["stretch_limit"])
            x[k + 1] = x[k] + direction * want

    def end_substep(self, h):
        """speeds; on a contact the speed into the surface goes and the sliding part loses friction"""
        x, v, max_speed = self.x, self.v, self.s["max_speed"]
        for k in range(self.root + 1, self.tail + 1):
            v[k] = (x[k] - self.old[k]) / h
            if self.touched[k]:
                c = self.contact[k]
                into = v[k].dot(c)
                if into < 0.0:
                    v[k] = v[k] - c * into
                slide = v[k] - c * v[k].dot(c)
                v[k] = v[k] - slide * self.fric
            speed = v[k].length
            if max_speed > 0.0 and speed > max_speed:
                v[k] = v[k] * (max_speed / speed)

    def output(self):
        """step 6: the joints (the aim axis down the chain, the up axis nearest the FK's under the solved parent,
        blended with the FK), the chain's points and speeds"""
        chain, hook, x, v = self.chain, self.hook, self.x, self.v
        root, tip, tail, axis, up = self.root, self.tip, self.tail, self.axis, self.up
        for k in range(root, tail + 1):
            hook.anim_prev[k] = self.a[k].copy()
        blend = min(max(self.s["blend"], 0.0), 1.0)
        ia = axis % 3
        for k in range(root, tip + 1):
            F = self.A[k]
            if k > root:
                bone = self.arm.data.bones[chain.joints[k]]
                if bone.parent is not None and bone.parent.name == chain.joints[k - 1]:
                    F = _rigid(hook.out[k - 1] @ self.local_of(chain.joints[k]))
            pos = x[k]          # the root: its animated place, pushed out of the shapes (a[root] without a step)
            fr = F.to_3x3()
            aim = _unit(x[k + 1] - pos, _axis(fr, axis)) * (-1.0 if axis >= 3 else 1.0)
            if ia == up:
                rot = fr
            else:
                cols = [None, None, None]
                ic = 3 - ia - up
                cols[ia] = aim
                cols[up] = _unit(fr.col[up] - aim * fr.col[up].dot(aim), fr.col[ic].copy())
                cols[ic] = cols[(ic + 1) % 3].cross(cols[(ic + 2) % 3])
                rot = Matrix((cols[0], cols[1], cols[2])).transposed()
            out = fr.to_quaternion().slerp(rot.to_quaternion(), blend).to_matrix().to_4x4()
            out.translation = F.translation.lerp(pos, blend)
            hook.out[k] = out
            chain.mats[k] = out.copy()
        chain.mats[tail].translation = x[tail]
        for k in range(root + 1, tail + 1):
            chain.vel[k] = v[k]


def _link(p, wp, q, wq, rest, k):
    """a distance constraint softened to k (this pass's share), roots unmoved; returns the new (p, q)"""
    if k <= 0.0 or wp + wq <= 0.0:
        return p, q
    d = q - p
    length = d.length
    if length < SHORT:
        return p, q
    c = d * ((length - rest) / length * k / (wp + wq))
    return p + c * wp, q - c * wq


def sheet_links(members, cloth):
    """the sheet's links (chain_solver.md "Sheets"): neighbours point by point at the same depth (stretch), the
    diagonals (shear), the tendril after next (bend); rest lengths from the animated pose, tails included, up to the
    shorter tendril. [(member a, node a, member b, node b, rest, rate)]"""
    links = []
    n = len(members)
    if cloth is None or n < 2:
        return links

    def add(ta, da, tb, db, rate):
        if rate <= 0.0 or da > members[ta].nodes() or db > members[tb].nodes() or (da == 0 and db == 0):
            return
        ka, kb = members[ta].root + da, members[tb].root + db
        links.append((ta, ka, tb, kb, (members[tb].a[kb] - members[ta].a[ka]).length, rate))
    for i in range(n):
        j = i + 1 if i + 1 < n else (0 if cloth["closed"] and n > 2 else -1)
        if j >= 0:
            depth = min(members[i].nodes(), members[j].nodes())
            for d in range(1, depth + 1):
                add(i, d, j, d, cloth["stretch"])
            for d in range(depth):
                add(i, d, j, d + 1, cloth["shear"])
                add(i, d + 1, j, d, cloth["shear"])
        b = i + 2 if i + 2 < n else ((i + 2) % n if cloth["closed"] and n > 3 else -1)
        if b >= 0:
            depth = min(members[i].nodes(), members[b].nodes())
            for d in range(1, depth + 1):
                add(i, d, b, d, cloth["bend"])
    return links


def solve_set(members, cloth, T, ground):
    """steps 5-6 for a set of prepared tendrils: one, or a <cloth>'s sheet (cloth = its values, members in sheet
    order), its links first in each pass, then the members' constraints, then their lengths. T = the time the solve
    covers."""
    if not members:
        return
    substeps = max(min(max(t.hook.substeps, 1), 16) for t in members)
    iterations = max(min(max(t.hook.iterations, 1), 8) for t in members)
    if T > 0.0 and not any(t.reset for t in members):
        steps = min(max(math.ceil(T * substeps - 1e-4), 1), 64)
        h = T / steps
        for t in members:
            t.gather(ground)
        links = sheet_links(members, cloth)
        # a per-frame rate, as a share per substep, spread over the passes
        shares = {rate: 1.0 - (1.0 - _per_step(rate, h)) ** (1.0 / iterations) for *_, rate in links}
        for step in range(1, steps + 1):
            for t in members:
                t.begin_substep(h, step / steps)
            for it in range(iterations):
                # the sheet's links first, so the members' shapes / ground then push out what they pulled in (after
                # the shapes, the coat ended passes 0.53 cm inside the body against 0.09 alone)
                for ta, ka, tb, kb, rest, rate in links:
                    a, b = members[ta], members[tb]
                    a.x[ka], b.x[kb] = _link(a.x[ka], a.weight(ka), b.x[kb], b.weight(kb), rest, shares[rate])
                for t in members:
                    t.constrain(it == 0)
                for t in members:
                    t.lengths(h)
            for t in members:
                t.end_substep(h)
    for t in members:
        t.output()


def solve_tendril(chain, root, a_root, arm, local_of, T, shapes, ground):
    """A tendril on its own (no sheet): the note's steps 1-6 at the root's call."""
    solve_set([_Tendril(chain, root, a_root, arm, local_of, T, shapes)], None, T, ground)


def solve_sheet(members, cloth, arm, local_of, T, ground):
    """A <cloth> sheet at its first root's call: members = [(chain, root slot, its root's FK world, shapes)] in sheet
    order, cloth = {closed, stretch, shear, bend}. Each member's self collision skips its sheet neighbours on the same
    chain."""
    tendrils = [_Tendril(chain, slot, a_root, arm, local_of, T, shapes) for chain, slot, a_root, shapes in members]
    n = len(members)
    for i, (chain, _, _, _) in enumerate(members):
        for j, (other, slot, _, _) in enumerate(members):
            if other is chain and j != i and (j + 1 == i or i + 1 == j or
                                              (cloth["closed"] and ((j + 1) % n == i or (i + 1) % n == j))):
                tendrils[i].neighbours.append(slot)
    solve_set(tendrils, cloth, T, ground)


# ---- ground: the scene's stage collision ----------------------------------------------------------------------------

_tree = [None, None]        # (key, BVHTree)


def stage_meshes(scene):
    """the imported stage collision (.sbc) meshes of the scene"""
    from albam.engines.mtfw.collision import SBC_GROUP_INDEX
    return [ob for ob in scene.objects if ob.type == "MESH" and SBC_GROUP_INDEX in ob]


def ground_caster(scene):
    """cast(top, length) -> (normal turned up, hit point) of the first stage collision triangle straight below `top`
    within `length`, or None; None when the scene has no stage collision"""
    obs = stage_meshes(scene)
    if not obs:
        return None
    key = tuple((ob.name, len(ob.data.vertices), len(ob.data.polygons), tuple(map(tuple, ob.matrix_world)))
                for ob in obs)
    if _tree[0] != key:
        verts, polys = [], []
        for ob in obs:
            base = len(verts)
            verts += [ob.matrix_world @ vert.co for vert in ob.data.vertices]
            polys += [[base + i for i in poly.vertices] for poly in ob.data.polygons]
        _tree[:] = [key, BVHTree.FromPolygons(verts, polys)]
    tree = _tree[1]

    def cast(top, length):
        location, normal, _, _ = tree.ray_cast(top, DOWN, length)
        if location is None:
            return None
        n = -normal if normal.z < 0.0 else normal.copy()
        return _unit(n, UP), location
    return cast


def forget_ground():
    _tree[:] = [None, None]
