"""DMC4 model chains (`.phs` / `.clt` = rCnsChain, XFS v5) import / export: soft-body joints of a model (coat tails,
hair). Not the effect chains: EFL LineType / ClothType CHAIN ropes are a separate system in the game (uEffectVFR
moveChain 0x994C20, cloth 0x992EC0, with their own parameters) and live in efl/sim.py; the two share no solver code
(callees checked 2026-10-10: only sqrt / sin / cos in common). The XFS format is the vendored dmc4xml package; the
runtime is in Vibed/RE/chain_cnschain.md (cCnsChain move 0x42DB00, solver 0x430A20).

A chain file is one set of soft-body settings over up to 32 slots of joints of the model it hangs on, -1 between
tendrils: usually one tendril (Nero's coat `pl000_03.mod` has six files, pl000_03_00..05.phs, one tail each), but
Sanctus' and Berial's files hold up to 7 (see _joint_list). Import makes an Empty `PHS_<file>` holding every setting as a custom
property (with a tooltip), finds the model's armature by itself (find_model_armature: an imported .mod named like the
chain without its `_NN` parts, pl000_03_00 -> pl000_03.mod, that has all the chain's joints; else the active
armature), parents the Empty to it and puts the chain's bones in a bone collection `Chain <file>`. Without a model the
chain waits; it attaches when the model is imported (wire_scene), or with Attach to Armature. Edit the settings in
Object Properties > Custom Properties, and the chain by adding or removing bones of that collection (32 slots at
most, separators included; see chain_joints for where new bones go).

Export writes the source file back with the new values (its XFS layout is kept, so untouched files come back
byte-identical). The per-bone limits (mBoneData, never enabled in the game's files) are kept as they are.

The motion preview (the game's solver on the armature while the animation plays) is cns_chain_preview.py.
"""
import bpy
from mathutils import Matrix

from dmc4xml import xfs as xfs_codec
from dmc4xml.dti import dti_name

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.vfs import VirtualFileData

JOINT_PROP = "mtfw.anim_retarget"     # bone property: the game joint number
ARMATURE_PROP = "phs_armature"        # Empty: the armature the chain was attached to
COLLECTION_PROP = "phs_collection"    # Empty: name of the bone collection holding the chain
JOINTS_PROP = "phs_joints"            # Empty: the chain's joint numbers (used without an armature)
MAX_JOINTS = 32
SPECIAL = ("mBone", "mBoneData")
AXES_DIR = "0 +X, 1 +Y, 2 -Z, 3 -X, 4 -Y, 5 -Z (the game has no +Z here: 2 is -Z too)"
AXES_UP = "0 +X, 1 +Y, 2 +Z, 3 -X, 4 -Y, 5 -Z"

# tooltips (Vibed/RE/chain_cnschain.md); units: game cm, one step per 60 fps frame
HELP = {
    "mQuality": "Simulation quality setting (2 in every game file)",
    "mBlend": "How much of the simulated motion is shown: 0 = the animation only, 1 = fully simulated (the game "
              "ramps toward this value)",
    "mDir": "Bone axis that points along the chain to the next joint: " + AXES_DIR,
    "mUp": "Bone axis kept close to the animated joint's (sets the twist): " + AXES_UP,
    "mTailLength": "Length (cm) of the extra segment after the last joint, along mDir",
    "mGravity": "Gravity (cm per frame squared, game axes: Y is up); in the parent's frame when mGravityLocal is on",
    "mSpring": "Pull back when a joint has moved beyond its bone length: velocity -= overshoot x this, every frame",
    "mDamping": "Velocity multiplier every frame (1 = no damping; values above 1 speed the chain up until mMaxSpeed "
                "stops it)",
    "mMaxSpeed": "Speed limit of a joint (cm per frame)",
    "mWind": "Constant wind (cm per frame squared, game axes); in the parent's frame when mWindLocal is on",
    "mTurbulence": "Random wind: (random - 0.5) x this per axis, re-rolled every frame. In the game it only shows when "
                   "frames run shorter than 1/60 s (slow motion): at full speed it's re-rolled before it's added",
    "mFloorLevel": "Floor height (cm, game Y) the joints stay above (-9999 = none); a joint that hits it loses most "
                   "of its speed (x mDamping x 0.1)",
    "mCollisionSize": "Radius (cm) of the chain's segments against the collision shapes (.col) of the body",
    "mStretch": "Let the chain stretch instead of keeping its bone lengths (mSpring pulls it back)",
    "mStretchLimit": "Longest a segment may get when mStretch is on, as a multiple of its bone length (negative = no "
                     "limit)",
    "mParentMode": "What carries the chain: 0 = the model's own world matrix, 1 = its parent unit's",
    "mPosLocal": "Carry the joints with the parent's movement (with mRotLocal: its full motion)",
    "mPosLocalY": "Carry the joints with the parent's vertical movement only",
    "mRotLocal": "Carry the joints with the parent's rotation",
    "mWindLocal": "Wind is given in the parent's frame (else world)",
    "mGravityLocal": "Gravity is given in the parent's frame (else world)",
}
ENUM_RANGES = {"mDir": (0, 5), "mUp": (0, 5), "mParentMode": (0, 1)}

