"""ModelExtension lists in plain Python (engines/mtfw/movedef/ext_list.py): the formats the runner reads come back byte
for byte, edits change only their own text, and the checks report what the runner would, including the collision
model that isn't out yet when a chain spawns."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402

common.plain()
from movedef import ext_list  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


DRESS = """<extensions>\r
  <attach path="model\\game\\pl000\\ellen_dress" to="model\\game\\pl000\\pl000"/>\r
  <attach path="model\\game\\pl000\\ellen_danglies" to="model\\game\\pl000\\pl000"/>\r
  <model path="model\\game\\pl000\\ellen_dress" collision_model="model\\game\\pl000\\pl000">\r
    <chain clt="chains\\dress_00" col="chains\\dress"/>\r
  </model>\r
  <!-- the danglies collide with the skirt -->\r
  <model path="model\\game\\pl000\\ellen_danglies" collision_model="model\\game\\pl000\\ellen_dress">\r
    <chain clt="chains\\danglies_l" col="chains\\danglies"/>\r
  </model>\r
</extensions>\r
"""
HIDE = """<extensions>
  <hide path="model\\game\\pl000\\pl000_01"/>  <!-- face -->
  <custom thing="kept"/>
</extensions>
"""

d = ext_list.parse(DRESS)
check(d.text() == DRESS, "CRLF list with a comment comes back byte for byte")
check(ext_list.parse(HIDE).text() == HIDE, "a list with an element the runner doesn't read comes back byte for byte")
check(ext_list.issues([("dress.xml", d)]) == [], "the working list has no issues")

chain = next(e for e in d.elems if e.tag == "chain")
chain.set("col", "chains\\other")
check(d.text() == DRESS.replace('col="chains\\dress"', 'col="chains\\other"'), "an edit changes only its value")

d = ext_list.parse(DRESS)
top = d.children(d.root, "attach")
d.add("hide", d.root, [("path", "x")], after=d.children(d.root, "model")[-1])
text = d.text()
check('<hide path="x"/>' in text and text.replace('\n  <hide path="x"/>', "") == DRESS, "a new entry adds only its line")

d = ext_list.new_list()
d.add("attach", d.root, [("path", "a"), ("to", "b")])
check(ext_list.parse(d.text()).child(ext_list.parse(d.text()).root, "attach").get("to") == "b", "a new list reads back")

# the same order mistake the Ellen lists had: danglies.xml sorts before dress.xml
DANGLIES = """<extensions>
  <attach path="part" to="body"/>
  <model path="part" collision_model="skirt"><chain clt="c" col="k"/></model>
</extensions>"""
SKIRT = '<extensions><attach path="skirt" to="body"/></extensions>'
found = ext_list.issues([("danglies.xml", ext_list.parse(DANGLIES)), ("dress.xml", ext_list.parse(SKIRT))])
check(len(found) == 1 and "attached after" in found[0][2], "a collision model attached later is reported")
check(ext_list.issues([("a.xml", ext_list.parse(SKIRT)), ("b.xml", ext_list.parse(DANGLIES))]) == [],
      "attached first, no issue")


def problems(text):
    return [m for _, _, m in ext_list.issues([("x.xml", ext_list.parse(text))])]


check(any("needs to=" in m for m in problems('<extensions><attach path="a"/></extensions>')), "attach needs to=")
check(any("skin or rigid" in m for m in problems('<extensions><attach path="a" to="b" mode="x"/></extensions>')), "mode")
check(any("three numbers" in m for m in problems('<extensions><attach path="a" to="b" joint="1" pos="1 2"/></extensions>')),
      "pos needs three numbers")
check(any("no collision model" in m for m in problems('<extensions><model path="a"><chain clt="b" col="c"/></model></extensions>')),
      "a col without a collision model is reported")
check(any("no extension" in m for m in problems('<extensions><hide path="a.mod"/></extensions>')), "paths have no extension")

a = ext_list.parse('<extensions><attach path="a" to="b" joint="3" pos="1,2 3" scale="2"/></extensions>')
e = a.child(a.root, "attach")
check(ext_list.effective_mode(e) == "rigid", "a joint means rigid")
check(ext_list.rigid_offset(e) == ([1.0, 2.0, 3.0], [0.0] * 3, [2.0] * 3), "offsets read as the runner reads them")
check(ext_list.stem("model\\game\\pl000\\pl000.mod") == "model\\game\\pl000\\pl000", "stem")
check(ext_list.stem("a.b\\c") == "a.b\\c", "stem keeps a dotted folder")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
