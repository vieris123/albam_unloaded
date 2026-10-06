"""Effect Editor > Change Type: rebuild a record's particle or move block as another type (efl/retype.py).

The new block's own values come from a template, a real block of the target type found in the game's effects:
the effect itself, the other imported effects, then every .efl under the Game Files folders (indexed once per
session). The changed block is stored on the record object (efl_replaced for source records, efl_raw for new ones)
and the effect is rebuilt, so the record keeps its place in the file.
"""
import base64
import os

import bpy

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from .efl import EffectList, EflError, schema
from .efl.edit import apply_keyframes, apply_props, apply_subs, block_props, keyframe_props, sub_props
from .efl.model import Block
from .efl.retype import (RETYPE_SLOTS, RetypeError, offered_types, retype, template_score, variant_of,
                         variants)
from .effect_export import (_raw_of, _replaced_of, _report_failure, apply_to_scene, effect_root, record_object,
                            source_bytes)

TYPE_PROP = {"ptcl": "efl_particle_type", "move": "efl_move_type"}

_templates = {}       # (slot, type, variant) -> (score, block bytes, source label)
_indexed = set()      # Game Files .efl paths already indexed
_enum_cache = {}      # Blender needs enum item lists kept alive


def _index(efl, label):
    for i, record in enumerate(efl.records):
        for slot in RETYPE_SLOTS:
            block = getattr(record, slot)
            if block is None:
                continue
            key = (slot, block.type, variant_of(block))
            score = template_score(block)
            if key not in _templates or score < _templates[key][0]:
                _templates[key] = (score, bytes(block.data), f"{label}, record {i:02d}")


def _index_bytes(data, label):
    try:
        _index(EffectList.from_bytes(data), label)
    except (EflError, Exception):
        pass


def find_template(context, slot, btype, variant):
    """(Block, source label) of the best example of that block type, or (None, None)."""
    key = (slot, btype, variant)
    for ob in bpy.data.objects:   # imported effects are few and may have changed: always indexed again
        if ob.albam_asset.extension == "efl":
            try:
                _index_bytes(source_bytes(ob), ob.albam_asset.relative_path or ob.name)
            except AlbamCheckFailure:
                pass
    if key not in _templates or _templates[key][0] > 0:
        rfs = context.scene.albam.rfs
        for item in rfs.file_list:
            path = item.absolute_path
            if not path.lower().endswith(".efl") or path in _indexed:
                continue
            _indexed.add(path)
            try:
                with open(path, "rb") as f:
                    _index_bytes(f.read(), os.path.basename(path))
            except OSError:
                continue
            if key in _templates and _templates[key][0] == 0:
                break
    if key not in _templates:
        return None, None
    _score, data, label = _templates[key]
    return Block(slot, btype, bytearray(data)), label


def current_block(ob, slot):
    """The record object's block in a slot as it would be exported (source or replaced bytes plus its edits)."""
    replaced = _replaced_of(ob) or {}
    if slot in replaced:
        btype, data = replaced[slot]
    elif int(ob["efl_record"]) < 0:
        raw = _raw_of(ob) or {}
        if slot not in raw:
            return None
        btype, data = raw[slot]
    else:
        root = effect_root(ob)
        record = EffectList.from_bytes(source_bytes(root)).records[int(ob["efl_record"])]
        block = getattr(record, slot)
        if block is None:
            return None
        btype, data = block.type, bytes(block.data)
    block = Block(slot, btype, bytearray(data))
    problems = []
    for props, apply in ((ob.get(f"efl_{slot}"), apply_props), ((ob.get("efl_kf") or {}).get(slot), apply_keyframes),
                         ((ob.get("efl_sub") or {}).get(slot), apply_subs)):
        if props is not None:
            problems += apply(block, props)[1]
    if problems:
        raise AlbamCheckFailure("The record has edits that can't be written", details="\n".join(problems),
                                solution="Fix or revert those values first")
    return block


def store_block(ob, block):
    """Make block the record object's block in its slot (export reads it from here)."""
    slot = block.kind
    entry = {"type": block.type, "data": base64.b64encode(bytes(block.data)).decode("ascii")}
    key = "efl_raw" if int(ob["efl_record"]) < 0 else "efl_replaced"
    stored = ob.get(key)
    stored = stored.to_dict() if hasattr(stored, "to_dict") else dict(stored or {})
    stored[slot] = entry
    ob[key] = stored
    ob[f"efl_{slot}"] = block_props(block)
    for key, props in (("efl_kf", keyframe_props(block)), ("efl_sub", sub_props(block))):
        value = ob.get(key)
        value = value.to_dict() if hasattr(value, "to_dict") else dict(value or {})
        value[slot] = props
        ob[key] = value
    ob[TYPE_PROP[slot]] = block.type_name


