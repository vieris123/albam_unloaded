"""The MoveDef elements and attributes the dmc4_hook runner reads (`Vibed/MoveDef/schema.md` "Implemented",
`dev/movedef/XmlMove.cpp`), with the runner's default for each attribute and a plain-language help line (the Blender
panel's tooltips). Nothing here invents format: an element or attribute the runner doesn't read is not listed (a file
may still carry one; the reader keeps it as it is).

Kinds: int, hex (an int written as 0x..), float, bool, enum (one of `items`; other text is kept as typed), str, motion
("bank:slot"), frame (a motion frame at 60 fps; in Blender a pose marker), cats (space-separated cancel categories).
"""

MIN_ID = {"pl000": 0x34, "pl006": 0x6C}      # first free atckId per character (MoveDef.cpp MIN_ID: Nero, Dante)
FREE_BANKS = range(10, 15)                    # fixed banks an <lmt bank=> may name (10-14)
OWN = "lmt"                                   # bank key of the move's own <lmt> blocks (block=, <slot>s)
# banks the motion registry fills per character (schema.md: 10-14, Nero's 4 / 6-9 too); motion= may not name them
RUNTIME_BANKS = {"pl000": frozenset((4, 6, 7, 8, 9, 10, 11, 12, 13, 14)), "pl006": frozenset(FREE_BANKS)}
MAX_MOTION_BANK = 15                          # the motion word's bank is one nibble
# Nero's Buster grabs play from motion bank 15 (the grabbed enemy's LMT, motion\pl000\<target>\pl000_<target>_00);
# their scripts are .ctn banks 10-29, one per target (Vibed/RE/chartbl_ctn_hang.md, setShortGrabEnemyReactionFunc)
GRAB_BANK = 15
GRAB_CTN_BANKS = {10: "em000", 11: "em003", 12: "em005", 13: "em006", 14: "em010", 15: "em011", 16: "em012",
                  17: "em013", 18: "em015", 19: "em016", 20: "em017", 21: "em018", 22: "em019", 23: "em021",
                  24: "em022", 25: "em023", 26: "em026", 27: "pl006", 28: "pl002", 29: "pl023"}
MAX_SHELLS = 8                                # <shell>s used per stage
MAX_CANCEL_WORDS = 5                          # the row's cancelId words

CHARACTERS = (("pl000", "Nero", "Nero (pl000)"), ("pl006", "Dante", "Dante (pl006)"))
CATEGORIES = ("C_NORM0", "C_NORM1", "C_NORM2", "C_COMMAND", "C_JUMP", "C_CHOUHATSU", "C_GUN", "C_ALL")
CONTACT_BYTES = ("atck", "free2", "camVib", "free1", "free0", "padVib")   # contact set 0, info index 0-5
BUTTONS = ("melee", "gun", "jump", "lockon", "style")
DIRECTIONS = ("forward", "down", "back", "left", "right", "up")

_CATEGORY_HELP = {
    "C_NORM0": "the melee attacks' window (strings, the next hit)",
    "C_NORM1": "second melee window (vanilla files use C_NORM0 only)",
    "C_NORM2": "third melee window",
    "C_COMMAND": "command moves (lock-on + stick + button)",
    "C_JUMP": "jumps, the enemy step and the air hike",
    "C_CHOUHATSU": "the taunt",
    "C_GUN": "gun moves",
    "C_ALL": "everything else (walking, guarding, other actions)",
}


def _items(*names, helps=None):
    helps = helps or {}
    return tuple((n, n, helps.get(n, n)) for n in names)


class Attr:
    __slots__ = ("name", "kind", "default", "help", "items", "required")

    def __init__(self, name, kind, default, help, items=(), required=False):
        self.name, self.kind, self.default, self.help = name, kind, default, help
        self.items, self.required = items, required


