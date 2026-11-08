"""MoveDef move files in Blender (Dope Sheet > Action Editor sidebar > Albam [Beta] > Moves): the dmc4_hook runner's
XML (`Vibed/MoveDef/schema.md` "Implemented") authored from LMT animations.

A move is `scene.albam.movedefs.moves[i]`: the file's elements as a flat list (`elems`, document order, each with
its attributes as text) plus the text it was read from (`source`), so writing patches that text and keeps comments,
formatting and anything the runner or Albam doesn't model (`movedef/doc.py`). The panel draws the elements as a
tree with a widget per attribute kind (`movedef/schema.py`, which also holds the tooltips).

Frames: an element with a motion frame inside a stage (cancel, trigger, effect, se, shell, launch, next, the stage's
cancel_frame) gets a pose marker on the stage's action (its first <slot>'s block, its block= or its motion=); the marker
is the frame: drag it in the Action editor. Markers are named `md <tag>` and linked by name (`AlbamMoveElem.marker`),
like the LMT events. Game frames come from the action's LMT export timing (start and frame rate). A stage whose
motion isn't an action in the scene keeps plain numbers.
"""
import os
import re

import bpy

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.engines.mtfw.movedef import doc as mdoc
from albam.engines.mtfw.movedef import schema as mschema
from albam.engines.mtfw.movedef import check as mcheck
from albam.engines.mtfw.movedef import extract as mextract

MARKER_PREFIX = "md "
CHARACTER_OF_LMT = re.compile(r"^(pl\d{3})_(\d{2})$", re.I)   # vanilla body LMTs: pl000_04 -> bank 3
GRAB_LMT = re.compile(r"^pl000_((?:em|pl)\d{3})_\d{2}$", re.I)  # Buster grabs: pl000_em010_00 -> bank 15


def _animation():
    from albam.engines.mtfw import animation
    return animation


def fmt_number(value):
    """A number as the files write it: 12, 1.1, -0.5"""
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.4f}".rstrip("0").rstrip(".")


# ---- the scene's LMT files ------------------------------------------------------------------------------------

def lmt_groups(context):
    return context.scene.albam.lmt_groups.anim_group


def lmt_stem(group):
    return os.path.splitext(os.path.basename(group.export_path))[0] if group.export_path else group.name


def vanilla_bank(group):
    """(character, bank) of a vanilla body LMT (pl000_04 -> ("pl000", 3)) or of a Buster grab LMT (pl000_em010_00 ->
    ("pl000", 15)), or None"""
    m = CHARACTER_OF_LMT.match(lmt_stem(group))
    if m:
        return m.group(1).lower(), int(m.group(2)) - 1
    return ("pl000", mschema.GRAB_BANK) if grab_target(group) else None


def grab_target(group):
    """The grabbed target of a Buster grab LMT (pl000_em010_00 -> "em010"), or None"""
    m = GRAB_LMT.match(lmt_stem(group))
    return m.group(1).lower() if m and m.group(1).lower() in mschema.GRAB_CTN_BANKS.values() else None


def find_group(context, move, bank):
    """The LMT file that holds `bank`'s blocks for this move: its own LMT for OWN (block=, <slot>s) or its <lmt>'s
    fixed bank, else the character's vanilla body LMT of that bank (pl000_NN, bank NN - 1)"""
    d = move_doc(move)
    lmt = d.child(d.root, "lmt")
    if lmt is not None and (bank == mschema.OWN or mcheck.parse_int(lmt.get("bank")) == bank):
        group = lmt_groups(context).get(move.lmt_group) if move.lmt_group else None
        if group is None and lmt.get("path"):
            stem = lmt.get("path").replace("/", "\\").rpartition("\\")[2].lower()
            group = next((g for g in lmt_groups(context) if lmt_stem(g).lower() == stem), None)
        return group
    character = d.root.get("character", "")
    own = lmt_groups(context).get(move.lmt_group) if move.lmt_group else None
    if own is not None and vanilla_bank(own) == (character, bank):
        return own                    # the move's own pick first (several grab LMTs all play from bank 15)
    return next((g for g in lmt_groups(context) if vanilla_bank(g) == (character, bank)), None)


def block_action(group, slot):
    if group is None:
        return None
    lmt_props = _animation().get_lmt_props
    for item in group.actions:
        if item.action is not None and lmt_props(item.action).lmt_id == slot:
            return item.action
    return None


def block_length(action):
    """Length in game frames, 0 when the action has no keys"""
    if action is None:
        return None
    from albam.lib import blender_compat as compat
    keys = sum(len(fc.keyframe_points) for fc in compat.action_fcurves(action))
    return _animation().get_lmt_props(action).num_frames if keys else 0


def stage_action(context, move, d, stage):
    motions = mcheck.stage_motions(d, stage)
    if not motions:
        return None
    bank, slot = motions[0]
    return block_action(find_group(context, move, bank), slot)


# ---- the property groups --------------------------------------------------------------------------------------

_ENUM_CACHE = {}


def _owner(attr):
    """(move, elem) an attribute item belongs to"""
    idx = [int(i) for i in re.findall(r"\[(\d+)\]", attr.path_from_id())]
    move = attr.id_data.albam.movedefs.moves[idx[0]]
    return move, move.elems[idx[1]]


def _spec(attr):
    elem = mschema.ELEMENTS.get(attr.key)
    return elem.attrs.get(attr.name) if elem is not None else None


def _kind(attr):
    spec = _spec(attr)
    return spec.kind if spec is not None else "str"


def _get_int(self):
    return mcheck.parse_int(self.value, 0) if mcheck.parse_int(self.value) is not None else \
        mcheck.parse_int((_spec(self).default if _spec(self) else "0"), 0) or 0


def _set_int(self, value):
    if (_kind(self) == "hex" or self.value.lower().startswith("0x")) and value >= 0:
        self.value = f"0x{value:X}"
    else:
        self.value = str(value)


