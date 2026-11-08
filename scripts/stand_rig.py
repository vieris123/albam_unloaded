"""Animation controls for Nero's Devil Trigger stand (pl020) and its Devil Bringer arm model (wp024), on the rig that
stand_taunt_retarget.py saves. Run it on that file (Blender's Text Editor > Run Script, or headless:
`blender -b stand_taunt_retarget.blend --python scripts/stand_rig.py`, which saves the file); the retarget script runs
it too before saving. Running it again rebuilds the controls.

What it adds:
- readable bone names (the joints the retarget maps them to: `forearm_l`, `thumb_1_r`; others `joint_<n>`), with every
  LMT action of both armatures renamed along;
- the stand's and the arm's meshes, and Nero's body (pl000.mod, without the head, hair and coat models), on any of the
  three armatures that has none (the first retarget runs didn't keep them);
- the stand's sword (wp040) in the right hand, on wp024's joint 150 where the game draws it, shown while the stand's
  `show_sword` is on, with the hand's fingers closed on it then (the grip of the arm's vanilla motion 0x31C, frame 3,
  held by `GRIP-` bones under the hand);
- control shapes, colours (left blue, right red, middle yellow), bone collections (Twist and Mechanism hidden), and
  location / scale locks on every game bone but the root and the lower spine;
- `follow_nero` on the stand object: 1 = the stand copies Nero's pose (the retarget), 0 = it plays its own keys;
- IK for both arms (`ik_arm_l` / `ik_arm_r`, 0 = FK, 1 = IK): a hand control (`IK-hand_l/r`, a cube under the root)
  and an elbow pole (`POLE-arm_l/r`). Blender's IK can't solve the game's bones (5 cm stubs pointing up), so it solves
  a helper chain (`MCH-*`, elbow bent 2 mm back so a straight arm knows which way to fold) whose follower bones
  (`FOL-*`, the game bones' rest frames) the game bones copy their rotation from. The right arm's upper part is the
  stand's joint 6 and its forearm and hand are the wp024 bones, so its helper chain lives in the stand and the wp024
  bones copy from it: everything is posed from the stand armature, fingers of the right hand on wp024 itself;
- the text block `stand_rig_ui.py` (3D View sidebar > Stand Rig: the switches, the bone collections and Bake on
  Export; Blender runs it when the file is opened with scripts allowed, else Text Editor > Run Script once).

The game only reads keys, so anything the constraints make (IK, the arm's place on the stand, the retarget) reaches
it through the bake the UI text adds to LMT export (a baked copy of each action is exported, played with its other
half; the action keeps its own keys). Every control and helper bone is Not a Game Joint: never exported, and their curves
are left out of LMT export.
"""
import importlib.util, math, os, sys  # noqa: E401
import bpy
from mathutils import Matrix, Vector

# stand joint <- Nero joint (stand_taunt_retarget.py retargets by these; the names come from Nero's joints)
STAND_MAP = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 9, 8: 10, 9: 11, 10: 12,
             100: 116, 101: 117, 102: 118, 103: 119, 104: 120, 105: 121, 106: 122, 107: 123, 108: 124,
             11: 13, 12: 14, 13: 18, 200: 200, 201: 204, 202: 205, 203: 206, 204: 207, 205: 208, 206: 209, 207: 212, 208: 213}
# arm joint <- Nero joint; joint 0 follows the stand's ARM_ATTACH helper instead
ARM_MAP = {1: 7, 2: 8, 3: 100, 4: 101, 5: 102, 6: 103, 7: 104, 8: 105, 9: 106, 10: 107, 11: 108,
           12: 109, 13: 110, 14: 111, 15: 112, 16: 113, 17: 114, 18: 115}
