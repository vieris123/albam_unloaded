"""Blender version differences, in one place (2026-10-14: Blender 4.2 and 5.4).

- Actions: Blender 5 has only slotted, layered actions. `Action.fcurves` / `Action.groups` are gone; curves live in
  the channelbag of a slot (`action.layers[0].strips[0].channelbag(slot)`), an ID plays the slot its animation data
  names (`action_slot`), and assigning a new or copied action leaves that slot empty. 4.2 keeps the flat lists.
  Every action Albam makes has one slot, so the helpers take the action and use the owner's slot when the owner is
  given and plays it, else the action's first slot (made with id type OBJECT when `ensure`).
- Geometry Nodes modifier inputs: `modifier["Socket_n"]` in 4.2, `modifier.properties.inputs["Socket_n"]` in 5.
  On the 5.4 build installed on 2026-10-14 the latter is unusable (a value set this way never reaches the
  evaluation; an ID value hangs the depsgraph), so the effect code keeps per-object values as node defaults in a
  wrapper group instead (`effect_sim._wrapped_modifier`) and these helpers are kept for simple cases only.
- Set Curve Normal: the mode is a node property in 4.2 and a menu socket "Mode" in 5 ("Minimum Twist" / "Z Up" /
  "Free").
"""
import bpy

LEGACY_ACTIONS = "fcurves" in bpy.types.Action.bl_rna.properties   # 4.2 (and 4.4's compatibility accessors)


# -- actions ------------------------------------------------------------------------------------------

def ensure_action(owner, name):
    """The owner's action, made (and assigned, with a slot) when it has none."""
    ad = owner.animation_data or owner.animation_data_create()
    if ad.action is None:
        assign_action(owner, bpy.data.actions.new(name))
    return ad.action


def assign_action(owner, action):
    """Assign an action to an ID; on Blender 5 also pick its slot (a new action gets one for the owner)."""
    ad = owner.animation_data or owner.animation_data_create()
    ad.action = action
    if action is None or LEGACY_ACTIONS or not hasattr(ad, "action_slot"):
        return action
    if ad.action_slot is None:
        suitable = list(getattr(ad, "action_suitable_slots", ()))
        if suitable:
            ad.action_slot = suitable[0]
        elif action.slots:
            ad.action_slot = action.slots[0]
        else:
            ad.action_slot = action.slots.new(id_type=owner.id_type, name=owner.name)
    return action


def _slot(action, owner=None, ensure=False):
    ad = owner.animation_data if owner is not None else None
    if ad is not None and ad.action == action and ad.action_slot is not None:
        return ad.action_slot
    if action.slots:
        return action.slots[0]
    if not ensure:
        return None
    slot = action.slots.new(id_type=owner.id_type if owner is not None else "OBJECT",
                            name=owner.name if owner is not None else action.name)
    if ad is not None and ad.action == action and ad.action_slot is None:
        ad.action_slot = slot
    return slot


def channelbag(action, owner=None, ensure=False):
    """Blender 5: the channelbag holding the action's curves (None without one unless ensure). 4.2: None."""
    if LEGACY_ACTIONS or action is None:
        return None
    slot = _slot(action, owner, ensure)
    if slot is None:
        return None
    layer = action.layers[0] if action.layers else (action.layers.new("Layer") if ensure else None)
    if layer is None:
        return None
    strip = layer.strips[0] if layer.strips else (layer.strips.new(type="KEYFRAME") if ensure else None)
    if strip is None:
        return None
    return strip.channelbag(slot, ensure=ensure)


def fcurves_of(action, owner=None):
    """The F-curves of an action: the owner's slot on Blender 5 (else the first slot); [] for None."""
    if action is None:
        return []
    if LEGACY_ACTIONS:
        return list(action.fcurves)
    bag = channelbag(action, owner)
    return list(bag.fcurves) if bag is not None else []


def action_fcurves(action):
    """Every F-curve of an action, whichever slot it belongs to."""
    if action is None:
        return []
    if LEGACY_ACTIONS:
        return list(action.fcurves)
    out = []
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                out.extend(bag.fcurves)
    return out


def action_has_curves(action):
    return bool(action_fcurves(action))


def fcurve_new(action, data_path, index=0, group="", owner=None):
    """A new F-curve on an action, in a channel group when one is named."""
    if LEGACY_ACTIONS:
        return action.fcurves.new(data_path, index=index, action_group=group)
    return channelbag(action, owner, ensure=True).fcurves.new(data_path, index=index, group_name=group)


def fcurve_find(action, data_path, index=0, owner=None):
    if action is None:
        return None
    if LEGACY_ACTIONS:
        return action.fcurves.find(data_path, index=index)
    bag = channelbag(action, owner)
    return bag.fcurves.find(data_path, index=index) if bag is not None else None


def fcurve_remove(action, fcurve, owner=None):
    if LEGACY_ACTIONS:
        action.fcurves.remove(fcurve)
        return
    bag = channelbag(action, owner)
    if bag is not None:
        bag.fcurves.remove(fcurve)


def group_ensure(action, name, owner=None):
    """The action's channel group of that name (made if missing); None for an empty name."""
    if not name:
        return None
    groups = action.groups if LEGACY_ACTIONS else channelbag(action, owner, ensure=True).groups
    return groups.get(name) or groups.new(name)


# -- geometry nodes --------------------------------------------------------------------------------------

def node_input_identifier(modifier, name):
    """The socket identifier ("Socket_n") of a node-group modifier input by its name, or None."""
    for item in modifier.node_group.interface.items_tree:
        if getattr(item, "in_out", None) == "INPUT" and item.name == name:
            return item.identifier
    return None


def _inputs(modifier):
    properties = getattr(modifier, "properties", None)
    return getattr(properties, "inputs", None) if properties is not None else None


def set_node_input(modifier, name, value):
    """Set a node-group modifier's input by socket name (4.2: modifier[identifier]; 5: properties.inputs)."""
    identifier = node_input_identifier(modifier, name)
    if identifier is None:
        return False
    inputs = _inputs(modifier)
    if inputs is not None:
        inputs[identifier] = value
    else:
        modifier[identifier] = value
    return True


def get_node_input(modifier, name, default=None):
    identifier = node_input_identifier(modifier, name)
    if identifier is None:
        return default
    inputs = _inputs(modifier)
    try:
        return inputs[identifier] if inputs is not None else modifier[identifier]
    except (KeyError, TypeError):
        return default


def set_curve_normal_free(node):
    """Set Curve Normal node: use the per-point Normal input."""
    if hasattr(node, "mode"):
        node.mode = "FREE"
    else:
        node.inputs["Mode"].default_value = "Free"