def _get_float(self):
    value = mcheck.parse_float(self.value)
    if value is None:
        value = mcheck.parse_float(_spec(self).default if _spec(self) else "0", 0.0)
    return value


def _set_float(self, value):
    self.value = fmt_number(value)


def _get_bool(self):
    return self.value.strip().lower() in ("true", "1", "yes", "on")


def _set_bool(self, value):
    self.value = "true" if value else "false"


def _enum_items(self, context):
    spec = _spec(self)
    choices = list(spec.items) if spec is not None else []
    if spec is not None and spec.kind == "attackref":
        move, _ = _owner(self)
        choices = [(e.attrs["name"].value, e.attrs["name"].value, "An <attack> of this file")
                   for e in move.elems if e.tag == "attack" and "name" in e.attrs]
    if self.value not in [c[0] for c in choices]:
        choices.append((self.value, self.value or "(empty)", "As written in the file"))
    key = (self.key, self.name, self.value)
    items = _ENUM_CACHE.get(key)
    if items is None:
        items = [(c[0] or "_empty", c[1], c[2], i) for i, c in enumerate(choices)]
        _ENUM_CACHE[key] = items
    return items


def _get_enum(self):
    for item in _enum_items(self, None):
        if item[0] == (self.value or "_empty"):
            return item[3]
    return 0


def _set_enum(self, index):
    for item in _enum_items(self, None):
        if item[3] == index:
            self.value = "" if item[0] == "_empty" else item[0]
            return


def _get_cats(self):
    present = set(self.value.replace(",", " ").split())
    return [c in present for c in mschema.CATEGORIES]


def _set_cats(self, values):
    self.value = " ".join(c for c, on in zip(mschema.CATEGORIES, values) if on)


def _get_frame(self):
    move, elem = _owner(self)
    frame = marker_game_frame(bpy.context, move, elem)
    return frame if frame is not None else _get_float(self)


def _set_frame(self, value):
    self.value = fmt_number(value)
    move, elem = _owner(self)
    place_marker(bpy.context, move, elem, value)


_VALUE_TIP = "Value of this attribute (hover its name for what it does)"


@blender_registry.register_blender_prop
class AlbamMoveAttr(bpy.types.PropertyGroup):
    """An attribute of a MoveDef element; `value` is the text in the file, the v_* properties edit it by kind"""
    key: bpy.props.StringProperty(options={"HIDDEN"})          # the element's schema key
    value: bpy.props.StringProperty(name="Value", description=_VALUE_TIP)
    v_int: bpy.props.IntProperty(name="Value", description=_VALUE_TIP, get=_get_int, set=_set_int)
    v_float: bpy.props.FloatProperty(name="Value", description=_VALUE_TIP, get=_get_float, set=_set_float)
    v_bool: bpy.props.BoolProperty(name="Value", description=_VALUE_TIP, get=_get_bool, set=_set_bool)
    v_enum: bpy.props.EnumProperty(name="Value", description=_VALUE_TIP, items=_enum_items, get=_get_enum,
                                   set=_set_enum)
    v_cats: bpy.props.BoolVectorProperty(name="Categories", description="Cancel categories (C_NORM0 ... C_ALL)",
                                         size=len(mschema.CATEGORIES), get=_get_cats, set=_set_cats)
    v_frame: bpy.props.FloatProperty(
        name="Frame", description="Motion frame (60 fps). With a pose marker this moves the marker; dragging the "
        "marker in the Action editor changes it", get=_get_frame, set=_set_frame, min=0.0, precision=1)


@blender_registry.register_blender_prop
class AlbamMoveElem(bpy.types.PropertyGroup):
    """An element of a MoveDef file (`movedef/doc.py` Elem) and the pose marker of its frame"""
    uid: bpy.props.IntProperty()
    tag: bpy.props.StringProperty()
    key: bpy.props.StringProperty()
    parent: bpy.props.IntProperty(default=-1)
    src: bpy.props.IntProperty(default=-1)
    attrs: bpy.props.CollectionProperty(type=AlbamMoveAttr)
    marker: bpy.props.StringProperty(name="Marker", description="Pose marker holding this element's frame")


def _on_active_elem(self, context):
    """Select the element's marker and move the playhead to it"""
    try:
        elem = self.elems[self.active_elem]
    except IndexError:
        return
    action, marker = find_marker(context, self, elem)
    if marker is None:
        return
    for m in action.pose_markers:
        m.select = m == marker
    context.scene.frame_current = marker.frame


@blender_registry.register_blender_prop
class AlbamMove(bpy.types.PropertyGroup):
    """One MoveDef file"""
    source: bpy.props.StringProperty(options={"HIDDEN"})        # the text it was read / last written from
    elems: bpy.props.CollectionProperty(type=AlbamMoveElem)
    active_elem: bpy.props.IntProperty(name="Element", update=_on_active_elem)
    xml_path: bpy.props.StringProperty(
        name="File", subtype="FILE_PATH",
        description="Where the move was read from / last written (nativePC\\movedef\\<name>.xml in the game)")
    lmt_group: bpy.props.StringProperty(
        name="LMT", description="The LMT file (LMT panel) that is the move's <lmt>: block= and <slot>s play its blocks")
    report: bpy.props.StringProperty(options={"HIDDEN"})        # the last check, newline-joined


@blender_registry.register_blender_prop_albam(name="movedefs")
class AlbamMoveDefs(bpy.types.PropertyGroup):
    """The scene's MoveDef move files"""
    moves: bpy.props.CollectionProperty(type=AlbamMove)
    active: bpy.props.IntProperty(name="Move")


def active_move(context):
    defs = context.scene.albam.movedefs
    try:
        return defs.moves[defs.active]
    except IndexError:
        return None


# ---- the file <-> the property groups -------------------------------------------------------------------------