ARM_ROOT_NAME = "arm_root"      # the arm's joint 0: placed on the stand's joint 6, never posed by hand
ATTACH_BONE = "ARM_ATTACH"
RETARGET = "RETARGET_"          # the retarget's constraints (stand_taunt_retarget.py)
RIG = "RIG_"                    # this rig's constraints
FOLLOW, IK_L, IK_R = "follow_nero", "ik_arm_l", "ik_arm_r"
SWORD = "show_sword"            # stand object property: the sword's meshes show
SWORD_MESH = "stand_rig_sword_mesh"   # on the sword's meshes: 1 = follows show_sword (0: one the import hides)
SWORD_JOINT = 150               # wp024's joint the game draws the sword in while it's drawn
SWORD_TIP = "Show the stand's Yamato (wp040) in its right hand"
MARK = "albam_stand_rig"        # object property: "stand" / "arm" (the UI finds the rigs by it)
PREBEND = 0.002                 # m the helper elbow sits behind the real one
POLE_DISTANCE = 0.5             # m behind the elbow
BACK = Vector((0.0, 1.0, 0.0))  # the stand faces -Y; elbows point back
UI_TEXT = "stand_rig_ui.py"
WIDGETS = "WGT_stand_rig"
HELPER_PREFIXES = ("MCH-", "FOL-", "IK-", "POLE-", "GRIP-")
GRIP = "GRIP-"                  # the arm's finger bones in the sword grip, under the hand
GRIP_BLOCK, GRIP_FRAME = 0x1C, 3   # the arm's mimic LMT (wp024_04) motion 0x31C, frame 3: the stand holds the sword there
                                # (the stand's sword-in-hand event bit 31 is on over frames 0-5)
ARM_HAND, ARM_FINGERS = 2, range(3, 19)
STAND_COLLECTIONS = ("Torso", "Legs", "Arm.L", "Fingers.L", "Arm.R", "IK", "Root", "Extras", "Twist", "Mechanism")
ARM_COLLECTIONS = ("Arm.R", "Fingers.R", "Extras", "Twist", "Mechanism")
HIDDEN_COLLECTIONS = ("Twist", "Mechanism")
LEFT, RIGHT, MIDDLE, CONTROL = "THEME04", "THEME01", "THEME09", "THEME03"

FOLLOW_TIP = "1: the stand copies Nero's pose (the retarget). 0: it plays its own keys, for animating it by hand"
IK_TIPS = {IK_L: "Left arm: 0 = FK (rotate the arm bones), 1 = IK (move the IK-hand_l cube, the POLE-arm_l diamond "
                 "turns the elbow)",
           IK_R: "Right arm: 0 = FK (rotate upper_arm_r on the stand, forearm_r / hand_r on wp024), 1 = IK (move the "
                 "IK-hand_r cube, the POLE-arm_r diamond turns the elbow)"}


def _albam():
    """albam's joints / compat / mesh modules (the add-on may be enabled already, or not registered yet)"""
    if not hasattr(bpy.types.Scene, "albam"):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(_HERE)))))
        import albam
        albam.register()
    from albam.engines.mtfw import joints, mesh
    from albam.lib import blender_compat as compat
    from albam.lib.blender import _display_vectors
    return joints, compat, mesh, _display_vectors


_HERE = __file__ if os.path.isfile(__file__) else os.path.join(
    os.path.dirname(sys.modules["albam"].__file__) if "albam" in sys.modules else
    r"E:\DMC mod stuffs\blender_addon\addons\albam", "scripts", "stand_rig.py")


def _joint(bone):
    value = bone.get("mtfw.anim_retarget")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _game_bones(ob, joints):
    return {_joint(b): b for b in ob.data.bones if _joint(b) is not None and not joints.is_helper(b)}


def find_rigs():
    """(stand, arm): the armatures marked by a build, else the ones with the retarget's attach bone / constraint"""
    stand = next((o for o in bpy.data.objects if o.get(MARK) == "stand"), None)
    arm = next((o for o in bpy.data.objects if o.get(MARK) == "arm"), None)
    if stand is None:
        stand = next((o for o in bpy.data.objects if o.type == "ARMATURE" and ATTACH_BONE in o.data.bones), None)
    if arm is None and stand is not None:
        arm = next((o for o in bpy.data.objects if o.type == "ARMATURE" and o is not stand and any(
            c.type == "COPY_TRANSFORMS" and c.target == stand and c.subtarget == ATTACH_BONE
            for pb in o.pose.bones for c in pb.constraints)), None)
    return stand, arm


def find_nero(stand):
    """Nero's armature: what the stand's retarget constraints copy from"""
    return next((c.target for pb in stand.pose.bones for c in pb.constraints
                 if c.name.startswith(RETARGET) and getattr(c, "target", None) is not None
                 and c.target.type == "ARMATURE" and c.target.get(MARK) is None), None)


# -- names ---------------------------------------------------------------------------------------------------------

