"""ModelExtension lists: `nativePC\\model_ext\\*.xml`, read by dmc4_hook's ModelExtension (src/dev/model_ext/ModelExtension.cpp,
`reload` / `parse_attach`), which owns the format: every element and attribute here is one it reads. Pure Python.

The text handling is MoveDef's (`doc.py`: a file comes back byte for byte apart from what was edited, elements the
runner doesn't read are kept). `issues` reports what the runner would warn about, plus what it can't: lists load in
sorted name order and a chain looks up its collision model when it spawns, so a collision model that isn't out yet
leaves the chain silently without collision.
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
}
PARENTS = {"attach": ROOT, "model": ROOT, "hide": ROOT, "chain": "model"}
REQUIRED = {"attach": ("path", "to"), "model": ("path",), "chain": ("clt",), "hide": ("path",)}
EXTENSIONS = (".mod", ".phs", ".clt", ".col")


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


def rigid_offset(attach):
    """(pos, rot, scale) of a rigid <attach>, as the runner reads them: what's missing stays at its default"""
    pos, rot, scale = [0.0] * 3, [0.0] * 3, [1.0] * 3
    for target, name in ((pos, "pos"), (rot, "rot"), (scale, "scale")):
        values = _floats(attach.get(name, "")) or []
        target[:len(values[:3])] = values[:3]
    values = _floats(attach.get("scale", "")) or []
    if len(values) == 1:
        scale = values * 3
    return pos, rot, scale


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
        if a.kind in ("model", "chain", "col") and value.lower().endswith(EXTENSIONS):
            say("warning", f"<{e.tag}> {a.name}=\"{value}\": game paths have no extension")
        elif a.kind == "int":
            try:
                int(value)
            except ValueError:
                say("error", f"<{e.tag}> {a.name}=\"{value}\" isn't a whole number")
        elif a.kind == "mode" and value.lower() not in ("skin", "rigid"):
            say("error", f"<{e.tag}> mode=\"{value}\": skin or rigid")
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


def issues(lists):
    """[(level "error" / "warning", file name, message)] for `lists` = [(file name, Doc)]: all the lists the game reads
    together, since a collision model's order runs across files"""
    out = []
    order = {}
    ordered = sorted(lists, key=lambda item: item[0])
    for name, d in ordered:
        for e in d.elems:
            _check_elem(d, e, lambda level, message, name=name: out.append((level, name, message)))
        for attach in d.children(d.root, "attach"):
            path = normalize(attach.get("path", ""))
            if path and path in order:
                out.append(("warning", name, f"{attach.get('path')} is attached twice: check it goes on different models"))
            order.setdefault(path, len(order))
    for name, d in ordered:
        for chain in (e for e in d.elems if e.tag == "chain"):
            model = normalize(d.parent_of(chain).get("path", ""))
            other = normalize(collision_model(d, chain))
            if not chain.get("col", "").strip() or other == model or other not in order:
                continue
            if order[other] > order.get(model, -1):
                out.append(("warning", name, f"chain {chain.get('clt')}: its collision model {other} is attached after "
                                             f"{model}, so the chain would spawn without collision. Attach it first: "
                                             "same list, earlier in the file, or a list earlier by name"))
    return out