def move_doc(move):
    elems = [mdoc.Elem(e.uid, e.tag, e.key, e.parent, e.src, [(a.name, a.value) for a in e.attrs])
             for e in move.elems]
    return mdoc.Doc(move.source, elems)


def store_doc(move, d, markers=None):
    """Fill the move's elements from a Doc; `markers` {uid: marker name} keeps their markers"""
    markers = markers if markers is not None else {e.uid: e.marker for e in move.elems}
    move.elems.clear()
    for e in d.elems:
        item = move.elems.add()
        item.uid, item.tag, item.key, item.parent, item.src = e.uid, e.tag, e.key, e.parent, e.src
        item.name = e.tag
        item.marker = markers.get(e.uid, "")
        for k, v in e.attrs:
            a = item.attrs.add()
            a.name, a.key, a.value = k, e.key, v
    move.source = d.source
    move.name = d.root.get("name", "") if d.root is not None else move.name


def move_name(move):
    root = move.elems[0] if len(move.elems) else None
    if root is None:
        return move.name
    a = root.attrs.get("name")
    return a.value if a is not None else root.tag


def elem_by_uid(move, uid):
    return next((e for e in move.elems if e.uid == uid), None)


def stage_of(move, elem):
    while elem is not None and elem.tag != "stage":
        elem = elem_by_uid(move, elem.parent)
    return elem


def frame_attr(elem):
    spec = mschema.ELEMENTS.get(elem.key)
    return spec.frame if spec is not None else None


# ---- markers --------------------------------------------------------------------------------------------------

def _elem_action(context, move, elem):
    stage = stage_of(move, elem)
    if stage is None:
        return None
    d = move_doc(move)
    return stage_action(context, move, d, d.by_uid(stage.uid))


def find_marker(context, move, elem):
    """(action, marker) of an element's frame, (action, None) without one"""
    action = _elem_action(context, move, elem)
    if action is None or not elem.marker:
        return action, None
    return action, action.pose_markers.get(elem.marker)


def marker_game_frame(context, move, elem):
    action, marker = find_marker(context, move, elem)
    if marker is None:
        return None
    return _animation().ExportTiming(action).to_game(marker.frame)


def place_marker(context, move, elem, game_frame):
    """Put (or move) the element's marker on its game frame; False when its stage has no action"""
    action, marker = find_marker(context, move, elem)
    if action is None:
        return False
    timing = _animation().ExportTiming(action)
    if marker is None:
        name = _animation().unique_marker_name(action, f"{MARKER_PREFIX}{elem.tag}")
        marker = action.pose_markers.new(name)
        elem.marker = marker.name
    marker.frame = int(round(timing.to_action(game_frame)))
    return True


def remove_marker(context, move, elem):
    action, marker = find_marker(context, move, elem)
    if marker is not None:
        action.pose_markers.remove(marker)
    elem.marker = ""


def make_markers(context, move):
    """A marker for every frame of the move that has none (import, a stage's motion changed)"""
    made = 0
    for elem in move.elems:
        attr = frame_attr(elem)
        if not attr or attr not in elem.attrs:
            continue
        action, marker = find_marker(context, move, elem)
        if action is None or marker is not None:
            continue
        frame = mcheck.parse_float(elem.attrs[attr].value)
        if frame is not None and place_marker(context, move, elem, frame):
            made += 1
    return made


def sync_frames(context, move):
    """Write the markers' frames into the frame attributes (a marker on the frame the text already rounds to
    keeps the text)"""
    for elem in move.elems:
        attr = frame_attr(elem)
        if not attr or attr not in elem.attrs:
            continue
        action, marker = find_marker(context, move, elem)
        if marker is None:
            continue
        timing = _animation().ExportTiming(action)
        item = elem.attrs[attr]
        old = mcheck.parse_float(item.value)
        if old is not None and int(round(timing.to_action(old))) == marker.frame:
            continue
        item.value = fmt_number(round(timing.to_game(marker.frame), 3))


# ---- checks ---------------------------------------------------------------------------------------------------

def other_moves(context, move):
    """mcheck.Other of the scene's other moves and of the files in the game folder's movedef\\ (not this one)"""
    out = []
    for other in context.scene.albam.movedefs.moves:
        if other == move or not len(other.elems):
            continue
        o = mcheck.summary(move_doc(other))
        o.where = "in the scene"
        out.append(o)
    names = {o.name for o in out}
    from albam.blender_ui.export_panel import game_folder
    folder = game_folder(context)
    movedef_dir = os.path.join(folder, "movedef") if folder else ""
    own = os.path.normcase(bpy.path.abspath(move.xml_path)) if move.xml_path else ""
    if movedef_dir and os.path.isdir(movedef_dir):
        for name in sorted(os.listdir(movedef_dir)):
            path = os.path.join(movedef_dir, name)
            if not name.lower().endswith(".xml") or os.path.normcase(path) == own:
                continue
            try:
                with open(path, encoding="utf-8-sig") as f:
                    d = mdoc.parse(f.read())
            except (OSError, ValueError):
                continue
            if d.root.tag != "move":
                continue
            o = mcheck.summary(d)
            if o.name in names or o.name == move_name(move):
                continue
            o.where = os.path.join("movedef", name)
            out.append(o)
    return out


def shared_commands(context, move):
    out = {}
    for other in context.scene.albam.movedefs.moves:
        if other == move or not len(other.elems):
            continue
        d = move_doc(other)
        commands = d.children(d.root, "command")
        if d.root.tag == "move":
            commands = commands[1:]           # a move's own (first) command isn't shared
        out.setdefault(d.root.get("character", ""), set()).update(c.get("name") for c in commands)
    return out


