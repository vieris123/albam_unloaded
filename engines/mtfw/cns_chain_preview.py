"""Motion preview of DMC4 model chains (`.phs` = rCnsChain, imported by cns_chain.py): the game's soft-body solver
replayed on the armature while the animation plays. Preview only: nothing is keyed or exported.

The solver follows the DX9 code (Vibed/RE/chain_cnschain.md):
- cCnsChain::move 0x42DB00, once per frame: the step (1 per 60 fps frame), the wind (mWind; the mTurbulence offset
  only applies when a frame is shorter than one step, see _Chain.move), the parent frame and its motion since the last
  frame (mParentMode 0 = the model's world matrix, 1 = its parent unit's; mPosLocal / mPosLocalY / mRotLocal), the
  reset (the first 2 frames copy the animation).
- the per-joint solve 0x430A20, called for every chain joint in hierarchy order after its parent's final matrix:
  node i + 1 (the next slot's joint, or a virtual tail mTailLength along mDir after the last) is carried with the
  parent frame, gets vel += (gravity + wind) * t, pos += vel * t, then is put back at the rest length L (= |bind
  local translation of the next joint|) from the joint (with mStretch: only beyond L * mStretchLimit), kept above
  mFloorLevel (vel *= mDamping * 0.1 when it hits), pushed out of the collision shapes (joint and node by the same
  amount, vel = 0; 0x438DB0), then vel += -(distance - L) * dir * mSpring * t (if it was beyond L), vel *= mDamping,
  |vel| clamped to mMaxSpeed. The joint is then turned so its mDir axis points at node i + 1 and its mUp axis stays
  close to the animated one (Gram-Schmidt, mDir exact), placed at node i (the chain root keeps its animated
  position), and blended with the animation in the parent's frame by mBlend (sub_48DFB0: Z and Y axes lerped, then
  orthonormalised with Z exact; position lerped).

Blender: units are converted (cm -> m, game Y up -> Blender Z up; bone frames are the game joint frames, so bone axis
k is joint axis k). Per scene frame the solver steps round(60 / fps) times. A frame_change_pre handler puts the chain
bones back to their pose without the preview (stored when it was turned on, `phs_preview_base`), so the animation
sets them; the frame_change_post handler reads the animated pose, steps the chains of each armature and writes the
chain bones' matrix_basis. Frames are cached per armature: playing forward steps, a cached frame shows its pose,
any other frame starts over there (reset). Simulate Range runs the scene range once to fill the cache. The parent
frame is the armature object's world matrix times its `root_motion` bone (LMT import's root motion, which is the
character's movement in the game); mode 1 uses the armature's parent armature when it has one.

Collision: the shapes of an imported `.col` (col_shapes.py, a COL_ object: spheres / capsules on joints of the body
model), every group and shape tested in file order as the game does.

A chain a ModelExtension `<physics>` entry names (a scene list, its model and file) runs dmc4_hook's solver instead
(cns_chain_hook.py, Vibed/ModelExt/chain_solver.md): once per scene frame over the frame's time, with substeps. The
Chain panel's dmc4_hook box adds, edits and removes that entry. A `<cloth>` joins such tendrils, from any of the
armature's chains, into one sheet solved together (cns_chain_hook.solve_sheet). `<link>`s run after either solver.

wire_scene connects the pieces after any .mod / .phs / .col import, in any order: a chain or .col waiting for its
model attaches when it comes, a chain picks up the COL_ object of its default .col (pl000_03_00.phs ->
pl000_03.col), and a coat model (COAT_BODY_JOINT) is attached to the shapes' body armature at its joint. What's still
missing is listed on the chain (`phs_status`, shown in the Chain panel).
"""
import json
import math
import random

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from albam.lib import blender_compat as compat
from albam.lib import nla
from albam.registry import blender_registry
from albam.engines.mtfw import col_shapes
from albam.engines.mtfw import cns_chain
from albam.engines.mtfw import cns_chain_hook
from albam.engines.mtfw.cns_chain import (ARMATURE_PROP, COLLECTION_PROP, JOINTS_PROP, _stem, attach_chain,
                                          chain_armature, chain_joints, find_chain_armature, _joint_bones)

SCALE = 0.01                        # game cm -> m
GAME_STEP = 60.0                    # solver steps per second
RESET_FRAMES = 2                    # move 0x4309C0: the reset state lasts until its timer (+1 per frame) reaches 3
EPS = 1.1920929e-07
BASE_PROP = "_phs_preview_base"     # Empty: {bone name: 16 floats}, the chain bones' pose without the preview
                                    # (leading _: Blender hides it in Custom Properties; a dict can't have a tooltip)
NO_JOINT = 255


def game_vec(v):
    """game axes (Y up, cm) -> Blender (Z up, m)"""
    return Vector((v[0], -v[2], v[1])) * SCALE


def _settings(ob):
    def f(name, default):
        return float(ob.get(name, default))

    def vec(name):
        v = list(ob.get(name, (0.0, 0.0, 0.0)))[:3]
        return game_vec(v + [0.0] * (3 - len(v)))
    return {
        "blend": f("mBlend", 1.0), "dir": int(ob.get("mDir", 4)), "up": int(ob.get("mUp", 2)),
        "tail": f("mTailLength", 10.0) * SCALE, "gravity": vec("mGravity"), "wind": vec("mWind"),
        "turbulence": f("mTurbulence", 0.0) * SCALE, "spring": f("mSpring", 0.01), "damping": f("mDamping", 0.98),
        "max_speed": f("mMaxSpeed", 10.0) * SCALE, "floor": f("mFloorLevel", -9999.0) * SCALE,
        "stretch": bool(ob.get("mStretch", False)), "stretch_limit": f("mStretchLimit", 100.0),
        "radius": f("mCollisionSize", 5.0) * SCALE, "parent_mode": int(ob.get("mParentMode", 0)),
        "pos_local": bool(ob.get("mPosLocal", False)), "pos_local_y": bool(ob.get("mPosLocalY", False)),
        "rot_local": bool(ob.get("mRotLocal", False)), "wind_local": bool(ob.get("mWindLocal", False)),
        "gravity_local": bool(ob.get("mGravityLocal", False)),
        # read by dmc4_hook's solver only (cns_chain_hook)
        "mute_wind": bool(ob.get("mMuteWind", False)), "mute_collision": bool(ob.get("mMuteCollision", False)),
        "floor_on": f("mFloorLevel", -9999.0) > -9000.0,
    }


def _rotation(m):
    """rotation part with the axes normalised (the game normalises the rows before using a frame)"""
    return m.to_3x3().normalized()


def _axis(m3, index):
    """axis enum 0..5 = +X +Y +Z -X -Y -Z: a column of a 3x3 (bone frames = joint frames)"""
    v = m3.col[index % 3].copy()
    return -v if index >= 3 else v


def _orient(primary_axis, primary, hint_axis, hint):
    """3x3 with axis primary_axis along primary (exact) and hint_axis as close as possible to hint, right-handed
    (sMath::setOrientationZY and its siblings: X = Y x Z, Y = Z x X, Z = X x Y)"""
    cols = [None, None, None]
    cols[primary_axis] = primary.normalized()
    cols[hint_axis] = hint
    other = 3 - primary_axis - hint_axis
    cols[other] = cols[(other + 1) % 3].cross(cols[(other + 2) % 3])
    if cols[other].length < EPS:
        return None
    cols[other].normalize()
    cols[hint_axis] = cols[(hint_axis + 1) % 3].cross(cols[(hint_axis + 2) % 3]).normalized()
    return Matrix((cols[0], cols[1], cols[2])).transposed()


def limit_angles(local, limits):
    """mBoneAdjust (calcJointImpl 0x433376 before the blend, 0x43418D after it): the bone's measured axis (column
    `grid` of its rotation in the parent's frame) gives two angles (cUtil::calcAngleXY / calcPitch + atan2), each
    clamped to its Min / Max (degrees); if either was clamped the rotation is rebuilt from the two angles (the game's
    order: grid 2 X then Y, grid 1 X then Z, grid 0 Y then Z; no roll), the position kept."""
    grid, lo, hi = limits
    d = local.to_3x3().normalized().col[grid]
    if grid == 2:
        a1, a2, i1, i2 = -math.atan2(d.y, math.hypot(d.x, d.z)), math.atan2(d.x, d.z), 0, 1
    elif grid == 1:
        a1, a2, i1, i2 = -math.atan2(d.y, math.hypot(d.x, d.z)), math.atan2(d.y, d.x), 0, 2
    else:
        a1, a2, i1, i2 = math.atan2(d.x, d.z), math.atan2(d.y, d.x), 1, 2
    a1, a2 = math.degrees(a1), math.degrees(a2)
    clamped = False
    if lo[i1] > a1:
        a1, clamped = lo[i1], True
    if a1 > hi[i1]:
        a1, clamped = hi[i1], True
    if lo[i2] > a2:
        a2, clamped = lo[i2], True
    if a2 > hi[i2]:
        a2, clamped = hi[i2], True
    if not clamped:
        return local
    r1, r2 = math.radians(a1), math.radians(a2)
    if grid == 2:
        rot = Matrix.Rotation(r2, 3, "Y") @ Matrix.Rotation(r1, 3, "X")
    elif grid == 1:
        rot = Matrix.Rotation(r2, 3, "Z") @ Matrix.Rotation(r1, 3, "X")
    else:
        rot = Matrix.Rotation(r2, 3, "Z") @ Matrix.Rotation(r1, 3, "Y")
    out = rot.to_4x4()
    out.translation = local.translation
    return out