# tooltips for Albam's own bookkeeping properties on chain Empties and collision shape objects (apply_tips)
_INTERNAL = "Albam internal, don't edit: "
INTERNAL_TIPS = {
    "phs_name": _INTERNAL + "the name this chain Empty was made with (a Shift+D copy has another name and becomes a "
                            "new chain)",
    "phs_armature": _INTERNAL + "the armature the chain is attached to (change it with Attach to Armature)",
    "phs_collection": _INTERNAL + "the bone collection holding the chain's bones (edit the bones in it instead)",
    "phs_model": "Game path of the model the chain belongs to (found next to the chain in the Game Files); its "
                 "imported armature is the one the chain attaches to",
    "phs_missing_joints": "Joint numbers of this chain that its armature doesn't have (kept in the file as they are)",
    "phs_status": "What's still missing for this chain (also shown in the Chain panel)",
    "phs_export_notes": "What the last export changed in the file",
    "col_root": _INTERNAL + "the collision shape file (COL_ Empty) this object belongs to",
    "col_kind": _INTERNAL + "what this object is in the file: sphere, capsule end a / b, or tube (display only)",
    "col_capsule": _INTERNAL + "key shared by a capsule's two ends and its tube",
    "col_name": _INTERNAL + "the name this shape object was made with (a Shift+D copy has another name and becomes "
                            "a new shape)",
    "col_src": _INTERNAL + "group and index of the shape in the source file (exported in that place)",
    "col_radius": _INTERNAL + "radius (cm) at the last sync, to tell which end of a capsule was resized",
    "col_unbuilt": _INTERNAL + "source shapes that have no objects (type 1, or joints the armature lacks): kept as "
                               "they are",
    "col_built": _INTERNAL + "the file's shapes are objects (until then export keeps the source's shapes)",
    "col_missing_joints": "Joint numbers the file's shapes use that the armature doesn't have (those shapes are "
                          "kept as they are)",
}


def apply_tips(ob):
    """give ob's Albam bookkeeping properties their tooltips (types Blender can't describe are skipped)"""
    for key, text in INTERNAL_TIPS.items():
        if key in ob:
            try:
                ob.id_properties_ui(key).update(description=text)
            except TypeError:
                pass


def _joint_bones(armature):
    out = {}
    if armature is not None:
        for bone in armature.data.bones:
            joint = bone.get(JOINT_PROP)
            if joint is not None:
                out.setdefault(int(joint), bone)
    return out


def _stem(path):
    return path.replace("/", "\\").rsplit("\\", 1)[-1].split(".")[0].lower()


def model_armatures(scene):
    """imported .mod armatures in the scene"""
    return [ob for ob in scene.objects if ob.type == "ARMATURE" and ob.albam_asset.extension == "mod"]


def _active_armature(context):
    ob = getattr(context, "active_object", None)
    while ob is not None and ob.type != "ARMATURE":
        ob = ob.parent
    return ob


