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

Version 2 of the note (its last section): soft constraints in XPBD form (`compliance`: a 0-1 rate keeps its meaning at
any substep or pass count, and is version 1 at 4 substeps exactly), settings spread along the tendril (`along`), the
reference motion carried apart for moving and turning (the animated pose too), and damping toward the animated speed.

`ground` casts a line per point at the scene's imported stage collision (.sbc meshes); without any it's skipped.
"""
import math

from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

SCALE = 0.01                    # game cm -> m
MAX_STEP = 2.0                  # one frame's time at most (ChainSolver on_move)
TELEPORT = 500.0 * SCALE        # a root jumping farther than this in a frame snaps the chain to the animation
UP = Vector((0.0, 0.0, 1.0))
DOWN = Vector((0.0, 0.0, -1.0))
TINY = 1e-6 * SCALE             # safe_normalize
SHORT = 1e-5 * SCALE            # a segment too short to have a direction
AXES = ("+x", "+y", "+z", "-x", "-y", "-z")     # axis codes 0-5
# <physics> settings that take one value or 2-8 along the tendril (chain_solver.md V2.2)
CURVES = ("stiffness", "pin", "damping", "radius", "limit", "gravity")


def _values(v):
    return [float(x) for x in v] if isinstance(v, (list, tuple)) else [float(v)]


def along(values, u):
    """a setting spread evenly from the root (u 0) to the tail (u 1), read linearly; one value holds everywhere"""
    if len(values) == 1:
        return values[0]
    t = min(max(u, 0.0), 1.0) * (len(values) - 1)
    i = min(int(t), len(values) - 2)
    return values[i] + (values[i + 1] - values[i]) * (t - i)


def compliance(rate):
    """a 0-1 per-frame rate as an XPBD compliance, in frames squared (chain_solver.md V2.1): version 1's share per
    substep at 4 substeps exactly. 0 = hard (rate 1); None = the constraint is off (rate 0 or less)"""
    if rate <= 0.0:
        return None
    if rate >= 1.0:
        return 0.0
    return (1.0 / (1.0 - (1.0 - rate) ** 0.25) - 1.0) / 16.0


class Hook:
    """A chain's <physics> settings (movedef.ext_list.physics_values) over its file's (cns_chain_preview._settings),
    and the runner's per-tendril state (indexed by the tendril root's slot)."""

    def __init__(self, values, s):
        self.values = dict(values)
        self.substeps = values["substeps"]
        self.iterations = values["iterations"]
        # the settings that can vary along the tendril are lists of 1-8 values (along)
        self.stiffness = _values(values["stiffness"])
        self.pin = _values(values["pin"])
        self.limit = _values(values["limit"])
        self.gravity = _values(values.get("gravity", 1.0))
        local = s["pos_local"] or s["pos_local_y"] or s["rot_local"]
        self.inertia = values["inertia"] if values["inertia"] is not None else (0.0 if local else 1.0)
        move, turn = values.get("inertia_move"), values.get("inertia_turn")
        self.inertia_move = move if move is not None else self.inertia
        self.inertia_turn = turn if turn is not None else self.inertia
        self.friction = values["friction"]
        # speed lost per frame; auto = 1 - mDamping, at least 0.1: the game's solver drops the speed its length
        # correction implies (RE note 3.2g), so mDamping 1.0 still loses energy there; here it would swing for good
        damping = values.get("damping")
        self.damping = (_values(damping) if damping is not None
                        else [max(0.1, 1.0 - min(max(s["damping"], 0.0), 1.0))])
        radius = values["radius"]
        self.radius = [r * SCALE for r in _values(radius)] if radius is not None else [s["radius"]]
        self.ground = values["ground"]
        self.backstop = bool(values.get("backstop", False))     # V2.4: contacts push toward the animated side
        self.damp_world = bool(values.get("damp_world", False))  # V2.5: damping toward zero world speed
        self.self = values["self"]
        self.axis = values["axis"] if values["axis"] is not None else min(max(s["dir"], 0), 5)
        self.up = s["up"] % 3
        self.clear()

    def clear(self):
        self.seen = set()           # nodes with a previous animated place
        self.anim_prev = {}
        self.ref_prev = {}          # tendril root -> the reference frame at its last solve
        self.shapes_prev = {}       # tendril root -> the shapes [(a, b, r)] at its last solve (V2.6)
        self.out = {}               # slot -> the joint's last result (world, rigid)
        self.solved = {}            # slot -> the point after the last solve (V2.7: the solver's own state)
        self.written = {}           # slot -> what output() put in mats[slot] (the drawn position)

    def state_point(self, chain, k):
        """V2.7: node k's point to start from: the solver's own while mats[k] still holds what output() wrote, else
        mats[k] (another writer: the game's solver, a reset)"""
        drawn = chain.mats[k].translation
        if k in self.solved and (drawn - self.written[k]).length < 1e-3 * SCALE:
            return self.solved[k].copy()
        return drawn.copy()


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


def _project(lams, key, C, w_sum, alpha_t):
    """one XPBD step of constraint `key` (its lambda kept in `lams` for the substep): dlambda for value C over the
    weights w_sum, compliance alpha_t = alpha / h^2"""
    lam = lams.get(key, 0.0)
    dl = (-C - alpha_t * lam) / (w_sum + alpha_t)
    lams[key] = lam + dl
    return dl


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

        # settings along the tendril (V2.2): node k's value acts on segment k-1..k (stiffness, pin, limit) or on
        # point k (damping, gravity); radius per node, a segment's taken where it's closest
        u = {k: (k - root) / (tail - root) for k in nodes}
        self.r = {k: along(hook.radius, u[k]) for k in nodes}
        later = range(root + 1, tail + 1)
        self.stiff_c = {k: compliance(along(hook.stiffness, u[k])) for k in later}
        self.pin_c = {k: compliance(along(hook.pin, u[k])) for k in later}
        self.limit = {k: min(max(along(hook.limit, u[k]), 0.0), 180.0) for k in later}
        self.damping = {k: min(max(along(hook.damping, u[k]), 0.0), 1.0) for k in later}
        self.gravity = {k: along(hook.gravity, u[k]) for k in later}
        self.stretch_c = compliance(s["spring"]) if s["stretch"] else None

        # 2. reset: the first solve, the game's reset state (cCnsChain::move still runs), or the root jumped
        self.reset = root not in hook.seen or chain.in_reset or (a[root] - hook.anim_prev[root]).length > TELEPORT
        # 3. points
        self.x, self.v = {}, {}
        for k in nodes:
            self.x[k] = a[k].copy() if self.reset else hook.state_point(chain, k)
            self.v[k] = Vector() if self.reset else chain.vel[k].copy()
            if self.reset or k not in hook.seen:
                hook.anim_prev[k] = a[k].copy()
            hook.seen.add(k)
        self.x[root] = a[root].copy()
        if self.reset:
            hook.shapes_prev.pop(root, None)

        # 4. inertia (V2.3): the parts of the reference frame's turn and move the points are carried by, and the
        # previous animated pose with them, so the substep targets start where the carried points are
        ref = chain.parent
        self.ref_rot = ref.to_3x3()
        self.carry = None               # (origin, turn, shift) when this solve carries: the last shapes go with it
        if not self.reset:
            turn_part = 1.0 - min(max(hook.inertia_turn, 0.0), 1.0)
            move_part = 1.0 - min(max(hook.inertia_move, 0.0), 1.0)
            prev = hook.ref_prev.get(root)
            if (turn_part > 0.0 or move_part > 0.0) and prev is not None and T > 0.0:
                r0, r1 = prev.to_3x3().normalized(), ref.to_3x3().normalized()
                p0 = prev.translation.copy()
                turn = Quaternion().slerp((r1 @ r0.transposed()).to_quaternion(), turn_part).to_matrix()
                shift = (ref.translation - p0) * move_part
                self.carry = (p0, turn, shift)
                for k in range(root + 1, tail + 1):
                    self.x[k] = p0 + turn @ (self.x[k] - p0) + shift
                    self.v[k] = turn @ self.v[k]
                for k in nodes:
                    hook.anim_prev[k] = p0 + turn @ (hook.anim_prev[k] - p0) + shift
        hook.ref_prev[root] = ref.copy()

        self.g = self.ref_rot @ s["gravity"] if s["gravity_local"] else s["gravity"].copy()
        self.wind = Vector() if s["mute_wind"] else chain.wind.copy()
        if s["wind_local"]:
            self.wind = self.ref_rot @ self.wind
        self.shapes_to = [] if s["mute_collision"] else [(sa.copy(), sb.copy(), sr) for sa, sb, sr in shapes]
        self.shapes_from = self.shapes = self.shapes_to
        self.old, self.contact, self.touched = {}, {}, {}
        self.at = {k: hook.anim_prev[k].copy() for k in nodes}      # the substep targets, before the first
        self.planes, self.others = {}, []
        self.lams, self.alpha_t = {}, 1.0

    def nodes(self):
        return self.tail - self.root

    def weight(self, k):
        return 0.0 if k == self.root else 1.0

    def gather(self, ground):
        """before the substeps: the shapes' start (V2.6), the ground under each point, the other tendrils' segments with
        their radii (self)"""
        x, a = self.x, self.a
        # V2.6: the substeps move the shapes from where they were at the last solve, carried like the points, to where
        # they are now (taken once at the frame's pose, a leg's whole frame of motion hit the points in the first
        # substep). None before (first solve, a reset, another shape count): as now throughout
        prev = self.hook.shapes_prev.get(self.root)
        self.shapes_from = self.shapes_to
        if prev is not None and len(prev) == len(self.shapes_to):
            if self.carry is not None:
                p0, turn, shift = self.carry
                prev = [(p0 + turn @ (pa - p0) + shift, p0 + turn @ (pb - p0) + shift, pr) for pa, pb, pr in prev]
            self.shapes_from = [(pa, pb, now[2]) for (pa, pb, _), now in zip(prev, self.shapes_to)]
        self.hook.shapes_prev[self.root] = self.shapes_to
        self.shapes = self.shapes_to
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
            chain, radius = self.chain, self.hook.radius
            for k, name in enumerate(chain.joints):
                if name is None or self.root <= k <= self.tip:
                    continue
                o_root, o_tip = tendril(chain, k)
                if o_root in self.neighbours:
                    continue
                span = o_tip + 1 - o_root
                self.others.append((self.hook.state_point(chain, k), self.hook.state_point(chain, k + 1),
                                    along(radius, (k - o_root) / span), along(radius, (k + 1 - o_root) / span)))

    def begin_substep(self, h, f):
        """targets, root push, forces: damping toward the animated speed (V2.3; zero world speed with damp_to="world",
        V2.5), then gravity and wind"""
        hook, x, v, root, r = self.hook, self.x, self.v, self.root, self.r
        self.fric = _per_step(hook.friction, h)
        self.lams, self.alpha_t = {}, 1.0 / (h * h)
        at_prev = self.at
        self.at = {k: hook.anim_prev[k].lerp(self.a[k], f) for k in range(root, self.tail + 1)}
        if self.shapes_from is not self.shapes_to:
            self.shapes = [(fa.lerp(ta, f), fb.lerp(tb, f), tr)
                           for (fa, fb, _), (ta, tb, tr) in zip(self.shapes_from, self.shapes_to)]
        self.old[root] = x[root].copy()         # where the root was, for V2.4's side (before its target and push)
        x[root] = self.at[root].copy()
        # root push: the root, a sphere of its radius, out of every shape (the game keeps a root's push too; Nero's
        # coat roots _02 / _03 sit inside a body shape at bind and would hold their first segment in it)
        for ca, cb, cr in self.shapes:
            _, w = _closest(x[root], x[root], ca, cb)
            d = x[root] - ca.lerp(cb, w)
            pen = r[root] + cr - d.length
            if pen > 0.0:
                x[root] = x[root] + _unit(d, UP) * pen
        for k in range(root + 1, self.tail + 1):
            va = Vector() if hook.damp_world else (self.at[k] - at_prev[k]) / h
            v[k] = va + (v[k] - va) * (1.0 - self.damping[k]) ** h
            v[k] = v[k] + (self.g * self.gravity[k] + self.wind) * h
            self.old[k] = x[k].copy()
            x[k] = x[k] + v[k] * h
            self.touched[k] = False

    def _goal(self, kind, k, p, goal, alpha):
        """a soft goal constraint |p - goal| (only p moves, the goal fixed), XPBD"""
        d = p - goal
        C = d.length
        if C < SHORT:
            return p
        dl = _project(self.lams, (kind, k), C, 1.0, alpha * self.alpha_t)
        return p + d * (dl / C)

    def constrain(self):
        """one constraint pass up to the lengths: stiffness and pin (soft, every pass), shapes, self, ground, limit"""
        s, x, at, r = self.s, self.x, self.at, self.r
        root, tail = self.root, self.tail
        touched, contact = self.touched, self.contact
        for k in range(root + 1, tail + 1):
            alpha = self.stiff_c[k]
            if alpha is not None:       # stiffness: toward the animated direction, the length kept as it is
                goal = x[k - 1] + _unit(at[k] - at[k - 1], DOWN) * (x[k] - x[k - 1]).length
                x[k] = self._goal("stiffness", k, x[k], goal, alpha)
            alpha = self.pin_c[k]
            if alpha is not None:       # pin: toward the animated place
                x[k] = self._goal("pin", k, x[k], at[k], alpha)
        for k in range(root, tail):         # shapes: both ends pushed, weighted by u; the root doesn't move
            for ca, cb, cr in self.shapes:
                u, w = _closest(x[k], x[k + 1], ca, cb)
                p, q = x[k].lerp(x[k + 1], u), ca.lerp(cb, w)
                ru = r[k] + (r[k + 1] - r[k]) * u
                pen = ru + cr - (p - q).length
                if pen <= 0.0:
                    continue
                n = _unit(p - q, _unit(x[k + 1] - ca, UP))
                # V2.4: a point that crossed to the other side of the shape from its reference is pushed out on the
                # reference's side. The reference is where the segment was at the substep's start (a tunnelled point
                # goes back where it entered), or with backstop its animated place (a stuck strip comes back: Ellen's
                # skirt behind a thigh, 2026-11-11; opt-in, since long coat tails swinging round the legs get thrown
                # across them)
                ra, rb = (at[k], at[k + 1]) if self.hook.backstop else (self.old[k], self.old[k + 1])
                ua, wa_ = _closest(ra, rb, ca, cb)
                side = ra.lerp(rb, ua) - ca.lerp(cb, wa_)
                if (p - q).dot(side) < 0.0 and side.length > 1e-4 * SCALE:
                    n = side.normalized()
                    pen = ru + cr - (p - q).dot(n)
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
        if self.others:                     # self: the other tendrils, both radii, half the push
            for k in range(root, tail):
                for oa, ob, ra, rb in self.others:
                    u, w = _closest(x[k], x[k + 1], oa, ob)
                    p, q = x[k].lerp(x[k + 1], u), oa.lerp(ob, w)
                    dist = (p - q).length
                    pen = r[k] + (r[k + 1] - r[k]) * u + ra + (rb - ra) * w - dist
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
                d = (x[k] - p).dot(n) - r[k]
                if d < 0.0:
                    x[k] = x[k] - n * d
                    touched[k], contact[k] = True, n
            if s["floor_on"] and x[k].z < s["floor"] + r[k]:
                x[k].z = s["floor"] + r[k]
                touched[k], contact[k] = True, UP.copy()
        for k in range(root + 1, tail + 1):     # limit: within node k's degrees of the animated direction, length kept
            if self.limit[k] <= 0.0:
                continue
            lim = math.radians(self.limit[k])
            cos_limit, sin_limit = math.cos(lim), math.sin(lim)
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

    def lengths(self):
        """lengths last, root to tail, each child moved onto its parent's sphere (exact); with mStretch a soft stretch
        (len - L > 0, compliance from mSpring) instead, each segment then capped at L x mStretchLimit"""
        s, x, at, L, root = self.s, self.x, self.at, self.L, self.root
        if not s["stretch"]:
            for k in range(root, self.tail):
                d = x[k + 1] - x[k]
                length = d.length
                direction = d / length if length > SHORT else _unit(at[k + 1] - at[k], DOWN)
                x[k + 1] = x[k] + direction * L[k]
            return
        for k in range(root, self.tail):    # per segment, root to tail: its soft stretch, then its cap (the runner's)
            if self.stretch_c is not None:
                d = x[k + 1] - x[k]
                length = d.length
                if length - L[k] > 0.0 and length >= SHORT:
                    wa = 0.0 if k == root else 1.0
                    n = d / length
                    # two points: alpha = W x compliance, W = the weights' sum (version 1's share was split over both)
                    dl = _project(self.lams, ("stretch", k), length - L[k], wa + 1.0,
                                  (wa + 1.0) * self.stretch_c * self.alpha_t)
                    x[k] = x[k] - n * (wa * dl)
                    x[k + 1] = x[k + 1] + n * dl
            if s["stretch_limit"] >= 0.0:
                d = x[k + 1] - x[k]
                length = d.length
                cap = L[k] * s["stretch_limit"]
                if length > cap:
                    direction = d / length if length > SHORT else _unit(at[k + 1] - at[k], DOWN)
                    x[k + 1] = x[k] + direction * cap

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
            hook.written[k] = out.translation.copy()
        # V2.7: the solver keeps its own points; mBlend only shapes what's drawn (fed back, it snapped the points
        # 1 - mBlend of the way to the FK every frame while their speeds stayed the solver's)
        for k in range(root, tail + 1):
            hook.solved[k] = x[k].copy()
        chain.mats[tail].translation = x[tail]
        hook.written[tail] = x[tail].copy()
        for k in range(root + 1, tail + 1):
            chain.vel[k] = v[k]


def _link(lams, key, p, wp, q, wq, rest, alpha_t):
    """a soft distance constraint |q - p| - rest (both signs, XPBD, compliance alpha_t = alpha / h^2), roots
    unmoved; returns the new (p, q)"""
    if wp + wq <= 0.0:
        return p, q
    d = q - p
    length = d.length
    if length < SHORT:
        return p, q
    n = d / length
    # two points: alpha = W x compliance, W = wp + wq (version 1's share per substep was split over both ends)
    dl = _project(lams, key, length - rest, wp + wq, (wp + wq) * alpha_t)
    return p - n * (wp * dl), q + n * (wq * dl)


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
    covers. Every soft constraint (links, stiffness, pin, stretch) is XPBD: its lambda starts at 0 each substep."""
    if not members:
        return
    if T <= 0.0 and not any(t.reset for t in members):
        return      # nothing stepped: the joints keep their stored result (the game's pause, RE note 3.2b; step 6)
    substeps = max(min(max(t.hook.substeps, 1), 16) for t in members)
    iterations = max(min(max(t.hook.iterations, 1), 8) for t in members)
    if T > 0.0 and not any(t.reset for t in members):
        steps = min(max(math.ceil(T * substeps - 1e-4), 1), 64)
        h = T / steps
        for t in members:
            t.gather(ground)
        links = sheet_links(members, cloth)
        alphas = [compliance(rate) / (h * h) for *_, rate in links]     # rate > 0 there, so never None
        for step in range(1, steps + 1):
            for t in members:
                t.begin_substep(h, step / steps)
            lams = {}
            for _ in range(iterations):
                # the sheet's links first, so the members' shapes / ground then push out what they pulled in (after
                # the shapes, the coat ended passes 0.53 cm inside the body against 0.09 alone)
                for i, (ta, ka, tb, kb, rest, _rate) in enumerate(links):
                    a, b = members[ta], members[tb]
                    a.x[ka], b.x[kb] = _link(lams, i, a.x[ka], a.weight(ka), b.x[kb], b.weight(kb), rest, alphas[i])
                for t in members:
                    t.constrain()
                for t in members:
                    t.lengths()
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