def wanted_names(ob, mapping, joints, root_name=None):
    names = {}
    for j, b in _game_bones(ob, joints).items():
        if j == 0 and root_name:
            names[b.name] = root_name
        elif j in mapping:
            names[b.name] = joints.PLAYER_JOINTS.get(mapping[j], (f"joint_{j}",))[0]
        else:
            names[b.name] = f"joint_{j}"
    return {old: new for old, new in names.items() if old != new}


def rename_bones(ob, wanted, joints):
    """Rename by the map (two passes, so names can swap), fixing the armature's other actions the way Albam's
    Name Bones does; Blender fixes vertex groups, constraints, drivers and the action it plays."""
    if not wanted:
        return {}
    for k, old in enumerate(wanted):
        ob.data.bones[old].name = f"stand_rig_tmp_{k}"
    renamed = {}
    for k, (old, new) in enumerate(wanted.items()):
        bone = ob.data.bones[f"stand_rig_tmp_{k}"]
        bone.name = new
        renamed[old] = bone.name
    for action in joints._owned_actions(ob):
        joints._rename_in_action(action, renamed)
    return renamed


# -- meshes --------------------------------------------------------------------------------------------------------

def _import_model(model_path, mesh):
    """Import a model from the Game Files; its armature, or None when the file isn't there"""
    rfs = bpy.context.scene.albam.rfs
    item = next((i for i in rfs.file_list if i.name.lower().endswith(model_path.lower())), None)
    if item is None:
        print(f"stand rig: {model_path} isn't in the Game Files")
        return None
    before = set(bpy.data.objects)
    mesh.build_blender_model(item, bpy.context)
    return next(o for o in bpy.data.objects if o.type == "ARMATURE" and o not in before)


def add_sword(stand, arm, joints, mesh):
    """wp040, the stand's Yamato, in the arm's hand. The game draws the sword model in the frame of wp024's joint 150
    while the stand's motion has its sword-in-hand event bit 31 (uPlNeroDevil::updatePosition; else in stand joint 151,
    sheathed), so the model's space (Albam's GAME_FRAME) goes onto that bone. The meshes the import shows follow the
    stand's show_sword switch."""
    hand = _game_bones(arm, joints).get(SWORD_JOINT)
    if hand is None:
        print(f"stand rig: {arm.name} has no joint {SWORD_JOINT}, so the sword isn't attached")
        return 0
    sword = next((o for o in bpy.data.objects if o.get(MARK) == "sword"), None)
    added = 0
    if sword is None:
        sword = _import_model("model::game::wp040::wp040.mod", mesh)
        if sword is None:
            return 0
        sword[MARK] = "sword"
        collection = arm.users_collection[0]
        for ob in [sword] + [c for c in sword.children if c.type == "MESH"]:
            for c in list(ob.users_collection):
                c.objects.unlink(ob)
            collection.objects.link(ob)
            ob.hide_select = True
            if ob.type == "MESH":
                ob[SWORD_MESH] = not ob.hide_viewport
                added += 1
        sword.hide_set(True)
    sword.parent = arm
    sword.parent_type = "BONE"
    sword.parent_bone = hand.name
    sword.matrix_parent_inverse = Matrix.Translation((0.0, -hand.length, 0.0)) @ joints.GAME_FRAME.inverted()
    sword.matrix_basis = Matrix.Identity(4)
    if SWORD not in stand.keys():
        stand[SWORD] = True
    stand.id_properties_ui(SWORD).update(description=SWORD_TIP)
    for ob in sword.children:
        if ob.type != "MESH" or not ob.get(SWORD_MESH):
            continue
        for path in ("hide_viewport", "hide_render"):
            driver = ob.driver_add(path).driver
            driver.type = "SCRIPTED"
            for v in list(driver.variables):
                driver.variables.remove(v)
            var = driver.variables.new()
            var.name, var.type = "show", "SINGLE_PROP"
            var.targets[0].id = stand
            var.targets[0].data_path = f'["{SWORD}"]'
            driver.expression = "not show"
    return added