# -- operator ---------------------------------------------------------------------------------------

def _type_items(self, context):
    items = [(str(t), f"{t} {name}", f"Make the {'particle' if self.slot == 'ptcl' else 'move'} block a {name}")
             for t, name in offered_types(self.slot)]
    _enum_cache[("types", self.slot)] = items or [("0", "0", "")]
    return _enum_cache[("types", self.slot)]


def _variant_items(self, context):
    try:
        btype = int(self.new_type)
    except (TypeError, ValueError):
        btype = -1
    kind = "line type" if btype in schema.LINE_PTCL_TYPES else "cloth type"
    items = [("-1", "As the example", f"Keep the {kind} of the game example the block is built from")]
    items += [(str(v), f"{v} {name}", f"Make it a {name} {kind}") for v, name in variants(self.slot, btype)]
    _enum_cache[("variants", self.slot, btype)] = items
    return items


@blender_registry.register_blender_type
class ALBAM_OT_EflChangeType(bpy.types.Operator):
    """Rebuild this record's particle or move block as another type. Fields both types have are kept (colours,
    textures, sizes, speeds...), the rest come from an example of the new type in the game's effects (the
    imported ones, then the Game Files folders), or from defaults when none is found. The effect is rebuilt"""
    bl_idname = "albam.efl_change_type"
    bl_label = "Change Type"
    bl_options = {"REGISTER", "UNDO"}

    slot: bpy.props.EnumProperty(
        name="Block", items=[("ptcl", "Particle", "The particle block: what is drawn"),
                             ("move", "Move", "The move block: how particles move")],
        description="Which block of the record to change")
    new_type: bpy.props.EnumProperty(name="New Type", items=_type_items,
                                     description="The type to rebuild the block as")
    variant: bpy.props.EnumProperty(
        name="Line / Cloth Type", items=_variant_items,
        description="For line and cloth particles: the LineType / ClothType. Each one carries its own extra "
                    "settings, which come from the example (or defaults)")

    @classmethod
    def poll(cls, context):
        return record_object(context.active_object) is not None

    def invoke(self, context, event):
        ob = record_object(context.active_object)
        block = (ob.get(f"efl_{self.slot}") or {})
        if "type" in block and str(block["type"]) in {i[0] for i in _type_items(self, context)}:
            self.new_type = str(block["type"])
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        ob = record_object(context.active_object)
        current = (ob.get(f"efl_{self.slot}") or {}).get("type_name", "none")
        layout.label(text=f"Currently: {current}")
        layout.prop(self, "new_type")
        if variants(self.slot, int(self.new_type)):
            layout.prop(self, "variant")
        layout.label(text="Shared fields are kept; the rest come from a game example.", icon="INFO")

    def execute(self, context):
        ob = record_object(context.active_object)
        root = effect_root(ob)
        btype = int(self.new_type)
        variant = int(self.variant) if variants(self.slot, btype) and self.variant != "-1" else None
        try:
            old = current_block(ob, self.slot)
            if old is None:
                self.report({"ERROR"}, f"This record has no {self.slot} block to change")
                return {"CANCELLED"}
            if old.type == btype and (variant is None or variant_of(old) == variant):
                self.report({"INFO"}, f"Already a {old.type_name}")
                return {"CANCELLED"}
            template, source = find_template(context, self.slot, btype, variant)
            if template is None and variant is None and variants(self.slot, btype):
                template, source = find_template(context, self.slot, btype, None)
                if template is None:   # any variant of the type will do
                    for v, _ in variants(self.slot, btype):
                        template, source = find_template(context, self.slot, btype, v)
                        if template is not None:
                            break
            new, notes = retype(old, btype, template, variant if template is None or variant is not None
                                else variant_of(template))
            store_block(ob, new)
            apply_to_scene(context, root)
        except RetypeError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        except Exception as err:
            return _report_failure(self, err)
        where = f" (example: {source})" if source else ""
        self.report({"INFO"}, f"{self.slot} is now {new.type_name}{where}: " + "; ".join(notes))
        return {"FINISHED"}
