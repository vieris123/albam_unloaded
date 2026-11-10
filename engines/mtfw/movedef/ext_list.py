"""ModelExtension lists: `nativePC\\model_ext\\*.xml`, read by dmc4_hook's ModelExtension (src/dev/model_ext/ModelExtension.cpp),
which owns the format (`Vibed\\ModelExt\\schema.md`): every element and attribute here is one it reads. Pure Python.

The text handling is MoveDef's (`doc.py`: a file comes back byte for byte apart from what was edited, elements the
runner doesn't read are kept). `issues` reports what the runner would warn about or refuse.
"""
import re
from collections import namedtuple

from .doc import new_doc, parse as parse_doc

ROOT = "extensions"
DEFAULT_LINE = 29       # model_attach::kDefaultLine

Attr = namedtuple("Attr", "name kind default help")

ELEMENTS = {
    "attach": (
        Attr("path", "model", "", "The model to attach: its game path, without extension"),
        Attr("to", "model", "", "The model it goes on. Every live model with this path gets one"),
        Attr("joint", "int", "", "Rigid: the joint number of the owner it rides on (-1 = the owner's root). Giving a "
                                 "joint makes the mode rigid unless Mode says otherwise"),
        Attr("mode", "mode", "", "skin: every joint with the owner's number copies the owner's joint, the others stay "
                                 "free for chains. rigid: the whole model rides one joint. Absent: rigid with a "
                                 "joint, else skin"),
        Attr("pos", "vec3", "0 0 0", "Rigid: position in the joint's frame, in cm (x y z)"),
        Attr("rot", "vec3", "0 0 0", "Rigid: rotation in the joint's frame, degrees about x, then y, then z"),
        Attr("scale", "scale", "1", "Rigid: scale, one number or x y z"),
        Attr("line", "int", str(DEFAULT_LINE), "The move line the model updates on (0-31). It has to run after its "
                                               "owner's: leave it unless you know the order"),
    ),
    "model": (
        Attr("path", "model", "", "The model these chains go on: its game path, without extension"),
        Attr("collision_model", "model", "", "The model the chains' .col shapes sit on, for the chains here that don't "
                                             "name their own"),
    ),
    "chain": (
        Attr("clt", "chain", "", "The chain file's game path, without extension. It has to be named .clt on disk "
                                 "(Albam's .phs)"),
        Attr("col", "col", "", "The .col with the shapes it collides with, without extension. Needs a collision model"),
        Attr("collision_model", "model", "", "The model carrying those shapes. Absent: the one of the <model> above"),
    ),
    "hide": (
        Attr("path", "model", "", "A model not to draw. It stays loaded and animated, so a chain or a collision shape "
                                  "can still use it"),
    ),
    "pin": (
        Attr("joint", "joint", "", "The joint of this model that follows"),
        Attr("to", "source", "", "The joint it follows, on the source model"),
        Attr("of", "of", "", "The source model. Absent: the model this one is attached to (itself if none). self: this "
                             "model"),
        Attr("mode", "pin", "all", "all: the whole matrix. rot: only the rotation, the joint keeps its animated position"),
        Attr("blend", "blend", "1", "0-1: how far from the joint's own animation to the result"),
        Attr("pos", "vec3", "0 0 0", "Offset in the source joint's frame, in cm (x y z)"),
        Attr("rot", "vec3", "0 0 0", "Offset rotation, degrees about x, then y, then z"),
        Attr("scale", "scale", "1", "Offset scale, one number or x y z"),
    ),
    "aim": (
        Attr("joint", "joint", "", "The joint of this model that turns"),
        Attr("to", "source", "", "The joint it points at, on the source model: only that joint's position counts"),
        Attr("of", "of", "", "The source model. Absent: the model this one is attached to (itself if none). self: this "
                             "model"),
        Attr("axis", "axis", "+z", "The joint's axis that points at the target: x, +x, -x, y, ..."),
        Attr("up", "axis", "+y", "The joint's axis kept closest to where the animation left it. It needs a different "
                                 "letter from Axis, or the game refuses the entry"),
        Attr("blend", "blend", "1", "0-1: how far from the joint's own animation to the aim"),
        Attr("limit", "scale", "", "The most it may turn from the animation, in degrees either way: one number, or x y z "
                                   "for the joint's axes. The preview doesn't apply this limit"),
    ),
    "offset": (
        Attr("joint", "joint", "", "The joint of this model to move, turn or scale"),
        Attr("pos", "vec3", "0 0 0", "Position in the joint's frame, in cm (x y z)"),
        Attr("rot", "vec3", "0 0 0", "Rotation, degrees about x, then y, then z"),
        Attr("scale", "scale", "1", "Scale, one number or x y z"),
        Attr("add", "bool", "true", "true: on top of the animation. false: replaces the joint's animated place relative "
                                    "to its parent"),
    ),
    "link": (
        Attr("a", "joint", "", "A joint of this model held by one of its chains"),
        Attr("b", "joint", "", "The other joint, held by the same chain or another one of this model's chains. Not two "
                               "tendril roots: a root keeps its animated place, so its partner takes the whole pull"),
        Attr("max", "length", "", "The farthest apart they may be, in cm. Nothing happens while they're closer; the rest "
                                  "distance or a little more keeps neighbouring tendrils from parting"),
        Attr("stiffness", "unit", "1", "0-1: how much of the excess distance is taken out on each of the runner's 4 "
                                       "passes"),
    ),
}
_WEIGHT_LIST = (
    Attr("speed", "number", "1", "Curve frames per game frame. Negative plays backwards, 0 holds Frame"),
    Attr("rate", "number", "1", "This list's share when several play: a key's weight is the sum of each list's curve "
                                "x rate, divided by the sum of the rates"),
    Attr("frame", "number", "0", "The curve frame the list starts on"),
    Attr("loop", "bool", "true", "true: starts over after its last frame. false: stops on its last frame"),
)
ELEMENTS["shape"] = (
    Attr("shp", "shape", "", "The morph targets (.shp, without extension). Albam writes it beside the .mod, at the "
                             "model's path, from the meshes' shape keys"),
    Attr("shw", "weights", "", "The weight list (.shw, without extension) played from the start, list 0. Albam writes "
                               "<model>.shw (the keys' set values) and <model>_<clip>.shw per shape-key action beside "
                               "the .mod. The same as a first <weights>"),
) + _WEIGHT_LIST
ELEMENTS["weights"] = (
    Attr("shw", "weights", "", "Another weight list (.shw, without extension), playing with the others"),
) + _WEIGHT_LIST
MAX_WEIGHT_LISTS = 4    # cShape::WeightNode[4]
# dmc4_hook's chain solver (sdk/ChainSolver.cpp; the algorithm is Vibed/ModelExt/chain_solver.md)
ELEMENTS["physics"] = (
    Attr("clt", "chain", "", "The chain file this model's chains with it are solved for: its game path, without "
                             "extension. The game's own chains count (Nero's coat: pl000_03_00 .. _05 on pl000_03)"),
    Attr("substeps", "count", "4", "Steps per 60 fps frame, 1-16. More keeps fast moves from carrying a segment "
                                   "through a collision shape"),
    Attr("iterations", "count", "2", "Constraint passes per step, 1-8"),
    Attr("stiffness", "unit", "0", "0-1 per frame: each segment turns toward its animated direction (keeps a skirt's "
                                   "shape)"),
    Attr("pin", "unit", "0", "0-1 per frame: each point moves toward its animated place"),
    Attr("inertia", "unit", "", "0-1: how much of the model's motion the chain lags behind. Absent: 0 if the chain "
                                "file has Follow Position, Follow Height Only or Follow Rotation on, else 1"),
    Attr("limit", "degrees", "0", "Degrees a segment may leave its animated direction, 0-180. 0 = no limit"),
    Attr("friction", "unit", "0.2", "0-1 per frame: sliding speed lost while a point touches a shape or the floor"),
    Attr("radius", "cm", "", "The segments' radius against the collision shapes, in cm. Absent: the chain file's "
                             "collision radius (mCollisionSize)"),
    Attr("ground", "bool", "false", "true: every point stays above the stage floor (a line cast per point per frame)"),
    Attr("self", "bool", "false", "true: the chain's tendrils push each other apart"),
    Attr("axis", "axis", "", "The joint axis aimed down the chain: x, +x, -x, ... (+z works here, the game's solver "
                             "can't). Absent: the chain file's mDir"),
)
RANGES = {("physics", "substeps"): (1, 16), ("physics", "iterations"): (1, 8), ("physics", "limit"): (0.0, 180.0)}
# tendrils on that solver joined into one sheet (chain_solver.md "Sheets")
ELEMENTS["cloth"] = (
    Attr("roots", "roots", "", "The first joint of each tendril, in order across the sheet, two or more (Nero's coat: "
                               "1 8 14 20 26 32). Each must start a tendril of a chain on this model that a <physics> "
                               "entry puts on dmc4_hook's solver. A <cloth> can't cross models"),
    Attr("closed", "bool", "false", "true: the last tendril joins the first too (a skirt all the way round). The coats "
                                    "are open at the front"),
    Attr("stretch", "unit", "1", "0-1 per frame: neighbouring tendrils keep their animated distance, point by point"),
    Attr("shear", "unit", "0.5", "0-1 per frame: the diagonals between neighbours, which stop the sheet skewing"),
    Attr("bend", "unit", "0", "0-1 per frame: each tendril and the one after next, which resists folding across the "
                              "sheet"),
)
MAX_CLOTH_ROOTS = 32        # parse_cloth reads 32 numbers at most
CONSTRAINTS = ("pin", "aim", "offset")
PARENTS = {"attach": ROOT, "model": ROOT, "hide": ROOT, "chain": "model", "pin": "model", "aim": "model", "offset": "model",
           "link": "model", "shape": "model", "weights": "shape", "physics": "model", "cloth": "model"}
