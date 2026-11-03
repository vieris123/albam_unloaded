"""Reading and writing MoveDef XML so that a file comes back byte for byte, apart from what was edited.

A file is read into a flat list of `Elem`s in document order: every element (known to the runner or not), its
attributes as the text written in the file (entities resolved), its parent (by uid) and `src`, its position among the
source's elements. Comments, whitespace, line breaks inside tags, attribute order and quoting stay in the source text;
`write` patches that text: changed attribute values are replaced inside their tag, removed attributes and elements
cut out (with their indentation and a comment on the same line after them), new ones inserted after their previous
sibling in the list, indented like their siblings. A new file is written the same way from a source holding only the
root element.

The reader is a small tokenizer for the subset the runner's pugixml reads (elements, attributes, comments, the
declaration). Like pugixml it accepts "--" inside comments, which Python's expat rejects.

    doc = parse(text)
    doc.elems[3].set("frame", "30")
    text = doc.text()          # == the old text except for that attribute value
"""
import re

from .schema import ROOTS, key_for

DECLARATION = '<?xml version="1.0" encoding="utf-8"?>\n'
INDENT = "  "

_NAME = r"[A-Za-z_:][\w.:-]*"
_ATTR = re.compile(r"(\s+)(" + _NAME + r")(\s*=\s*)(\"[^\"]*\"|'[^']*')")
_START = re.compile(r"<(" + _NAME + r")((?:\s+" + _NAME + r"\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*(/?)>")
_END = re.compile(r"</(" + _NAME + r")\s*>")
_ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


class MoveDefError(ValueError):
    pass


class Elem:
    __slots__ = ("uid", "tag", "key", "parent", "src", "attrs")

    def __init__(self, uid, tag, key, parent=-1, src=-1, attrs=None):
        self.uid, self.tag, self.key, self.parent, self.src = uid, tag, key, parent, src
        self.attrs = [list(a) for a in (attrs or ())]

    def get(self, name, default=None):
        for k, v in self.attrs:
            if k == name:
                return v
        return default

    def has(self, name):
        return any(k == name for k, _ in self.attrs)

    def set(self, name, value):
        for a in self.attrs:
            if a[0] == name:
                a[1] = value
                return
        self.attrs.append([name, value])

    def remove(self, name):
        self.attrs = [a for a in self.attrs if a[0] != name]

    def __repr__(self):
        return f"<{self.tag} uid={self.uid} parent={self.parent} src={self.src} {self.attrs}>"


class Doc:
    def __init__(self, source, elems):
        self.source, self.elems = source, elems

    @property
    def root(self):
        return self.elems[0] if self.elems else None

    def children(self, elem, tag=None):
        uid = elem.uid if isinstance(elem, Elem) else elem
        return [e for e in self.elems if e.parent == uid and (tag is None or e.tag == tag)]

    def child(self, elem, tag):
        found = self.children(elem, tag)
        return found[0] if found else None

    def by_uid(self, uid):
        return next((e for e in self.elems if e.uid == uid), None)

    def parent_of(self, elem):
        return self.by_uid(elem.parent)

    def new_uid(self):
        return max((e.uid for e in self.elems), default=-1) + 1

    def descendants(self, elem):
        out, frontier = [], {elem.uid}
        for e in self.elems:
            if e.parent in frontier:
                out.append(e)
                frontier.add(e.uid)
        return out

    def add(self, tag, parent, attrs=(), after=None):
        """A new element (src -1) under `parent`, after `after` (an Elem) or as its parent's last child"""
        parent = parent if isinstance(parent, Elem) or parent is None else self.by_uid(parent)
        elem = Elem(self.new_uid(), tag, key_for(tag, parent.key) if parent else tag,
                    parent.uid if parent else -1, -1, attrs)
        anchor = after if after is not None else parent
        if anchor is None:
            at = len(self.elems)
        else:
            at = self.elems.index(anchor) + 1 + len(self.descendants(anchor))
        self.elems.insert(at, elem)
        return elem

    def remove(self, elem):
        gone = {elem.uid} | {e.uid for e in self.descendants(elem)}
        self.elems = [e for e in self.elems if e.uid not in gone]

    def text(self):
        return write(self.source, self.elems)