class Element:
    """`frame` names the attribute that is a motion frame (a pose marker in Blender), `multiple` whether the parent
    may hold several, `children` the element keys allowed inside, `starter` the attributes a new one is made with."""
    __slots__ = ("key", "tag", "help", "attrs", "children", "multiple", "frame", "starter")

    def __init__(self, key, help, attrs, children=(), multiple=False, frame=None, starter=None):
        self.key, self.help, self.attrs, self.children = key, help, {a.name: a for a in attrs}, children
        self.tag = key.split(".")[-1]
        self.multiple, self.frame = multiple, frame
        self.starter = starter if starter is not None else tuple(a.name for a in attrs if a.required)


_CHAR = _items("pl000", "pl006", helps={"pl000": "Nero", "pl006": "Dante"})
_BTN = _items(*BUTTONS, helps={"lockon": "lock-on"})
_CATS = _items(*CATEGORIES, helps=_CATEGORY_HELP)
_BYTES = _items(*CONTACT_BYTES, helps={
    "atck": "contact byte atck", "free0": "stage trigger byte free0 (read back by <next byte=>)",
    "free1": "stage trigger byte free1", "free2": "stage trigger byte free2",
    "camVib": "camera shake request (uDevilCamera::vibReq id + 1)", "padVib": "pad vibration request (1-based id)"})

# the kAttackStatus values a <shell> or an <attack> may set: (name, kind, game field, RED-ComboA_00's value = what an
# <attack> without atk / entry starts from, `kDefaultAttack` in the runner)
_ATTACK_FIELDS = (
    ("damage_type", "int", "damage reaction type", "0"),
    ("damage_type_b", "int", "second reaction type (launches ...)", "2"),
    ("level_i", "int", "attack level I", "2"),
    ("level_b", "int", "attack level B", "0"),
    ("attack_id", "int", "mAttackID", "0"),
    ("range_type", "int", "range type", "0"),
    ("hit_stop", "int", "hit stop", "3"),
    ("hitmark", "int", "hit mark effect", "7"),
    ("hit_se", "int", "hit sound", "0"),
    ("attack_flag", "hex", "attack flags", "0"),
    ("blown_angle", "int", "blown angle type (knock direction rule)", "0"),
    ("element", "int", "element", "0"),
    ("damage", "float", "damage", "80"),
    ("stylish_point", "float", "style points", "130"),
    ("stylish_timer", "float", "style timer", "250"),
    ("dt_add", "float", "Devil Trigger gain", "120"),
)
_SHELL_VALUES = tuple(
    Attr(name, kind, "-1", f"Override: {what} (-1 = the attack's / the entry's)")
    for name, kind, what, _ in _ATTACK_FIELDS)
_ATTACK_VALUES = tuple(
    Attr(name, kind, "-1", f"The hit's {what}. Not given (-1): the entry's, or without atk / entry Nero's "
         f"RED-ComboA_00 value ({combo})")
    for name, kind, what, combo in _ATTACK_FIELDS)
_ENTRY_HELP = ("Entry of that .atk: its index, or its name (mAsName, case-insensitive, 15 characters; 14 = "
               "Dropkick on Nero)")

_SHELL = (
    Attr("attack", "attackref", "", "An <attack> of this file the hitbox uses (instead of atk / entry); the shell's "
         "own values still override it"),
    Attr("atk", "str", "Collision\\pl000 / pl006",
         "The .atk file the attack entry is copied from (game path, no extension). Default: the character's own"),
    Attr("entry", "entry", "0", _ENTRY_HELP),
    Attr("kind", "int", "1", "Collision group kind (1 = a player attack)"),
    Attr("vsattr", "hex", "0", "Versus attribute; 0 = the game's table for the kind"),
    Attr("unitline", "hex", "0x12", "Unit line the hitbox unit runs on"),
    Attr("radius", "float", "60", "Capsule radius, cm"),
    Attr("length", "float", "120", "Capsule length along the move's direction, cm"),
    Attr("height", "float", "80", "Height of the capsule's start above the feet, cm"),
    Attr("life", "float", "90", "Ticks the hitbox lives at most (it also ends with the move)"),
    Attr("knock", "enum", "direction", "Which way hit enemies are knocked",
         _items("direction", "facing", "away", helps={
             "direction": "along the move's direction", "facing": "along the player's facing",
             "away": "away from the player"})),
    Attr("knock_angle", "float", "0", "Degrees added to the knock direction (direction / facing)"),
    Attr("one_hit", "bool", "false", "Hit each enemy once"),
    Attr("show", "bool", "false", "Draw the capsule in game (debug)"),
) + _SHELL_VALUES