REQUIRED = {"attach": ("path", "to"), "model": ("path",), "chain": ("clt",), "hide": ("path",),
            "pin": ("joint", "to"), "aim": ("joint", "to"), "offset": ("joint",), "link": ("a", "b", "max"),
            "shape": ("shp",), "weights": ("shw",), "physics": ("clt",), "cloth": ("roots",)}
EXTENSIONS = (".mod", ".phs", ".clt", ".col", ".shp", ".shw")
AXES = ("x", "+x", "-x", "y", "+y", "-y", "z", "+z", "-z")


def parse(text):
    return parse_doc(text, (ROOT,))


def new_list():
    return new_doc(ROOT)


def spec(tag, name):
    return next((a for a in ELEMENTS.get(tag, ()) if a.name == name), None)


def normalize(path):
    """A path as the runner compares it: lower case, backslashes, no trailing slash or space"""
    return path.lower().replace("/", "\\").rstrip("\\ ")


def stem(path):
    """A game path without its extension, as lists write it"""
    tail = path.replace("/", "\\").rsplit("\\", 1)[-1]
    return path[:len(path) - len(tail) + tail.index(".")] if "." in tail else path


def collision_model(d, chain):
    """The collision model a <chain> uses: its own attribute, present even when empty, else its <model>'s"""
    return chain.get("collision_model") if chain.has("collision_model") else d.parent_of(chain).get("collision_model", "")