# ---- reading --------------------------------------------------------------------------------------------------

def unescape(value):
    def one(m):
        name = m.group(1)
        if name.startswith("#x") or name.startswith("#X"):
            return chr(int(name[2:], 16))
        if name.startswith("#"):
            return chr(int(name[1:]))
        return _ENTITIES.get(name, m.group(0))
    return re.sub(r"&(#?\w+);", one, value)


def escape(value):
    return value.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;").replace("\n", "&#10;")


class _Node:
    """An element of the source: its start tag (`head`), what's between its tags (`items`: text chunks and child
    nodes) and its end tag (`foot`, None when self-closing). Writing joins them back."""
    __slots__ = ("tag", "head", "items", "foot", "indent")

    def __init__(self, tag, head, foot, indent):
        self.tag, self.head, self.foot, self.indent = tag, head, foot, indent
        self.items = []

    def text(self, out):
        out.append(self.head)
        for item in self.items:
            if isinstance(item, str):
                out.append(item)
            else:
                item.text(out)
        if self.foot is not None:
            out.append(self.foot)


def _line(text, at):
    return text.count("\n", 0, at) + 1


def _tokenize(text):
    """(prolog, root _Node, epilog, nodes in document order)"""
    pos, n = 0, len(text)
    stack, nodes = [], []
    root = None
    prolog_end = None
    epilog_start = None
    last_text = ""
    while pos < n:
        lt = text.find("<", pos)
        if lt < 0:
            chunk = text[pos:]
            if stack:
                stack[-1].items.append(chunk)
            elif chunk.strip():
                raise MoveDefError(f"text after the root element (line {_line(text, pos)})")
            break
        if lt > pos:
            chunk = text[pos:lt]
            if stack:
                stack[-1].items.append(chunk)
            elif chunk.strip():
                raise MoveDefError(f"text outside the root element (line {_line(text, pos)})")
            last_text = chunk
        if text.startswith("<!--", lt):
            end = text.find("-->", lt + 4)
            if end < 0:
                raise MoveDefError(f"comment not closed (line {_line(text, lt)})")
            end += 3
        elif text.startswith("<?", lt):
            end = text.find("?>", lt + 2)
            if end < 0:
                raise MoveDefError(f"declaration not closed (line {_line(text, lt)})")
            end += 2
        elif text.startswith("<![CDATA[", lt):
            end = text.find("]]>", lt)
            if end < 0:
                raise MoveDefError(f"CDATA not closed (line {_line(text, lt)})")
            end += 3
        elif text.startswith("<!", lt):
            end = text.find(">", lt) + 1
            if end <= 0:
                raise MoveDefError(f"<! not closed (line {_line(text, lt)})")
        elif text.startswith("</", lt):
            m = _END.match(text, lt)
            if not m:
                raise MoveDefError(f"bad end tag (line {_line(text, lt)})")
            if not stack or stack[-1].tag != m.group(1):
                want = stack[-1].tag if stack else "nothing"
                raise MoveDefError(f"</{m.group(1)}> closes <{want}> (line {_line(text, lt)})")
            node = stack.pop()
            node.foot = m.group(0)
            pos = m.end()
            if not stack:
                epilog_start = pos
            continue
        else:
            m = _START.match(text, lt)
            if not m:
                raise MoveDefError(f"bad start tag (line {_line(text, lt)})")
            if not stack and root is not None:
                raise MoveDefError(f"a second root element <{m.group(1)}> (line {_line(text, lt)})")
            indent = last_text[last_text.rfind("\n") + 1:] if "\n" in last_text and not last_text.strip() else None
            node = _Node(m.group(1), m.group(0), None, indent)
            nodes.append(node)
            if stack:
                stack[-1].items.append(node)
            else:
                root = node
                prolog_end = lt
            if m.group(3):
                if not stack:
                    epilog_start = m.end()
            else:
                node.foot = ""          # set by its end tag
                stack.append(node)
            pos = m.end()
            last_text = ""
            continue
        chunk = text[lt:end]
        if stack:
            stack[-1].items.append(chunk)
        pos = end
    if stack:
        raise MoveDefError(f"<{stack[-1].tag}> is never closed")
    if root is None:
        raise MoveDefError("no root element")
    return text[:prolog_end], root, text[epilog_start:], nodes