def add_meshes(ob, model_path, joints, mesh):
    """Import the model again and move its meshes onto `ob` (vertex groups renamed by joint number)."""
    if any(c.type == "MESH" for c in ob.children):
        return 0
    fresh = _import_model(model_path, mesh)
    if fresh is None:
        return 0
    by_joint = {j: b.name for j, b in _game_bones(ob, joints).items()}
    fresh_joint = {b.name: _joint(b) for b in fresh.data.bones}
    collection = ob.users_collection[0]
    moved = 0
    for child in list(fresh.children):
        if child.type != "MESH":
            continue
        for vg in child.vertex_groups:
            target = by_joint.get(fresh_joint.get(vg.name))
            if target is not None:
                vg.name = target
        for mod in child.modifiers:
            if mod.type == "ARMATURE":
                mod.object = ob
        child.parent = ob
        child.matrix_parent_inverse = Matrix.Identity(4)
        for c in list(child.users_collection):
            c.objects.unlink(child)
        collection.objects.link(child)
        child.hide_select = True
        moved += 1
    data = fresh.data
    bpy.data.objects.remove(fresh)
    if data.users == 0:
        bpy.data.armatures.remove(data)
    return moved


# -- widgets -------------------------------------------------------------------------------------------------------

def _widget(name, verts, edges):
    ob = bpy.data.objects.get(name)
    if ob is not None:
        return ob
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    ob = bpy.data.objects.new(name, me)
    coll = bpy.data.collections.get(WIDGETS)
    if coll is None:
        coll = bpy.data.collections.new(WIDGETS)
        bpy.context.scene.collection.children.link(coll)
    coll.objects.link(ob)
    coll.hide_viewport = True
    coll.hide_render = True
    return ob


def widgets():
    n = 32
    circle = [(math.cos(2 * math.pi * k / n), 0.0, math.sin(2 * math.pi * k / n)) for k in range(n)]
    ring = [(k, (k + 1) % n) for k in range(n)]
    cube = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
    cube_edges = [(a, b) for a in range(8) for b in range(a + 1, 8) if bin(a ^ b).count("1") == 1]
    diamond = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
    diamond_edges = [(a, b) for a in range(6) for b in range(a + 1, 6) if a // 2 != b // 2]
    square = [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1), (0, 0, 1.4)]   # a square, its arrow along +Z
    return {"circle": _widget("WGT-circle", circle, ring),
            "cube": _widget("WGT-cube", cube, cube_edges),
            "diamond": _widget("WGT-diamond", diamond, diamond_edges),
            "root": _widget("WGT-root", square, [(0, 1), (1, 2), (2, 3), (3, 0), (3, 4), (4, 2)])}


# shapes: joint -> (radius m, fraction of the way to the child, direction override in armature space or None)
DOWN, UP = Vector((0, 0, -1)), Vector((0, 0, 1))
STAND_SHAPES = {0: (0.45, 0.0, UP), 1: (0.30, 0.35, None), 2: (0.30, 0.45, None), 3: (0.12, 0.5, None),
                4: (0.18, 0.0, UP), 5: (0.09, 0.5, None), 6: (0.11, 0.35, None), 7: (0.09, 0.5, None),
                8: (0.11, 0.35, None), 9: (0.10, 0.4, None), 10: (0.08, 0.3, None), 11: (0.34, 0.0, DOWN),
                12: (0.14, 0.0, DOWN), 13: (0.14, 0.0, DOWN)}
ARM_SHAPES = {1: (0.10, 0.4, None), 2: (0.08, 0.3, None)}
FINGER, EXTRA = (0.025, 0.5, None), (0.04, 0.5, None)
SHAPE_OFFSET = {0: 0.0, 4: 0.12, 11: 0.06, 12: 0.18, 13: 0.18}   # m along the override direction
FRONT = Vector((0, -1, 0))


def _orient(bone, y_world, z_world=None):
    """custom-shape rotation putting the shape's Y axis along y_world (and its Z toward z_world)"""
    m = bone.matrix_local.to_3x3().transposed()
    y = (m @ y_world).normalized()
    if z_world is None:
        return y.to_track_quat("Y", "Z").to_euler("XYZ")
    z = m @ z_world
    z = (z - y * z.dot(y)).normalized()
    return Matrix((y.cross(z), y, z)).transposed().to_euler("XYZ")


def _shape(pb, bone, widget, radius, along, direction, vectors, offset=0.0):
    vec, length = vectors.get(bone.name, (UP, 0.1))
    d = direction if direction is not None else vec
    local = bone.matrix_local.to_3x3().transposed() @ d
    pb.custom_shape = widget
    pb.use_custom_shape_bone_size = False
    pb.custom_shape_rotation_euler = _orient(bone, d)
    pb.custom_shape_translation = local.normalized() * (offset if direction is not None else along * length)
    pb.custom_shape_scale_xyz = (radius, radius, radius)
    pb.bone.show_wire = True