def effective_mode(attach):
    return attach.get("mode", "rigid" if attach.has("joint") else "skin").lower()


def _floats(value):
    out = []
    for part in value.replace(",", " ").split():
        try:
            out.append(float(part))
        except ValueError:
            return None
    return out


def offset_values(elem):
    """(pos, rot, scale) of an entry, as the runner reads them: what's missing stays at its default"""
    pos, rot, scale = [0.0] * 3, [0.0] * 3, [1.0] * 3
    for target, name in ((pos, "pos"), (rot, "rot"), (scale, "scale")):
        values = _floats(elem.get(name, "")) or []
        target[:len(values[:3])] = values[:3]
    values = _floats(elem.get("scale", "")) or []
    if len(values) == 1:
        scale = values * 3
    return pos, rot, scale


def joint_number(elem, name="joint"):
    """An entry's joint number, or None while it's empty or not a number"""
    try:
        return int(elem.get(name, ""))
    except ValueError:
        return None


def blend_of(elem):
    values = _floats(elem.get("blend", "1")) or [1.0]
    return min(max(values[0], 0.0), 1.0)


def is_true(value):
    """pugixml's as_bool"""
    return value[:1] in ("1", "t", "T", "y", "Y")


def _check_elem(d, e, say):
    if e.tag not in ELEMENTS:
        if e.parent >= 0:
            say("warning", f"<{e.tag}>: the runner doesn't read this element, it's kept as it is")
        return
    if PARENTS[e.tag] != d.parent_of(e).tag:
        say("warning", f"<{e.tag}> inside <{d.parent_of(e).tag}>: the runner doesn't look for it there")
    for name, _ in e.attrs:
        if spec(e.tag, name) is None:
            say("warning", f"<{e.tag}> {name}=: the runner doesn't read this attribute")
    for name in REQUIRED[e.tag]:
        if not e.get(name, "").strip():
            say("error", f"<{e.tag}> needs {name}=")
    for a in ELEMENTS[e.tag]:
        value = e.get(a.name)
        if value is None:
            continue
        if a.kind in ("model", "chain", "col", "shape", "weights") and value.lower().endswith(EXTENSIONS):
            say("warning", f"<{e.tag}> {a.name}=\"{value}\": game paths have no extension")
        elif a.kind == "int":
            try:
                int(value)
            except ValueError:
                say("error", f"<{e.tag}> {a.name}=\"{value}\" isn't a whole number")
        elif a.kind == "mode" and value.lower() not in ("skin", "rigid"):
            say("error", f"<{e.tag}> mode=\"{value}\": skin or rigid")
        elif a.kind == "pin" and value not in ("all", "rot"):
            say("error", f"<{e.tag}> mode=\"{value}\": all or rot")
        elif a.kind in ("joint", "source") and value.strip():
            number = joint_number(e, a.name)
            if number is None or not 0 <= number <= 255:
                say("error", f"<{e.tag}> {a.name}=\"{value}\": a joint number, 0-255")
        elif a.kind == "axis" and value.lower() not in AXES:
            say("error", f"<{e.tag}> {a.name}=\"{value}\": x, +x, -x, y, ... ")
        elif a.kind in ("blend", "unit"):
            values = _floats(value)
            if not values or not 0.0 <= values[0] <= 1.0:
                say("warning", f"<{e.tag}> {a.name}=\"{value}\": 0-1, the game clamps it")
        elif a.kind == "number":
            values = _floats(value)
            if not values or len(values) != 1:
                say("error", f"<{e.tag}> {a.name}=\"{value}\": a number")
        elif a.kind == "roots":
            problem = cloth_problem(e)
            if problem is not None:
                say("error", f"<cloth> roots=\"{value}\": {problem}, the game drops it")
                continue
            numbers, left = _number_list(value, MAX_CLOTH_ROOTS)
            if left:
                say("warning", f"<cloth> roots=\"{value}\": the game reads only the first {len(numbers)} numbers")
            elif any(v != int(v) for v in numbers):
                say("warning", f"<cloth> roots=\"{value}\": joint numbers are whole numbers")
        elif a.kind in ("count", "degrees", "cm"):
            try:
                number = int(value) if a.kind == "count" else float(value)
            except ValueError:
                say("error", f"<{e.tag}> {a.name}=\"{value}\": " + ("a whole number" if a.kind == "count" else "a number"))
                continue
            low, high = RANGES.get((e.tag, a.name), (0.0, None))
            if number < low or (high is not None and number > high):
                limits = f"{low}-{high}" if high is not None else f"at least {low}"
                say("warning", f"<{e.tag}> {a.name}=\"{value}\": {limits}, the game clamps it")
        elif a.kind == "length" and value.strip():
            values = _floats(value)
            if not values or len(values) != 1 or values[0] <= 0.0:
                say("error", f"<{e.tag}> {a.name}=\"{value}\": a distance in cm, above 0")
        elif a.kind in ("vec3", "scale"):
            values = _floats(value)
            if values is None or (len(values) != 3 and not (a.kind == "scale" and len(values) == 1)):
                say("error", f"<{e.tag}> {a.name}=\"{value}\": three numbers" + (" or one" if a.kind == "scale" else ""))
    if e.tag == "attach":
        if normalize(e.get("path", "")) == normalize(e.get("to", "?")):
            say("error", f"<attach> of {e.get('path')} to itself")
        try:
            line = int(e.get("line", DEFAULT_LINE))
        except ValueError:
            line = DEFAULT_LINE
        if not 0 <= line <= 31:
            say("error", f"<attach> line={line}: the move lines are 0-31, the attachment wouldn't spawn")
        if effective_mode(e) == "skin" and any(e.has(n) for n in ("joint", "pos", "rot", "scale")):
            say("warning", f"<attach> of {e.get('path')}: skin mode ignores joint, pos, rot and scale")
    if e.tag == "chain" and e.get("col", "").strip() and not collision_model(d, e).strip():
        say("warning", f"chain {e.get('clt')}: a col with no collision model is ignored")
    if e.tag == "aim":
        axis, up = e.get("axis", "+z").lower(), e.get("up", "+y").lower()
        if axis in AXES and up in AXES and axis[-1] == up[-1]:
            say("error", f"<aim> joint {e.get('joint')}: axis and up on the same letter, the game refuses it")
    if e.tag == "link" and joint_number(e, "a") is not None and joint_number(e, "a") == joint_number(e, "b"):
        say("error", f"<link> joint {e.get('a')} to itself: the game refuses it")
    if e.tag == "shape" and len(weight_lists(d, e)) > MAX_WEIGHT_LISTS:
        say("warning", f"<shape> {e.get('shp')}: {len(weight_lists(d, e))} weight lists, the game plays the first "
                       f"{MAX_WEIGHT_LISTS}")


