"""MoveDef XML in plain Python (engines/mtfw/movedef): every example file reads and writes back byte for byte, the
working examples pass the checks, edits change only their own lines (attribute, removal, insertion, a new file), and
every script of Nero's and Dante's .ctn extracts into <cancel> / <trigger> elements that the checks accept."""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402

common.plain()
sys.path.insert(0, os.path.join(common.ALBAM, "albam_vendor"))
from movedef import doc, check as mcheck, extract  # noqa: E402
from dmc4xml import ctn  # noqa: E402

EXAMPLES = os.path.join(common.DATA, "Vibed", "MoveDef", "examples")
SKETCHES = {"new_move.xml", "streak.xml"}       # v0.1 design sketches, not loadable by the runner
CTNS = [os.path.join(common.NERO, "chartbl", "pl000.ctn"),
        os.path.join(common.ARCTOOL, "uPlayerDante-vanilla", "chartbl", "pl006.ctn")]
common.skip_unless(EXAMPLES, *CTNS)

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


texts = {}
for path in sorted(glob.glob(os.path.join(EXAMPLES, "*.xml"))):
    with open(path, encoding="utf-8", newline="") as f:
        texts[os.path.basename(path)] = f.read()
docs = {name: doc.parse(text) for name, text in texts.items()}
for name, d in docs.items():
    check(d.text() == texts[name], f"{name}: written back unchanged, byte-identical")
for name, d in docs.items():
    if name in SKETCHES:
        continue
    others = [mcheck.summary(o) for n, o in docs.items() if o is not d and n not in SKETCHES]
    errors, warnings = mcheck.check(d, mcheck.Env(others=others))
    check(not errors and not warnings, f"{name}: the checks pass ({errors} {warnings})")

# edits stay local
src = texts["gerb.xml"]
d = doc.parse(src)
shell = next(e for e in d.elems if e.tag == "shell")
shell.set("radius", "75")
out = d.text()
diff = [(a, b) for a, b in zip(src.splitlines(), out.splitlines()) if a != b]
check(len(diff) == 1 and 'radius="75"' in diff[0][1] and diff[0][1].replace("75", "60") == diff[0][0],
      f"an attribute edit changes only its value inside a wrapped tag ({diff})")
d = doc.parse(src)
d.remove(next(e for e in d.elems if e.tag == "slot" and e.get("dir") == "back"))
out = d.text()
check(len(out.splitlines()) == len(src.splitlines()) - 1 and 'dir="back"' not in out,
      "a removed element takes its line with it")
d = doc.parse(src)
stage = next(e for e in d.elems if e.tag == "stage")
slots = [e for e in d.elems if e.tag == "slot"]
up = d.add("slot", stage, [("dir", "up"), ("block", "5")], after=slots[-1])
d.add("cancel", stage, [("frame", "30"), ("kind", "open"), ("categories", "C_ALL")], after=up)
out = d.text()
lines = out.splitlines()
i = next(k for k, line in enumerate(lines) if 'dir="right"' in line)
check(lines[i + 1] == '    <slot dir="up" block="5"/>' and lines[i + 2].startswith('    <cancel frame="30"'),
      f"new elements go after their sibling, indented like it ({lines[i:i + 3]})")
check(len(lines) == len(src.splitlines()) + 2, "and nothing else changes")
again = doc.parse(out)
check([e.tag for e in again.elems] == [e.tag for e in d.elems], "the result reads back in the list's order")

fresh = doc.new_doc("move", [("name", "x"), ("character", "pl006"), ("id", "0x6C")])
fresh.add("lmt", fresh.root, [("bank", "10"), ("path", r"motion\pl006\x")])
st = fresh.add("stage", fresh.root, [("name", "main"), ("motion", "10:0")])
fresh.add("cancel", st, [("frame", "10"), ("categories", "C_ALL")])
text = fresh.text()
check(text == '<?xml version="1.0" encoding="utf-8"?>\n<move name="x" character="pl006" id="0x6C">\n'
      '  <lmt bank="10" path="motion\\pl006\\x"/>\n  <stage name="main" motion="10:0">\n'
      '    <cancel frame="10" categories="C_ALL"/>\n  </stage>\n</move>\n', f"a new file:\n{text}")
check(doc.parse('<move><!-- a -- b --></move>').root.tag == "move", "comments with -- read, as pugixml reads them")
for bad in ("<move><stage></move>", "<move a=1/>", "<table/>"):
    try:
        doc.parse(bad)
        check(False, f"{bad!r} is refused")
    except doc.MoveDefError as err:
        check(True, f"{bad!r} is refused ({err})")

# every vanilla script extracts
for path in CTNS:
    data = open(path, "rb").read()
    table = ctn.read(data)
    character = os.path.basename(path)[:5]
    scripts = loops = elements = 0
    problems = []
    for bank, b in enumerate(table.banks):
        if b is None:
            continue
        for slot, s in enumerate(b.slots):
            if s is None:
                continue
            scripts += 1
            found, notes = extract.script_elements(data, bank, slot)
            loops += any("loops" in n for n in notes)
            elements += len(found)
            d = doc.new_doc("move", [("name", "x"), ("character", character), ("ids", "28"), ("overlay", "true")])
            motion_bank = 15 if character == "pl000" and bank >= 10 else bank   # grab scripts: motion bank 15
            st = d.add("stage", d.root, [("name", "s"), ("motion", f"{motion_bank}:{slot}")])
            for tag, attrs in found:
                d.add(tag, st, attrs)
            errors, _ = mcheck.check(doc.parse(d.text()))
            if errors:
                problems.append(f"{bank}:{slot:#x} {errors[:2]}")
    check(not problems, f"{os.path.basename(path)}: {scripts} scripts -> {elements} elements, {loops} loop "
          f"(flagged); every one checks clean {problems[:3]}")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