def _colour(bone, x):
    bone.color.palette = LEFT if x > 1e-3 else RIGHT if x < -1e-3 else MIDDLE


# -- removal (rebuilds) ---------------------------------------------------------------------------------------------

def remove(stand, arm):
    for ob in (stand, arm):
        if ob is None:
            continue
        if ob.animation_data is not None:
            for fc in list(ob.animation_data.drivers):
                if ".constraints[" in fc.data_path and (RIG in fc.data_path or RETARGET in fc.data_path):
                    ob.animation_data.drivers.remove(fc)
        for pb in ob.pose.bones:
            for con in [c for c in pb.constraints if c.name.startswith(RIG)]:
                pb.constraints.remove(con)
        for name in [c.name for c in ob.data.collections_all if c.name in STAND_COLLECTIONS + ARM_COLLECTIONS]:
            ob.data.collections.remove(ob.data.collections_all[name])
    for ob in (stand, arm):
        if ob is not None and any(b.name.startswith(HELPER_PREFIXES) for b in ob.data.bones):
            _edit(ob)
            for eb in [e for e in ob.data.edit_bones if e.name.startswith(HELPER_PREFIXES)]:
                ob.data.edit_bones.remove(eb)
            bpy.ops.object.mode_set(mode="OBJECT")


def _edit(ob):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.hide_set(False)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")


# -- IK ------------------------------------------------------------------------------------------------------------

def _new_bone(ob, name, matrix=None, head=None, tail=None, parent=None, connect=False, length=0.05):
    eb = ob.data.edit_bones.new(name)
    if matrix is not None:
        eb.length = length
        eb.matrix = matrix
    else:
        eb.head, eb.tail = head, tail
    if parent is not None:
        eb.parent = ob.data.edit_bones[parent]
        eb.use_connect = connect
    return eb


def _arm_rest_in_stand(stand, arm, arm_bone):
    """where the arm bone's rest frame sits in the stand's armature space (its root on ARM_ATTACH)"""
    root = arm.data.bones[ARM_ROOT_NAME].matrix_local
    return stand.data.bones[ATTACH_BONE].matrix_local @ root.inverted() @ arm.data.bones[arm_bone].matrix_local


def build_ik(stand, arm, sb, ab):
    """sb / ab: joint -> bone name. Returns the IK constraints, by side."""
    L = {"shoulder": sb[7], "upper": sb[8], "fore": sb[9], "hand": sb[10]}
    R = {"shoulder": sb[5], "upper": sb[6], "fore": ab[1], "hand": ab[2]}
    root = sb[0]
    rest = {b.name: b.matrix_local.copy() for b in stand.data.bones}
    right_fore = _arm_rest_in_stand(stand, arm, R["fore"])
    right_hand = _arm_rest_in_stand(stand, arm, R["hand"])
    _edit(stand)
    sides = {"l": (L, rest[L["upper"]], rest[L["fore"]], rest[L["hand"]]),
             "r": (R, rest[R["upper"]], right_fore, right_hand)}
    for s, (names, upper, fore, hand) in sides.items():
        u, e, w = upper.to_translation(), fore.to_translation(), hand.to_translation()
        e_bent = e + BACK * PREBEND
        _new_bone(stand, f"MCH-upper_arm_{s}", head=u, tail=e_bent, parent=names["shoulder"])
        _new_bone(stand, f"MCH-forearm_{s}", head=e_bent, tail=w, parent=f"MCH-upper_arm_{s}", connect=True)
        _new_bone(stand, f"FOL-upper_arm_{s}", matrix=upper, parent=f"MCH-upper_arm_{s}")
        _new_bone(stand, f"FOL-forearm_{s}", matrix=fore, parent=f"MCH-forearm_{s}")
        _new_bone(stand, f"IK-hand_{s}", matrix=hand, parent=root, length=0.12)
        pole = e + BACK * POLE_DISTANCE
        _new_bone(stand, f"POLE-arm_{s}", head=pole, tail=pole + Vector((0, 0, 0.05)), parent=root)
    bpy.ops.object.mode_set(mode="OBJECT")
    ik = {}
    for s in "lr":
        pb = stand.pose.bones[f"MCH-forearm_{s}"]
        con = pb.constraints.new("IK")
        con.name = RIG + "ik"
        con.target, con.subtarget = stand, f"IK-hand_{s}"
        con.pole_target, con.pole_subtarget = stand, f"POLE-arm_{s}"
        con.chain_count = 2
        con.use_stretch = False
        ik[s] = con
    for s in "lr":
        for name in (f"MCH-upper_arm_{s}", f"MCH-forearm_{s}", f"FOL-upper_arm_{s}", f"FOL-forearm_{s}",
                     f"IK-hand_{s}", f"POLE-arm_{s}"):
            stand.data.bones[name]["mtfw.not_joint"] = 1
    return ik, sides


