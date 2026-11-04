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

CNS = """<extensions>
  <model path="a">
    <pin joint="1" to="2" of="self" mode="rot" blend="0.5" pos="1 2 3"/>
    <aim joint="2" to="3" axis="-x" up="+y" limit="30"/>
    <offset joint="3" rot="0 0 90" add="false"/>
  </model>
</extensions>
"""
check(ext_list.parse(CNS).text() == CNS and ext_list.issues([("x.xml", ext_list.parse(CNS))]) == [],
      "the schema's constraints round-trip with no issues")


def problems(text):
    return [m for _, _, m in ext_list.issues([("x.xml", ext_list.parse(text))])]


check(any("first in file order" in m for m in problems(
    '<extensions><model path="a"><pin joint="1" to="2"/><offset joint="1"/></model></extensions>')), "two entries on a joint")
check(any("same letter" in m for m in problems(
    '<extensions><model path="a"><aim joint="1" to="2" axis="y" up="-y"/></model></extensions>')), "aim axes on one letter")
check(any("0-255" in m for m in problems('<extensions><model path="a"><offset joint="300"/></model></extensions>')),
      "joint range")
check(any("all or rot" in m for m in problems(
    '<extensions><model path="a"><pin joint="1" to="2" mode="x"/></model></extensions>')), "pin mode")
check(any("needs to=" in m for m in problems('<extensions><model path="a"><pin joint="1"/></model></extensions>')),
      "pin needs to=")
check(any("hit shake" in m for m in problems(
    '<extensions><model path="model\\game\\pl006\\pl006"><offset joint="13"/></model></extensions>')),
      "a player body's joint 13 is the game's")
check(any("coat" in m for m in problems(
    '<extensions><model path="Model/Game/pl000/PL000_03"><offset joint="0"/></model></extensions>')), "the coat's joint 0")
check(not problems('<extensions><model path="model\\game\\pl000\\ellen_dress"><offset joint="13"/></model></extensions>'),
      "another model's joint 13 is free")
check(any("refuses" in m and "leg IK" in m for m in problems(
    '<extensions><model path="model\\game\\pl009\\pl009"><offset joint="20"/></model></extensions>')), "an ankle is refused")
found = problems('<extensions><model path="model\\game\\pl000\\pl000"><offset joint="15"/></model></extensions>')
check(len(found) == 1 and "overrides it while" in found[0], "a shin is only warned about")
check(any("coat" in m for m in problems(
    '<extensions><model path="model\\game\\pl006\\pl006_03"><offset joint="7"/></model></extensions>')), "Dante's coat 0-7")
check(any("face" in m for m in problems(
    '<extensions><model path="model\\game\\pl000\\pl000_01"><offset joint="4"/></model></extensions>')), "the face 0-4")
check(not problems('<extensions><model path="model\\game\\pl000\\pl000_02"><offset joint="2"/></model></extensions>'),
      "hair joint 2 is free")

LINK = '<extensions><model path="a"><chain clt="c"/><link a="221" b="216" max="12" stiffness="0.5"/></model></extensions>'
check(ext_list.parse(LINK).text() == LINK and not problems(LINK), "<link> round-trips with no issues")
d = ext_list.parse(LINK)
check(ext_list.link_values(d.child(d.child(d.root, "model"), "link")) == (221, 216, 12.0, 0.5), "link values")
check(not ext_list.constraints(d) and len(ext_list.links(d)) == 1, "a link isn't a constraint (it holds no joint)")
check(any("needs max=" in m for m in problems('<extensions><model path="a"><link a="1" b="2"/></model></extensions>')),
      "a link needs max=")
check(any("to itself" in m for m in problems('<extensions><model path="a"><link a="3" b="3" max="5"/></model></extensions>')),
      "a link to itself")
check(any("above 0" in m for m in problems('<extensions><model path="a"><link a="1" b="2" max="-1"/></model></extensions>')),
      "max above 0")
check(any("0-1" in m for m in problems(
    '<extensions><model path="a"><link a="1" b="2" max="5" stiffness="2"/></model></extensions>')), "stiffness 0-1")
check(any("doesn't look for it there" in m for m in problems('<extensions><link a="1" b="2" max="5"/></extensions>')),
      "a link belongs in a <model>")

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
check(ext_list.offset_values(e) == ([1.0, 2.0, 3.0], [0.0] * 3, [2.0] * 3), "offsets read as the runner reads them")
check(ext_list.stem("model\\game\\pl000\\pl000.mod") == "model\\game\\pl000\\pl000", "stem")
check(ext_list.stem("a.b\\c") == "a.b\\c", "stem keeps a dotted folder")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