_FRAME = Attr("frame", "frame", "0", "Motion frame (60 fps) it happens on: the pose marker's frame", required=True)

_LIST = (
    Element("move", "One player move: its row, input, LMT and stage. Goes in nativePC\\movedef\\", (
        Attr("name", "str", "", "The move's name: unique across the movedef folder, used by <follows> / <next> of "
             "other files and in the runner's log", required=True),
        Attr("character", "enum", "", "Whose move it is", _CHAR, required=True),
        Attr("id", "hex", "0", "atckId: Nero 0x34 and up, Dante 0x6C and up, unique; an overlay names a vanilla id",
             required=True),
        Attr("ids", "str", "", "Overlay only: every vanilla id it covers, space separated (Nero's Streak runs as 28 "
             "or 29)"),
        Attr("overlay", "bool", "false", "On: the move adds to a VANILLA move (id) instead of being a new one: no "
             "row, bank or table, its stage's <next>s / effects / cancels ride the vanilla motion"),
        Attr("version", "int", "2", "Schema version"),
    ), children=("lmt", "table", "command", "attack", "stage", "routine", "stages")),
    Element("attack", "What a hit does, for this file's <shell attack=>s: an .atk entry (atk / entry) with values "
            "overriding it, or defined by its values alone (no file entry needed)", (
        Attr("name", "str", "", "The name <shell attack=> uses; also the hit's mAsName in the game (15 characters, "
             "longer is cut), unique in the file", required=True),
        Attr("atk", "str", "", "Take the attack from this .atk (game path, no extension; entry 0 without entry=)"),
        Attr("entry", "entry", "", _ENTRY_HELP + "; alone: of the character's own .atk"),
    ) + _ATTACK_VALUES, multiple=True, starter=("name",)),
    Element("commands", "A library of shared input commands any move of the character can name in <input>", (
        Attr("character", "enum", "", "Whose commands they are", _CHAR, required=True),
    ), children=("command",)),
    Element("stages", "Optional wrapper around the <stage>s", (), children=("stage",)),
    Element("routine", "Marks an overlay on a vanilla move's own state function", (
        Attr("native", "hex", "0", "Address of the native state function"),
    )),
    Element("lmt", "The move's own LMT file, loaded at runtime (per player object)", (
        Attr("path", "str", "", "Game path of the LMT, no extension (motion\\pl000\\gerb). Without bank= the motion "
             "registry places it in a free bank; moves naming the same path share its blocks", required=True),
        Attr("bank", "int", "", "A fixed bank 10-14 instead of the registry's: reserves that bank (one LMT per bank "
             "per character). Only to match a C++ mod that still has its own bank"),
    )),
    Element("table", "The move-table row: how the game picks the move (input, string position, conditions)", (
        Attr("attr", "enum", "command", "Which button family starts it", _items(
            "melee", "gun", "command", "proper", helps={
                "melee": "the melee button", "gun": "the gun button", "command": "an input command (<input>)",
                "proper": "proper (4)"}), required=True),
        Attr("level", "int", "7", "Row level"),
        Attr("start", "bool", "true", "May start from neutral"),
        Attr("cancel", "bool", "false", "May be entered by cancelling an attack"),
        Attr("repeat", "bool", "false", "May chain into itself"),
        Attr("weapon", "int", "-1", "-1 any, or the weapon id (RedQueen 0 ... Rebellion 4, Gilgamesh 5, Lucifer 6, "
             "Coyote 7, Pandora 8, EbonyIvory 9)"),
        Attr("style", "int", "-1", "-1 any, 0 SM, 1 GS, 2 TS, 3 RG, 4 DS"),
        Attr("etc", "int", "0", "Extra condition (DT states)"),
        Attr("air", "enum", "air", "Where it may start", _items("ground", "air", "both", "fly"), required=True),
        Attr("cancel_words", "str", "", "Five cancelId words, comma separated: used as they are instead of "
             "<follows> / <window>"),
    ), children=("input", "follows", "window")),
    Element("input", "The row's input: a <command> name (this file or a shared one) or a CMD_ID number", (
        Attr("command", "str", "", "Command name or CMD_ID number", required=True),
    )),
    Element("follows", "String step: the move follows another (name or vanilla id) once its window is open", (
        Attr("move", "str", "", "The move it follows: a MoveDef name or a vanilla atckId", required=True),
        Attr("window", "enum", "", "The cancel window that must be open (takes a second cancel word)", _CATS),
        Attr("or", "bool", "false", "Or with the other entries instead of and"),
    ), multiple=True),
    Element("window", "A cancel window that must be open", (
        Attr("category", "enum", "C_NORM0", "Cancel category", _CATS, required=True),
        Attr("or", "bool", "false", "Or with the other entries instead of and"),
    ), multiple=True),
    Element("command", "An input command (lock-on + stick + button ...), one free command bit (11 in the game)", (
        Attr("name", "str", "", "Name <input command=> refers to", required=True),
        Attr("condition", "enum", "none", "What must hold while it's entered", _items(
            "none", "lockon", "dash", "laser", helps={"lockon": "lock-on held"}), required=True),
        Attr("predicate", "enum", "", "A runner-side check each tick", _items(
            "stick_sideways", helps={"stick_sideways": "the stick leans left or right of the facing"})),
        Attr("side_angle", "float", "50", "stick_sideways on a shared command: degrees from the side axis"),
        Attr("active", "int", "1", "Active flag"),
    ), children=("btn", "lever"), multiple=True),
    Element("btn", "A button step of the command", (
        Attr("id", "enum", "melee", "Button", _BTN, required=True),
        Attr("mode", "enum", "trg", "How", _items("trg", "rel", "on", helps={
            "trg": "pressed", "rel": "released", "on": "held"}), required=True),
        Attr("timer", "int", "0", "Frames allowed to the next step (0 = no limit)"),
    ), multiple=True),
    Element("lever", "A stick step of the command", (
        Attr("dir", "enum", "centred", "Stick direction", _items("centred", "forward", "back", "any"), required=True),
        Attr("mode", "enum", "target45", "Relative to", _items("target45", "target70", "screen", helps={
            "target45": "the lock-on target, 45 deg", "target70": "the lock-on target, 70 deg",
            "screen": "the screen"})),
        Attr("timer", "int", "-1", "Frames allowed to the next step (<= 0 = no limit)"),
    ), multiple=True),
    Element("stage", "What the move plays and does: motion, cancels, triggers, effects, transitions", (
        Attr("name", "str", "", "Stage name (log)", required=True),
        Attr("block", "int", "", "Block of the move's own <lmt> the stage plays, when there are no <slot>s (0-255)"),
        Attr("motion", "motion", "", "bank:slot of a vanilla motion the stage plays (an overlay's motion, a borrowed "
             "vanilla one), when there's no block= or <slot>s"),
        Attr("ctn", "motion", "", "bank:slot of a vanilla .ctn script borrowed for the motion (a runtime bank has "
             "none of its own)"),
        Attr("attr", "enum", "null_trans_off", "The motion request's attribute", _items("none", "null_trans_off")),
        Attr("interp", "float", "4", "Blend-in frames"),
        Attr("start", "float", "0", "Start frame of the motion"),
        Attr("speed", "float", "1", "Motion speed"),
        Attr("stop", "bool", "false", "Zero the velocity at entry (a stationary move)"),
        Attr("status", "enum", "", "jump: set the jump status at the launch (the air rules apply)", _items("jump")),
        Attr("land", "enum", "exit", "What a landing does (ballistic stages)", _items("exit", "none")),
        Attr("cancel_frame", "frame", "", "Open every cancel window at this frame (a pose marker)"),
        Attr("enemy_step", "bool", "true", "The enemy step may interrupt from frame 0"),
        Attr("eat_press", "enum", "", "Ignore this button until it's released once after entry", _BTN),
        Attr("watchdog", "int", "60", "Ticks without motion progress before the move bails out"),
    ), children=("slot", "cancel", "trigger", "next", "effect", "se", "kill_effect", "finish_effect", "shell",
                 "launch", "air_jump"), multiple=True, frame="cancel_frame", starter=("name",)),
    Element("slot", "The LMT block played for a stick direction", (
        Attr("dir", "enum", "forward", "Stick direction", _items(*DIRECTIONS), required=True),
        Attr("block", "int", "0", "Block (slot) of the <lmt> file", required=True),
        Attr("speed", "float", "-1", "This direction's launch speed (absent = the launch's)"),
        Attr("rise", "float", "", "This direction's launch rise (absent = the launch's)"),
        Attr("effect_roll", "float", "", "This direction's take-off effect roll (180 = upside down)"),
        Attr("damage_type_b", "int", "-1", "This direction's shell reaction (-1 = the shell's)"),
    ), multiple=True),
    Element("cancel", "A cancel window opening (or closing) at a frame", (
        _FRAME,
        Attr("kind", "enum", "open", "What the window does", _items("open", "buffer", "close", helps={
            "open": "the next attack starts at once", "buffer": "the input is kept and the attack waits for the "
            "move to allow it", "close": "close the window"})),
        Attr("categories", "cats", "", "Categories, space separated (empty = every category)"),
    ), multiple=True, frame="frame", starter=("frame", "categories")),
    Element("trigger", "Sets a contact byte at a frame (read back by <next byte=>)", (
        _FRAME,
        Attr("byte", "enum", "free0", "Contact byte", _BYTES, required=True),
        Attr("value", "int", "1", "Value", required=True),
    ), multiple=True, frame="frame"),
    Element("next", "A transition, checked every tick: fires when every condition given holds", (
        Attr("to", "str", "exit", "exit, or move:<name> (a hand-off to another move of the character)",
             required=True),
        Attr("on", "enum", "", "Condition", _items("motion_end", "landing", "always")),
        Attr("frame", "frame", "", "The motion has reached this frame (a pose marker). A looping block wraps, so a "
             "frame past its end never fires: use ticks= for a time limit"),
        Attr("ticks", "int", "-1", "This many ticks (60 a second) have passed since the stage started (an overlay: "
             "since its motion started)"),
        Attr("byte", "enum", "", "This contact byte equals value", _BYTES),
        Attr("value", "int", "1", "The value byte= must have"),
        Attr("button", "enum", "", "This button is pressed this tick (held / idle below)", _BTN),
        Attr("held", "bool", "false", "button= held instead of pressed"),
        Attr("idle", "int", "-1", "button= not pressed for this many ticks (a mash that stopped)"),
        Attr("stick", "enum", "", "Stick condition", _items("neutral")),
    ), multiple=True, frame="frame", starter=("to",)),
    Element("effect", "An effect fired at a frame", (
        _FRAME,
        Attr("list", "int", "-1", "Effect table list (with index=); or efl="),
        Attr("index", "hex", "0", "Index in the effect list"),
        Attr("efl", "str", "", "Game path of an .efl (no extension), instead of list / index"),
        Attr("joint", "enum", "self", "Where", _items("self", "weapon", helps={
            "self": "the player", "weapon": "the held weapon"})),
        Attr("group", "int", "-1", "Spawn group mask (-1 = all)"),
        Attr("material", "str", "-1", "Spawn material mask: -1 all, ground = the surface under the player"),
        Attr("unitline", "hex", "0x14", "Unit line"),
        Attr("type", "int", "0", "uPlayer::setEffect type"),
        Attr("id", "int", "-1", "Id a later kill / finish names (-1 = none)"),
        Attr("repeat", "enum", "once", "loop: fired again each time a looping motion wraps", _items("once", "loop")),
    ), multiple=True, frame="frame", starter=("frame", "list", "index")),
    Element("se", "A sound fired at a frame", (
        _FRAME, Attr("id", "int", "0", "Sound id (the player's SE resource)", required=True),
    ), multiple=True, frame="frame"),
    Element("kill_effect", "Removes the effect registered with id at a frame", (
        _FRAME, Attr("id", "int", "-1", "The <effect id=>", required=True),
    ), multiple=True, frame="frame"),
    Element("finish_effect", "Lets the effect registered with id finish at a frame", (
        _FRAME, Attr("id", "int", "-1", "The <effect id=>", required=True),
    ), multiple=True, frame="frame"),
    Element("shell", "A hitbox capsule riding the player from a frame", (_FRAME,) + _SHELL,
            multiple=True, frame="frame"),
    Element("launch", "The ballistic jump: velocity at a frame, then gravity", (
        _FRAME,
        Attr("direction", "enum", "stick", "Direction", _items("stick", "facing", "vertical", helps={
            "stick": "the stick relative to the facing (picks the <slot>)", "facing": "the facing",
            "vertical": "up on the ground, down in the air"}), required=True),
        Attr("speed", "float", "0", "Speed along the direction", required=True),
        Attr("rise", "float", "0", "Upward speed", required=True),
        Attr("gravity", "float", "0", "Added to the vertical speed every tick", required=True),
        Attr("max_fall", "float", "30", "Fall speed cap"),
        Attr("side_angle", "float", "50", "Degrees from the side axis that count as left / right"),
        Attr("face", "enum", "false", "Turn the player toward the jump", _items("false", "true", "all", helps={
            "true": "forward, left, right (a back jump keeps facing)", "all": "every direction"})),
    ), children=("launch.effect", "launch.se", "launch.shell"), frame="frame"),
    Element("launch.effect", "The take-off effect (an effect list entry at the player, leaned into the jump)", (
        Attr("list", "int", "0", "Effect table list (the air hike: Nero 1, Dante 2)", required=True),
        Attr("index", "hex", "0", "Index (the air hike: Nero 0x28, Dante 0x14)", required=True),
        Attr("tilt", "float", "0", "Degrees leaned toward the launch direction"),
        Attr("roll", "float", "0", "Degrees about forward (180 = upside down)"),
    )),
    Element("launch.se", "The take-off sound", (
        Attr("id", "int", "0", "Sound id", required=True),
    )),
    Element("launch.shell", "A hitbox capsule spawned at the launch, along its direction", _SHELL, multiple=True),
    Element("air_jump", "The move as an air jump", (
        Attr("cost", "int", "0", "Air jumps it uses up", required=True),
        Attr("required", "bool", "false", "Refuse to start with no air jump left"),
        Attr("suppress_air_hike", "bool", "false", "The air hike steps aside for this move's press"),
        Attr("per_air", "int", "0", "Starts between landings (0 = no cap)"),
    )),
)

ELEMENTS = {e.key: e for e in _LIST}
ROOTS = ("move", "commands")


def key_for(tag, parent_key):
    """The element key of `tag` inside an element with key `parent_key` (launch children are their own)"""
    if parent_key == "launch" and f"launch.{tag}" in ELEMENTS:
        return f"launch.{tag}"
    return tag


def spec_for(tag, parent_key=None):
    """The Element of `tag` inside `parent_key`, or None when the runner doesn't read it there"""
    if parent_key is None:
        return ELEMENTS.get(tag) if tag in ROOTS else None
    parent = ELEMENTS.get(parent_key)
    key = key_for(tag, parent_key)
    if parent is None or key not in parent.children:
        return None
    return ELEMENTS.get(key)