def check_move(context, move):
    """(errors, warnings) of the move as it would be written (frames synced from the markers first)"""
    sync_frames(context, move)
    d = move_doc(move)
    known, cache = set(), {}
    banks = set()
    for stage in mcheck.stages(d):
        banks.update(b for b, _ in mcheck.stage_motions(d, stage))
    for bank in banks:
        if bank is not None and find_group(context, move, bank) is not None:
            known.add(bank)

    def length(bank, slot):
        if (bank, slot) not in cache:
            cache[(bank, slot)] = block_length(block_action(find_group(context, move, bank), slot))
        return cache[(bank, slot)]

    env = mcheck.Env(block_length=length, known_banks=known, others=other_moves(context, move),
                     shared_commands=shared_commands(context, move), atk_names=lambda p: atk_names(context, p),
                     atk_damage=lambda p: atk_damage(context, p))
    return mcheck.check(d, env)


def _atk_entries(context, path):
    try:
        data = context.scene.albam.rfs.get_vfile("dmc4", path.replace("/", "\\") + ".atk").get_bytes()
    except (KeyError, AttributeError):
        return None
    from dmc4xml import atk
    try:
        return atk.read(data).entries
    except atk.AtkError:
        return None


def atk_names(context, path):
    """Entry names of an .atk game path (no extension) in Game Files, None when it isn't there or can't be read"""
    entries = _atk_entries(context, path)
    return [e.name for e in entries] if entries is not None else None


def atk_damage(context, path):
    """Entry damage values of an .atk game path, like atk_names"""
    entries = _atk_entries(context, path)
    return [e.damage for e in entries] if entries is not None else None


# ---- new moves ------------------------------------------------------------------------------------------------

def free_id(context, move, character):
    used = set()
    for o in other_moves(context, move):
        if o.character == character:
            used.update(o.ids)
    used.update(mschema.HOOK_IDS.get(character, {}))
    first = mschema.MIN_ID.get(character, 0x34)
    return next(i for i in range(first, first + 512) if i not in used)


def lmt_game_path(context, group):
    """Game path (no extension) of an LMT file: its path under a Game Files root or the game folder, else
    motion\\<character>\\<name>"""
    path = bpy.path.abspath(group.export_path) if group.export_path else ""
    roots = [f.absolute_path for f in context.scene.albam.rfs.file_list if f.is_root]
    from albam.blender_ui.export_panel import game_folder
    if game_folder(context):
        roots.append(game_folder(context))
    for root in roots:
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            continue
        if path and not rel.startswith(".."):
            return os.path.splitext(rel)[0].replace("/", "\\")
    character = (vanilla_bank(group) or ("pl000", 0))[0]
    return f"motion\\{character}\\{lmt_stem(group)}"


def new_move(context, name, character, kind, group, action, attr="command", air="air"):
    """A move file in the scene from an LMT animation: `kind` NEW (a move of its own: id, table row, <lmt> placed by
    the motion registry, stage on the animation's block) or OVERLAY (on a vanilla move: the animation is the vanilla motion)"""
    defs = context.scene.albam.movedefs
    move = defs.moves.add()
    move.lmt_group = group.name if group is not None else ""
    slot = _animation().get_lmt_props(action).lmt_id if action is not None else 0
    if kind == "OVERLAY":
        d = mdoc.new_doc("move", [("name", name), ("character", character), ("ids", ""), ("overlay", "true"),
                                  ("version", "2")])
        vb = vanilla_bank(group) if group is not None else None
        bank = vb[1] if vb else 0
        d.add("stage", d.root, [("name", "main"), ("motion", f"{bank}:0x{slot:X}")])
    else:
        store_doc(move, mdoc.new_doc("move", [("name", name)]))   # other_moves needs a named move
        lmt_path = lmt_game_path(context, group) if group is not None else f"motion\\{character}\\{name}"
        d = mdoc.new_doc("move", [("name", name), ("character", character),
                                  ("id", f"0x{free_id(context, move, character):X}"), ("version", "2")])
        table = d.add("table", d.root, [("attr", attr), ("level", "7"), ("start", "true"), ("cancel", "false"),
                                        ("repeat", "false"), ("weapon", "-1"), ("style", "-1"), ("etc", "0"),
                                        ("air", air)])
        if attr == "command":
            command = f"{name}_input"
            d.add("input", table, [("command", command)])
            c = d.add("command", d.root, [("name", command), ("condition", "lockon")])
            d.add("btn", c, [("id", "style"), ("mode", "trg")])
        d.add("lmt", d.root, [("path", lmt_path)])
        d.add("stage", d.root, [("name", "main"), ("block", str(slot)), ("ctn", "0:5"),
                                ("attr", "null_trans_off"), ("interp", "4"), ("watchdog", "60")])
    store_doc(move, d, {})
    move.xml_path = ""
    defs.active = len(defs.moves) - 1
    return move


def add_element(context, move, parent_uid, tag, frame=None):
    """A new element with its starter attributes (the runner's defaults); one with a frame gets a marker"""
    d = move_doc(move)
    parent = d.by_uid(parent_uid)
    spec = mschema.spec_for(tag, parent.key)
    attrs = []
    for name in (spec.starter if spec is not None else ()):
        a = spec.attrs[name]
        value = a.default
        if a.kind == "frame":
            value = fmt_number(frame if frame is not None else 0.0)
        elif tag == "attack" and name == "name":
            taken = {e.get("name") for e in d.children(d.root, "attack")}
            value = next(f"attack{i}" for i in range(1, 999) if f"attack{i}" not in taken)
        elif a.kind == "enum" and not value and a.items:
            value = a.items[0][0]
        elif a.kind == "cats" and not value:
            value = "C_ALL"
        attrs.append((name, value))
    same = [e for e in d.children(parent) if e.tag == tag]
    elem = d.add(tag, parent, attrs, after=same[-1] if same else None)
    store_doc(move, d)
    item = elem_by_uid(move, elem.uid)
    if spec is not None and spec.frame and spec.frame in item.attrs:
        place_marker(context, move, item, mcheck.parse_float(item.attrs[spec.frame].value, 0.0))
    move.active_elem = list(move.elems).index(item)
    return item


