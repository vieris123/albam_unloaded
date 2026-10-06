"""Spawn filter: which records of an effect the game builds for one spawn call (efl_import_plan.md 3.2).

The game builds a record only when (gen GroupFlag & group mask) and (gen MaterialFlag & material mask) are both
non-zero (uEffectVFR::matchGeneratorFilter 0x9DD560). The two masks come from the spawn call
(sDevil4Effect::setEffectConst / SetEffectStay): the group mask picks a variant of the effect, the material mask is
the ground surface under the character (cUtil::getEfctMtrlFlg 0x45F780). If no record passes, nothing is shown.

Every record is still imported (export needs them all); records that don't pass get their particle and shape
objects hidden (their Empty stays, so they can still be edited). The masks are stored on the effect root as
efl_group_mask / efl_material_mask.
"""
import bpy

from .effect_export import all_record_objects

ALL = 0xFFFFFFFF
GROUP_BITS = 16          # GroupFlag bits used in the DX9 files go up to 0x200
GROUP_KEY = "efl_group_mask"
MATERIAL_KEY = "efl_material_mask"
HIDDEN_KEY = "efl_filter_hidden"   # on hidden objects: their own (hide_viewport, hide_render) before the filter

GROUP_DESCRIPTION = (
    "Which variant of the effect to show, as the game's spawn call picks it. A record plays only if its "
    "generator's GroupFlag shares a bit with this mask. Most calls pass All. Some pick a bit: e.g. Dante's "
    "Gilgamesh attacks pass 7 (bits 1, 2 and 4) or 3 (bits 1 and 2). Look at the records' GroupFlag values "
    "(Effect Editor, Generator tab) to see which bits an effect uses")
GROUP_ALL_DESCRIPTION = (
    "Show the records of every group (mask 0xFFFFFFFF, what most of the game's spawn calls pass). Turn off "
    "to pick group bits below")
GROUP_BITS_DESCRIPTION = (
    "Group bits of the spawn call's mask. A record plays if its GroupFlag has any of the bits that are on. "
    "Turning on several bits shows several variants at once, as the game does for masks like 7")
SURFACE_DESCRIPTION = (
    "The ground surface the effect is spawned on. The game casts a ray down from the character and passes the "
    "surface's bit; a record plays only if its generator's MaterialFlag has that bit. Landing, footstep and "
    "impact effects carry one set of records per surface (e.g. dust or a splash). Use All to see every set")

# (bit, label, SBC surface ids it stands for) from cUtil::getEfctMtrlFlg. The surface names aren't known.
SURFACES = (
    (0x01, "Surface 0x01", "surface ids 1-8, 0x18, 0x1F-0x21"),
    (0x02, "Surface 0x02", "surface ids 9-0xC, 0x1E"),
    (0x04, "Surface 0x04", "surface ids 0x10-0x11"),
    (0x08, "Surface 0x08", "surface ids 0x12-0x17"),
    (0x10, "Surface 0x10 (water / rain)", "surface id 0xD, or any surface while the jungle weather is rainy"),
    (0x20, "Surface 0x20", "surface ids 0x19, 0x1A, 0x1D"),
    (0x40, "Surface 0x40", "surface id 0x1B"),
    (0x80, "Surface 0x80", "surface ids 0xE-0xF"),
)
SURFACE_ITEMS = [("ALL", "All surfaces", "Show the records of every surface (mask 0xFFFFFFFF), as spawn calls "
                  "that don't depend on the ground do")] + [
    (f"{bit:#04x}", label, f"Spawned on {ids} (the effect's material bit {bit:#04x})")
    for bit, label, ids in SURFACES]


def group_all_prop(update=None):
    return bpy.props.BoolProperty(name="All Groups", default=True, description=GROUP_ALL_DESCRIPTION,
                                  update=update)


def group_bits_prop(update=None):
    return bpy.props.BoolVectorProperty(name="Group Bits", size=GROUP_BITS, description=GROUP_BITS_DESCRIPTION,
                                        update=update)


def surface_prop(update=None):
    return bpy.props.EnumProperty(name="Surface", items=SURFACE_ITEMS, default="ALL",
                                  description=SURFACE_DESCRIPTION, update=update)