def find_model_armature(context, stems, joints, directory="", allow_active=True, partial=False):
    """The armature a file's joint numbers belong to: the first imported .mod whose file name (no extension, any
    case) is in stems, in that order, and has every joint (one in the same folder wins a tie); else, with
    allow_active, the active armature if it has them; else None. Models of one character share joint numbers (the
    coat pl000_03.mod has the body's 0-38), so a file whose model is known must not fall back to another one.
    With partial, a model with only some of the joints will do (the one with the most): a hitbox file may name
    joints its model doesn't have; those shapes are skipped and listed."""
    need = set(int(j) for j in joints)

    def fits(ob):
        have = need & set(_joint_bones(ob))
        return (len(have), have == need) if partial else (len(have), True) if have == need else None

    models = model_armatures(context.scene)
    directory = directory.lower()
    for stem in stems:
        found = [ob for ob in models if _stem(ob.albam_asset.relative_path) == stem.lower()]
        found = [ob for ob in found if fits(ob) is not None and (fits(ob)[0] or not need)]
        if found:
            # most joints, then same folder
            return max(found, key=lambda ob: (fits(ob), ob.albam_asset.relative_path.lower().rpartition("\\")[0]
                                              == directory))
    active = _active_armature(context) if allow_active else None
    if active is not None and fits(active) is not None and (fits(active)[0] or not need):
        return active
    return None


def chain_model_stems(relative_path):
    """pl000_03_00 -> [pl000_03_00, pl000_03, pl000]: the chain's own name, then without its _NN parts"""
    parts = _stem(relative_path).split("_")
    return ["_".join(parts[:k]) for k in range(len(parts), 0, -1)]


def _folder(relative_path):
    return relative_path.replace("/", "\\").rpartition("\\")[0]


def game_file_exists(context, path):
    try:
        context.scene.albam.rfs.get_vfile("dmc4", path)
    except (KeyError, AttributeError):
        return False
    return True


def chain_model_path(context, relative_path):
    """Game path of the model a chain belongs to: the first <name>.mod in the chain's folder (pl000_03_00 ->
    pl000_03.mod, not the body pl000.mod, which has the same joint numbers), or "" if none is in the Game Files."""
    folder = _folder(relative_path)
    for stem in chain_model_stems(relative_path):
        path = f"{folder}\\{stem}.mod" if folder else f"{stem}.mod"
        if game_file_exists(context, path):
            return path
    return ""


def find_chain_armature(context, ob):
    model = ob.get("phs_model", "")
    stems = [_stem(model)] if model else chain_model_stems(ob.albam_asset.relative_path)
    joints = [j for j in ob.get(JOINTS_PROP, []) if j >= 0]
    return find_model_armature(context, stems, joints, _folder(ob.albam_asset.relative_path), allow_active=not model)


def attach_chain(ob, armature, load_bones=True):
    """Put chain Empty ob on armature: parent, bone collection `Chain <file>` with the chain's bones (the old one, on
    the previous armature, is removed). Returns the joints the armature doesn't have."""
    old = chain_armature(ob)
    if old is not None:
        coll = old.data.collections.get(ob.get(COLLECTION_PROP, ""))
        if coll is not None:
            old.data.collections.remove(coll)
    joints = [int(j) for j in ob.get(JOINTS_PROP, []) if j >= 0]
    ob.parent = armature
    ob.matrix_parent_inverse = Matrix.Identity(4)
    ob[ARMATURE_PROP] = armature
    stem = ob.name[4:] if ob.name.startswith("PHS_") else ob.name
    coll = armature.data.collections.new(f"Chain {stem}")
    ob[COLLECTION_PROP] = coll.name
    bones = _joint_bones(armature)
    missing = []
    for j in joints:
        if j in bones:
            coll.assign(bones[j])
        else:
            missing.append(j)
    if missing:
        ob["phs_missing_joints"] = missing
    elif "phs_missing_joints" in ob:
        del ob["phs_missing_joints"]
    if load_bones:
        load_bone_data(ob, armature)
    apply_tips(ob)
    return missing


def _root_object(x):
    root = x.root
    if dti_name(x.layouts[root.layout].dti) != "rCnsChain":
        raise AlbamCheckFailure("Not a chain file", details=f"Its object is {dti_name(x.layouts[root.layout].dti)}.",
                                solution="Import a .phs / .clt chain (rCnsChain).")
    return root, x.layouts[root.layout]


def _load(file_item, context):
    ob = build_chain_object(file_item.get_bytes(), file_item.display_name.split(".")[0], file_item.app_id,
                            file_item.relative_path, file_item.extension, context,
                            chain_model_path(context, file_item.relative_path))
    armature = find_chain_armature(context, ob)
    if armature is not None:
        attach_chain(ob, armature)
    from albam.engines.mtfw.cns_chain_preview import wire_scene
    wire_scene(context)
    return None     # linked already (the importer links returned objects again)


