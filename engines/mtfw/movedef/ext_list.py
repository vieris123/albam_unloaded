"""ModelExtension lists: `nativePC\\model_ext\\*.xml`, read by dmc4_hook's ModelExtension (src/dev/model_ext/ModelExtension.cpp),
which owns the format (`Vibed\\ModelExt\\schema.md`): every element and attribute here is one it reads. Pure Python.

The text handling is MoveDef's (`doc.py`: a file comes back byte for byte apart from what was edited, elements the
runner doesn't read are kept). `issues` reports what the runner would warn about or refuse.
"""
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
CONSTRAINTS = ("pin", "aim", "offset")
PARENTS = {"attach": ROOT, "model": ROOT, "hide": ROOT, "chain": "model", "pin": "model", "aim": "model", "offset": "model",
           "link": "model", "shape": "model", "weights": "shape"}
REQUIRED = {"attach": ("path", "to"), "model": ("path",), "chain": ("clt",), "hide": ("path",),
            "pin": ("joint", "to"), "aim": ("joint", "to"), "offset": ("joint",), "link": ("a", "b", "max"),
            "shape": ("shp",), "weights": ("shw",)}
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
    attached, taken, shaped = set(), set(), set()
    for name, d in sorted(lists, key=lambda item: item[0]):
        for e, model in shapes(d):
            path = normalize(model.get("path", ""))
            if path and path in shaped:
                out.append(("warning", name, f"{model.get('path')} has a <shape> already: the first listed wins"))
            shaped.add(path)
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
