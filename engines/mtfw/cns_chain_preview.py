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

wire_scene connects the pieces after any .mod / .phs / .col import, in any order: a chain or .col waiting for its
model attaches when it comes, a chain picks up the COL_ object of its default .col (pl000_03_00.phs ->
pl000_03.col), and a coat model (COAT_BODY_JOINT) is attached to the shapes' body armature at its joint. What's still
missing is listed on the chain (`phs_status`, shown in the Chain panel).
"""
import json
import random

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from albam.registry import blender_registry
from albam.engines.mtfw import col_shapes
from albam.engines.mtfw.cns_chain import (ARMATURE_PROP, _stem, attach_chain, chain_armature,
                                          chain_joints, find_chain_armature, _joint_bones)

SCALE = 0.01                        # game cm -> m
GAME_STEP = 60.0                    # solver steps per second
RESET_FRAMES = 2                    # move 0x4309C0: the reset state lasts until its timer (+1 per frame) reaches 3
EPS = 1.1920929e-07
BASE_PROP = "phs_preview_base"      # Empty: {bone name: 16 floats}, the chain bones' pose without the preview
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
        self.joints = [bones[j].name if j in bones else None for j in chain_joints(ob, problems)]
        self.rng = random.Random(self.name)
        self.mats = [Matrix.Identity(4) for _ in range(len(self.joints) + 1)]
        self.vel = [Vector() for _ in range(len(self.joints) + 1)]
        self.reset()

    def reset(self):
        self.resetting = RESET_FRAMES
        self.prev_parent = None
        self.turb_timer, self.turb = 0.0, Vector()

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
            if nxt >= len(self.joints):
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
        sim.translation = self.mats[slot].translation if slot > 0 else origin
        if parent_final is None:
            final = _blend(sim, joint, s["blend"])
        else:
            frame = _rotation(parent_final).to_4x4()
            frame.translation = parent_final.translation
            inv = frame.inverted_safe()
            final = frame @ _blend(inv @ sim, inv @ joint, s["blend"])
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


_col_cache = {}     # COL_ Empty name -> (size of its bytes, parsed rCollisionShape)


def _collision_source(ob):
    """(parsed .col, the armature its shapes hang on) of a chain, or None"""
    settings = ob.albam_phs
    root = settings.collision_shapes
    if not settings.collision or root is None:
        return None
    arm = root.get(ARMATURE_PROP)
    if not isinstance(arm, bpy.types.Object) or arm.type != "ARMATURE":
        return None
    data = root.albam_asset.original_bytes
    cached = _col_cache.get(root.name)
    if cached is None or cached[0] != len(data):
        cached = _col_cache[root.name] = (len(data), col_shapes.read_col(root))
    return cached[1], arm


def default_col_path(ob):
    """the body shapes next to a player chain: model\\game\\pl000\\pl000_03_00.phs -> ...\\pl000_03.col"""
    path = ob.albam_asset.relative_path
    if not path:
        return ""
    stem, _, _ = path.rpartition(".")
    head, _, tail = stem.rpartition("_")
    return (head if tail.isdigit() and head else stem) + ".col"


# ---- runners: the enabled chains of one armature ----------------------------------------------------------------

class _Runner:
    def __init__(self, arm, chain_obs):
        self.arm_name = arm.name
        self.key = _key(arm, chain_obs)
        self.chains = [(ob.name, _Chain(ob, arm)) for ob in chain_obs]
        self.cache = {}         # frame -> {bone name: matrix_basis}
        self.last = None

    def reset(self):
        for _, chain in self.chains:
            chain.reset()

    def step(self, scene, steps):
        arm = bpy.data.objects[self.arm_name]
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
        for _ in range(steps):
            final.clear()
            for ob_name, chain in self.chains:
                chain.move(_parent_frame(arm, chain.s["parent_mode"]), 1.0)
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
                final[name] = chain.solve(slot, anim, parent_final, arm, 1.0, shapes_by_chain[chain.name])
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


def _key(arm, chain_obs):
    parts = [arm.name]
    for ob in chain_obs:
        s = ob.albam_phs
        parts.append((ob.name, repr(sorted((k, repr(_settings(ob)[k])) for k in _settings(ob))),
                      tuple(chain_joints(ob, [])), s.collision,
                      s.collision_shapes.name if s.collision_shapes else "",
                      repr(s.collision_shapes.get(ARMATURE_PROP)) if s.collision_shapes else ""))
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
    try:
        col_shapes.update_visibility(scene)
    except Exception as err:                # noqa: BLE001 - never break playback
        print(f"COL visibility: {err}")
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


def register_handlers():
    for handlers, fn in ((bpy.app.handlers.frame_change_pre, _on_frame_change_pre),
                         (bpy.app.handlers.frame_change_post, _on_frame_change_post),
                         (bpy.app.handlers.load_post, _on_load)):
        if fn not in handlers:
            handlers.append(fn)


def unregister_handlers():
    for handlers, fn in ((bpy.app.handlers.frame_change_pre, _on_frame_change_pre),
                         (bpy.app.handlers.frame_change_post, _on_frame_change_post),
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
        ob["phs_status"] = status


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
            missing = col_shapes.build_shapes(target, arm, context)
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


# ---- panels ---------------------------------------------------------------------------------------------------------

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

        box = layout.box()
        row = box.row()
        row.enabled = arm is not None
        row.prop(settings, "preview", icon="PHYSICS")
        row = box.row()
        row.enabled = settings.preview
        row.operator("albam.phs_simulate_range", icon="PLAY")

        for line in ob.get("phs_status", []):
            layout.label(text=line, icon="INFO")


@blender_registry.register_blender_type
class ALBAM_PT_ColShapes(bpy.types.Panel):
    bl_label = "Collision Shapes"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return col_shapes.col_root_of(context.object) is not None

    def draw(self, context):
        root = col_shapes.col_root_of(context.object)
        layout = self.layout
        if root != context.object:
            layout.label(text=f"Part of {root.name}", icon="OBJECT_DATA")
        arm = _shape_armature(root)
        row = layout.row()
        row.label(text=f"On {arm.name}" if arm else "Not on an armature", icon="ARMATURE_DATA" if arm else "ERROR")
        row.operator("albam.attach_to_armature", text="Attach", icon="LINKED")
        missing = list(root.get("col_missing_joints", []))
        if missing:
            layout.label(text=f"Joints not on the armature: {missing}", icon="ERROR")
        if col_shapes.FOLLOW_PROP in root:
            layout.prop(root, f'["{col_shapes.FOLLOW_PROP}"]', text="Follow Animation Events")
            groups = col_shapes.active_groups(root, context.scene.frame_current)
            if root[col_shapes.FOLLOW_PROP]:
                layout.label(text="No LMT events on this armature's action: every group shown" if groups is None
                             else f"On at this frame: groups {sorted(groups)}", icon="TIME")
        col = layout.column(align=True)
        kinds, flags = list(root.get("col_group_kinds", [])), list(root.get("col_group_flags", []))
        shapes = {}
        for entry in json.loads(root.get(col_shapes.SHAPES_PROP, "[]")):
            shapes[entry[4]] = shapes.get(entry[4], 0) + 1
        summary = {}                    # (kind, flags) -> [groups, shapes]
        for i, (kind, flag) in enumerate(zip(kinds, flags)):
            row = summary.setdefault((kind, flag), [0, 0])
            row[0] += 1
            row[1] += shapes.get(i, 0)
        col.label(text=f"{len(kinds)} group(s), {sum(shapes.values())} shape(s) built", icon="MESH_CAPSULE")
        for (kind, flag), (groups, count) in sorted(summary.items(), key=lambda kv: -kv[1][0]):
            col.label(text=f"{groups} x kind {kind}, {col_shapes.flag_text(flag)}: {count} shape(s)")
        layout.label(text="Import only: edits aren't exported yet", icon="INFO")