NAME_PROP = "phs_name"          # the Empty's name when made: a Shift+D copy has another name (a new chain)


def build_chain_object(data, stem, app_id, relative_path, extension, context, model_path=""):
    """chain file bytes -> the Empty `PHS_<stem>` with its settings, linked and in the export list (not attached)"""
    try:
        x = xfs_codec.read(data)
    except xfs_codec.XfsError as err:
        raise AlbamCheckFailure("Can't read this chain file", details=str(err),
                                solution="Only DX9 DMC4 chains (XFS version 5) are supported.")
    root, layout = _root_object(x)

    ob = bpy.data.objects.new(f"PHS_{stem}", None)
    ob.empty_display_type = "PLAIN_AXES"
    ob.empty_display_size = 0.1
    joints = []
    for prop, items in zip(layout.props, root.values):
        if prop.name == "mBone":
            joints = _joint_list(v for (_, v) in (xfs_codec.item_value(prop, raw) for raw in items))
            continue
        if prop.name in SPECIAL or len(items) != 1 or prop.type in xfs_codec.OBJECT_TYPES:
            continue
        kind, value = xfs_codec.item_value(prop, items[0])
        if kind == "scalar":
            ob[prop.name] = bool(value) if prop.type == 0x3 else value
        elif kind == "floats":
            ob[prop.name] = list(value[:3])
        else:
            continue
        ui = ob.id_properties_ui(prop.name)
        extra = {}
        if prop.name in ENUM_RANGES:
            extra = {"min": ENUM_RANGES[prop.name][0], "max": ENUM_RANGES[prop.name][1]}
        ui.update(description=HELP.get(prop.name, prop.name), **extra)
    ob[JOINTS_PROP] = joints
    ob.id_properties_ui(JOINTS_PROP).update(
        description="The chain's slots: joint numbers root to tip, -1 between tendrils (one file can hold several). "
                    "Read from the bone collection on export when the chain has an armature; edit this list only for "
                    "a chain without one")
    ob["phs_model"] = model_path or ""
    ob.id_properties_ui("phs_model").update(
        description="Game path of the model the chain belongs to (found in the Game Files next to the chain; empty "
                    "if it isn't there). Its imported armature is the one the chain attaches to")

    ob.albam_asset.original_bytes = data
    ob.albam_asset.app_id = app_id
    ob.albam_asset.relative_path = relative_path
    ob.albam_asset.extension = extension
    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = ob
    context.scene.albam.exportable.file_list.update()
    context.collection.objects.link(ob)
    ob[NAME_PROP] = ob.name
    apply_tips(ob)
    return ob


# ---- new chains ----------------------------------------------------------------------------------------------------

# rCnsChain::setDefault 0x466250 (Vibed/RE/chain_cnschain.md section 2); mQuality isn't set there: 2 in every file
DEFAULTS = {"mBlend": 1.0, "mDir": 4, "mUp": 2, "mTailLength": 10.0, "mGravity": [0.0, -1.0, 0.0],
            "mWind": [0.0, 0.0, 0.0], "mTurbulence": 0.0, "mSpring": 0.01, "mDamping": 0.98, "mMaxSpeed": 10.0,
            "mFloorLevel": -9999.0, "mStretch": False, "mStretchLimit": 100.0, "mCollisionSize": 5.0,
            "mParentMode": 0, "mPosLocal": False, "mPosLocalY": False, "mRotLocal": False, "mWindLocal": False,
            "mGravityLocal": False}


def template_bytes(context):
    """bytes of any chain file to build a new one on (the XFS layout of rCnsChain): an imported chain's source, else
    the first .phs / .clt in the Game Files; None without any"""
    for ob in bpy.data.objects:
        if ob.albam_asset.extension in ("phs", "clt") and ob.albam_asset.original_bytes:
            return bytes(ob.albam_asset.original_bytes)
    for item in context.scene.albam.rfs.file_list:
        if item.name.lower().endswith((".phs", ".clt")) and not item.is_expandable:
            try:
                return bytes(item.get_bytes())
            except Exception:           # noqa: BLE001 - try the next one
                continue
    return None