def _blend(sim, anim, w):
    """sub_48DFB0 in Blender's column form: Z and Y axes lerped (w = simulated), rebuilt with Z exact, position
    lerped. Both are rigid (no scale)."""
    if w >= 1.0:
        return sim.copy()
    if w <= 0.0:
        return anim.copy()
    z = sim.col[2].xyz * w + anim.col[2].xyz * (1.0 - w)
    y = sim.col[1].xyz * w + anim.col[1].xyz * (1.0 - w)
    rot = _orient(2, z, 1, y) if z.length > EPS else None
    if rot is None:
        rot = anim.to_3x3()
    out = rot.to_4x4()
    out.translation = sim.translation * w + anim.translation * (1.0 - w)
    return out


def _closest_on_segment(a, b, p):
    ab = b - a
    denom = ab.length_squared
    t = 0.0 if denom < 1e-12 else max(0.0, min(1.0, (p - a).dot(ab) / denom))
    return a + ab * t


def _closest_segments(p0, p1, q0, q1):
    """closest points of segments p0p1 and q0q1 (sub_8D0F00)"""
    d1, d2, r = p1 - p0, q1 - q0, p0 - q0
    a, e, f = d1.length_squared, d2.length_squared, d2.dot(r)
    if a < 1e-12 and e < 1e-12:
        return p0.copy(), q0.copy()
    if a < 1e-12:
        return p0.copy(), _closest_on_segment(q0, q1, p0)
    c = d1.dot(r)
    if e < 1e-12:
        return _closest_on_segment(p0, p1, q0), q0.copy()
    b = d1.dot(d2)
    denom = a * e - b * b
    s = max(0.0, min(1.0, (b * f - c * e) / denom)) if denom > 1e-12 else 0.0
    t = (b * s + f) / e
    if t < 0.0:
        t, s = 0.0, max(0.0, min(1.0, -c / a))
    elif t > 1.0:
        t, s = 1.0, max(0.0, min(1.0, (b - c) / a))
    return p0 + d1 * s, q0 + d2 * t


def _away_from(seg, q):
    """a unit vector perpendicular to seg (the game's fallback when the centre lies on the segment)"""
    axis = seg.normalized() if seg.length > EPS else Vector((0.0, 0.0, 1.0))
    ref = Vector((0.0, 1.0, 0.0)) if abs(axis.y) < 0.9999 else Vector((1.0, 0.0, 0.0))
    return axis.cross(ref).cross(axis).normalized()


def collide(p0, p1, radius, shapes):
    """cCnsChain collision 0x438DB0: the segment p0-p1 with radius against every shape (("sphere", c, r) or
    ("capsule", a, b, r)) in order; on each hit both ends move by normal * depth (depth <= 0, normal toward the
    shape, sub_8C1D20 / sub_8C2230). Returns (hit, push of p0, p0, p1)."""
    start = p0.copy()
    p0, p1 = p0.copy(), p1.copy()
    hit = False
    for shape in shapes:
        if shape[0] == "sphere":
            centre, r = shape[1], shape[2]
            q = _closest_on_segment(p0, p1, centre)
            other = centre
        else:
            a, b, r = shape[1], shape[2], shape[3]
            q, other = _closest_segments(p0, p1, a, b)
        d = other - q
        dist = d.length
        n = d / dist if dist >= 1e-8 else _away_from(p1 - p0, q)
        depth = dist - (radius + r)
        if depth <= 0.0:
            p0 += n * depth
            p1 += n * depth
            hit = True
    return hit, p0 - start, p0, p1


class _Chain:
    """One cCnsChain: its settings, joints (bone name per slot, None if missing) and simulation state."""

    def __init__(self, ob, arm):
        self.name = ob.name
        self.s = _settings(ob)
        problems = []
        bones = _joint_bones(arm)
        # one entry per slot: None for the -1 between tendrils (the slot after a tendril's tip holds its tail)
        self.joints = [bones[j].name if j >= 0 and j in bones else None for j in chain_joints(ob, problems)]
        self.limits = [cns_chain.bone_limits(arm.pose.bones[n]) if n is not None else None for n in self.joints]
        self.rng = random.Random(self.name)
        self.mats = [Matrix.Identity(4) for _ in range(len(self.joints) + 1)]
        self.vel = [Vector() for _ in range(len(self.joints) + 1)]
        values = _physics(ob)       # a ModelExtension <physics> entry: dmc4_hook's solver (cns_chain_hook)
        self.hook = cns_chain_hook.Hook(values, self.s) if values is not None else None
        self.reset()

    def reset(self):
        self.resetting = RESET_FRAMES
        self.prev_parent = None
        self.turb_timer, self.turb = 0.0, Vector()
        if self.hook is not None:
            self.hook.clear()

    def move(self, parent, t):
        """per-frame part (0x42DB00): wind with turbulence, the parent frame delta"""
        s = self.s
        self.wind = s["wind"].copy()
        self.turb_timer += t
        if self.turb_timer < 1.0:
            self.wind += self.turb * t
        else:                                   # re-rolled, but not added this frame: at a steady step of 1 the
            self.turb_timer = 0.0               # turbulence never applies (0x42DCF6)
            self.turb = Vector([(self.rng.random() - 0.5) * s["turbulence"] for _ in range(3)])
            self.turb = Vector((self.turb.x, -self.turb.z, self.turb.y))
        prev = self.prev_parent if self.prev_parent is not None else parent
        self.parent = parent
        self.parent_rot = _rotation(parent)
        self.delta = Matrix.Identity(4)
        if s["pos_local"] or s["pos_local_y"]:
            if s["rot_local"]:
                self.delta = parent @ prev.inverted_safe()
            else:
                move = parent.translation - prev.translation
                if s["pos_local_y"]:
                    move = Vector((0.0, 0.0, move.z))
                self.delta = Matrix.Translation(move)
        elif s["rot_local"]:                    # (not in the game's files) rotation about the parent's origin
            rot = (self.parent_rot @ _rotation(prev).transposed()).to_4x4()
            self.delta = Matrix.Translation(parent.translation) @ rot @ Matrix.Translation(-parent.translation)
        self.carry = s["pos_local"] or s["pos_local_y"] or s["rot_local"]
        self.prev_parent = parent.copy()
        self.in_reset = self.resetting > 0
        if self.resetting > 0:
            self.resetting -= 1

    def rest_length(self, slot, arm):
        """L of segment slot: |bind local translation| of the next slot's joint, or mTailLength after the last"""
        if slot + 1 >= len(self.joints) or self.joints[slot + 1] is None:
            return self.s["tail"]
        bone = arm.data.bones[self.joints[slot + 1]]
        local = bone.matrix_local if bone.parent is None else bone.parent.matrix_local.inverted() @ bone.matrix_local
        return local.translation.length

    def solve(self, slot, joint, parent_final, arm, t, shapes):
        """0x430A20 for chain slot `slot`: joint = its animated world matrix (parent's final world @ animated local),
        parent_final = the parent's final world matrix (None for a root bone). Returns the joint's final world."""
        s = self.s
        nxt = slot + 1
        if self.in_reset:
            self.mats[slot] = joint.copy()
            self.vel[slot] = Vector()
            if nxt >= len(self.joints) or self.joints[nxt] is None:     # a tendril's tip: place its tail
                tail = joint.copy()
                d = s["dir"]
                axis = _axis(_rotation(joint), {2: 5}.get(d, d))      # the reset's switch: 2 is -Z, like 5
                tail.translation = joint.translation + axis * s["tail"]
                self.mats[nxt] = tail
                self.vel[nxt] = Vector()
            return joint
        length = self.rest_length(slot, arm)
        p = self.mats[nxt].translation.copy()
        vel = self.vel[nxt]
        if self.carry:
            p = (self.delta @ p.to_4d()).xyz
            vel = self.delta.to_3x3() @ vel
        wind = self.parent_rot @ self.wind if s["wind_local"] else self.wind
        gravity = self.parent_rot @ s["gravity"] if s["gravity_local"] else s["gravity"]
        vel = vel + (gravity + wind) * t
        p = p + vel * t
        origin = joint.translation.copy()
        d = p - origin
        dist = d.length
        direction = d / dist if dist >= EPS else d
        if not s["stretch"]:
            p = origin + direction * length
        elif s["stretch_limit"] >= 0.0 and dist > length * s["stretch_limit"]:
            p = origin + direction * length * s["stretch_limit"]
        if s["floor"] > p.z:
            p.z = s["floor"]
            vel = vel * (s["damping"] * 0.1)
        if shapes:
            hit, push, _, _ = collide(origin, p, s["radius"], shapes)
            if hit:
                origin += push
                p += push
                vel = Vector()
        if dist > length:
            vel = vel - direction * ((dist - length) * s["spring"] * t)
        if t > 0.0:
            vel = vel * s["damping"]
        if vel.length > s["max_speed"]:
            vel = vel.normalized() * s["max_speed"]
        self.vel[nxt] = vel
        self.mats[nxt].translation = p

        aim = p - origin
        if 3 <= s["dir"] <= 5:
            aim = -aim
        rot = _rotation(joint)
        dir_axis, up_axis = s["dir"] % 3, s["up"] % 3
        if dir_axis != up_axis and aim.length > EPS:
            built = _orient(dir_axis, aim, up_axis, _axis(rot, s["up"]))
            if built is not None:
                rot = built
        sim = rot.to_4x4()
        # a tendril's root (slot 0, or right after a -1) keeps its animated position; the others sit on node i
        sim.translation = self.mats[slot].translation if slot > 0 and self.joints[slot - 1] is not None else origin
        limits = self.limits[slot]
        if parent_final is None:
            frame = Matrix.Identity(4)
        else:
            frame = _rotation(parent_final).to_4x4()
            frame.translation = parent_final.translation
        inv = frame.inverted_safe()
        local_sim = inv @ sim
        if limits is not None:
            local_sim = limit_angles(local_sim, limits)
        local = _blend(local_sim, inv @ joint, s["blend"])
        if limits is not None:
            local = limit_angles(local, limits)
        final = frame @ local
        self.mats[slot] = final.copy()
        return final