def remove_element(context, move, elem):
    d = move_doc(move)
    target = d.by_uid(elem.uid)
    for e in [target] + d.descendants(target):
        item = elem_by_uid(move, e.uid)
        if item is not None:
            remove_marker(context, move, item)
    d.remove(target)
    store_doc(move, d)
    move.active_elem = min(move.active_elem, len(move.elems) - 1)


def import_text(context, text, path=""):
    d = mdoc.parse(text)
    defs = context.scene.albam.movedefs
    move = defs.moves.add()
    store_doc(move, d, {})
    move.xml_path = path
    lmt = d.child(d.root, "lmt")
    if lmt is not None and lmt.get("path"):
        stem = lmt.get("path").replace("/", "\\").rpartition("\\")[2].lower()
        group = next((g for g in lmt_groups(context) if lmt_stem(g).lower() == stem), None)
        if group is not None:
            move.lmt_group = group.name
    defs.active = len(defs.moves) - 1
    make_markers(context, move)
    return move


def write_text(context, move):
    """The move's file text after syncing its frames from the markers; AlbamCheckFailure on errors"""
    sync_frames(context, move)
    errors, warnings = check_move(context, move)
    move.report = "\n".join([f"error: {e}" for e in errors] + [f"warning: {w}" for w in warnings])
    if errors:
        raise AlbamCheckFailure(f"{move_name(move)} can't be written", "; ".join(errors),
                                "Fix them in the Moves panel (the list under Check)")
    return move_doc(move).text(), warnings


def after_write(move, text):
    """The written text is the new source: re-read it, keeping each element's marker (same document order)"""
    d = mdoc.parse(text)
    old = list(move.elems)
    if [e.tag for e in old] == [e.tag for e in d.elems]:
        markers = {new.uid: item.marker for new, item in zip(d.elems, old)}
    else:
        markers = {}
    store_doc(move, d, markers)


# ---- operators ------------------------------------------------------------------------------------------------

def _lmt_items(self, context):
    items = [(g.name, g.name, f"LMT file {lmt_stem(g)}") for g in lmt_groups(context)]
    return items or [("", "(no LMT in the scene)", "")]