def next_chain_path(context, model_path, extension="phs"):
    """<model folder>\\<model>_NN.<extension> with the first NN no chain in the scene or the Game Files uses"""
    folder, stem = _folder(model_path), _stem(model_path) if model_path else "chain"
    taken = {ob.albam_asset.relative_path.lower() for ob in bpy.data.objects
             if ob.albam_asset.extension in ("phs", "clt")}
    for n in range(100):
        path = f"{folder}\\{stem}_{n:02d}.{extension}" if folder else f"{stem}_{n:02d}.{extension}"
        if path.lower() not in taken and not game_file_exists(context, path):
            return path
    return f"{folder}\\{stem}_new.{extension}"


def new_chain(context, armature, bones, path, settings=None):
    """a new chain Empty on armature over bones (parents first), its file at path: the template's XFS layout with
    the game's defaults (or `settings`, e.g. a duplicated chain's), written by the exporter like any chain"""
    data = template_bytes(context)
    if data is None:
        raise AlbamCheckFailure("No chain file to build on", details="A new chain uses the layout of an existing one.",
                                solution="Add a Game Files folder that has a .phs (e.g. a player's model folder), or "
                                         "import any chain first.")
    joints = slots_from_bones(armature, bones)
    if not joints:
        raise AlbamCheckFailure("No joints for the chain", details="The selected bones have no joint numbers.",
                                solution="Select the model's bones (they carry mtfw.anim_retarget).")
    if len(joints) > MAX_JOINTS:
        raise AlbamCheckFailure("Too many bones", details=f"{len(joints)} slots (bones plus one -1 between "
                                                          f"tendrils); a chain holds 32 at most.",
                                solution="Select fewer bones, or make two chains.")
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else "phs"
    ob = build_chain_object(data, _stem(path), "dmc4", path, ext if ext in ("phs", "clt") else "phs", context,
                            armature.albam_asset.relative_path)
    for key, value in (settings or DEFAULTS).items():
        if key in ob:
            ob[key] = value
    ob[JOINTS_PROP] = joints
    attach_chain(ob, armature, load_bones=False)        # the template's per-slot data isn't this chain's
    return ob


@blender_registry.register_import_function(app_id="dmc4", extension="phs", file_category="CHAIN")
def load_phs(file_item, context):
    return _load(file_item, context)


@blender_registry.register_import_function(app_id="dmc4", extension="clt", file_category="CHAIN")
def load_clt(file_item, context):
    return _load(file_item, context)


# ---- export ------------------------------------------------------------------------------------------------------

def chain_armature(ob):
    arm = ob.get(ARMATURE_PROP)
    if isinstance(arm, bpy.types.Object) and arm.type == "ARMATURE":
        return arm
    return ob.parent if ob.parent is not None and ob.parent.type == "ARMATURE" else None


SEPARATOR = -1


def _joint_list(values):
    """mBone items -> the chain's slot list: joint numbers, with -1 between tendrils, trailing -1 dropped. The game
    registers every slot that isn't -1 (cCnsChain::move 0x42DE20 walks all 32), a joint followed by -1 is the tip of
    its tendril (virtual tail) and one after a -1 is a tendril root (keeps its animated position), so one file can
    hold several tendrils: Sanctus pl023_02_007 holds 7, Berial em018_00 3, Nero's coat files 1 each."""
    out = [int(v) if v >= 0 else SEPARATOR for v in values]
    while out and out[-1] < 0:
        out.pop()
    return out


def _normalize(slots):
    """no leading, doubled or trailing separators (no empty tendrils)"""
    out = []
    for j in slots:
        if j < 0 and (not out or out[-1] < 0):
            continue
        out.append(j)
    while out and out[-1] < 0:
        out.pop()
    return out


def tendrils(slots):
    """[[joint, ...], ...] of a slot list"""
    out, cur = [], []
    for j in slots:
        if j < 0:
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(j)
    if cur:
        out.append(cur)
    return out


def slots_from_bones(armature, bones):
    """slot list for a set of bones: armature order (parents first); a bone continues the tendril if its parent is
    the slot before it, else a new tendril starts (-1)"""
    order = {b.name: i for i, b in enumerate(armature.data.bones)}
    slots, previous = [], None
    for b in sorted(bones, key=lambda b: order[b.name]):
        if b.get(JOINT_PROP) is None:
            continue
        if slots and b.parent != previous:
            slots.append(SEPARATOR)
        slots.append(int(b[JOINT_PROP]))
        previous = b
    return slots


