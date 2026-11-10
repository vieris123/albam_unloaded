"""An animation rig for Nero (pl000), the stand rig's controls on Nero's own body, in a .blend of its own.

Headless, from nothing (imports everything, builds the controls, saves `nero_rig.blend` under ALBAM_NERO_RIG_OUT,
default E:\\DMC mod stuffs\\nero_rig):
    "C:\\Program Files\\Blender Foundation\\Blender 4.2\\blender.exe" -b --factory-startup --python scripts/nero_rig.py
Run it again on that file (Text Editor > Run Script, or `blender -b nero_rig.blend --python scripts/nero_rig.py`,
which saves) to rebuild the controls; the imports are kept.

What the file holds:
- Nero's body (pl000.mod) with his face (pl000_01) and hair (pl000_02) meshes moved onto the body armature: in the game
  their joints copy body joints' world matrices (uPlayerNero::initModel 0x7E3760: face joints 0-4 <- body 2, 3, 4, 5,
  9; hair 0 / 1 <- face 1 / 2 = body 3 / 4), and their rest frames are the body's turned by nothing, moved by one
  offset, so the meshes go on with that offset;
- the coat (pl000_03.mod, its six .phs chains and pl000_03.col), hung on body joint 2 by Albam, with the chain
  preview on: the coat swings while the animation plays (preview only, as in the game the chains are physics);
- Red Queen (wp001) on the joint the game draws it on: uPlWpRedQueen::update 0x838A50 parents it to
  {152 weapon_back, 150 prop_r, 151 prop_l}[event bits 27-28] (`red_queen_place` 0 / 1 / 2), and Blue Rose (wp000) on
  151 while event bit 26 is on (uPlWpBlueRose::update 0x831F50; `show_blue_rose`; hidden otherwise). With
  `weapons_follow_events` the two follow the events of the LMT animation playing, else they're set by hand. The hand
  holding a weapon closes on it (the finger pose of a vanilla frame with it in that hand, `GRIP-` bones), as much as
  that hand's grip switch says (`grip_l` / `grip_r`, keyable: 0 leaves the fingers to their own keys, for a gun spin);
- Nero's four body LMTs (pl000_01, 02, 04, 06) as reference animations and a place for new ones;
- control shapes, colours (left blue, right red, middle yellow), bone collections, location / scale locks;
- IK for the arms and the legs (`ik_arm_l/r`, `ik_leg_l/r`: 0 = FK, 1 = IK) through a helper chain (`MCH-*`, the
  joint bent 2 mm the way it folds) whose followers (`FOL-*`) the game bones copy their rotation from, as on the stand
  rig: Blender's IK can't solve the game's bones (5 cm stubs pointing up). Hand controls hang from the root (joint 0),
  feet and knee poles from root_motion, so the feet stay planted when the body moves;
- the text block `nero_rig_ui.py` (3D View sidebar > Nero Rig: the switches, the bone collections, Bake on Export).

The game only reads keys: what the constraints make (IK, grips) reaches it through the bake the UI text adds to LMT
export (a baked copy of each action is exported; the action keeps its own keys). Every control and helper bone is Not
a Game Joint, never exported, and their curves are left out of LMT export.
"""
import importlib.util, math, os, sys  # noqa: E401
import bpy
from mathutils import Matrix, Vector

_HERE = __file__ if os.path.isfile(__file__) else os.path.join(
    os.path.dirname(sys.modules["albam"].__file__) if "albam" in sys.modules else
    r"E:\DMC mod stuffs\blender_addon\addons\albam", "scripts", "nero_rig.py")