def _parent_frame(arm, mode):
    holder = arm
    if mode == 1 and arm.parent is not None and arm.parent.type == "ARMATURE":
        holder = arm.parent
    frame = holder.matrix_world.copy()
    root = holder.pose.bones.get("root_motion") if holder.pose else None
    if root is not None:
        frame = frame @ root.matrix
    out = _rotation(frame).to_4x4()
    out.translation = frame.translation
    return out


def _rest_rel(bone):
    return bone.matrix_local if bone.parent is None else bone.parent.matrix_local.inverted() @ bone.matrix_local


def _rigid(m):
    out = _rotation(m).to_4x4()
    out.translation = m.translation
    return out


def _shapes(ob, arm, world_of):
    """the chain's collision shapes in world space: [("sphere", c, r) | ("capsule", a, b, r)]"""
    source = _collision_source(ob)
    if source is None:
        return []
    col, coll_arm = source
    bones = _joint_bones(coll_arm)
    out = []

    def place(joint, pos):
        bone = bones.get(joint)
        if joint == NO_JOINT or bone is None:
            return None
        if coll_arm == arm:
            m = world_of(bone.name)
        else:
            m = coll_arm.matrix_world @ coll_arm.pose.bones[bone.name].matrix
        return (m @ (Vector(pos[:3]) * SCALE).to_4d()).xyz       # pos in the joint's frame, cm

    for group in col.groups:
        for shape in group.shapes:
            radius = shape.radius * SCALE
            if shape.type == 0:
                c = place(shape.bone0, shape.pos0)
                if c is not None:
                    out.append(("sphere", c, radius))
            elif shape.type == 3:
                a, b = place(shape.bone0, shape.pos0), place(shape.bone1, shape.pos1)
                if a is not None and b is not None:
                    out.append(("capsule", a, b, radius))
    return out


_col_cache = {}     # COL_ Empty name -> (frame, parsed rCollisionShape as the objects have it now)


def _collision_source(ob):
    """(parsed .col as its objects are now, the armature its shapes hang on) of a chain, or None"""
    settings = ob.albam_phs
    root = settings.collision_shapes
    if not settings.collision or root is None:
        return None
    arm = root.get(ARMATURE_PROP)
    if not isinstance(arm, bpy.types.Object) or arm.type != "ARMATURE":
        return None
    frame = bpy.context.scene.frame_current
    cached = _col_cache.get(root.name)
    if cached is None or cached[0] != frame:
        from dmc4xml import col as col_codec
        try:
            current = col_codec.read(col_shapes.build_col(root))     # edited shapes included
        except Exception:                   # noqa: BLE001 - a broken edit: fall back to the file
            current = col_shapes.read_col(root)
        cached = _col_cache[root.name] = (frame, current)
    return (cached[1], arm) if cached[1] is not None else None


def default_col_path(ob):
    """the body shapes next to a player chain: model\\game\\pl000\\pl000_03_00.phs -> ...\\pl000_03.col"""
    path = ob.albam_asset.relative_path
    if not path:
        return ""
    stem, _, _ = path.rpartition(".")
    head, _, tail = stem.rpartition("_")
    return (head if tail.isdigit() and head else stem) + ".col"


# ---- runners: the enabled chains of one armature ----------------------------------------------------------------

LINK_PASSES = 4


def _links(arm):
    from albam.engines.mtfw.model_ext import preview_links      # model_ext's lists name the links
    try:
        return preview_links(arm)
    except Exception as err:            # noqa: BLE001 - a broken list mustn't stop the chains
        print(f"PHS preview ({arm.name}): links skipped: {err}")
        return []


def _cloths(arm):
    """the live <cloth> sheets on the armature's chains (model_ext.cloth_sheets), [] when a list is broken"""
    from albam.engines.mtfw.model_ext import cloth_sheets
    try:
        return cloth_sheets(arm)
    except Exception as err:            # noqa: BLE001 - a broken list mustn't stop the chains
        print(f"PHS preview ({arm.name}): <cloth> skipped: {err}")
        return []


def _physics(ob):
    """the chain's <physics> settings (movedef.ext_list.physics_values) from the scene's lists, None: the game's solver"""
    from albam.engines.mtfw.model_ext import physics_settings
    try:
        return physics_settings(ob)
    except Exception as err:            # noqa: BLE001 - a broken list mustn't stop the chains
        print(f"PHS preview ({ob.name}): <physics> skipped: {err}")
        return None


def _tendril(chain, slot):
    """(root slot, tip slot) of the tendril holding `slot`; the tip's tail point is mats[tip + 1]"""
    root, tip = slot, slot
    while root > 0 and chain.joints[root - 1] is not None:
        root -= 1
    while tip + 1 < len(chain.joints) and chain.joints[tip + 1] is not None:
        tip += 1
    return root, tip


def apply_links(links, owners, final):
    """ModelExtension <link> (dmc4_hook sdk/ChainLink.cpp, schema.md "<link>"), after the chains have solved:
    LINK_PASSES passes over every link; a stretched one moves each joint half the excess x stiffness toward the other
    (a tendril root keeps its place, its partner takes it all); a moved joint turns about its tendril parent, keeping
    that distance, and the rest of its tendril (tail included) moves with it. Then every joint of a touched tendril
    turns by the smallest rotation that re-aims it at its next point, the chains' stored points take the new places
    and the velocity away from the partner is dropped. `owners` = {bone: (_Chain, slot)}, `final` = {bone: world}."""
    if not links:
        return
    points = {}

    def pos(chain, i):
        key = (id(chain), i)
        if key not in points:
            points[key] = chain.mats[i].translation.copy()
        return points[key]

    def move(chain, slot, target):
        root, tip = _tendril(chain, slot)
        parent = pos(chain, slot - 1)
        current = pos(chain, slot)
        to = target - parent
        if to.length < EPS:
            return
        delta = parent + to.normalized() * (current - parent).length - current
        for i in range(slot, tip + 2):
            points[(id(chain), i)] = pos(chain, i) + delta

    touched = {}
    for _ in range(LINK_PASSES):
        for name_a, name_b, max_len, stiffness in links:
            (ca, sa), (cb, sb) = owners[name_a], owners[name_b]
            pa, pb = pos(ca, sa), pos(cb, sb)
            d = pb - pa
            dist = d.length
            if dist <= max_len or dist < EPS:
                continue
            excess = (dist - max_len) * stiffness
            root_a, root_b = _tendril(ca, sa)[0] == sa, _tendril(cb, sb)[0] == sb
            wa, wb = (0.0, 1.0) if root_a else (1.0, 0.0) if root_b else (0.5, 0.5)
            u = d / dist
            if wa:
                move(ca, sa, pa + u * (excess * wa))
            if wb:
                move(cb, sb, pb - u * (excess * wb))
            for chain, slot in ((ca, sa), (cb, sb)):
                touched[(id(chain), _tendril(chain, slot))] = (chain, _tendril(chain, slot))
    new = []
    for chain, (root, tip) in touched.values():
        for i in range(root, tip + 1):
            old = chain.mats[i]
            old_aim = chain.mats[i + 1].translation - old.translation
            new_aim = pos(chain, i + 1) - pos(chain, i)
            turn = old_aim.rotation_difference(new_aim).to_matrix() if old_aim.length > EPS and new_aim.length > EPS \
                else Matrix.Identity(3)
            m = (turn @ old.to_3x3()).to_4x4()
            m.translation = pos(chain, i)
            new.append((chain, i, m))
        new.append((chain, tip + 1, None))
    for chain, i, m in new:
        if m is None:
            chain.mats[i].translation = pos(chain, i)
            continue
        chain.mats[i] = m
        final[chain.joints[i]] = m.copy()
    for name_a, name_b, _, _ in links:
        for (chain, slot), other in ((owners[name_a], name_b), (owners[name_b], name_a)):
            u = final[other].translation - final[chain.joints[slot]].translation
            if u.length > EPS:
                u.normalize()
                along = chain.vel[slot].dot(u)
                if along < 0.0:
                    chain.vel[slot] = chain.vel[slot] - u * along