def draw_filter(layout, owner, root=None):
    """The group / surface widgets (import options or Effect Editor). root: show the effect's flag values."""
    col = layout.column(align=True)
    row = col.row(align=True)
    row.prop(owner, "group_all", toggle=True)
    if not owner.group_all:
        for start in (0, 8):
            row = col.row(align=True)
            for i in range(start, start + 8):
                row.prop(owner, "group_bits", index=i, text=f"{1 << i:x}", toggle=True)
        col.label(text=f"Group mask {group_mask(False, owner.group_bits):#x}")
    if root is not None:
        col.label(text="Records' groups: " + group_summary(root))
    col = layout.column(align=True)
    col.prop(owner, "surface", text="")
    if root is not None:
        col.label(text="Records' surfaces: " + material_summary(root))


def _u32(value):
    if value is None:
        return ALL
    return (int(value, 0) if isinstance(value, str) else int(value)) & 0xFFFFFFFF


def _prop(value):
    return f"{value:#010x}" if value >= 2 ** 31 else value   # ID property ints are signed 32-bit


def group_mask(group_all, group_bits):
    if group_all:
        return ALL
    return sum(1 << i for i, on in enumerate(group_bits) if on)


def material_mask(surface):
    return ALL if surface == "ALL" else int(surface, 0)


def masks_from_options(options):
    """(group mask, material mask) from import options (or the editor state: same property names)."""
    return group_mask(options.group_all, options.group_bits), material_mask(options.surface)


def get_masks(root):
    return _u32(root.get(GROUP_KEY)), _u32(root.get(MATERIAL_KEY))


def set_masks(root, group, material):
    root[GROUP_KEY] = _prop(group & 0xFFFFFFFF)
    root[MATERIAL_KEY] = _prop(material & 0xFFFFFFFF)


def options_from_masks(group, material):
    """(group_all, group_bits, surface) showing the masks in the option widgets."""
    group_all = group == ALL
    bits = [bool(group >> i & 1) for i in range(GROUP_BITS)]
    surface = "ALL" if material == ALL else next(
        (identifier for identifier, _, _ in SURFACE_ITEMS[1:] if int(identifier, 0) == material), "ALL")
    return group_all, bits, surface


def record_flags(ob):
    """(GroupFlag, MaterialFlag) of a record object (all bits when it has no generator)."""
    gen = ob.get("efl_gen")
    if gen is None:
        return ALL, ALL
    return _u32(gen.get("GroupFlag", ALL)), _u32(gen.get("MaterialFlag", ALL))


def record_passes(ob, group, material):
    flags = record_flags(ob)
    return bool(flags[0] & group) and bool(flags[1] & material)


def _dependents(record):
    """Objects showing a record: its particle/light/ribbon objects and shapes (not other records)."""
    out = set(record.children_recursive)
    for ob in bpy.data.objects:
        if ob.get("efl_generator") == record:
            out.add(ob)
            out.update(ob.children_recursive)
    return {ob for ob in out if "efl_record" not in ob}


def apply_filter(root):
    """Hide the objects of records that don't pass the root's masks, show the others again.
    Returns (records shown, records total)."""
    from . import effect_sim
    group, material = get_masks(root)
    records = all_record_objects(root)
    shown = 0
    scene = bpy.context.scene
    for record in records:
        passes = record_passes(record, group, material)
        record["efl_filtered"] = not passes
        shown += passes
        for ob in _dependents(record):
            if not passes and HIDDEN_KEY not in ob:
                ob[HIDDEN_KEY] = [ob.hide_viewport, ob.hide_render]
                ob.hide_viewport = ob.hide_render = True
            elif passes and HIDDEN_KEY in ob:
                ob.hide_viewport, ob.hide_render = (bool(v) for v in ob[HIDDEN_KEY])
                del ob[HIDDEN_KEY]
                if effect_sim.SIM_KEY in ob and scene is not None:   # skipped while hidden: catch up
                    effect_sim.update_object(ob, scene)
    root["efl_filter_shown"] = shown
    return shown, len(records)


def is_hidden(ob):
    """True for objects hidden by the filter (the particle handler skips them)."""
    return HIDDEN_KEY in ob


def group_summary(root):
    """'0x1 x5, 0x2 x3, all x4': the GroupFlag values of the effect's records, for the panels."""
    return _summary([record_flags(ob)[0] for ob in all_record_objects(root)])


def material_summary(root):
    return _summary([record_flags(ob)[1] for ob in all_record_objects(root)])


def _summary(values):
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return ", ".join(f"{'all' if v == ALL else hex(v)} x{n}" for v, n in sorted(counts.items()))