def _attrs(head):
    return [(m.group(2), unescape(m.group(4)[1:-1])) for m in _ATTR.finditer(head)]


def parse(text, roots=ROOTS):
    """Doc of a file's text: a `<move>` or a `<commands>` file, or one whose root is in `roots` (ext_list.py)"""
    _, root, _, nodes = _tokenize(text)
    if root.tag not in roots:
        names = " or ".join(f"<{r}>" for r in roots)
        raise MoveDefError(f"the root element is <{root.tag}>, not {names}")
    index = {id(n): i for i, n in enumerate(nodes)}
    parents = {}
    for node in nodes:
        for item in node.items:
            if isinstance(item, _Node):
                parents[id(item)] = node
    elems = []
    keys = {}
    for i, node in enumerate(nodes):
        parent = parents.get(id(node))
        parent_uid = index[id(parent)] if parent is not None else -1
        key = node.tag if parent is None else key_for(node.tag, keys.get(parent_uid))
        keys[i] = key
        elems.append(Elem(i, node.tag, key, parent_uid, i, _attrs(node.head)))
    return Doc(text, elems)


def new_source(root_tag):
    return f"{DECLARATION}<{root_tag}/>\n"


def new_doc(root_tag, attrs=()):
    doc = Doc(new_source(root_tag), [])
    root = Elem(0, root_tag, root_tag, -1, -1, attrs)
    doc.elems.append(root)
    return doc


# ---- writing --------------------------------------------------------------------------------------------------

def _patch_head(head, attrs):
    """`head` (a start tag) with the attribute values of `attrs` ([name, value]); others removed, new ones appended"""
    wanted = {k: v for k, v in attrs}
    out, at, last = [], 0, None
    seen = set()
    for m in _ATTR.finditer(head):
        name = m.group(2)
        out.append(head[at:m.start()])
        at = m.end()
        if name not in wanted:
            continue
        seen.add(name)
        old = unescape(m.group(4)[1:-1])
        if old == wanted[name]:
            out.append(m.group(0))
        else:
            quote = m.group(4)[0]
            value = escape(wanted[name]) if quote == '"' else escape(wanted[name]).replace("'", "&apos;")
            out.append(f"{m.group(1)}{name}{m.group(3)}{quote}{value}{quote}")
        last = len(out)
    rest = head[at:]
    added = "".join(f' {k}="{escape(v)}"' for k, v in attrs if k not in seen)
    if added:
        close = re.search(r"\s*/?>\Z", rest)
        rest = rest[:close.start()] + added + rest[close.start():]
    del last
    return "".join(out) + rest


def _new_node(elem, indent):
    attrs = "".join(f' {k}="{escape(v)}"' for k, v in elem.attrs)
    return _Node(elem.tag, f"<{elem.tag}{attrs}/>", None, indent)


def _child_indent(parent):
    for i, item in enumerate(parent.items):
        if isinstance(item, _Node) and item.indent is not None:
            return item.indent
    return (parent.indent if parent.indent is not None else "") + INDENT


def _is_blank(item):
    return isinstance(item, str) and not item.strip() and not item.startswith("<")