class _Runner:
    def __init__(self, arm, chain_obs):
        self.arm_name = arm.name
        self.key = _key(arm, chain_obs)
        self.chains = [(ob.name, _Chain(ob, arm)) for ob in chain_obs]
        # <cloth> sheets whose members are all previewed here on the hook solver (else their tendrils solve alone)
        hooked = {chain.name: chain for _, chain in self.chains if chain.hook is not None}
        self.sheets = [sheet for sheet in _cloths(arm)
                       if all(c in hooked and hooked[c].joints[s] is not None for c, s in sheet["members"])]
        self.sheet_of = {member: sheet for sheet in self.sheets for member in sheet["members"]}
        self.cache = {}         # frame -> {bone name: matrix_basis}
        self.last = None

    def reset(self):
        for _, chain in self.chains:
            chain.reset()

    def step(self, scene, steps):
        """one scene frame: `steps` steps of the game's solver; chains on dmc4_hook's solver (a <physics> entry) solve
        once, on the last step, over the frame's time (cns_chain_hook)"""
        arm = bpy.data.objects[self.arm_name]
        hook_time = cns_chain_hook.frame_time(scene)
        ground = cns_chain_hook.ground_caster(scene) if any(c.hook is not None and c.hook.ground
                                                           for _, c in self.chains) else None
        owners = {}
        for ob_name, chain in self.chains:
            for slot, name in enumerate(chain.joints):
                if name is not None:
                    owners[name] = (chain, slot)
        under = set()                          # bones below a chain bone: their world comes from ours
        for bone in arm.data.bones:
            if bone.parent is not None and (bone.parent.name in owners or bone.parent.name in under):
                under.add(bone.name)
        basis = {name: arm.pose.bones[name].matrix_basis.copy() for name in owners}
        evaluated = {}
        final = {}

        def world_of(name):
            if name in final:
                return final[name]
            bone = arm.data.bones[name]
            if name in under or name in owners:
                parent = world_of(bone.parent.name) if bone.parent is not None else arm.matrix_world
                local = _rest_rel(bone) @ (basis[name] if name in basis else arm.pose.bones[name].matrix_basis)
                return _rigid(parent @ local)
            if name not in evaluated:
                evaluated[name] = _rigid(arm.matrix_world @ arm.pose.bones[name].matrix)
            return evaluated[name]

        order = [b.name for b in arm.data.bones if b.name in owners]
        links = [link for link in _links(arm) if link[0] in owners and link[1] in owners]
        by_name = {chain.name: chain for _, chain in self.chains}
        rank = {name: i for i, name in enumerate(order)}
        for sheet in self.sheets:
            sheet["first"] = min((by_name[c].joints[s] for c, s in sheet["members"]), key=lambda n: rank.get(n, 1 << 30))
        def local_of(name):
            return _rest_rel(arm.data.bones[name]) @ basis[name]

        for i in range(steps):
            last = i == steps - 1
            final.clear()
            for ob_name, chain in self.chains:
                if chain.hook is None:
                    chain.move(_parent_frame(arm, chain.s["parent_mode"]), 1.0)
                elif last:      # cCnsChain::move runs as usual (wind, turbulence, the reset state), once a frame
                    chain.move(_parent_frame(arm, chain.s["parent_mode"]), hook_time)
            shapes_by_chain = {}
            for name in order:
                chain, slot = owners[name]
                bone = arm.data.bones[name]
                parent_final = world_of(bone.parent.name) if bone.parent is not None else None
                anim = _rigid((parent_final if parent_final is not None else arm.matrix_world)
                              @ _rest_rel(bone) @ basis[name])
                if chain.name not in shapes_by_chain:
                    ob = bpy.data.objects.get(chain.name)
                    shapes_by_chain[chain.name] = _shapes(ob, arm, world_of) if ob is not None else []
                if chain.hook is None:
                    final[name] = chain.solve(slot, anim, parent_final, arm, 1.0, shapes_by_chain[chain.name])
                    continue
                if last and cns_chain_hook.tendril(chain, slot)[0] == slot:     # a tendril root's call solves it
                    sheet = self.sheet_of.get((chain.name, slot))
                    if sheet is None:
                        cns_chain_hook.solve_tendril(chain, slot, anim, arm, local_of, hook_time,
                                                     cns_chain_hook.capsules(shapes_by_chain[chain.name]), ground)
                    elif sheet["first"] == name:
                        # a sheet solves at its first root the pass reaches; the other roots' FK is composed from
                        # their parents (world_of), their own calls only take their results
                        members = []
                        for chain_name, root in sheet["members"]:
                            member = by_name[chain_name]
                            if member.name not in shapes_by_chain:
                                ob = bpy.data.objects.get(member.name)
                                shapes_by_chain[member.name] = _shapes(ob, arm, world_of) if ob is not None else []
                            bone_name = member.joints[root]
                            members.append((member, root, anim if bone_name == name else world_of(bone_name),
                                            cns_chain_hook.capsules(shapes_by_chain[member.name])))
                        cns_chain_hook.solve_sheet(members, sheet, arm, local_of, hook_time, ground)
                final[name] = chain.hook.out.get(slot, anim).copy()
            apply_links(links, owners, final)
        out = {}
        inv = arm.matrix_world.inverted_safe()
        for name in order:
            bone = arm.data.bones[name]
            pose = inv @ final[name]
            parent_pose = inv @ world_of(bone.parent.name) if bone.parent is not None else Matrix.Identity(4)
            out[name] = (parent_pose @ _rest_rel(bone)).inverted_safe() @ pose
        return out

    def apply(self, frame_pose):
        arm = bpy.data.objects.get(self.arm_name)
        if arm is None:
            return
        for name, m in frame_pose.items():
            pb = arm.pose.bones.get(name)
            if pb is not None:
                pb.matrix_basis = m


_runners = {}       # armature name -> _Runner


def preview_chains(scene):
    """{armature: [chain Empties with the preview on]}"""
    out = {}
    for ob in scene.objects:
        if ob.type == "EMPTY" and ARMATURE_PROP in ob and ob.albam_phs.preview:
            arm = chain_armature(ob)
            if arm is not None:
                out.setdefault(arm, []).append(ob)
    return out


def _limits_key(ob):
    arm, names = _chain_bone_names(ob)
    return repr([cns_chain.bone_limits(arm.pose.bones[n]) for n in names]) if arm is not None else ""


def _animation_key(arm):
    """what animates the armature and the objects it hangs from (a coat follows the body): a cached frame of
    another animation or NLA layout is stale"""
    parts, ob = [], arm
    while ob is not None:
        parts.append(nla.state(ob))
        ob = ob.parent
    return parts


def _key(arm, chain_obs):
    parts = [arm.name, repr(_links(arm)), repr(_cloths(arm)), _animation_key(arm)]
    for ob in chain_obs:
        s = ob.albam_phs
        parts.append((ob.name, repr(sorted((k, repr(_settings(ob)[k])) for k in _settings(ob))),
                      tuple(chain_joints(ob, [])), _limits_key(ob), s.collision,
                      s.collision_shapes.name if s.collision_shapes else "",
                      repr(s.collision_shapes.get(ARMATURE_PROP)) if s.collision_shapes else "",
                      repr(_physics(ob))))
    return repr(parts)


def _steps(scene):
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    return max(1, round(GAME_STEP / fps)) if fps > 0 else 1


def _restore_base(scene, chains_by_arm):
    for arm, obs in chains_by_arm.items():
        for ob in obs:
            for name, values in dict(ob.get(BASE_PROP, {})).items():
                pb = arm.pose.bones.get(name)
                if pb is not None:
                    pb.matrix_basis = Matrix([values[0:4], values[4:8], values[8:12], values[12:16]])


@persistent
def _on_frame_change_pre(scene, depsgraph=None):
    _restore_base(scene, preview_chains(scene))


@persistent
def _on_frame_change_post(scene, depsgraph=None):
    # not hide_set here: changing the view layer's bases inside the frame update crashes Blender 5.4 during playback
    col_shapes.queue_visibility()
    frame = scene.frame_current
    chains_by_arm = preview_chains(scene)
    for arm_name in [n for n in _runners if n not in {a.name for a in chains_by_arm}]:
        del _runners[arm_name]
    for arm, obs in chains_by_arm.items():
        try:
            runner = _runners.get(arm.name)
            if runner is None or runner.key != _key(arm, obs):
                runner = _runners[arm.name] = _Runner(arm, obs)
            if runner.last is not None and frame == runner.last + 1:
                pose = runner.step(scene, _steps(scene))
                runner.last = frame
            elif frame in runner.cache:
                runner.apply(runner.cache[frame])
                continue
            else:
                runner.reset()
                pose = runner.step(scene, 1)
                runner.last = frame
            runner.cache[frame] = pose
            runner.apply(pose)
        except Exception as err:            # noqa: BLE001 - never break playback
            print(f"PHS preview ({arm.name}): {err}")


@persistent
def _on_load(_dummy=None):
    _runners.clear()
    _col_cache.clear()
    cns_chain_hook.forget_ground()


# ---- Shift+D on a chain Empty makes a new chain ---------------------------------------------------------------------

def adopt_chain_copies(context=None):
    """A copied PHS_ Empty (its name isn't the one it was made with) becomes a chain of its own: the next free file
    name next to its model, its own bone collection with the same bones, its own export list entry; settings stay
    as copied, the preview starts off. Returns the adopted chains."""
    context = context or bpy.context
    adopted = []
    for ob in list(bpy.data.objects):
        if ob.type != "EMPTY" or ob.albam_asset.extension not in ("phs", "clt") or cns_chain.NAME_PROP not in ob:
            continue
        if ob.name == ob[cns_chain.NAME_PROP]:
            continue
        joints = chain_joints(ob, [])                       # the source's bone collection, still shared
        if COLLECTION_PROP in ob:
            del ob[COLLECTION_PROP]
        if BASE_PROP in ob:
            del ob[BASE_PROP]
        ob.albam_phs.preview = False
        ob[JOINTS_PROP] = joints
        model = ob.get("phs_model", "") or ob.albam_asset.relative_path
        ob.albam_asset.relative_path = cns_chain.next_chain_path(context, model, ob.albam_asset.extension)
        arm = chain_armature(ob)
        if arm is not None:
            attach_chain(ob, arm)
        exportable = context.scene.albam.exportable.file_list.add()
        exportable.bl_object = ob
        ob[cns_chain.NAME_PROP] = ob.name
        cns_chain.apply_tips(ob)
        adopted.append(ob)
    return adopted


_adopt_pending = [False]


def _adopt_timer():
    _adopt_pending[0] = False
    try:
        adopt_chain_copies()
    except Exception as err:                # noqa: BLE001 - never break editing
        print(f"PHS copy: {err}")
    return None