def build_grip(stand, arm, ab, compat):
    """The fingers close on the sword while show_sword is on: GRIP- bones under the hand hold the finger pose of a
    vanilla sword motion (relative to the hand), and each finger copies its GRIP- bone with the switch as influence."""
    from albam.engines.mtfw import animation
    action = next((a for a in bpy.data.actions if "wp024_04" in a.name.lower()
                   and animation.get_lmt_props(a).lmt_id == GRIP_BLOCK), None)
    if action is None or ARM_HAND not in ab:
        print("stand rig: no wp024_04 motion 0x31C in the file, so the hand has no sword grip")
        return None
    hand = ab[ARM_HAND]
    fingers = [b.name for b in arm.data.bones if b.name in {ab[j] for j in ARM_FINGERS if j in ab}]   # parents first
    modes = {n: arm.pose.bones[n].rotation_mode for n in [hand] + fingers}
    for n in modes:
        arm.pose.bones[n].rotation_mode = "QUATERNION"
    compat.assign_action(arm, action)
    bpy.context.scene.frame_set(GRIP_FRAME)
    hand_pose = arm.pose.bones[hand].matrix.copy()
    rel = {n: hand_pose.inverted() @ arm.pose.bones[n].matrix for n in fingers}
    compat.assign_action(arm, None)
    for n, mode in modes.items():
        arm.pose.bones[n].rotation_mode = mode
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    hand_rest = arm.data.bones[hand].matrix_local
    _edit(arm)
    for n in fingers:
        bone = arm.data.bones[n]
        parent = bone.parent.name if bone.parent is not None else hand
        _new_bone(arm, GRIP + n, matrix=hand_rest @ rel[n], parent=GRIP + parent if parent in rel else parent,
                  length=bone.length)
    bpy.ops.object.mode_set(mode="OBJECT")
    for n in fingers:
        arm.data.bones[GRIP + n]["mtfw.not_joint"] = 1
        con = arm.pose.bones[n].constraints.new("COPY_TRANSFORMS")
        con.name = RIG + "grip"
        con.target, con.subtarget = arm, GRIP + n
        _drive(con, "show", [("show", stand, f'["{SWORD}"]')])
    return action.name


def calibrate_pole(stand, con, side):
    """the pole angle that leaves the helper chain on its rest pose with the controls at rest"""
    upper = stand.pose.bones[f"MCH-upper_arm_{side}"]
    fore = stand.pose.bones[f"MCH-forearm_{side}"]
    rest_u = stand.data.bones[upper.name].matrix_local
    rest_f = stand.data.bones[fore.name].matrix_local

    def error(angle):
        con.pole_angle = angle
        bpy.context.view_layer.update()
        return (upper.matrix.to_quaternion().rotation_difference(rest_u.to_quaternion()).angle +
                fore.matrix.to_quaternion().rotation_difference(rest_f.to_quaternion()).angle)
    best = min((math.radians(a) for a in range(-180, 180, 5)), key=error)
    step = math.radians(2.5)
    while step > 1e-6:
        best = min((best - step, best, best + step), key=error)
        step *= 0.5
    con.pole_angle = best
    return error(best)


def _copy_rotation(pb, target, subtarget):
    con = pb.constraints.new("COPY_ROTATION")
    con.name = RIG + "ik_follow"
    con.target, con.subtarget = target, subtarget
    con.target_space = con.owner_space = "WORLD"
    con.mix_mode = "REPLACE"
    return con


