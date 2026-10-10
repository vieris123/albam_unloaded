"""DMC4 model chains (`.phs` / `.clt` = rCnsChain, XFS v5) import / export: soft-body joints of a model (coat tails,
hair). Not the effect chains: EFL LineType / ClothType CHAIN ropes are a separate system in the game (uEffectVFR
moveChain 0x994C20, cloth 0x992EC0, with their own parameters) and live in efl/sim.py; the two share no solver code
(callees checked 2026-10-10: only sqrt / sin / cos in common). The XFS format is the vendored dmc4xml package; the
runtime is in Vibed/RE/chain_cnschain.md (cCnsChain move 0x42DB00, solver 0x430A20).

A chain file is one soft-body chain: up to 32 joints of the model it hangs on (Nero's coat `pl000_03.mod` has six:
pl000_03_00..05.phs), plus physics settings. Import makes an Empty `PHS_<file>` holding every setting as a custom
property (with a tooltip), finds the model's armature by itself (find_model_armature: an imported .mod named like the
chain without its `_NN` parts, pl000_03_00 -> pl000_03.mod, that has all the chain's joints; else the active
armature), parents the Empty to it and puts the chain's bones in a bone collection `Chain <file>`. Without a model the
chain waits; it attaches when the model is imported (wire_scene), or with Attach to Armature. Edit the settings in
Object Properties > Custom Properties, and the chain by adding or removing bones of that collection (32 at most;
parents before children, new bones go after their parent).

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
    return find_model_armature(context, stems, ob.get(JOINTS_PROP, []), _folder(ob.albam_asset.relative_path),
                               allow_active=not model)


def attach_chain(ob, armature):
    """Put chain Empty ob on armature: parent, bone collection `Chain <file>` with the chain's bones (the old one, on
    the previous armature, is removed). Returns the joints the armature doesn't have."""
    old = chain_armature(ob)
    if old is not None:
        coll = old.data.collections.get(ob.get(COLLECTION_PROP, ""))
        if coll is not None:
            old.data.collections.remove(coll)
    joints = [int(j) for j in ob.get(JOINTS_PROP, [])]
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
    return missing


def _root_object(x):
    root = x.root
    if dti_name(x.layouts[root.layout].dti) != "rCnsChain":
        raise AlbamCheckFailure("Not a chain file", details=f"Its object is {dti_name(x.layouts[root.layout].dti)}.",
                                solution="Import a .phs / .clt chain (rCnsChain).")
    return root, x.layouts[root.layout]


def _load(file_item, context):
    data = file_item.get_bytes()
    try:
        x = xfs_codec.read(data)
    except xfs_codec.XfsError as err:
        raise AlbamCheckFailure("Can't read this chain file", details=str(err),
                                solution="Only DX9 DMC4 chains (XFS version 5) are supported.")
    root, layout = _root_object(x)
    stem = file_item.display_name.split(".")[0]

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
        description="The chain's joint numbers, root to tip (read from the bone collection on export when the chain "
                    "has an armature; edit this list only for a chain without one)")
    ob["phs_model"] = chain_model_path(context, file_item.relative_path)
    ob.id_properties_ui("phs_model").update(
        description="Game path of the model the chain belongs to (found in the Game Files next to the chain; empty "
                    "if it isn't there). Its imported armature is the one the chain attaches to")

    ob.albam_asset.original_bytes = data
    ob.albam_asset.app_id = file_item.app_id
    ob.albam_asset.relative_path = file_item.relative_path
    ob.albam_asset.extension = file_item.extension
    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = ob
    context.scene.albam.exportable.file_list.update()
    context.collection.objects.link(ob)
    armature = find_chain_armature(context, ob)
    if armature is not None:
        attach_chain(ob, armature)
    from albam.engines.mtfw.cns_chain_preview import wire_scene
    wire_scene(context)
    return None     # linked above (the importer links returned objects again)


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


def _joint_list(values):
    """mBone items -> joint numbers up to the first -1 (the files may hold leftovers after it)"""
    out = []
    for v in values:
        if v < 0:
            break
        out.append(v)
    return out


def chain_joints(ob, problems):
    """Joint numbers in file order: from the bone collection when the chain has an armature, else the property.
    A chain is a set of joints in a fixed order, not always one line: Sanctus' pl023 chains hold several strands or
    branch (pl023_02_028: 28-42, then 46-48, then 43-45). Bones still in the collection keep the source order; a
    new bone goes right after its parent (or at the end), so parents always come first."""
    source = [int(j) for j in ob.get(JOINTS_PROP, [])]
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
    order = [j for j in source if j in by_joint]
    new = sorted((j for j in by_joint if j not in order), key=lambda j: len(by_joint[j].parent_recursive))
    for j in new:
        parent = by_joint[j].parent
        pj = int(parent[JOINT_PROP]) if parent is not None and parent.get(JOINT_PROP) is not None else None
        if pj in order:
            k = order.index(pj) + 1
            while k < len(order) and pj in [int(p[JOINT_PROP]) for p in by_joint[order[k]].parent_recursive
                                             if p.get(JOINT_PROP) is not None]:
                k += 1                              # after the parent's existing descendants
            order.insert(k, j)
        else:
            order.append(j)
    return order


def build_phs(ob):
    """Chain Empty -> (bytes, notes)"""
    x = xfs_codec.read(bytes(ob.albam_asset.original_bytes))
    root, layout = _root_object(x)
    problems, notes = [], []
    for i, (prop, items) in enumerate(zip(layout.props, root.values)):
        if prop.name == "mBone":
            joints = chain_joints(ob, problems)
            if len(joints) > MAX_JOINTS:
                problems.append(f"{len(joints)} joints (32 at most)")
                continue
            old = [v for (_, v) in (xfs_codec.item_value(prop, raw) for raw in items)]
            if joints == _joint_list(old):
                continue                            # unchanged: keep the source list, leftovers included
            new = joints + [-1] * (len(old) - len(joints))
            notes.append(f"chain joints {_joint_list(old)} -> {joints}")
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
    bl_obj["phs_export_notes"] = notes[:100]
    return [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]


@blender_registry.register_export_function(app_id="dmc4", extension="phs")
def export_phs(bl_obj):
    return _export(bl_obj)


@blender_registry.register_export_function(app_id="dmc4", extension="clt")
def export_clt(bl_obj):
    return _export(bl_obj)