@blender_registry.register_blender_type
class ALBAM_OT_MoveDefNew(bpy.types.Operator):
    """Make a MoveDef move file from the selected LMT animation: a new move (its own id, input, LMT and stage on
    this animation) or an overlay on the vanilla move whose motion this is"""
    bl_idname = "albam.movedef_new"
    bl_label = "New Move"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name="Name", description="The move's name (also the file name)",
                                   default="new_move")
    character: bpy.props.EnumProperty(name="Character", items=mschema.CHARACTERS, description="Whose move it is")
    kind: bpy.props.EnumProperty(name="Kind", items=(
        ("NEW", "New Move", "A move of its own: an id, a move-table row, its LMT (the motion registry picks the bank)"),
        ("OVERLAY", "Overlay on Vanilla", "Adds to a vanilla move (cancels, effects, hand-offs on its motion); "
         "the animation must be a vanilla one (pl000_NN / pl006_NN)"),
    ), description="What the file is")
    attr: bpy.props.EnumProperty(name="Input", items=(
        ("command", "Command", "Started by an input command (lock-on + button ...)"),
        ("melee", "Melee", "Started by the melee button"),
        ("gun", "Gun", "Started by the gun button"),
    ), description="The row's input")
    air: bpy.props.EnumProperty(name="Where", items=(
        ("ground", "Ground", "Starts on the ground"), ("air", "Air", "Starts in the air"),
        ("both", "Both", "Starts anywhere")), default="air", description="Where the move may start")

    def invoke(self, context, event):
        anim = _animation().get_active_anim(context)
        group = _animation().get_active_lmt(context)
        if group is not None:
            vb = vanilla_bank(group)
            if vb:
                self.character = vb[0]
                self.kind = "OVERLAY"
        if anim is not None and anim.action is not None:
            self.name = re.sub(r"\W+", "_", anim.action.name).strip("_").lower() or "new_move"
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        col = self.layout.column()
        col.use_property_split = True
        col.prop(self, "name")
        col.prop(self, "character")
        col.prop(self, "kind")
        if self.kind == "NEW":
            col.prop(self, "attr")
            col.prop(self, "air")
        anim = _animation().get_active_anim(context)
        text = anim.action.name if anim and anim.action else "none (the stage gets block 0)"
        col.label(text=f"Animation: {text}", icon="ACTION")

    def execute(self, context):
        anim = _animation().get_active_anim(context)
        group = _animation().get_active_lmt(context)
        action = anim.action if anim else None
        move = new_move(context, self.name, self.character, self.kind, group, action, self.attr, self.air)
        make_markers(context, move)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_MoveDefImport(bpy.types.Operator):
    """Read a MoveDef .xml into the Moves list (everything in it is kept when it's written back)"""
    bl_idname = "albam.movedef_import"
    bl_label = "Import Move XML"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.xml", options={"HIDDEN"})

    def invoke(self, context, event):
        from albam.blender_ui.export_panel import game_folder
        folder = game_folder(context)
        if folder and not self.filepath:
            self.filepath = os.path.join(folder, "movedef", "")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            with open(self.filepath, encoding="utf-8-sig", newline="") as f:
                text = f.read()
            move = import_text(context, text, self.filepath)
        except (OSError, ValueError) as err:
            self.report({"ERROR"}, f"{os.path.basename(self.filepath)}: {err}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Read {move_name(move)}")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_MoveDefWrite(bpy.types.Operator):
    """Check the move and write its .xml (frames from the markers). The file goes in nativePC\\movedef\\ of the
    game; the runner reads it at start-up (or its panel's Reload)"""
    bl_idname = "albam.movedef_write"
    bl_label = "Write Move XML"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.xml", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return active_move(context) is not None

    def invoke(self, context, event):
        move = active_move(context)
        from albam.blender_ui.export_panel import game_folder
        folder = game_folder(context)
        if move.xml_path:
            self.filepath = bpy.path.abspath(move.xml_path)
        elif folder:
            self.filepath = os.path.join(folder, "movedef", move_name(move) + ".xml")
        else:
            self.filepath = move_name(move) + ".xml"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        move = active_move(context)
        try:
            text, warnings = write_text(context, move)
            os.makedirs(os.path.dirname(os.path.abspath(self.filepath)), exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        except AlbamCheckFailure:
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
            return {"CANCELLED"}
        except OSError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        after_write(move, text)
        move.xml_path = self.filepath
        note = f" ({len(warnings)} warning(s), see Check)" if warnings else ""
        self.report({"INFO"}, f"Wrote {self.filepath}{note}")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_MoveDefCheck(bpy.types.Operator):
    """Check the move as the runner would read it (ids, banks, blocks, frames inside the motion, names), without
    writing it"""
    bl_idname = "albam.movedef_check"
    bl_label = "Check"

    @classmethod
    def poll(cls, context):
        return active_move(context) is not None

    def execute(self, context):
        move = active_move(context)
        sync_frames(context, move)
        errors, warnings = check_move(context, move)
        move.report = "\n".join([f"error: {e}" for e in errors] + [f"warning: {w}" for w in warnings])
        if errors:
            self.report({"WARNING"}, f"{len(errors)} error(s)")
        else:
            self.report({"INFO"}, "No errors" + (f", {len(warnings)} warning(s)" if warnings else ""))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_MoveDefRemove(bpy.types.Operator):
    """Remove the selected move from the scene (and its markers); its file on disk stays"""
    bl_idname = "albam.movedef_remove"
    bl_label = "Remove Move"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return active_move(context) is not None

    def execute(self, context):
        defs = context.scene.albam.movedefs
        move = active_move(context)
        for elem in move.elems:
            remove_marker(context, move, elem)
        defs.moves.remove(defs.active)
        defs.active = max(0, min(defs.active, len(defs.moves) - 1))
        return {"FINISHED"}


def _child_items(self, context):
    move = active_move(context)
    items = []
    if move is not None and len(move.elems):
        elem = move.elems[min(move.active_elem, len(move.elems) - 1)]
        spec = mschema.ELEMENTS.get(elem.key)
        d = move_doc(move)
        present = {e.key for e in d.children(elem.uid)}
        for key in (spec.children if spec is not None else ()):
            child = mschema.ELEMENTS[key]
            if not child.multiple and key in present:
                continue
            items.append((child.tag, f"<{child.tag}>", child.help))
    _ENUM_CACHE[("children", tuple(items))] = items
    return items or [("", "(nothing can go in here)", "")]


@blender_registry.register_blender_type
class ALBAM_OT_MoveDefAddElement(bpy.types.Operator):
    """Add an element inside the selected one (a frame goes on the current frame, as a pose marker)"""
    bl_idname = "albam.movedef_add_element"
    bl_label = "Add Element"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "tag"

    tag: bpy.props.EnumProperty(name="Element", items=_child_items)

    @classmethod
    def poll(cls, context):
        move = active_move(context)
        return move is not None and len(move.elems) > 0

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        move = active_move(context)
        if not self.tag:
            return {"CANCELLED"}
        parent = move.elems[min(move.active_elem, len(move.elems) - 1)]
        frame = None
        stage = stage_of(move, parent)
        if stage is not None or self.tag == "stage":
            action = _elem_action(context, move, parent)
            if action is not None:
                frame = max(0.0, _animation().ExportTiming(action).to_game(context.scene.frame_current))
        add_element(context, move, parent.uid, self.tag, frame)
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_MoveDefRemoveElement(bpy.types.Operator):
    """Remove the selected element and everything inside it (with their markers)"""
    bl_idname = "albam.movedef_remove_element"
    bl_label = "Remove Element"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        move = active_move(context)
        return move is not None and 0 < move.active_elem < len(move.elems)

    def execute(self, context):
        move = active_move(context)
        remove_element(context, move, move.elems[move.active_elem])
        return {"FINISHED"}


def _attr_items(self, context):
    move = active_move(context)
    items = []
    if move is not None and len(move.elems):
        elem = move.elems[min(move.active_elem, len(move.elems) - 1)]
        spec = mschema.ELEMENTS.get(elem.key)
        for name, a in (spec.attrs.items() if spec is not None else ()):
            if name not in elem.attrs:
                items.append((name, name, a.help))
    _ENUM_CACHE[("attrs", tuple(items))] = items
    return items or [("", "(every attribute is set)", "")]


@blender_registry.register_blender_type
class ALBAM_OT_MoveDefAddAttr(bpy.types.Operator):
    """Set an attribute the selected element doesn't have yet (it starts at the runner's default)"""
    bl_idname = "albam.movedef_add_attr"
    bl_label = "Add Attribute"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "name"

    name: bpy.props.EnumProperty(name="Attribute", items=_attr_items)

    @classmethod
    def poll(cls, context):
        move = active_move(context)
        return move is not None and len(move.elems) > 0

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        move = active_move(context)
        elem = move.elems[min(move.active_elem, len(move.elems) - 1)]
        spec = mschema.ELEMENTS.get(elem.key)
        a = spec.attrs.get(self.name) if spec is not None else None
        if a is None:
            return {"CANCELLED"}
        item = elem.attrs.add()
        item.name, item.key = a.name, elem.key
        value = a.default
        if a.kind == "frame":
            action = _elem_action(context, move, elem)
            game = _animation().ExportTiming(action).to_game(context.scene.frame_current) if action else 0.0
            value = fmt_number(max(0.0, game))
        elif a.kind == "enum" and not value and a.items:
            value = a.items[0][0]
        item.value = value
        if a.kind == "frame" and frame_attr(elem) == a.name:
            place_marker(context, move, elem, mcheck.parse_float(value, 0.0))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_MoveDefRemoveAttr(bpy.types.Operator):
    """Remove this attribute (the runner then uses its default)"""
    bl_idname = "albam.movedef_remove_attr"
    bl_label = "Remove Attribute"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    attr: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        move = active_move(context)
        elem = move.elems[move.active_elem]
        i = elem.attrs.find(self.attr)
        if i < 0:
            return {"CANCELLED"}
        if frame_attr(elem) == self.attr:
            remove_marker(context, move, elem)
        elem.attrs.remove(i)
        return {"FINISHED"}


def attr_tooltip(elem_key, name):
    elem = mschema.ELEMENTS.get(elem_key)
    a = elem.attrs.get(name) if elem is not None else None
    if a is None:
        return f"{name}: the runner doesn't read this attribute; it's kept in the file as it is"
    default = f"\nAbsent: {a.default}" if a.default not in ("", None) else ""
    choices = ""
    if a.items:
        choices = "\n" + "\n".join(f"{i[0]}: {i[2]}" for i in a.items if i[2] != i[0])
    return f"{a.help}{default}{choices}"


@blender_registry.register_blender_type
class ALBAM_OT_MoveDefAttrInfo(bpy.types.Operator):
    """What this attribute does"""
    bl_idname = "albam.movedef_attr_info"
    bl_label = "Attribute Info"
    bl_options = {"INTERNAL"}

    key: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    attr: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        return attr_tooltip(properties.key, properties.attr)

    def execute(self, context):
        self.report({"INFO"}, f"{self.attr}: " + attr_tooltip(self.key, self.attr).replace("\n", " "))
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_MoveDefExtractCtn(bpy.types.Operator):
    """Fill the selected stage's cancels and triggers from the game's .ctn script of its motion (chartbl\\<character>
    .ctn in Game Files): the vanilla windows as a starting point. Existing <cancel> / <trigger>s are replaced"""
    bl_idname = "albam.movedef_extract_ctn"
    bl_label = "Cancels from .ctn"
    bl_options = {"REGISTER", "UNDO"}

    grab: bpy.props.EnumProperty(name="Grabbed", items=[
        (str(b), t, f"The grab script of {t} (.ctn bank {b})") for b, t in mschema.GRAB_CTN_BANKS.items()],
        description="A Buster grab (motion bank 15) has one script per grabbed enemy (.ctn banks 10-29): which "
                    "one to read. The overlay itself covers that slot of every enemy's grab")

    @classmethod
    def poll(cls, context):
        move = active_move(context)
        return move is not None and len(move.elems) and \
            stage_of(move, move.elems[min(move.active_elem, len(move.elems) - 1)]) is not None

    def _stage(self, context):
        move = active_move(context)
        d = move_doc(move)
        return move, d, d.by_uid(stage_of(move, move.elems[move.active_elem]).uid)

    @staticmethod
    def _is_grab(d, st):
        motion = mcheck.parse_motion(st.get("motion"))
        return d.root.get("character", "") == "pl000" and motion is not None and motion[0] == mschema.GRAB_BANK

    def invoke(self, context, event):
        move, d, st = self._stage(context)
        if not self._is_grab(d, st):
            return self.execute(context)
        group = lmt_groups(context).get(move.lmt_group) if move.lmt_group else None
        target = grab_target(group) if group is not None else None
        bank = next((b for b, t in mschema.GRAB_CTN_BANKS.items() if t == target), None)
        if bank is not None:
            self.grab = str(bank)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        move, d, st = self._stage(context)
        character = d.root.get("character", "")
        motion = mcheck.parse_motion(st.get("motion"))
        if self._is_grab(d, st):
            motion = (int(self.grab), motion[1])
        elif motion is None or motion[0] in mschema.FREE_BANKS:
            motion = mcheck.parse_motion(st.get("ctn")) or motion
        if motion is None:
            self.report({"ERROR"}, "The stage has no motion= or ctn= to read the script of")
            return {"CANCELLED"}
        path = f"chartbl\\{character}.ctn"
        try:
            data = context.scene.albam.rfs.get_vfile("dmc4", path).get_bytes()
        except (KeyError, AttributeError):
            self.report({"ERROR"}, f"{path} isn't in Game Files (add the character's extracted arc folder)")
            return {"CANCELLED"}
        try:
            found, notes = mextract.script_elements(data, *motion)
        except ValueError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        for e in d.children(st):
            if e.tag in ("cancel", "trigger"):
                item = elem_by_uid(move, e.uid)
                remove_marker(context, move, item)
                d.remove(e)
        for tag, attrs in found:
            d.add(tag, st, attrs, after=([c for c in d.children(st) if c.tag in ("slot", "cancel", "trigger")]
                                         or [None])[-1])
        store_doc(move, d)
        make_markers(context, move)
        self.report({"INFO"}, f"{len(found)} element(s) from .ctn bank {motion[0]} slot {motion[1]:#x}" +
                    (f"; {'; '.join(notes)}" if notes else ""))
        return {"FINISHED"}


# ---- the panel ------------------------------------------------------------------------------------------------

def _summary(elem):
    spec = mschema.ELEMENTS.get(elem.key)
    parts = []
    for a in elem.attrs:
        if spec is not None and spec.frame == a.name:
            parts.insert(0, f"@{a.value}")
        elif a.name in ("name", "dir", "block", "categories", "kind", "byte", "value", "to", "id", "list", "index",
                        "command", "motion", "bank", "path", "move", "category", "on", "efl", "entry", "attack",
                        "ticks"):
            parts.append(a.value if a.name in ("name", "categories", "dir", "to") else f"{a.name}={a.value}")
    return " ".join(parts)


@blender_registry.register_blender_type
class ALBAM_UL_Moves(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        root = item.elems[0] if len(item.elems) else None
        overlay = root is not None and root.attrs.get("overlay") is not None and \
            root.attrs["overlay"].value == "true"
        layout.label(text=move_name(item) or "(no name)", icon="ANIM" if not overlay else "MOD_ARRAY")
        sub = layout.row()
        sub.alignment = "RIGHT"
        ident = root.attrs.get("id") or root.attrs.get("ids") if root is not None else None
        sub.label(text=ident.value if ident is not None else "")


@blender_registry.register_blender_type
class ALBAM_UL_MoveElems(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        depth, parent = 0, item.parent
        uids = {e.uid: e for e in data.elems}
        while parent in uids:
            depth += 1
            parent = uids[parent].parent
        row = layout.row(align=True)
        for _ in range(depth):
            row.separator(factor=1.5)
        known = item.key in mschema.ELEMENTS
        row.label(text=f"<{item.tag}>", icon="KEYFRAME" if item.marker else "DOT")
        sub = row.row()
        sub.active = known
        sub.label(text=_summary(item) if known else "(not read by the runner, kept)")


def entry_label(context, move, elem):
    """What an element's entry= picks from its .atk: "14 Dropkick", or why it can't say"""
    if elem.tag == "shell" and elem.attrs.get("attack") is not None:
        return "(from the attack)"
    atk = elem.attrs.get("atk")
    character = move.elems[0].attrs.get("character") if len(move.elems) else None
    path = atk.value if atk is not None else "Collision\\" + (character.value if character else "pl000")
    names = atk_names(context, path)
    if names is None:
        return "(.atk not in Game Files)"
    entry = elem.attrs.get("entry")
    index = mcheck.resolve_entry(names, entry.value if entry is not None else "0")
    if index is None:
        return "(no such entry)"
    return f"{index} {names[index] or '(no name)'}"


class MoveDefPanelBase:
    bl_category = "Albam [Beta]"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_context = "action"
    bl_region_type = "UI"


@blender_registry.register_blender_type
class ALBAM_PT_MoveDefs(MoveDefPanelBase, bpy.types.Panel):
    """MoveDef move files (dmc4_hook runner): authored from the LMT animations"""
    bl_idname = "ALBAM_PT_MoveDefs"
    bl_label = "Moves (MoveDef)"

    def draw(self, context):
        layout = self.layout
        defs = context.scene.albam.movedefs
        row = layout.row()
        row.template_list("ALBAM_UL_Moves", "moves", defs, "moves", defs, "active", rows=3)
        col = row.column(align=True)
        col.operator("albam.movedef_new", icon="ADD", text="")
        col.operator("albam.movedef_remove", icon="REMOVE", text="")
        col.separator()
        col.operator("albam.movedef_import", icon="IMPORT", text="")
        move = active_move(context)
        if move is None:
            layout.label(text="New Move works from the selected LMT animation", icon="INFO")
            return
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop_search(move, "lmt_group", context.scene.albam.lmt_groups, "anim_group", text="LMT")
        row = layout.row(align=True)
        row.operator("albam.movedef_check", icon="CHECKMARK")
        row.operator("albam.movedef_write", icon="EXPORT", text="Write XML")
        if move.xml_path:
            layout.label(text=bpy.path.abspath(move.xml_path), icon="FILE")
        if move.report:
            box = layout.box()
            for line in move.report.split("\n"):
                kind, _, text = line.partition(": ")
                box.label(text=text, icon="ERROR" if kind == "error" else "INFO")


@blender_registry.register_blender_type
class ALBAM_PT_MoveDefElements(MoveDefPanelBase, bpy.types.Panel):
    bl_idname = "ALBAM_PT_MoveDefElements"
    bl_parent_id = "ALBAM_PT_MoveDefs"
    bl_label = "Elements"

    @classmethod
    def poll(cls, context):
        move = active_move(context)
        return move is not None and len(move.elems) > 0

    def draw(self, context):
        layout = self.layout
        move = active_move(context)
        row = layout.row()
        row.template_list("ALBAM_UL_MoveElems", "elems", move, "elems", move, "active_elem", rows=8,
                          sort_lock=True)
        col = row.column(align=True)
        col.operator("albam.movedef_add_element", icon="ADD", text="")
        col.operator("albam.movedef_remove_element", icon="REMOVE", text="")
        col.separator()
        col.operator("albam.movedef_extract_ctn", icon="IMPORT", text="")
        try:
            elem = move.elems[move.active_elem]
        except IndexError:
            return
        spec = mschema.ELEMENTS.get(elem.key)
        box = layout.box()
        box.label(text=f"<{elem.tag}>: {spec.help}" if spec else f"<{elem.tag}>: not read by the runner (kept)")
        col = box.column(align=True)
        for a in elem.attrs:
            row = col.row(align=True)
            split = row.split(factor=0.38, align=True)
            op = split.operator("albam.movedef_attr_info", text=a.name, emboss=False)
            op.key, op.attr = elem.key, a.name
            kind = _kind(a)
            if kind in ("int", "hex"):
                split.prop(a, "v_int" if mcheck.parse_int(a.value) is not None or not a.value else "value",
                           text="")
            elif kind == "float":
                split.prop(a, "v_float" if mcheck.parse_float(a.value) is not None else "value", text="")
            elif kind == "frame":
                split.prop(a, "v_frame", text="")
            elif kind == "bool":
                split.prop(a, "v_bool", text="", toggle=True)
            elif kind in ("enum", "attackref"):
                split.prop(a, "v_enum", text="")
            elif kind == "entry":
                split.prop(a, "value", text="")
                split.label(text=entry_label(context, move, elem))
            elif kind == "cats":
                cats = split.row(align=True)
                for i, c in enumerate(mschema.CATEGORIES):
                    cats.prop(a, "v_cats", index=i, text=c[2:], toggle=True)
            else:
                split.prop(a, "value", text="")
            rm = row.operator("albam.movedef_remove_attr", text="", icon="X", emboss=False)
            rm.attr = a.name
        box.operator("albam.movedef_add_attr", icon="ADD", text="Add Attribute")