def chain_joints(ob, problems):
    """The chain's slot list (joints, -1 between tendrils): from the bone collection when the chain has an armature,
    else the property. Bones still in the collection keep their slots and tendrils; a removed bone's slot goes (an
    emptied tendril with it); a new bone extends its parent's tendril when the parent is that tendril's tip, else
    starts a new tendril at the end (a branch, or a bone whose parent isn't in the chain)."""
    source = _normalize([int(j) for j in ob.get(JOINTS_PROP, [])])
    arm = chain_armature(ob)
    coll = arm.data.collections.get(ob.get(COLLECTION_PROP, "")) if arm is not None else None
    if coll is None:
        return source
    by_joint = {}
    for b in coll.bones:
        if b.get(JOINT_PROP) is None:
            problems.append(f"bone {b.name} has no joint number ({JOINT_PROP})")
            return source
        by_joint[int(b[JOINT_PROP])] = b
    if not by_joint:
        problems.append(f"bone collection {coll.name} is empty")
        return source
    slots = _normalize([j for j in source if j < 0 or j in by_joint])
    new = sorted((j for j in by_joint if j not in slots), key=lambda j: len(by_joint[j].parent_recursive))
    for j in new:
        parent = by_joint[j].parent
        pj = int(parent[JOINT_PROP]) if parent is not None and parent.get(JOINT_PROP) is not None else None
        if pj in slots:
            k = slots.index(pj) + 1
            if k == len(slots) or slots[k] < 0:
                slots.insert(k, j)                  # the parent is a tip: the tendril grows
                continue
        slots += ([SEPARATOR] if slots else []) + [j]
    return slots


# ---- per-bone limits (mBoneData) and tendril roots -----------------------------------------------------------------
#
# rCnsChain mBoneData = 32 cBONE_DATA, one per slot (createProperty 0x4665B0): +4 mBoneAdjustGrid (the bone axis the
# limits measure: 0 X, 1 Y, 2 Z), +8 mBoneAdjust (on / off), MinX / MinY / MinZ +0xC..0x14, MaxX / MaxY / MaxZ
# +0x18..0x20, degrees. Every one of the 1,312 entries in the DX9 files is grid 2, off, zeros. In Blender they're on
# the pose bone (`albam_chain`), so they follow the bone when slots move; export writes them into its slot.

BONE_FIELDS = ("mBoneAdjustGrid", "mBoneAdjust", "mBoneAdjustMinX", "mBoneAdjustMaxX", "mBoneAdjustMinY",
               "mBoneAdjustMaxY", "mBoneAdjustMinZ", "mBoneAdjustMaxZ")
AXES = (("0", "X", "Measure the bone's X axis: limits its Y and Z angles"),
        ("1", "Y", "Measure the bone's Y axis: limits its X and Z angles"),
        ("2", "Z", "Measure the bone's Z axis: limits its X and Y angles (the value in every game file)"))


def _chains_with_bone(pose_bone):
    arm = pose_bone.id_data
    joint = pose_bone.bone.get(JOINT_PROP)
    if joint is None:
        return []
    out = []
    for ob in bpy.data.objects:
        if ob.type == "EMPTY" and ob.albam_asset.extension in ("phs", "clt") and ob.users_collection and \
                chain_armature(ob) == arm and int(joint) in chain_joints(ob, []):
            out.append(ob)
    return out


def _owner(group):
    """the pose bone an albam_chain group belongs to (path_from_id isn't supported on pose bone groups)"""
    ptr = group.as_pointer()
    return next((pb for pb in group.id_data.pose.bones if pb.albam_chain.as_pointer() == ptr), None)


def _get_root(self):
    pb = _owner(self)
    chains = _chains_with_bone(pb) if pb is not None else []
    if not chains:
        return False
    slots = chain_joints(chains[0], [])
    i = slots.index(int(pb.bone[JOINT_PROP]))
    return i == 0 or slots[i - 1] < 0