# ---- bones assigned to a chain's bone collection get joint numbers --------------------------------------------------

_number_pending = [False]


def number_new_chain_bones():
    """joint numbers for the bones made in Blender and assigned to a chain's bone collection (chain_joints needs
    them to place the bone); returns [(bone name, number)]"""
    numbered = []
    for ob in list(bpy.data.objects):
        if ob.type == "EMPTY" and COLLECTION_PROP in ob:
            numbered += cns_chain.number_chain_bones(ob)
    return numbered


def _number_timer():
    _number_pending[0] = False
    try:
        number_new_chain_bones()
    except Exception as err:                # noqa: BLE001 - never break editing
        print(f"PHS joint numbers: {err}")
    return None


def _needs_numbers(updated):
    """chains on the updated armatures with an unnumbered bone in their collection (outside Edit Mode)"""
    for ob in bpy.data.objects:
        if ob.type == "EMPTY" and COLLECTION_PROP in ob:
            arm = chain_armature(ob)
            if arm is not None and arm.data in updated and arm.mode != "EDIT" and \
                    cns_chain.unnumbered_chain_bones(ob):
                return True
    return False


@persistent
def _on_depsgraph(scene, depsgraph):
    updated = set()
    for update in depsgraph.updates:
        ob = update.id.original if isinstance(update.id, bpy.types.Object) else None
        if ob is not None and cns_chain.NAME_PROP in ob and ob.name != ob[cns_chain.NAME_PROP]:
            if not _adopt_pending[0]:
                _adopt_pending[0] = True
                bpy.app.timers.register(_adopt_timer, first_interval=0.0)
        if ob is not None and ob.type == "ARMATURE":
            updated.add(ob.data)
        elif isinstance(update.id, bpy.types.Armature):
            updated.add(update.id.original)
    # a bone made in Blender and assigned to a chain's collection: give it a joint number (a timer: no ID writes in
    # the handler); the check itself only reads
    if updated and not _number_pending[0] and _needs_numbers(updated):
        _number_pending[0] = True
        bpy.app.timers.register(_number_timer, first_interval=0.0)