def _sibling(name):
    path = os.path.join(os.path.dirname(os.path.abspath(_HERE)), name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sr = _sibling("stand_rig")   # the shared helpers (widgets, shapes, bones, drivers)

DATA = os.environ.get("ALBAM_DMC4_DATA", r"E:\DMC mod stuffs")
NERO_FILES = os.path.join(DATA, "arctool", "uPlayerNero-vanilla")
OUT = os.environ.get("ALBAM_NERO_RIG_OUT", os.path.join(DATA, "nero_rig"))

BODY = "model::game::pl000::pl000.mod"
PARTS = (("model::game::pl000::pl000_01.mod", {0: 2, 1: 3, 2: 4, 3: 5, 4: 9}),   # face
         ("model::game::pl000::pl000_02.mod", {0: 3, 1: 4}))                      # hair
COAT = ["model::game::pl000::pl000_03.mod", "model::game::pl000::pl000_03.col"] + \
       [f"model::game::pl000::pl000_03_0{k}.phs" for k in range(6)]
RED_QUEEN, BLUE_ROSE = "model::game::wp001::wp001.mod", "model::game::wp000::wp000.mod"
LMTS = [f"motion::pl000::pl000_0{k}.lmt" for k in (1, 2, 4, 6)]

MARK = "albam_nero_rig"          # object property: "nero" / "red_queen" / "blue_rose"
RIG = "RIG_"                     # this rig's constraints
IK_PROPS = ("ik_arm_l", "ik_arm_r", "ik_leg_l", "ik_leg_r")
GRIP_PROPS = ("grip_l", "grip_r")
PLACE, GUN, FOLLOW_EVENTS = "red_queen_place", "show_blue_rose", "weapons_follow_events"
PLACE_JOINTS = (152, 150, 151)   # uPlWpRedQueen::update: the joint by event bits 27-28 (table 0xC3BB18)
GUN_JOINT = 151                  # uPlWpBlueRose::update
WEAPON_MESH = "nero_rig_weapon_mesh"   # on a weapon mesh the import showed (the hidden ones stay hidden)
HELPER_PREFIXES = ("MCH-", "FOL-", "IK-", "POLE-", "GRIP-")
GRIP = "GRIP-"
PREBEND = 0.002
POLE_DISTANCE = 0.5
BACK, FRONT, UP, DOWN = Vector((0, 1, 0)), Vector((0, -1, 0)), Vector((0, 0, 1)), Vector((0, 0, -1))
UI_TEXT = "nero_rig_ui.py"

# limbs: name -> (parent joint, upper, lower, end, the way the middle joint folds, the end control's parent)
LIMBS = {"arm_r": (5, 6, 7, 8, BACK, "root"), "arm_l": (9, 10, 11, 12, BACK, "root"),
         "leg_r": (13, 14, 15, 16, FRONT, "root_motion"), "leg_l": (13, 18, 19, 20, FRONT, "root_motion")}
# grips: (set name, hand joint, finger joints, the event test for a frame with the weapon in that hand, driver)
GRIPS = (("red_queen_r", 8, range(100, 116), lambda v: (v >> 27) & 3 == 1, "grip_r if place == 1 else 0"),
         ("red_queen_l", 12, range(116, 132), lambda v: (v >> 27) & 3 == 2 and not (v >> 26) & 1,
          "grip_l if place == 2 and not gun else 0"),
         ("blue_rose_l", 12, range(116, 132), lambda v: (v >> 26) & 1, "grip_l if gun else 0"))

COLLECTIONS = ("Torso", "Head", "Arm.L", "Fingers.L", "Leg.L", "Arm.R", "Fingers.R", "Leg.R", "IK", "Root", "Props",
               "Extras", "Twist", "Mechanism")
HIDDEN_COLLECTIONS = ("Twist", "Mechanism")
GROUPS = {0: "Torso", 1: "Torso", 2: "Torso", 13: "Torso", 3: "Head", 4: "Head", 153: "Torso", 154: "Torso",
          5: "Arm.R", 6: "Arm.R", 7: "Arm.R", 8: "Arm.R", 9: "Arm.L", 10: "Arm.L", 11: "Arm.L", 12: "Arm.L",
          14: "Leg.R", 15: "Leg.R", 16: "Leg.R", 17: "Leg.R", 18: "Leg.L", 19: "Leg.L", 20: "Leg.L", 21: "Leg.L",
          150: "Props", 151: "Props", 152: "Props"}
# shapes: joint -> (radius m, fraction of the way to the child, direction override or None, offset along it)
SHAPES = {0: (0.26, 0.0, UP, 0.0), 1: (0.17, 0.4, None, 0.0), 2: (0.19, 0.45, None, 0.0), 3: (0.07, 0.5, None, 0.0),
          4: (0.12, 0.0, UP, 0.11), 13: (0.21, 0.0, DOWN, 0.03),
          5: (0.06, 0.5, None, 0.0), 6: (0.065, 0.35, None, 0.0), 7: (0.055, 0.5, None, 0.0), 8: (0.05, 0.4, None, 0.0),
          9: (0.06, 0.5, None, 0.0), 10: (0.065, 0.35, None, 0.0), 11: (0.055, 0.5, None, 0.0),
          12: (0.05, 0.4, None, 0.0),
          14: (0.09, 0.3, None, 0.0), 15: (0.07, 0.3, None, 0.0), 16: (0.06, 0.0, FRONT, 0.04), 17: (0.04, 0.0, FRONT, 0.03),
          18: (0.09, 0.3, None, 0.0), 19: (0.07, 0.3, None, 0.0), 20: (0.06, 0.0, FRONT, 0.04), 21: (0.04, 0.0, FRONT, 0.03),
          150: (0.05, 0.0, UP, 0.0), 151: (0.05, 0.0, UP, 0.0), 152: (0.08, 0.0, UP, 0.0)}
FINGER, EXTRA = (0.015, 0.5, None, 0.0), (0.03, 0.5, None, 0.0)
MOVABLE = (0, 150, 151, 152)     # the joints the game's LMTs give location tracks: no location lock

TIPS = {"ik_arm_l": "Left arm: 0 = FK (rotate the arm bones), 1 = IK (move the IK-hand_l cube, the POLE-arm_l diamond "
                    "turns the elbow)",
        "ik_arm_r": "Right arm: 0 = FK, 1 = IK (the IK-hand_r cube, the POLE-arm_r diamond turns the elbow)",
        "ik_leg_l": "Left leg: 0 = FK, 1 = IK (move the IK-foot_l cube, the POLE-leg_l diamond turns the knee)",
        "ik_leg_r": "Right leg: 0 = FK, 1 = IK (the IK-foot_r cube, the POLE-leg_r diamond turns the knee)",
        PLACE: "Where Red Queen is drawn: 0 = on the back (joint 152), 1 = the right hand (150), 2 = the left hand "
               "(151), as event bits 27-28 (Main Sword Display) put it in the game",
        "grip_l": "Left hand's grip: 1 = the fingers close on the weapon in that hand (Blue Rose, or Red Queen "
                  "held there), 0 = the fingers play their own keys (a gun spin), between = a blend. Keyable",
        "grip_r": "Right hand's grip: 1 = the fingers close on Red Queen when it's in that hand, 0 = the fingers play "
                  "their own keys, between = a blend. Keyable",
        GUN: "Blue Rose in the left hand (joint 151), as event bit 26 (Gun Display) shows it in the game; hidden "
             "otherwise",
        FOLLOW_EVENTS: "Red Queen and Blue Rose follow the events of the LMT animation playing, as in the game (an "
                       "animation without events keeps the values set here)"}


# -- files ---------------------------------------------------------------------------------------------------------

def _rfs():
    rfs = bpy.context.scene.albam.rfs
    if not any(i.name.lower().endswith(BODY) for i in rfs.file_list):
        rfs.add_root_folder("dmc4", NERO_FILES)
    return rfs


def _item(path):
    item = next((i for i in _rfs().file_list if i.name.lower().endswith(path.lower())), None)
    if item is None:
        raise RuntimeError(f"{path} isn't in the Game Files (add {NERO_FILES})")
    return item


def import_file(path):
    """Import a game file as the Import button does; the new objects"""
    from albam.blender_ui.import_panel import ImportFileBase
    before = set(bpy.data.objects)
    ImportFileBase._execute(_item(path), bpy.context)
    return [o for o in bpy.data.objects if o not in before]


def _armature(objects):
    return next(o for o in objects if o.type == "ARMATURE")


def _joints_of(ob):
    return {sr._joint(b): b for b in ob.data.bones if sr._joint(b) is not None}


def move_part_meshes(nero, part, mapping):
    """The part model's meshes onto Nero's armature: vertex groups renamed to the body joints the game copies, the mesh
    moved by the offset between the two rests (the same for every joint)"""
    body, own = _joints_of(nero), _joints_of(part)
    k0 = next(iter(mapping))
    offset = body[mapping[k0]].head_local - own[k0].head_local
    worst = max((body[j].head_local - own[k].head_local - offset).length for k, j in mapping.items())
    names = {own[k].name: body[j].name for k, j in mapping.items()}
    moved = 0
    for child in [c for c in part.children if c.type == "MESH"]:
        for vg in child.vertex_groups:
            if vg.name in names:
                vg.name = names[vg.name]
        for mod in child.modifiers:
            if mod.type == "ARMATURE":
                mod.object = nero
        child.parent = nero
        child.matrix_parent_inverse = Matrix.Identity(4)
        child.matrix_basis = Matrix.Translation(offset)
        for c in list(child.users_collection):
            c.objects.unlink(child)
        nero.users_collection[0].objects.link(child)
        child.hide_select = True
        moved += 1
    data = part.data
    bpy.data.objects.remove(part)
    if data.users == 0:
        bpy.data.armatures.remove(data)
    return moved, worst


def _move_to(objects, collection):
    for ob in objects:
        for c in list(ob.users_collection):
            c.objects.unlink(ob)
        collection.objects.link(ob)


def setup_file(notes):
    """Import Nero, his parts, coat, weapons and LMTs into this (empty) file; Nero's armature"""
    scene = bpy.context.scene
    coll = bpy.data.collections.new("Nero")
    scene.collection.children.link(coll)
    nero = _armature(import_file(BODY))
    _move_to([nero] + list(nero.children), coll)
    nero[MARK] = "nero"
    for path, mapping in PARTS:
        part = _armature(import_file(path))
        n, worst = move_part_meshes(nero, part, mapping)
        notes.append(f"{path.split('::')[-1]}: {n} meshes on the body (rest mismatch {worst * 1000:.3f} mm)")
    coat = []
    for path in COAT:
        coat += import_file(path)
    for ob in coat:
        if ob.type == "EMPTY" and ob.albam_asset.extension == "phs":
            ob.albam_phs.preview = True
        elif ob.get("col_root") is not None or ob.name.startswith("COL_"):
            ob.hide_set(True)
    notes.append(f"coat: {sum(1 for o in coat if o.type == 'EMPTY' and o.albam_asset.extension == 'phs')} chains "
                 "previewed")
    for path, mark in ((RED_QUEEN, "red_queen"), (BLUE_ROSE, "blue_rose")):
        weapon = _armature(import_file(path))
        weapon[MARK] = mark
        meshes = [c for c in weapon.children if c.type == "MESH"]
        for m in meshes:
            m[WEAPON_MESH] = not m.hide_viewport
            m.hide_select = True
        _move_to([weapon] + meshes, coll)
        weapon.hide_set(True)
    scene.albam.import_options_lmt.armature = nero
    from albam.engines.mtfw import animation
    for path in LMTS:
        animation.load_lmt(_item(path), bpy.context)
    notes.append(f"{len(LMTS)} LMTs on Nero")
    return nero


# -- weapons -------------------------------------------------------------------------------------------------------

def _weapon(mark):
    return next((o for o in bpy.data.objects if o.get(MARK) == mark), None)


def attach_weapons(nero, joints):
    """Child Of constraints on the joints the game draws each weapon on, switched by the rig's properties"""
    body = _joints_of(nero)
    inverse = joints.GAME_FRAME.inverted()
    for mark, places in (("red_queen", [(j, f"place == {k}") for k, j in enumerate(PLACE_JOINTS)]),
                         ("blue_rose", [(GUN_JOINT, "1")])):
        weapon = _weapon(mark)
        if weapon is None:
            continue
        weapon.parent = None
        weapon.matrix_basis = Matrix.Identity(4)
        for con in [c for c in weapon.constraints if c.name.startswith(RIG)]:
            weapon.constraints.remove(con)
        for joint, expression in places:
            con = weapon.constraints.new("CHILD_OF")
            con.name = f"{RIG}joint_{joint}"
            con.target, con.subtarget = nero, body[joint].name
            con.inverse_matrix = inverse
            con.set_inverse_pending = False
            sr._drive(con, expression, [("place", nero, f'["{PLACE}"]')])
        for m in weapon.children:
            if m.type != "MESH" or not m.get(WEAPON_MESH):
                continue
            for path in ("hide_viewport", "hide_render"):
                if m.animation_data is not None:
                    old = m.animation_data.drivers.find(path)
                    if old is not None:
                        m.animation_data.drivers.remove(old)
                if mark != "blue_rose":
                    continue
                driver = m.driver_add(path).driver
                driver.type = "SCRIPTED"
                var = driver.variables.new()
                var.name, var.type = "gun", "SINGLE_PROP"
                var.targets[0].id = nero
                var.targets[0].data_path = f'["{GUN}"]'
                driver.expression = "not gun"


# -- grips ---------------------------------------------------------------------------------------------------------

def event_runs(action):
    """[(frame, value)] of an LMT action's first event table, by frame"""
    from albam.engines.mtfw import animation
    try:
        props = animation.get_lmt_props(action)
    except Exception:   # noqa: BLE001 - not an LMT action
        return []
    runs = []
    for i, event in enumerate(props.event_markers):
        if event.param_ev_type not in ("", "Hitbox"):
            continue
        marker = animation.find_event_marker(action, event, i)
        if marker is not None:
            runs.append((marker.frame, event.encode()))
    return sorted(runs)


def find_grip_frame(test, actions):
    """(action, frame): the middle of the longest run (at most 10 frames in) of a vanilla animation passing test"""
    best = None
    for action in actions:
        runs = event_runs(action)
        end = action.frame_range[1]
        for k, (frame, value) in enumerate(runs):
            if not test(value):
                continue
            length = (runs[k + 1][0] if k + 1 < len(runs) else end) - frame
            if length >= 6 and (best is None or length > best[2]):
                best = (action, frame + min(length // 2, 10), length)
    return best[:2] if best else None


def build_grips(nero, compat, notes):
    """GRIP- bones holding each grip's finger pose relative to the hand; the fingers copy them while the weapon is
    in that hand"""
    # only the vanilla animations the rig imported (named <armature>.<file>.<block>): an animation made here may pose
    # the fingers otherwise (a gun spin), and a rebuild would take that as the grip
    vanilla = tuple(f".{path.rsplit('::', 1)[1]}." for path in LMTS)
    lmt_actions = [a for a in bpy.data.actions if any(v in a.name for v in vanilla) and event_runs(a)]
    body = _joints_of(nero)
    found = {}
    for name, hand, fingers, test, _ in GRIPS:
        hit = find_grip_frame(test, lmt_actions)
        if hit is None:
            notes.append(f"no vanilla frame for the {name} grip: that hand stays as animated")
            continue
        action, frame = hit
        bones = [b.name for b in nero.data.bones if sr._joint(b) in fingers]   # parents first
        hand_name = body[hand].name
        modes = {n: nero.pose.bones[n].rotation_mode for n in [hand_name] + bones}
        for n in modes:
            nero.pose.bones[n].rotation_mode = "QUATERNION"
        compat.assign_action(nero, action)
        bpy.context.scene.frame_set(int(frame))
        hand_pose = nero.pose.bones[hand_name].matrix.copy()
        found[name] = (hand_name, bones, {n: hand_pose.inverted() @ nero.pose.bones[n].matrix for n in bones})
        compat.assign_action(nero, None)
        for n, mode in modes.items():
            nero.pose.bones[n].rotation_mode = mode
        for pb in nero.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        notes.append(f"{name} grip from {action.name} frame {int(frame)}")
    if not found:
        return
    sr._edit(nero)
    for name, (hand_name, bones, rel) in found.items():
        hand_rest = nero.data.bones[hand_name].matrix_local
        for n in bones:
            bone = nero.data.bones[n]
            parent = bone.parent.name if bone.parent is not None else hand_name
            sr._new_bone(nero, f"{GRIP}{name}-{n}", matrix=hand_rest @ rel[n],
                         parent=f"{GRIP}{name}-{parent}" if parent in rel else parent, length=bone.length)
    bpy.ops.object.mode_set(mode="OBJECT")
    drivers = {g[0]: g[4] for g in GRIPS}
    for name, (_, bones, _) in found.items():
        for n in bones:
            nero.data.bones[f"{GRIP}{name}-{n}"]["mtfw.not_joint"] = 1
            con = nero.pose.bones[n].constraints.new("COPY_TRANSFORMS")
            con.name = f"{RIG}grip_{name}"
            con.target, con.subtarget = nero, f"{GRIP}{name}-{n}"
            sr._drive(con, drivers[name], [("place", nero, f'["{PLACE}"]'), ("gun", nero, f'["{GUN}"]')] +
                      [(g, nero, f'["{g}"]') for g in GRIP_PROPS])


# -- IK ------------------------------------------------------------------------------------------------------------

def build_ik(nero):
    """The helper chains and controls of every limb; {limb: IK constraint}"""
    body = {j: b.name for j, b in _joints_of(nero).items()}
    rest = {b.name: b.matrix_local.copy() for b in nero.data.bones}
    root_motion = "root_motion" if "root_motion" in nero.data.bones else None
    sr._edit(nero)
    for limb, (parent, upper, lower, end, bend, holder) in LIMBS.items():
        u, e, w = (rest[body[j]].to_translation() for j in (upper, lower, end))
        e_bent = e + bend * PREBEND
        control = body[0] if holder == "root" else root_motion
        part, side = limb.split("_")[0], limb[-1]
        tip = "hand" if part == "arm" else "foot"
        sr._new_bone(nero, f"MCH-{part}_upper_{side}", head=u, tail=e_bent, parent=body[parent])
        sr._new_bone(nero, f"MCH-{part}_lower_{side}", head=e_bent, tail=w, parent=f"MCH-{part}_upper_{side}",
                     connect=True)
        sr._new_bone(nero, f"FOL-{part}_upper_{side}", matrix=rest[body[upper]], parent=f"MCH-{part}_upper_{side}")
        sr._new_bone(nero, f"FOL-{part}_lower_{side}", matrix=rest[body[lower]], parent=f"MCH-{part}_lower_{side}")
        sr._new_bone(nero, f"IK-{tip}_{side}", matrix=rest[body[end]], parent=control, length=0.1)
        pole = e + bend * POLE_DISTANCE
        sr._new_bone(nero, f"POLE-{limb}", head=pole, tail=pole + Vector((0, 0, 0.05)), parent=control)
    bpy.ops.object.mode_set(mode="OBJECT")
    ik = {}
    for limb in LIMBS:
        part, side = limb.split("_")[0], limb[-1]
        tip = "hand" if part == "arm" else "foot"
        con = nero.pose.bones[f"MCH-{part}_lower_{side}"].constraints.new("IK")
        con.name = RIG + "ik"
        con.target, con.subtarget = nero, f"IK-{tip}_{side}"
        con.pole_target, con.pole_subtarget = nero, f"POLE-{limb}"
        con.chain_count = 2
        con.use_stretch = False
        ik[limb] = con
        for name in (f"MCH-{part}_upper_{side}", f"MCH-{part}_lower_{side}", f"FOL-{part}_upper_{side}",
                     f"FOL-{part}_lower_{side}", f"IK-{tip}_{side}", f"POLE-{limb}"):
            nero.data.bones[name]["mtfw.not_joint"] = 1
    return ik


def calibrate_pole(ob, con, upper, lower):
    """the pole angle that leaves the helper chain on its rest pose with the controls at rest"""
    pu, pl = ob.pose.bones[upper], ob.pose.bones[lower]
    ru, rl = ob.data.bones[upper].matrix_local.to_quaternion(), ob.data.bones[lower].matrix_local.to_quaternion()

    def error(angle):
        con.pole_angle = angle
        bpy.context.view_layer.update()
        return (pu.matrix.to_quaternion().rotation_difference(ru).angle +
                pl.matrix.to_quaternion().rotation_difference(rl).angle)
    best = min((math.radians(a) for a in range(-180, 180, 5)), key=error)
    step = math.radians(2.5)
    while step > 1e-6:
        best = min((best - step, best, best + step), key=error)
        step *= 0.5
    con.pole_angle = best
    return error(best)


# -- removal (rebuilds) ---------------------------------------------------------------------------------------------

def remove(nero):
    if nero.animation_data is not None:
        for fc in list(nero.animation_data.drivers):
            if ".constraints[" in fc.data_path and RIG in fc.data_path:
                nero.animation_data.drivers.remove(fc)
    for pb in nero.pose.bones:
        for con in [c for c in pb.constraints if c.name.startswith(RIG)]:
            pb.constraints.remove(con)
    for name in [c.name for c in nero.data.collections_all if c.name in COLLECTIONS]:
        nero.data.collections.remove(nero.data.collections_all[name])
    if any(b.name.startswith(HELPER_PREFIXES) for b in nero.data.bones):
        sr._edit(nero)
        for eb in [e for e in nero.data.edit_bones if e.name.startswith(HELPER_PREFIXES)]:
            nero.data.edit_bones.remove(eb)
        bpy.ops.object.mode_set(mode="OBJECT")


# -- the build -----------------------------------------------------------------------------------------------------

def find_nero():
    return next((o for o in bpy.data.objects if o.get(MARK) == "nero"), None)


def _prop(ob, name, value, description, **limits):
    if name not in ob.keys():
        ob[name] = value
    ob.id_properties_ui(name).update(description=description, **limits)


def build():
    """Adds the controls (see the module docstring), importing everything first in an empty file; a list of notes"""
    joints, compat, _, display_vectors = sr._albam()
    notes = []
    nero = find_nero()
    if nero is None:
        nero = setup_file(notes)
    scene = bpy.context.scene
    keep_frame = scene.frame_current
    action = nero.animation_data.action if nero.animation_data else None
    remove(nero)
    compat.assign_action(nero, None)
    for pb in nero.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)

    for name in IK_PROPS:
        _prop(nero, name, 0.0, TIPS[name], min=0.0, max=1.0, soft_min=0.0, soft_max=1.0)
    _prop(nero, PLACE, 0, TIPS[PLACE], min=0, max=2)
    _prop(nero, GUN, False, TIPS[GUN])
    for name in GRIP_PROPS:
        _prop(nero, name, 1.0, TIPS[name], min=0.0, max=1.0, soft_min=0.0, soft_max=1.0)
    _prop(nero, FOLLOW_EVENTS, True, TIPS[FOLLOW_EVENTS])
    attach_weapons(nero, joints)
    build_grips(nero, compat, notes)

    ik = build_ik(nero)
    for limb, con in ik.items():
        part, side = limb.split("_")[0], limb[-1]
        err = calibrate_pole(nero, con, f"MCH-{part}_upper_{side}", f"MCH-{part}_lower_{side}")
        notes.append(f"pole angle {limb}: {math.degrees(con.pole_angle):.2f} deg (rest error {math.degrees(err):.4f} deg)")
    body = {j: b.name for j, b in _joints_of(nero).items()}
    for limb, (_, upper, lower, end, _, _) in LIMBS.items():
        part, side = limb.split("_")[0], limb[-1]
        tip = "hand" if part == "arm" else "foot"
        for joint, target in ((upper, f"FOL-{part}_upper_{side}"), (lower, f"FOL-{part}_lower_{side}"),
                              (end, f"IK-{tip}_{side}")):
            con = sr._copy_rotation(nero.pose.bones[body[joint]], nero, target)
            sr._drive(con, "ik", [("ik", nero, f'["ik_{limb}"]')])

    # display, collections, locks
    w = sr.widgets()
    coll = {n: nero.data.collections.new(n) for n in COLLECTIONS}
    for n in HIDDEN_COLLECTIONS:
        coll[n].is_visible = False
    game = {j: b for j, b in _joints_of(nero).items() if not joints.is_helper(b)}
    vectors = display_vectors(list(game.values()))
    for j, bone in game.items():
        pb = nero.pose.bones[bone.name]
        sr._colour(bone, bone.head_local.x)
        pb.lock_scale = (True, True, True)
        if j not in MOVABLE:
            pb.lock_location = (True, True, True)
        if j >= 200:
            coll["Twist"].assign(bone)
            continue
        if 100 <= j < 132:
            coll["Fingers.R" if j < 116 else "Fingers.L"].assign(bone)
            sr._shape(pb, bone, w["circle"], *FINGER[:3], vectors)
        elif j in SHAPES:
            coll[GROUPS.get(j, "Extras")].assign(bone)
            radius, along, direction, offset = SHAPES[j]
            sr._shape(pb, bone, w["circle"], radius, along, direction, vectors, offset)
        else:
            coll[GROUPS.get(j, "Extras")].assign(bone)
            sr._shape(pb, bone, w["circle"], *EXTRA[:3], vectors)
    for b in nero.data.bones:
        pb = nero.pose.bones[b.name]
        if b.name.startswith(("MCH-", "FOL-", GRIP)):
            coll["Mechanism"].assign(b)
        elif b.name.startswith("IK-"):
            coll["IK"].assign(b)
            sr._shape(pb, b, w["cube"], 0.1, 0.0, UP, {})
            pb.lock_scale = (True, True, True)
            b.color.palette = sr.LEFT if b.name.endswith("_l") else sr.RIGHT
        elif b.name.startswith("POLE-"):
            coll["IK"].assign(b)
            sr._shape(pb, b, w["diamond"], 0.04, 0.0, UP, {})
            pb.lock_rotation = pb.lock_scale = (True, True, True)
            b.color.palette = sr.LEFT if b.name.endswith("_l") else sr.RIGHT
        elif b.name == "root_motion":
            coll["Root"].assign(b)
            pb.custom_shape = w["root"]
            pb.use_custom_shape_bone_size = False
            pb.custom_shape_scale_xyz = (0.45, 0.45, 0.45)
            pb.custom_shape_rotation_euler = sr._orient(b, UP, FRONT)
            pb.custom_shape_translation = (0.0, 0.0, 0.0)
            b.color.palette = sr.CONTROL
    nero.show_in_front = True
    nero.data.display_type = "OCTAHEDRAL"

    compat.assign_action(nero, action)
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
    spec = importlib.util.spec_from_file_location("nero_rig_ui", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)   # registers its classes


if __name__ == "__main__":
    try:
        fresh = find_nero() is None and not bpy.data.filepath
        for note in build():
            print("nero rig:", note)
        if bpy.app.background:
            if fresh:
                os.makedirs(OUT, exist_ok=True)
                bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "nero_rig.blend"))
            elif bpy.data.filepath:
                bpy.ops.wm.save_mainfile()
            print("saved", bpy.data.filepath)
        print("DONE")
    except Exception:
        import traceback
        traceback.print_exc()
        if not bpy.app.background:
            raise
        sys.exit(1)