def _drive(con, expression, variables):
    fc = con.driver_add("influence")
    driver = fc.driver
    driver.type = "SCRIPTED"
    for v in list(driver.variables):
        driver.variables.remove(v)
    for name, idb, path in variables:
        var = driver.variables.new()
        var.name, var.type = name, "SINGLE_PROP"
        var.targets[0].id = idb
        var.targets[0].data_path = path
    driver.expression = expression
    return fc


def _prop(ob, name, value, description):
    if name not in ob.keys():
        ob[name] = value
    ob.id_properties_ui(name).update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, description=description)


# -- the build -----------------------------------------------------------------------------------------------------

def build(stand=None, arm=None, follow_nero=None):
    """Adds the controls (see the module docstring); returns a list of notes."""
    joints, compat, mesh, display_vectors = _albam()
    if stand is None or arm is None:
        found = find_rigs()
        stand, arm = stand or found[0], arm or found[1]
    if stand is None or arm is None or ATTACH_BONE not in stand.data.bones:
        raise RuntimeError("No stand rig in this file: run stand_taunt_retarget.py first (it makes the stand, the arm "
                           "and the ARM_ATTACH bone the arm hangs from)")
    notes = []
    scene = bpy.context.scene
    keep_frame = scene.frame_current
    actions = {ob: ob.animation_data.action if ob.animation_data else None for ob in (stand, arm)}
    remove(stand, arm)
    # names first, while the actions still play (Blender fixes the playing one), then meshes (vertex groups take the
    # new names)
    renamed = rename_bones(stand, wanted_names(stand, STAND_MAP, joints), joints)
    renamed_arm = rename_bones(arm, wanted_names(arm, ARM_MAP, joints, ARM_ROOT_NAME), joints)
    if renamed or renamed_arm:
        notes.append(f"renamed {len(renamed)} stand bones and {len(renamed_arm)} arm bones")
    retarget = [c for ob in (stand, arm) for pb in ob.pose.bones for c in pb.constraints
                if c.name.startswith(RETARGET) and c.type != "COPY_TRANSFORMS"]
    muted = {c: c.mute for c in retarget}
    for c in retarget:
        c.mute = True
    for ob in (stand, arm):
        compat.assign_action(ob, None)
        for pb in ob.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
    models = [(stand, "model::game::pl020::pl020.mod"), (arm, "model::game::wp024::wp024.mod")]
    nero = find_nero(stand)
    if nero is not None:
        models.append((nero, "model::game::pl000::pl000.mod"))
    for ob, path in models:
        n = add_meshes(ob, path, joints, mesh)
        if n:
            notes.append(f"{ob.name}: {n} meshes added")
    n = add_sword(stand, arm, joints, mesh)
    if n:
        notes.append(f"wp040: {n} sword meshes in the hand")
    sb = {j: b.name for j, b in _game_bones(stand, joints).items()}
    ab = {j: b.name for j, b in _game_bones(arm, joints).items()}
    grip = build_grip(stand, arm, ab, compat)
    if grip:
        notes.append(f"sword grip from {grip} frame {GRIP_FRAME}")

    # IK
    ik, sides = build_ik(stand, arm, sb, ab)
    for s, con in ik.items():
        err = calibrate_pole(stand, con, s)
        notes.append(f"pole angle {s}: {math.degrees(con.pole_angle):.2f} deg (rest error {math.degrees(err):.4f} deg)")
    _prop(stand, FOLLOW, 1.0, FOLLOW_TIP)
    for name in (IK_L, IK_R):
        _prop(stand, name, 0.0, IK_TIPS[name])
    stand[MARK], arm[MARK] = "stand", "arm"
    follow = ("follow", stand, f'["{FOLLOW}"]')
    for side, owners in (("l", ((stand, sb[8], "FOL-upper_arm_l"), (stand, sb[9], "FOL-forearm_l"),
                                (stand, sb[10], "IK-hand_l"))),
                         ("r", ((stand, sb[6], "FOL-upper_arm_r"), (arm, ab[1], "FOL-forearm_r"),
                                (arm, ab[2], "IK-hand_r")))):
        for ob, bone, target in owners:
            con = _copy_rotation(ob.pose.bones[bone], stand, target)
            _drive(con, "ik * (1 - follow)", [("ik", stand, f'["{IK_L if side == "l" else IK_R}"]'), follow])
    for c in retarget:
        _drive(c, "follow", [follow])

    # display, collections, locks
    w = widgets()
    for ob, game, shapes, names in ((stand, sb, STAND_SHAPES, STAND_COLLECTIONS), (arm, ab, ARM_SHAPES, ARM_COLLECTIONS)):
        coll = {n: ob.data.collections.new(n) for n in names}
        for n in HIDDEN_COLLECTIONS:
            coll[n].is_visible = False
        vectors = display_vectors([b for b in ob.data.bones if _joint(b) is not None and not joints.is_helper(b)])
        for j, name in game.items():
            bone, pb = ob.data.bones[name], ob.pose.bones[name]
            _colour(bone, bone.head_local.x if ob is stand else -1.0)
            pb.lock_scale = (True, True, True)
            if not (ob is stand and j in (0, 1)):
                pb.lock_location = (True, True, True)
            if j >= 200 or (ob is arm and j == 0):
                coll["Twist" if j >= 200 else "Mechanism"].assign(bone)
                continue
            if 100 <= j < 150 or (ob is arm and 3 <= j <= 18):
                coll["Fingers.L" if ob is stand else "Fingers.R"].assign(bone)
                _shape(pb, bone, w["circle"], *FINGER, vectors)
            elif j in shapes:
                group = "Arm.R" if ob is arm or j in (5, 6) else "Torso" if j in (0, 1, 2, 3, 4, 11) else \
                    "Legs" if j in (12, 13) else "Arm.L"
                coll[group].assign(bone)
                _shape(pb, bone, w["circle"], *shapes[j], vectors, SHAPE_OFFSET.get(j, 0.0))
            else:
                coll["Extras"].assign(bone)
                _shape(pb, bone, w["circle"], *EXTRA, vectors)
        if ob is stand:
            for b in ob.data.bones:
                pb = ob.pose.bones[b.name]
                if b.name.startswith(("MCH-", "FOL-")) or b.name == ATTACH_BONE:
                    coll["Mechanism"].assign(b)
                elif b.name.startswith("IK-"):
                    coll["IK"].assign(b)
                    _shape(pb, b, w["cube"], 0.12, 0.0, UP, {})
                    pb.lock_scale = (True, True, True)
                    b.color.palette = LEFT if b.name.endswith("_l") else RIGHT
                elif b.name.startswith("POLE-"):
                    coll["IK"].assign(b)
                    _shape(pb, b, w["diamond"], 0.05, 0.0, UP, {})
                    pb.lock_rotation = pb.lock_scale = (True, True, True)
                    b.color.palette = LEFT if b.name.endswith("_l") else RIGHT
                elif b.name == "root_motion":
                    coll["Root"].assign(b)
                    pb.custom_shape = w["root"]
                    pb.use_custom_shape_bone_size = False
                    pb.custom_shape_scale_xyz = (0.6, 0.6, 0.6)
                    pb.custom_shape_rotation_euler = _orient(b, UP, FRONT)
                    pb.custom_shape_translation = (0.0, 0.0, 0.0)
                    b.color.palette = CONTROL
        else:
            for b in ob.data.bones:
                if b.name == "root_motion" or b.name.startswith(GRIP):
                    coll["Mechanism"].assign(b)
        ob.show_in_front = True
        ob.data.display_type = "OCTAHEDRAL"

    # put things back
    for c, m in muted.items():
        c.mute = m
    if follow_nero is not None:
        stand[FOLLOW] = float(follow_nero)
    for ob, action in actions.items():
        compat.assign_action(ob, action)
    install_ui()
    scene.frame_set(keep_frame)
    return notes


def install_ui():
    """the UI text block (registered now, and on load when the file's scripts are allowed)"""
    path = os.path.join(os.path.dirname(os.path.abspath(_HERE)), UI_TEXT)
    source = open(path, encoding="utf-8").read()
    text = bpy.data.texts.get(UI_TEXT) or bpy.data.texts.new(UI_TEXT)
    text.from_string(source)
    text.use_module = True
    spec = importlib.util.spec_from_file_location("stand_rig_ui", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)   # registers its classes


if __name__ == "__main__":
    try:
        for note in build():
            print("stand rig:", note)
        if bpy.app.background and bpy.data.filepath:
            bpy.ops.wm.save_mainfile()
            print("saved", bpy.data.filepath)
        print("DONE")
    except Exception:
        import traceback
        traceback.print_exc()
        if not bpy.app.background:
            raise
        sys.exit(1)