# Joints the game's own constraints hold, by model file name: a list entry on them is refused (schema.md "Who wins").
# Player bodies (pl009 = Dante's DT body): the hit shake (uPlayer::setVibJointCnst 0x7AF480, cCnsRandom on 1 and 13) and
# the leg IK on the ankles (cLegIkCtrl::init 0x7B0AD0: legs 14 / 15 / 16 and 18 / 19 / 20, the cCnsIK on the ankle).
# Sub-models: their own joints that cCnsMatrix pins to the body (face 0-4, hair 0-1, coats; setupDanteModel 0x7B54D0,
# setupMajinModel 0x7B61C0).
_BODY = {1: "the hit shake", 13: "the hit shake", 16: "the leg IK", 20: "the leg IK"}
_FACE = {n: "the face's pin to the body" for n in range(5)}
_HAIR = {n: "the hair's pin to the body" for n in range(2)}
_DANTE_COAT = {n: "the coat's pin to the body" for n in range(8)}
GAME_HELD = {"pl000": _BODY, "pl006": _BODY, "pl009": _BODY, "pl000_01": _FACE, "pl006_01": _FACE,
             "pl000_02": _HAIR, "pl006_02": _HAIR, "pl000_03": {0: "the coat's pin to the body"},
             "pl006_03": _DANTE_COAT, "pl009_01": _DANTE_COAT}