def _remove(parent, node):
    items = parent.items
    i = next(k for k, item in enumerate(items) if item is node)
    lo, hi = i, i + 1
    # a comment on the same line after it goes with it
    if hi + 1 < len(items) and _is_blank(items[hi]) and "\n" not in items[hi] and \
            isinstance(items[hi + 1], str) and items[hi + 1].startswith("<!--"):
        hi += 2
    if lo > 0 and _is_blank(items[lo - 1]):
        lo -= 1
    del items[lo:hi]
    if all(_is_blank(item) for item in items) and parent.foot:
        parent.items = []
        parent.head = re.sub(r"\s*>\Z", "/>", parent.head)
        parent.foot = None


def _insert(parent, node, after):
    """Put `node` into `parent` after the node `after` (None: first), on its own line"""
    indent = _child_indent(parent)
    node.indent = indent
    if parent.foot is None:
        parent.head = re.sub(r"\s*/>\Z", ">", parent.head)
        parent.items = ["\n" + indent, node, "\n" + (parent.indent or "")]
        parent.foot = f"</{parent.tag}>"
        return
    items = parent.items
    if after is None:
        items[0:0] = ["\n" + indent, node]
        if len(items) == 2:
            items.append("\n" + (parent.indent or ""))
        return
    i = next(k for k, item in enumerate(items) if item is after) + 1
    # after a comment on the same line as `after`
    if i + 1 < len(items) and _is_blank(items[i]) and "\n" not in items[i] and \
            isinstance(items[i + 1], str) and items[i + 1].startswith("<!--"):
        i += 2
    items[i:i] = ["\n" + indent, node]


def _detach(nodes_parent, node):
    parent = nodes_parent.get(id(node))
    if parent is not None:
        _remove(parent, node)


def write(source, elems):
    """The file text: `source` with the attributes, removals, additions and moves of `elems`"""
    if not elems:
        raise MoveDefError("nothing to write")
    if elems[0].src < 0:
        source = new_source(elems[0].tag)
    prolog, root, epilog, nodes = _tokenize(source)
    parent_of = {}
    for node in nodes:
        for item in node.items:
            if isinstance(item, _Node):
                parent_of[id(item)] = node
    by_uid = {}
    for e in elems:
        if e.src >= 0:
            if e.src >= len(nodes) or nodes[e.src].tag != e.tag:
                raise MoveDefError(f"<{e.tag}> no longer matches the source file")
            by_uid[e.uid] = nodes[e.src]
    by_uid.setdefault(elems[0].uid, root)
    if elems[0].attrs != _attrs(root.head) or elems[0].src < 0:
        root.head = _patch_head(root.head, elems[0].attrs)
    for e in elems[1:]:
        node = by_uid.get(e.uid)
        if node is not None and e.attrs != _attrs(node.head):
            node.head = _patch_head(node.head, e.attrs)
    # elements the list no longer has (outermost first; their children go with them)
    kept = {id(n) for n in by_uid.values()}
    for node in nodes[1:]:
        if id(node) in kept:
            continue
        parent = parent_of.get(id(node))
        if parent is not None and any(item is node for item in parent.items):
            _remove(parent, node)
    # new elements, and elements now under another parent
    for k, e in enumerate(elems[1:], 1):
        parent = by_uid.get(e.parent)
        if parent is None:
            raise MoveDefError(f"<{e.tag}> has no parent element")
        node = by_uid.get(e.uid)
        if node is not None and parent_of.get(id(node)) is parent:
            continue
        if node is None:
            node = _new_node(e, None)
            by_uid[e.uid] = node
        else:
            _detach(parent_of, node)
        previous = None
        for other in elems[1:k]:
            if other.parent == e.parent:
                candidate = by_uid.get(other.uid)
                if candidate is not None and any(item is candidate for item in parent.items):
                    previous = candidate
        _insert(parent, node, previous)
        parent_of[id(node)] = parent
    out = []
    root.text(out)
    return prolog + "".join(out) + epilog