def _set_root(self, value):
    pb = _owner(self)
    if pb is None:
        return
    for ob in _chains_with_bone(pb):
        slots = chain_joints(ob, [])
        i = slots.index(int(pb.bone[JOINT_PROP]))
        if value and i > 0 and slots[i - 1] >= 0:
            slots.insert(i, SEPARATOR)          # this bone starts a tendril; the one before it becomes a tip
        elif not value and i > 0 and slots[i - 1] < 0:
            del slots[i - 1]                    # merge into the tendril before
        ob[JOINTS_PROP] = _normalize(slots)


@blender_registry.register_blender_props_to_type("PoseBone", "albam_chain")
class AlbamChainBone(bpy.types.PropertyGroup):
    root: bpy.props.BoolProperty(
        name="Tendril Root", get=_get_root, set=_set_root,
        description="This bone starts a tendril of its chain: it keeps its animated position, and the bone before "
                    "it (if any) becomes a tip with a virtual tail. Off: it continues the tendril before it")
    adjust: bpy.props.BoolProperty(
        name="Limit Angles",
        description="mBoneAdjust: clamp this bone's angles (measured in its parent's frame) to the ranges below, "
                    "before and after the blend with the animation. No game file turns it on")
    grid: bpy.props.EnumProperty(
        name="Measured Axis", items=AXES, default="2",
        description="mBoneAdjustGrid: which of the bone's axes the limits measure (the axis the bone points along)")
    limit_min: bpy.props.FloatVectorProperty(
        name="Min", size=3, subtype="XYZ",
        description="mBoneAdjustMinX / Y / Z, degrees (which two are used depends on the measured axis)")
    limit_max: bpy.props.FloatVectorProperty(
        name="Max", size=3, subtype="XYZ",
        description="mBoneAdjustMaxX / Y / Z, degrees (which two are used depends on the measured axis)")


def _bone_data_value(x, obj):
    sub = x.layouts[obj.layout]
    out = {}
    for sp, items in zip(sub.props, obj.values):
        if sp.name in BONE_FIELDS and len(items) == 1:
            out[sp.name] = xfs_codec.item_value(sp, items[0])[1]
    return out


def _bone_props_from(pb, vals):
    s = pb.albam_chain
    s.grid = str(int(vals.get("mBoneAdjustGrid", 2)) if int(vals.get("mBoneAdjustGrid", 2)) in (0, 1, 2) else 2)
    s.adjust = bool(vals.get("mBoneAdjust", 0))
    s.limit_min = [vals.get(f"mBoneAdjustMin{a}", 0.0) for a in "XYZ"]
    s.limit_max = [vals.get(f"mBoneAdjustMax{a}", 0.0) for a in "XYZ"]


def load_bone_data(ob, armature):
    """put the file's per-slot bone data on the chain's pose bones"""
    data = bytes(ob.albam_asset.original_bytes)
    if not data:
        return
    x = xfs_codec.read(data)
    root, layout = _root_object(x)
    items = next((it for p, it in zip(layout.props, root.values) if p.name == "mBoneData"), [])
    bones = _joint_bones(armature)
    for slot, joint in enumerate(_joint_list(xfs_codec.item_value(p, r)[1]
                                             for p, it in zip(layout.props, root.values) if p.name == "mBone"
                                             for r in it)):
        if joint >= 0 and joint in bones and slot < len(items) and not isinstance(items[slot], (bytes, bytearray)):
            _bone_props_from(armature.pose.bones[bones[joint].name], _bone_data_value(x, items[slot]))


def bone_limits(pose_bone):
    """(grid, (minX, minY, minZ), (maxX, maxY, maxZ)) in degrees, or None when off"""
    s = pose_bone.albam_chain
    return (int(s.grid), tuple(s.limit_min), tuple(s.limit_max)) if s.adjust else None