# thigh and shin: an entry installs, but the leg IK rewrites them while foot planting is on
LEG_IK_SOLVED = {14, 15, 18, 19}
PLAYER_BODIES = ("pl000", "pl006", "pl009")


def _file(model_path):
    return normalize(model_path).rsplit("\\", 1)[-1]


def game_held(model_path, number):
    """What of the game's holds this joint of the model, or None"""
    return GAME_HELD.get(_file(model_path), {}).get(number)


def constraints(d):
    """The <pin> / <aim> / <offset> entries of a list, with their <model>"""
    return [(e, d.parent_of(e)) for e in d.elems if e.tag in CONSTRAINTS and d.parent_of(e).tag == "model"]


def links(d):
    """The <link> entries of a list, with their <model> (not constraints: they hold no joint, schema.md "<link>")"""
    return [(e, d.parent_of(e)) for e in d.elems if e.tag == "link" and d.parent_of(e).tag == "model"]


def shapes(d):
    """The <shape> entries of a list, with their <model>"""
    return [(e, d.parent_of(e)) for e in d.elems if e.tag == "shape" and d.parent_of(e).tag == "model"]


def weight_lists(d, shape):
    """The elements of a <shape> naming a weight list: itself when it has shw=, then its <weights>"""
    return ([shape] if shape.get("shw", "").strip() else []) + d.children(shape, "weights")