def register_handlers():
    for handlers, fn in ((bpy.app.handlers.frame_change_pre, _on_frame_change_pre),
                         (bpy.app.handlers.frame_change_post, _on_frame_change_post),
                         (bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
                         (bpy.app.handlers.load_post, _on_load)):
        if fn not in handlers:
            handlers.append(fn)


def unregister_handlers():
    for handlers, fn in ((bpy.app.handlers.frame_change_pre, _on_frame_change_pre),
                         (bpy.app.handlers.frame_change_post, _on_frame_change_post),
                         (bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
                         (bpy.app.handlers.load_post, _on_load)):
        for handler in list(handlers):
            if getattr(handler, "__name__", "") == fn.__name__ and \
                    getattr(handler, "__module__", "") == fn.__module__:
                handlers.remove(handler)


# ---- turning it on / off ------------------------------------------------------------------------------------------

def _chain_bone_names(ob):
    arm = chain_armature(ob)
    if arm is None:
        return arm, []
    bones = _joint_bones(arm)
    return arm, [bones[j].name for j in chain_joints(ob, []) if j in bones]


def _store_base(ob):
    arm, names = _chain_bone_names(ob)
    if arm is None:
        return
    ob[BASE_PROP] = {n: [v for row in arm.pose.bones[n].matrix_basis for v in row] for n in names}


def _clear_base(ob):
    arm, _ = _chain_bone_names(ob)
    base = dict(ob.get(BASE_PROP, {}))
    if arm is not None:
        for name, values in base.items():
            pb = arm.pose.bones.get(name)
            if pb is not None:
                pb.matrix_basis = Matrix([values[0:4], values[4:8], values[8:12], values[12:16]])
    if BASE_PROP in ob:
        del ob[BASE_PROP]


def _preview_update(self, context):
    ob = self.id_data
    if self.preview:
        cns_chain.number_chain_bones(ob)
        if BASE_PROP not in ob:
            _store_base(ob)
    else:
        _clear_base(ob)
    arm = chain_armature(ob)
    if arm is not None:
        _runners.pop(arm.name, None)
    if context is not None and context.scene is not None:
        context.scene.frame_set(context.scene.frame_current)


def _settings_update(self, context):
    if self.collision_shapes is not None:
        _col_cache.pop(self.collision_shapes.name, None)


def _poll_col_root(self, obj):
    return col_shapes.is_col_root(obj)


# ---- dmc4_hook's solver: the chain's <physics> entry, edited from the Chain panel ---------------------------------
# (name, the runner's default when it isn't fixed by the chain file, as written in the list)
HOOK_ATTRS = (("substeps", "8"), ("iterations", "1"), ("stiffness", "0"), ("pin", "0"), ("inertia", None),
              ("inertia_move", None), ("inertia_turn", None), ("limit", "0"), ("friction", "0.2"), ("damping", None),
              ("gravity", "1"), ("radius", None), ("ground", "false"), ("self", "false"), ("axis", None))
_HOOK_DEFAULTS = {"substeps": 8, "iterations": 1, "stiffness": [0.0], "pin": [0.0], "inertia": None,
                  "inertia_move": None, "inertia_turn": None, "limit": [0.0], "friction": 0.2, "damping": None,
                  "gravity": [1.0], "radius": None, "ground": False, "self": False, "axis": None}


def _hook_effective(ob):
    """the settings the runner solves this chain with (the chain file's where the entry leaves one out); the ones
    along the tendril (cns_chain_hook.CURVES) as lists, radius in cm"""
    hook = cns_chain_hook.Hook(_physics(ob) or _HOOK_DEFAULTS, _settings(ob))
    return {"substeps": hook.substeps, "iterations": hook.iterations, "stiffness": hook.stiffness, "pin": hook.pin,
            "inertia": hook.inertia, "inertia_move": hook.inertia_move, "inertia_turn": hook.inertia_turn,
            "limit": hook.limit, "friction": hook.friction, "damping": hook.damping, "gravity": hook.gravity,
            "radius": [r / cns_chain_hook.SCALE for r in hook.radius], "ground": hook.ground, "self": hook.self,
            "axis": hook.axis}


def _hook_text(name, value):
    if name == "axis":
        return cns_chain_hook.AXES[value]
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return " ".join(_hook_text(name, v) for v in value)
    return f"{round(value, 4):g}"


def _along(ob, name):
    """the values of an entry's setting along the tendril as written ([] when it isn't in the entry)"""
    from albam.engines.mtfw import model_ext
    from albam.engines.mtfw.movedef import ext_list
    e = model_ext.physics_entry(bpy.context, ob)[2]
    if e is None or not e.has(name):
        return []
    return ext_list.parse_curve(e.get(name, ""))[0] or []


def _hook_prop(name):
    default = dict(HOOK_ATTRS)[name]

    def get(self):
        value = _hook_effective(self.id_data)[name]
        return value[0] if isinstance(value, list) else value      # along the tendril: the root's

    def set_(self, value):
        from albam.engines.mtfw import model_ext
        text = _hook_text(name, value)
        model_ext.set_physics_attr(bpy.context, self.id_data, name, None if text == default else text)
    return {"get": get, "set": set_}


def _hook_list_prop(name):
    """a setting along the tendril as its text: 2-8 numbers, root to tail"""
    default = dict(HOOK_ATTRS)[name]

    def get(self):
        return _hook_text(name, _hook_effective(self.id_data)[name])

    def set_(self, value):
        from albam.engines.mtfw import model_ext
        from albam.engines.mtfw.movedef import ext_list
        numbers, problem = ext_list.parse_curve(value)
        if problem is not None or not numbers:
            return          # the runner would drop the entry: keep what's there
        low, high = ext_list.CURVE_RANGES[name]
        text = _hook_text(name, [min(max(v, low), high) for v in numbers])
        model_ext.set_physics_attr(bpy.context, self.id_data, name, None if text == default else text)
    return {"get": get, "set": set_}


_ALONG_TIP = (": 2-8 numbers separated by spaces, spread evenly from the tendril's root to its tail and read "
              "linearly")
_AXIS_ITEMS = [(code, code.upper(), f"The joint's {code.upper()} axis points down the chain", i)
               for i, code in enumerate(cns_chain_hook.AXES)]


@blender_registry.register_blender_props_to_type("Object", "albam_phs")
class AlbamChainPreview(bpy.types.PropertyGroup):
    preview: bpy.props.BoolProperty(
        name="Preview Motion", update=_preview_update,
        description="Simulate this chain on its armature while the animation plays, the way the game does (preview "
                    "only: nothing is keyed or exported). Play forward from a frame, or use Simulate Range")
    collision: bpy.props.BoolProperty(
        name="Collision", default=True, update=_settings_update,
        description="Keep the chain out of the collision shapes, as the game does")
    collision_shapes: bpy.props.PointerProperty(
        type=bpy.types.Object, poll=_poll_col_root, name="Shapes", update=_settings_update,
        description="Imported collision shapes (a COL_ object from a .col file) the chain collides with. The game "
                    "uses the body's: for Nero's coat, model\\game\\pl000\\pl000_03.col on pl000.mod. Set by itself "
                    "when that file is imported")
    # dmc4_hook's solver: the attributes of the chain's <physics> entry (Vibed/ModelExt/schema.md), read and written
    # in its ModelExtension list
    hook_substeps: bpy.props.IntProperty(
        name="Substeps", min=1, max=16, **_hook_prop("substeps"),
        description="Steps per 60 fps frame. More keeps fast moves from carrying a segment through a collision shape")
    hook_iterations: bpy.props.IntProperty(
        name="Iterations", min=1, max=8, **_hook_prop("iterations"),
        description="Constraint passes per step: more holds lengths and collisions more exactly")
    hook_stiffness: bpy.props.FloatProperty(
        name="Stiffness", min=0.0, max=1.0, subtype="FACTOR", **_hook_prop("stiffness"),
        description="Per frame, how far each segment turns toward its animated direction (keeps a skirt's shape)")
    hook_pin: bpy.props.FloatProperty(
        name="Pin", min=0.0, max=1.0, subtype="FACTOR", **_hook_prop("pin"),
        description="Per frame, how far each point moves toward its animated place")
    hook_inertia: bpy.props.FloatProperty(
        name="Inertia", min=0.0, max=1.0, subtype="FACTOR", **_hook_prop("inertia"),
        description="How much of the model's motion the chain lags behind (1 = all of it). Left out of the list: 0 "
                    "when the chain file follows its parent (Follow Position / Height / Rotation), else 1")
    hook_inertia_move: bpy.props.FloatProperty(
        name="Inertia Move", min=0.0, max=1.0, subtype="FACTOR", **_hook_prop("inertia_move"),
        description="How much of the model's travel the chain lags behind. Left out of the list: Inertia. 0 with "
                    "Inertia Turn 1: a long coat rides along when the character runs or is launched, and still swings "
                    "out when it spins")
    hook_inertia_turn: bpy.props.FloatProperty(
        name="Inertia Turn", min=0.0, max=1.0, subtype="FACTOR", **_hook_prop("inertia_turn"),
        description="How much of the model's turning the chain lags behind. Left out of the list: Inertia")
    hook_limit: bpy.props.FloatProperty(
        name="Limit", min=0.0, max=180.0, **_hook_prop("limit"),
        description="Degrees a segment may leave its animated direction (0 = no limit)")
    hook_friction: bpy.props.FloatProperty(
        name="Friction", min=0.0, max=1.0, subtype="FACTOR", **_hook_prop("friction"),
        description="Per frame, the sliding speed a point loses while it touches a shape or the floor")
    hook_damping: bpy.props.FloatProperty(
        name="Damping", min=0.0, max=1.0, subtype="FACTOR", **_hook_prop("damping"),
        description="Per frame, the speed the chain loses beyond the animation's own motion: lower swings longer, "
                    "higher calms it. Left out of the list: 1 - the chain file's Damping, at least 0.1 (the coats' "
                    "Damping 1.0 never loses speed on this solver, the game's own loses it in its length correction)")
    hook_gravity: bpy.props.FloatProperty(
        name="Gravity", min=-100.0, max=100.0, soft_min=0.0, soft_max=2.0, **_hook_prop("gravity"),
        description="Times the chain file's gravity (1 = as it is)")
    hook_radius: bpy.props.FloatProperty(
        name="Radius (cm)", min=0.0, max=1000.0, **_hook_prop("radius"),
        description="The segments' radius against the collision shapes, in cm. Left out of the list: the chain "
                    "file's Collision Radius")
    hook_ground: bpy.props.BoolProperty(
        name="Ground", **_hook_prop("ground"),
        description="Keep every point above the stage floor (the game casts a line per point). The preview uses "
                    "the scene's imported stage collision (.sbc); without any it skips this")
    hook_self: bpy.props.BoolProperty(
        name="Self Collision", **_hook_prop("self"),
        description="The chain's tendrils push each other apart")
    hook_axis: bpy.props.EnumProperty(
        name="Axis", items=_AXIS_ITEMS, **_hook_prop("axis"),
        description="The joint axis aimed down the chain (+Z works on this solver, the game's can't). Left out of "
                    "the list: the chain file's Pointing Axis, where 2 means +Z here")
    # the settings along the tendril as text (2-8 numbers, root to tail), drawn instead of the single value once the
    # entry holds a list
    hook_stiffness_along: bpy.props.StringProperty(
        name="Stiffness", **_hook_list_prop("stiffness"),
        description="Stiffness along the tendril" + _ALONG_TIP + " (0.15 0.02: a firm waist, a loose hem)")
    hook_pin_along: bpy.props.StringProperty(
        name="Pin", **_hook_list_prop("pin"), description="Pin along the tendril" + _ALONG_TIP)
    hook_limit_along: bpy.props.StringProperty(
        name="Limit", **_hook_list_prop("limit"), description="Limit in degrees along the tendril" + _ALONG_TIP)
    hook_damping_along: bpy.props.StringProperty(
        name="Damping", **_hook_list_prop("damping"), description="Damping along the tendril" + _ALONG_TIP)
    hook_gravity_along: bpy.props.StringProperty(
        name="Gravity", **_hook_list_prop("gravity"), description="Gravity multiplier along the tendril" + _ALONG_TIP)
    hook_radius_along: bpy.props.StringProperty(
        name="Radius (cm)", **_hook_list_prop("radius"),
        description="Radius in cm along the tendril" + _ALONG_TIP + " (6 2: 6 cm at the root, 2 at the tail)")


# ---- finding and connecting the pieces ----------------------------------------------------------------------------

# chain models that hang on a body joint (the model's joint 0 follows it); uPlayerNero::initModel 0x7E3760 for
# Nero's coat, Dante's assumed to be the same (not traced)
COAT_BODY_JOINT = {"pl000_03": 2, "pl006_03": 2}


def attach_to_body(model_arm, body_arm, joint):
    """Parent model_arm to body_arm's joint so the model's joint 0 has that joint's world matrix: what the game does
    for Nero's coat (uPlayerNero::initModel 0x7E3760 gives coat joint 0 a cCnsMatrix constraint whose source is the
    body's joint 2 world matrix, player+0x61C0; the coat model itself has no parent joint and its motions don't
    animate joint 0)."""
    body = _joint_bones(body_arm).get(joint)
    root = _joint_bones(model_arm).get(0)
    if body is None or root is None:
        return False
    model_arm.parent = body_arm
    model_arm.parent_type = "BONE"
    model_arm.parent_bone = body.name
    # BONE parenting starts at the bone's tail; the model's joint 0 rest frame goes onto the body joint's frame
    model_arm.matrix_parent_inverse = Matrix.Translation((0.0, -body.length, 0.0)) @ root.matrix_local.inverted()
    model_arm.matrix_basis = Matrix.Identity(4)
    return True


def _chain_objects(scene):
    return [ob for ob in scene.objects if ob.type == "EMPTY" and ob.albam_asset.extension in ("phs", "clt")]


def _col_objects(scene):
    return [ob for ob in scene.objects if col_shapes.is_col_root(ob)]


def _body_joint(ob):
    model = ob.get("phs_model", "")
    return COAT_BODY_JOINT.get(_stem(model)) if model else None


def _shape_armature(root):
    arm = root.get(ARMATURE_PROP) if root is not None else None
    return arm if isinstance(arm, bpy.types.Object) and arm.type == "ARMATURE" else None


def wire_scene(context):
    """Connect what can be connected: chains and .col shapes waiting for their model's armature, a chain's collision
    shapes (the COL_ object of its default .col), a coat model on its body joint. Run after importing a .mod, .phs or
    .col; stores what's still missing on each chain (`phs_status`)."""
    scene = context.scene
    cols = _col_objects(scene)
    for root in cols:
        if _shape_armature(root) is None:
            arm = col_shapes.find_col_armature(context, root)
            if arm is not None:
                col_shapes.build_shapes(root, arm, context)
    for ob in _chain_objects(scene):
        status = []
        arm = chain_armature(ob)
        if arm is None:
            arm = find_chain_armature(context, ob)
            if arm is not None:
                attach_chain(ob, arm)
                _runners.pop(arm.name, None)
        if arm is None:
            model = ob.get("phs_model", "")
            status.append(f"Import its model ({model})" if model else
                          "Select the model's armature and use Attach to Armature")
        settings = ob.albam_phs
        if settings.collision_shapes is None:
            want = default_col_path(ob).lower()
            match = next((r for r in cols if r.albam_asset.relative_path.lower() == want), None)
            if match is not None:
                settings.collision_shapes = match
            elif _body_joint(ob) is not None:
                status.append(f"Import its collision shapes ({default_col_path(ob)})")
        body = _shape_armature(settings.collision_shapes)
        joint = _body_joint(ob)
        if joint is not None and arm is not None:
            if settings.collision_shapes is not None and body is None:
                name = col_shapes.body_model_stem(context, settings.collision_shapes.albam_asset.relative_path)
                status.append(f"Import the body model{f' ({name}.mod)' if name else ''}: the collision shapes "
                              "hang on it")
            elif body is not None and body != arm and arm.parent is None:
                if attach_to_body(arm, body, joint):
                    _runners.pop(arm.name, None)
            if body is not None and arm.parent != body:
                status.append(f"The coat isn't on the body: use Attach to Body (joint {joint})")
        ob["phs_status"] = "\n".join(status)
        cns_chain.apply_tips(ob)


# ---- operators ------------------------------------------------------------------------------------------------------

def _attach_target(context):
    """the chain or COL_ object the attach operator works on"""
    ob = context.object
    if ob is None:
        return None
    if ob.type == "EMPTY" and ob.albam_asset.extension in ("phs", "clt"):
        return ob
    return col_shapes.col_root_of(ob)


@blender_registry.register_blender_type
class ALBAM_OT_MtfwAttachToArmature(bpy.types.Operator):
    """Put a chain (PHS_) or collision shapes (COL_) on another armature: a chain gets its bone collection there, the
    shapes are rebuilt on its joints. The armature must have every joint number the file uses"""
    bl_idname = "albam.attach_to_armature"
    bl_label = "Attach to Armature"
    bl_options = {"REGISTER", "UNDO"}

    armature: bpy.props.StringProperty(
        name="Armature",
        description="Armature to attach to (bones are matched by joint number, mtfw.anim_retarget). Filled in with "
                    "the one found automatically: the file's model if it's imported, else the active armature")

    @classmethod
    def poll(cls, context):
        return _attach_target(context) is not None

    def invoke(self, context, event):
        target = _attach_target(context)
        if col_shapes.is_col_root(target):
            found = col_shapes.find_col_armature(context, target)
        else:
            found = find_chain_armature(context, target)
        self.armature = found.name if found is not None else ""
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop_search(self, "armature", context.scene, "objects", icon="ARMATURE_DATA")

    def execute(self, context):
        target = _attach_target(context)
        arm = context.scene.objects.get(self.armature)
        if arm is None or arm.type != "ARMATURE":
            self.report({"ERROR"}, f"'{self.armature}' isn't an armature in this scene")
            return {"CANCELLED"}
        if col_shapes.is_col_root(target):
            missing = col_shapes.attach_shapes(target, arm, context)
            _col_cache.pop(target.name, None)
            _runners.clear()
        else:
            old = chain_armature(target)
            if target.albam_phs.preview:
                target.albam_phs.preview = False
            missing = attach_chain(target, arm)
            for a in (old, arm):
                if a is not None:
                    _runners.pop(a.name, None)
        wire_scene(context)
        if missing:
            self.report({"WARNING"}, f"{arm.name} doesn't have joints {missing}")
        else:
            self.report({"INFO"}, f"{target.name} is on {arm.name}")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_PhsAttachToBody(bpy.types.Operator):
    """Parent the chain's model (its armature) to the armature of the chain's collision shapes (the body) so the
    model's joint 0 follows a body joint, as the game does for the coat: Nero's coat model (pl000_03.mod) hangs on
    the body's joint 2. Done by itself on import for Nero's and Dante's coats"""
    bl_idname = "albam.phs_attach_to_body"
    bl_label = "Attach to Body"
    bl_options = {"REGISTER", "UNDO"}

    joint: bpy.props.IntProperty(
        name="Body Joint", default=2, min=0, max=254,
        description="Joint number (mtfw.anim_retarget) of the body bone the model's joint 0 follows: 2 for Nero's "
                    "coat (uPlayerNero::initModel)")

    @classmethod
    def poll(cls, context):
        ob = context.object
        if ob is None or ARMATURE_PROP not in ob:
            return False
        arm, body = chain_armature(ob), _shape_armature(ob.albam_phs.collision_shapes)
        return arm is not None and body is not None and body != arm

    def invoke(self, context, event):
        self.joint = _body_joint(context.object) or 2
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        ob = context.object
        arm, body = chain_armature(ob), _shape_armature(ob.albam_phs.collision_shapes)
        if not attach_to_body(arm, body, self.joint):
            self.report({"ERROR"}, f"{body.name} has no joint {self.joint}, or {arm.name} has no joint 0")
            return {"CANCELLED"}
        _runners.pop(arm.name, None)
        wire_scene(context)
        context.scene.frame_set(context.scene.frame_current)
        self.report({"INFO"}, f"{arm.name} follows joint {self.joint} of {body.name}")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_PhsSimulateRange(bpy.types.Operator):
    """Run every previewed chain through the scene's frame range once, so any frame can be shown (scrubbing jumps
    otherwise restart the simulation at that frame)"""
    bl_idname = "albam.phs_simulate_range"
    bl_label = "Simulate Range"

    @classmethod
    def poll(cls, context):
        return bool(preview_chains(context.scene))

    def execute(self, context):
        scene = context.scene
        current = scene.frame_current
        _runners.clear()
        for frame in range(scene.frame_start, scene.frame_end + 1):
            scene.frame_set(frame)
        scene.frame_set(current)
        self.report({"INFO"}, f"Simulated frames {scene.frame_start}-{scene.frame_end}")
        return {"FINISHED"}


def _chain_of(context):
    ob = context.object
    return ob if ob is not None and ob.type == "EMPTY" and ob.albam_asset.extension in ("phs", "clt") else None


@blender_registry.register_blender_type
class ALBAM_OT_PhsHookUse(bpy.types.Operator):
    """Solve this chain with dmc4_hook's solver instead of the game's: adds a <physics> entry for its file and model
    to a ModelExtension list (the one with its model, else the first, else a new one). The preview follows it"""
    bl_idname = "albam.phs_hook_use"
    bl_label = "Use dmc4_hook's Solver"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        from albam.engines.mtfw import model_ext
        ob = _chain_of(context)
        return ob is not None and bool(model_ext.chain_model_path(ob)) and \
            model_ext.physics_entry(context, ob)[0] is None

    def execute(self, context):
        from albam.engines.mtfw import model_ext
        root = model_ext.add_physics(context, context.object)
        self.report({"INFO"}, f"<physics> added to {root.albam_asset.relative_path}")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_PhsHookRemove(bpy.types.Operator):
    """Go back to the game's solver for this chain: removes its <physics> entry from the ModelExtension list"""
    bl_idname = "albam.phs_hook_remove"
    bl_label = "Use the Game's Solver"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        from albam.engines.mtfw import model_ext
        ob = _chain_of(context)
        return ob is not None and model_ext.physics_entry(context, ob)[0] is not None

    def execute(self, context):
        from albam.engines.mtfw import model_ext
        model_ext.remove_physics(context, context.object)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_PhsHookDefault(bpy.types.Operator):
    """Take this setting out of the <physics> entry, so the runner's default (or the chain file's value) applies"""
    bl_idname = "albam.phs_hook_default"
    bl_label = "Use Default"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    attr: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        from albam.engines.mtfw import model_ext
        model_ext.set_physics_attr(context, context.object, self.attr, None)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_PhsHookAlong(bpy.types.Operator):
    """Vary this setting along the tendril (two values, root and tail, to edit as text), or go back to one value for
    the whole tendril (the root's)"""
    bl_idname = "albam.phs_hook_along"
    bl_label = "Along the Tendril"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    attr: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        from albam.engines.mtfw import model_ext
        ob = context.object
        value = _hook_effective(ob)[self.attr]
        if len(_along(ob, self.attr)) > 1:
            text = _hook_text(self.attr, value[0])
            model_ext.set_physics_attr(context, ob, self.attr, None if text == dict(HOOK_ATTRS)[self.attr] else text)
        else:
            model_ext.set_physics_attr(context, ob, self.attr, _hook_text(self.attr, [value[0], value[-1]]))
        return {"FINISHED"}


def _draw_hook(layout, context, ob):
    from albam.engines.mtfw import model_ext
    box = layout.box()
    box.label(text="dmc4_hook's Solver (ModelExtension <physics>)", icon="MOD_PHYSICS")
    root, _, e = model_ext.physics_entry(context, ob)
    if e is None:
        box.operator("albam.phs_hook_use", icon="ADD")
        if not model_ext.chain_model_path(ob):
            box.label(text="The chain's model has no game path", icon="ERROR")
        else:
            box.label(text="Solved by the game's solver", icon="INFO")
        return
    row = box.row()
    row.label(text=f"In {model_ext.file_name(root)}", icon="FILE_TEXT")
    row.operator("albam.phs_hook_remove", text="", icon="X")
    settings = ob.albam_phs
    col = box.column(align=True)
    for name, _ in HOOK_ATTRS:
        row = col.row(align=True)
        listed = name in cns_chain_hook.CURVES and len(_along(ob, name)) > 1
        row.prop(settings, f"hook_{name}_along" if listed else f"hook_{name}")
        if name in cns_chain_hook.CURVES:
            row.operator("albam.phs_hook_along", text="", icon="IPO_LINEAR", depress=listed).attr = name
        sub = row.row(align=True)
        sub.enabled = e.has(name)       # the setting is in the list: it can go back to the default
        sub.operator("albam.phs_hook_default", text="", icon="LOOP_BACK").attr = name
    for list_name, path, values in model_ext.cloth_entries(context):
        members, _ = model_ext.cloth_members(context, path, values)
        if members and any(member == ob for member, _ in members):
            box.label(text=f"In a <cloth> sheet of {len(members)} tendrils ({list_name}): it solves with them",
                      icon="MOD_CLOTH")
    if settings.hook_ground and not cns_chain_hook.stage_meshes(context.scene):
        box.label(text="Ground: no stage collision (.sbc) in the scene, the preview skips it", icon="INFO")
    arm = chain_armature(ob)
    if arm is not None and any(cns_chain.bone_limits(arm.pose.bones[n]) is not None for n in _chain_bone_names(ob)[1]):
        box.label(text="Per-bone limits (Chain Bone) aren't used by this solver", icon="INFO")
    if model_ext.physics_settings(ob) is None:
        box.label(text="The runner drops this entry (its axis isn't x, +x, -x, ...)", icon="ERROR")


# ---- panels ---------------------------------------------------------------------------------------------------------

# the chain's settings in the Chain panel, grouped (they're the Empty's custom properties, so each shows its
# tooltip from cns_chain.HELP; Custom Properties lists them too)
CHAIN_SETTING_GROUPS = (
    ("Forces", "FORCE_WIND", (("mGravity", "Gravity"), ("mGravityLocal", "Gravity in Parent's Frame"),
                              ("mWind", "Wind"), ("mWindLocal", "Wind in Parent's Frame"),
                              ("mTurbulence", "Turbulence"))),
    ("Response", "PHYSICS", (("mSpring", "Spring"), ("mDamping", "Damping"), ("mMaxSpeed", "Max Speed"),
                             ("mBlend", "Blend with Animation"))),
    ("Shape", "BONE_DATA", (("mDir", "Pointing Axis"), ("mUp", "Up Axis"), ("mTailLength", "Tail Length"),
                            ("mStretch", "Stretch"), ("mStretchLimit", "Stretch Limit"))),
    ("Collision & Floor", "MOD_PHYSICS", (("mCollisionSize", "Collision Radius"), ("mFloorLevel", "Floor Height"))),
    ("Carried by Parent", "CON_CHILDOF", (("mParentMode", "Parent"), ("mPosLocal", "Follow Position"),
                                          ("mPosLocalY", "Follow Height Only"), ("mRotLocal", "Follow Rotation"))),
)


def _draw_chain_settings(layout, ob):
    box = layout.box()
    box.label(text="Settings (hover a field for what it does)", icon="PREFERENCES")
    for title, icon, fields in CHAIN_SETTING_GROUPS:
        present = [(k, label) for k, label in fields if k in ob]
        if not present:
            continue
        col = box.column(align=True)
        col.label(text=title, icon=icon)
        for key, label in present:
            col.prop(ob, f'["{key}"]', text=label)


@blender_registry.register_blender_type
class ALBAM_PT_PhsChain(bpy.types.Panel):
    bl_label = "Chain"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == "EMPTY" and ob.albam_asset.extension in ("phs", "clt")

    def draw(self, context):
        ob = context.object
        layout = self.layout
        arm = chain_armature(ob)
        settings = ob.albam_phs

        box = layout.box()
        row = box.row()
        if arm is None:
            row.label(text="Not on an armature", icon="ERROR")
        else:
            _, names = _chain_bone_names(ob)
            row.label(text=f"{arm.name}: {len(names)} bone(s)", icon="ARMATURE_DATA")
        row.operator("albam.attach_to_armature", text="Attach", icon="LINKED")
        missing = list(ob.get("phs_missing_joints", []))
        if missing:
            box.label(text=f"Joints not on the armature: {missing}", icon="ERROR")
        if arm is not None:
            bones = _joint_bones(arm)
            col = box.column(align=True)
            for k, tendril in enumerate(cns_chain.tendrils(chain_joints(ob, []))):
                first, last = bones.get(tendril[0]), bones.get(tendril[-1])
                col.label(text=f"Tendril {k + 1}: {first.name if first else tendril[0]} -> "
                               f"{last.name if last else tendril[-1]} ({len(tendril)} bone(s))", icon="IPO_LINEAR")
            box.label(text="Roots / limits: select a bone, Bone Properties > Chain Bone", icon="INFO")

        _draw_chain_settings(layout, ob)

        box = layout.box()
        box.prop(settings, "collision")
        col = box.column()
        col.enabled = settings.collision
        col.prop(settings, "collision_shapes")
        body = _shape_armature(settings.collision_shapes)
        if settings.collision_shapes is not None:
            count = len(col_shapes.shapes_world(settings.collision_shapes))
            col.label(text=f"{count} shape(s) on {body.name}" if body else "Shapes aren't on an armature yet",
                      icon="MESH_CAPSULE")
        if arm is not None and body is not None and body != arm:
            row = col.row()
            row.label(text=f"Model on {body.name}: {arm.parent_bone}" if arm.parent == body else
                      "Model not on the body", icon="CONSTRAINT_BONE")
            row.operator("albam.phs_attach_to_body", text="Attach to Body")

        _draw_hook(layout, context, ob)

        box = layout.box()
        row = box.row()
        row.enabled = arm is not None
        row.prop(settings, "preview", icon="PHYSICS")
        row = box.row()
        row.enabled = settings.preview
        row.operator("albam.phs_simulate_range", icon="PLAY")

        status = ob.get("phs_status", "")
        for line in (status.splitlines() if isinstance(status, str) else list(status)):
            layout.label(text=line, icon="INFO")


@blender_registry.register_blender_type
class ALBAM_OT_PhsNew(bpy.types.Operator):
    """Make a new chain (.phs) from the selected bones of this armature (parents first, 32 at most), with the game's
    default settings; edit them in the chain Empty's Custom Properties and preview it. (Shift+D on a chain Empty
    also makes a new chain, with that chain's settings)"""
    bl_idname = "albam.phs_new"
    bl_label = "New Chain from Selected Bones"
    bl_options = {"REGISTER", "UNDO"}

    path: bpy.props.StringProperty(
        name="Game Path", description="Where the chain file goes in the game (.phs, or .clt, the game's own "
                                      "extension); Patch adds it to the archive")

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == "ARMATURE" and ob.mode == "POSE" and \
            bool(compat.selected_bones(ob))

    def invoke(self, context, event):
        arm = context.object
        self.path = cns_chain.next_chain_path(context, arm.albam_asset.relative_path or arm.name)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        arm = context.object
        path = self.path.strip().replace("/", "\\")
        if not path.lower().endswith((".phs", ".clt")):
            path += ".phs"
        if any(o.albam_asset.relative_path.lower() == path.lower() for o in bpy.data.objects
               if o.albam_asset.extension in ("phs", "clt")):
            self.report({"ERROR"}, f"{path} is already in the scene")
            return {"CANCELLED"}
        try:
            ob = cns_chain.new_chain(context, arm, compat.selected_bones(arm), path)
        except Exception:                   # noqa: BLE001 - shown in the popup
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
            return {"CANCELLED"}
        wire_scene(context)
        joints = [j for j in ob[JOINTS_PROP] if j >= 0]
        self.report({"INFO"}, f"{ob.name}: {len(joints)} joint(s) in {len(cns_chain.tendrils(ob[JOINTS_PROP]))} "
                              f"tendril(s), file {path}")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_PT_ArmatureChains(bpy.types.Panel):
    bl_label = "Model Chains"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE"

    def draw(self, context):
        arm = context.object
        layout = self.layout
        chains = [o for o in _chain_objects(context.scene) if chain_armature(o) == arm]
        col = layout.column(align=True)
        for o in chains:
            col.label(text=f"{o.name}: {len(_chain_bone_names(o)[1])} bone(s)  ({o.albam_asset.relative_path})",
                      icon="LINKED")
        if not chains:
            col.label(text="No chains on this armature", icon="INFO")
        row = layout.row()
        row.enabled = arm.mode == "POSE"
        row.operator("albam.phs_new", icon="ADD")
        if arm.mode != "POSE":
            layout.label(text="Pose Mode: select the chain's bones", icon="INFO")


# ---- deleted chains / collision files: cleanup when their export entry is dropped -----------------------------------

def _on_chain_deleted(ob):
    """a chain Empty was deleted: put its bones back (preview) and remove its bone collection unless a live chain
    still uses it"""
    _clear_base(ob)
    arm = chain_armature(ob)
    name = ob.get(COLLECTION_PROP, "")
    if arm is None or not name:
        return
    in_use = any(o != ob and o.users_collection and o.get(COLLECTION_PROP) == name and chain_armature(o) == arm
                 for o in bpy.data.objects)
    coll = arm.data.collections.get(name)
    if coll is not None and not in_use:
        arm.data.collections.remove(coll)
    _runners.pop(arm.name, None)


def _on_col_deleted(root):
    """a COL_ root was deleted: its shape objects go too (they're the file's contents)"""
    for ob in col_shapes.members(root):
        if ob.users_collection:
            bpy.data.objects.remove(ob)
    _col_cache.pop(root.name, None)


def _register_cull():
    from albam.blender_ui.export_panel import ON_CULL
    ON_CULL["phs"] = ON_CULL["clt"] = _on_chain_deleted
    ON_CULL["col"] = _on_col_deleted


_register_cull()


@blender_registry.register_blender_type
class ALBAM_PT_ChainBone(bpy.types.Panel):
    bl_label = "Chain Bone"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"

    @staticmethod
    def _pose_bone(context):
        ob = context.object
        bone = context.bone
        if ob is None or ob.type != "ARMATURE" or bone is None:
            return None
        return ob.pose.bones.get(bone.name)

    @classmethod
    def poll(cls, context):
        pb = cls._pose_bone(context)
        return pb is not None and bool(cns_chain._chains_with_bone(pb))

    def draw(self, context):
        pb = ALBAM_PT_ChainBone._pose_bone(context)
        layout = self.layout
        chains = cns_chain._chains_with_bone(pb)
        joint = int(pb.bone[cns_chain.JOINT_PROP])
        bones = _joint_bones(pb.id_data)
        for ob in chains:
            for k, tendril in enumerate(cns_chain.tendrils(chain_joints(ob, []))):
                if joint in tendril:
                    i = tendril.index(joint)
                    role = "root" if i == 0 else "tip" if i == len(tendril) - 1 else f"bone {i + 1} of {len(tendril)}"
                    tip = bones.get(tendril[-1])
                    layout.label(text=f"{ob.name}, tendril {k + 1}: {role} (tip {tip.name if tip else tendril[-1]})",
                                 icon="LINKED")
        s = pb.albam_chain
        layout.prop(s, "root")
        box = layout.box()
        box.prop(s, "adjust")
        col = box.column()
        col.enabled = s.adjust
        col.prop(s, "grid", expand=True)
        used = {"0": "Y and Z", "1": "X and Z", "2": "X and Y"}[s.grid]
        row = col.row()
        row.column().prop(s, "limit_min")
        row.column().prop(s, "limit_max")
        col.label(text=f"Degrees; this axis uses the {used} limits", icon="INFO")
        if s.grid != "2":
            col.label(text="X / Y: the game re-measures these off its limits (its math); Z behaves", icon="ERROR")
        box.label(text="No game chain turns limits on: check the effect in the game", icon="ERROR")