def _write_bone_data(x, items, slots, armature, problems):
    """write the pose bones' limits into the slots they occupy now (other slots: grid 2, off, zeros); returns
    whether anything changed"""
    bones = _joint_bones(armature)
    changed = False
    for slot, obj in enumerate(items):
        if isinstance(obj, (bytes, bytearray)):
            continue
        joint = slots[slot] if slot < len(slots) else SEPARATOR
        if joint >= 0 and joint in bones:
            s = armature.pose.bones[bones[joint].name].albam_chain
            want = {"mBoneAdjustGrid": int(s.grid), "mBoneAdjust": int(s.adjust),
                    **{f"mBoneAdjustMin{a}": float(v) for a, v in zip("XYZ", s.limit_min)},
                    **{f"mBoneAdjustMax{a}": float(v) for a, v in zip("XYZ", s.limit_max)}}
        else:
            want = {"mBoneAdjustGrid": 2, "mBoneAdjust": 0,
                    **{f"mBoneAdjust{m}{a}": 0.0 for m in ("Min", "Max") for a in "XYZ"}}
        sub = x.layouts[obj.layout]
        for k, (sp, its) in enumerate(zip(sub.props, obj.values)):
            if sp.name not in want or len(its) != 1:
                continue
            kind, old = xfs_codec.item_value(sp, its[0])
            new = want[sp.name]
            if isinstance(old, float) and abs(old - new) <= 1e-6:
                continue
            if not isinstance(old, float) and int(old) == int(new):
                continue
            obj.values[k] = [xfs_codec.item_bytes(sp, "scalar", bool(new) if sp.type == 0x3 else new)]
            changed = True
    return changed


def build_phs(ob):
    """Chain Empty -> (bytes, notes)"""
    x = xfs_codec.read(bytes(ob.albam_asset.original_bytes))
    root, layout = _root_object(x)
    problems, notes = [], []
    for i, (prop, items) in enumerate(zip(layout.props, root.values)):
        if prop.name == "mBone":
            joints = chain_joints(ob, problems)
            old = [v for (_, v) in (xfs_codec.item_value(prop, raw) for raw in items)]
            if len(joints) > len(old):
                problems.append(f"{len(joints)} slots with the -1 between tendrils ({len(old)} at most)")
                continue
            if joints == _normalize(_joint_list(old)):
                continue                            # unchanged: keep the source list as it is
            new = joints + [-1] * (len(old) - len(joints))
            notes.append(f"chain joints {tendrils(_joint_list(old))} -> {tendrils(joints)}")
            root.values[i] = [xfs_codec.item_bytes(prop, "scalar", v) for v in new]
            continue
        if prop.name in SPECIAL or prop.name not in ob or len(items) != 1:
            continue
        kind, old = xfs_codec.item_value(prop, items[0])
        value = ob[prop.name]
        if kind == "scalar":
            if prop.name in ENUM_RANGES and not ENUM_RANGES[prop.name][0] <= int(value) <= ENUM_RANGES[prop.name][1]:
                problems.append(f"{prop.name} = {value} (allowed {ENUM_RANGES[prop.name][0]}-{ENUM_RANGES[prop.name][1]})")
                continue
            new = xfs_codec.item_bytes(prop, "scalar", int(value) if prop.type != 0xC and prop.type != 0xD else float(value))
        elif kind == "floats":
            v = [float(c) for c in value]
            if len(v) != 3:
                problems.append(f"{prop.name} needs 3 numbers")
                continue
            if all(abs(a - b) <= 1e-7 * max(1.0, abs(b)) for a, b in zip(v, old[:3])):
                continue
            new = xfs_codec.item_bytes(prop, "floats", v + list(old[3:]))
        else:
            continue
        if new != items[0]:
            root.values[i] = [new]
            notes.append(f"{prop.name} changed")
    arm = chain_armature(ob)
    if arm is not None and not problems:
        bone_items = next((it for p, it in zip(layout.props, root.values) if p.name == "mBoneData"), [])
        if _write_bone_data(x, bone_items, chain_joints(ob, []), arm, problems):
            notes.append("per-bone limits (mBoneData) changed")
    if problems:
        raise AlbamCheckFailure(f"Chain {ob.name} can't be exported", details="\n".join(problems),
                                solution="Fix the listed settings / the chain's bone collection.")
    return xfs_codec.write(x), notes


def _export(bl_obj):
    data, notes = build_phs(bl_obj)
    asset = bl_obj.albam_asset
    print(f"PHS export {asset.relative_path}: {len(notes)} change(s)")
    for note in notes:
        print("  " + note)
    bl_obj["phs_export_notes"] = "\n".join(notes[:100])
    apply_tips(bl_obj)
    return [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]


@blender_registry.register_export_function(app_id="dmc4", extension="phs")
def export_phs(bl_obj):
    return _export(bl_obj)


@blender_registry.register_export_function(app_id="dmc4", extension="clt")
def export_clt(bl_obj):
    return _export(bl_obj)