def physics(d):
    """The <physics> entries of a list, with their <model>"""
    return [(e, d.parent_of(e)) for e in d.elems if e.tag == "physics" and d.parent_of(e).tag == "model"]


def axis_code(value):
    """the runner's parse_axis: 0-5 = +x +y +z -x -y -z, None if it isn't one"""
    value = value.strip().lower()
    if value not in AXES:
        return None
    return "xyz".index(value[-1]) + (3 if value[0] == "-" else 0)


def _leading(value, kind):
    """pugixml's as_int / as_float on a present attribute: the leading number of the text, else 0"""
    pattern = r"[+-]?\d+" if kind is int else r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?"
    match = re.match(pattern, value.strip())
    return kind(match.group(0)) if match else kind(0)


def cloths(d):
    """The <cloth> entries of a list, with their <model>"""
    return [(e, d.parent_of(e)) for e in d.elems if e.tag == "cloth" and d.parent_of(e).tag == "model"]


def _number_list(value, limit):
    """the runner's parse_floats: numbers separated by spaces / commas / tabs, up to `limit`, stopping at the first
    thing that isn't one. (numbers, whether text was left unread)"""
    out, rest = [], value
    while rest.strip() and len(out) < limit:
        match = re.match(r"\s*([+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)", rest)
        if not match:
            break
        out.append(float(match.group(1)))
        rest = rest[match.end():].lstrip(" ,\t")
    return out, bool(rest.strip())


def cloth_problem(e):
    """why the runner drops a <cloth> on its own (parse_cloth), or None"""
    numbers, _ = _number_list(e.get("roots", ""), MAX_CLOTH_ROOTS)
    roots = [int(v) for v in numbers]
    if len(roots) < 2:
        return "needs roots=, two or more joint numbers"
    for i, root in enumerate(roots):
        if not 0 <= root <= 255:
            return f"root {root} isn't a joint number 0-255"
        if root in roots[:i]:
            return f"root {root} is listed twice"
    return None


def cloth_values(e):
    """A <cloth> entry as the runner reads it: {roots (joint numbers, sheet order), closed, stretch, shear, bend}, or
    None when it drops the entry (cloth_problem)"""
    if cloth_problem(e) is not None:
        return None

    def unit(name, default):
        return min(max(_leading(e.get(name), float), 0.0), 1.0) if e.has(name) else default
    return {"roots": [int(v) for v in _number_list(e.get("roots", ""), MAX_CLOTH_ROOTS)[0]],
            "closed": is_true(e.get("closed", "false")), "stretch": unit("stretch", 1.0),
            "shear": unit("shear", 0.5), "bend": unit("bend", 0.0)}


def physics_values(e):
    """A <physics> entry's settings as the runner reads them (ModelExtension.cpp parse_physics): clamped, inertia /
    radius / axis None when absent (from the chain file). None when the runner drops the entry (no clt, bad axis)."""
    if not e.get("clt", "").strip():
        return None
    out = {}

    def number(name, kind, default, low, high):
        value = _leading(e.get(name, ""), kind) if e.has(name) else default
        return min(max(value, low), high) if high is not None else max(value, low)
    out["substeps"] = number("substeps", int, 4, 1, 16)
    out["iterations"] = number("iterations", int, 2, 1, 8)
    out["stiffness"] = number("stiffness", float, 0.0, 0.0, 1.0)
    out["pin"] = number("pin", float, 0.0, 0.0, 1.0)
    out["inertia"] = number("inertia", float, 1.0, 0.0, 1.0) if e.has("inertia") else None
    out["limit"] = number("limit", float, 0.0, 0.0, 180.0)
    out["friction"] = number("friction", float, 0.2, 0.0, 1.0)
    out["radius"] = number("radius", float, 0.0, 0.0, None) if e.has("radius") else None
    out["ground"] = is_true(e.get("ground", "false"))
    out["self"] = is_true(e.get("self", "false"))
    out["axis"] = None
    if e.has("axis"):
        out["axis"] = axis_code(e.get("axis"))
        if out["axis"] is None:
            return None
    return out


def link_values(e):
    """(a, b, max cm, stiffness) as the runner reads them; None while a joint or max isn't usable"""
    a, b = joint_number(e, "a"), joint_number(e, "b")
    length = _floats(e.get("max", ""))
    stiffness = _floats(e.get("stiffness", "1")) or [1.0]
    if a is None or b is None or a == b or not length or length[0] <= 0.0:
        return None
    return a, b, length[0], min(max(stiffness[0], 0.0), 1.0)


def issues(lists):
    """[(level "error" / "warning", file name, message)] for `lists` = [(file name, Doc)]: all the lists the game reads
    together, in the game's order, since a joint's first entry wins across files"""
    out = []
    attached, taken, shaped, solved, sheeted = set(), set(), set(), set(), {}
    for name, d in sorted(lists, key=lambda item: item[0]):
        for e, model in shapes(d):
            path = normalize(model.get("path", ""))
            if path and path in shaped:
                out.append(("warning", name, f"{model.get('path')} has a <shape> already: the first listed wins"))
            shaped.add(path)
        for e, model in physics(d):
            key = (normalize(model.get("path", "")), normalize(e.get("clt", "")))
            if key[1] and key in solved:
                out.append(("warning", name, f"<physics> {e.get('clt')} on {model.get('path')} is listed already: the "
                                             "first listed wins"))
            solved.add(key)
        for e, model in cloths(d):
            values = cloth_values(e)
            if values is None:
                continue
            path = normalize(model.get("path", ""))
            used = sheeted.setdefault(path, set())
            shared = [r for r in values["roots"] if r in used]
            if shared:
                out.append(("warning", name, f"<cloth> on {model.get('path')}: root {shared[0]} is in an earlier <cloth>: "
                                             "a tendril takes one sheet, so the game drops this one"))
                continue
            used.update(values["roots"])
        for e in d.elems:
            _check_elem(d, e, lambda level, message, name=name: out.append((level, name, message)))
        for attach in d.children(d.root, "attach"):
            path = normalize(attach.get("path", ""))
            if path and path in attached:
                out.append(("warning", name, f"{attach.get('path')} is attached twice: check it goes on different models"))
            attached.add(path)
        for e, model in constraints(d):
            held = game_held(model.get("path", ""), joint_number(e))
            if held is not None:
                out.append(("warning", name, f"<{e.tag}> joint {joint_number(e)} of {model.get('path')}: the game holds it "
                                             f"({held}), so it refuses this entry"))
            elif _file(model.get("path", "")) in PLAYER_BODIES and joint_number(e) in LEG_IK_SOLVED:
                out.append(("warning", name, f"<{e.tag}> joint {joint_number(e)} of {model.get('path')}: the leg IK "
                                             "overrides it while the feet are planted"))
            key = (normalize(model.get("path", "")), joint_number(e))
            if key[1] is not None and key in taken:
                out.append(("warning", name, f"<{e.tag}> joint {key[1]} of {model.get('path')}: the joint already has an "
                                             "entry, the first in file order wins"))
            taken.add(key)
    return out
