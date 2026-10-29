"""MoveDef move files (engines/mtfw/movedef_blender.py): a new move from an LMT animation (id, registry <lmt>, row,
stage block= on the animation), elements with frames as pose markers on the stage's action (a dragged marker is the
written frame), the checks (empty / missing block, frame outside the motion, block= vs motion=, fixed-bank clash), Write XML / Import XML keeping a hand-written file byte for
byte apart from the edit, and an overlay filled from Nero's .ctn (Streak's finish) like examples/nero_streak_cancels.xml.
"""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402
import traceback
sys.path.insert(0, common.ADDONS)
import bpy, albam
albam.register()
from albam.engines.mtfw import animation, movedef_blender as mb
from albam.engines.mtfw.movedef import doc as mdoc, check as mcheck
from albam.lib import blender_compat as compat

failures = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


EXAMPLES = os.path.join(common.DATA, "Vibed", "MoveDef", "examples")
CTN = os.path.join(common.NERO, "chartbl", "pl000.ctn")
common.skip_unless(os.path.join(EXAMPLES, "nero_million_stab.xml"), CTN)


class Stub:
    def __init__(self):
        self.texts = []
    def __getattr__(self, name):
        def f(*a, **k):
            if "text" in k:
                self.texts.append(k["text"])
            return self
        return f
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


def make_rig():
    data = bpy.data.armatures.new("rig")
    ob = bpy.data.objects.new("rig", data)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    b = data.edit_bones.new("b")
    b.head, b.tail = (0, 0, 0), (0, 0, 0.1)
    bpy.ops.object.mode_set(mode="OBJECT")
    return ob


def make_action(rig, name, slot, length, keys=True):
    action = compat.assign_action(rig, bpy.data.actions.new(name))
    if keys:
        pb = rig.pose.bones["b"]
        for f in (0, length - 1):
            pb.location = (0, 0, f * 0.01)
            pb.keyframe_insert("location", frame=f)
    action.albam_asset.app_id = "dmc4"
    props = animation.get_lmt_props(action)
    props.lmt_id, props.num_frames, props.source_fps = slot, length, 60.0
    action.use_fake_user = True
    return action


def make_lmt(name, path, actions):
    group = bpy.context.scene.albam.lmt_groups.add(name)
    group.export_path = path
    for a in actions:
        group.add(a)
    group.num_slots = len(actions)
    return group


def elems(move, tag):
    return [e for e in move.elems if e.tag == tag]


try:
    scene = bpy.context.scene
    scene.render.fps = 60
    rig = make_rig()
    a0 = make_action(rig, "stab_loop", 0, 40)
    a1 = make_action(rig, "stab_finish", 1, 60)
    a2 = make_action(rig, "nothing", 2, 30, keys=False)
    group = make_lmt("million_stab", r"X:\nativePC\motion\pl000\million_stab.lmt", [a0, a1, a2])

    # ---- a new move from an animation
    move = mb.new_move(bpy.context, "stab", "pl000", "NEW", group, a0, "melee", "ground")
    d = mb.move_doc(move)
    lmt, stage = d.child(d.root, "lmt"), mcheck.stages(d)[0]
    check(d.root.get("id") == "0x34" and d.root.get("character") == "pl000",
          f"the move gets Nero's first free id ({d.root.get('id')})")
    check(not lmt.has("bank") and lmt.get("path") == r"motion\pl000\million_stab",
          f"its LMT is left to the motion registry (no bank), path from the LMT's file name ({lmt.attrs})")
    check(stage.get("block") == "0" and not stage.has("motion") and stage.get("ctn") == "0:5",
          f"the stage plays the animation's block (block=) and borrows a vanilla script ({stage.attrs})")
    check(d.child(d.child(d.root, "table"), "input") is None and d.child(d.root, "command") is None,
          "a melee row has no input command")
    errors, warnings = mb.check_move(bpy.context, move)
    check(not errors, f"a new move checks clean ({errors})")

    # ---- an element with a frame is a pose marker
    stage_item = elems(move, "stage")[0]
    scene.frame_current = 12
    move.active_elem = list(move.elems).index(stage_item)
    bpy.ops.albam.movedef_add_element(tag="cancel")
    cancel = elems(move, "cancel")[0]
    marker = a0.pose_markers.get(cancel.marker)
    check(marker is not None and marker.frame == 12 and cancel.attrs["frame"].value == "12",
          f"a new cancel lands on the current frame as a marker of the stage's action "
          f"({cancel.marker}, {marker.frame if marker else None})")
    marker.frame = 20
    check(abs(cancel.attrs["frame"].v_frame - 20) < 1e-6, "the frame widget reads the dragged marker")
    cancel.attrs["categories"].v_cats = [False, False, False, False, True, False, False, False]
    check(cancel.attrs["categories"].value == "C_JUMP", "the category toggles write the names")
    kind = cancel.attrs.get("kind")
    if kind is None:
        move.active_elem = list(move.elems).index(cancel)
        bpy.ops.albam.movedef_add_attr(name="kind")
        kind = cancel.attrs["kind"]
    kind.v_enum = "buffer"
    check(kind.value == "buffer", "an enum widget writes its name")

    out = common.out_dir("movedef")
    path = os.path.join(out, "stab.xml")
    text, warnings = mb.write_text(bpy.context, move)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    mb.after_write(move, text)
    written = mdoc.parse(open(path, encoding="utf-8").read())
    c = [e for e in written.elems if e.tag == "cancel"][0]
    check(c.get("frame") == "20" and c.get("categories") == "C_JUMP" and c.get("kind") == "buffer",
          f"the written cancel has the marker's frame ({c.attrs})")
    cancel = elems(move, "cancel")[0]
    check(cancel.src >= 0 and a0.pose_markers.get(cancel.marker) is not None,
          "after writing, the element points into the new file and keeps its marker")
    check(text.startswith('<?xml version="1.0" encoding="utf-8"?>\n<move name="stab"') and "\n  <stage " in text
          and "\n    <cancel " in text, "a new file is indented like the examples")

    # ---- checks Blender can make
    mb.place_marker(bpy.context, move, cancel, 45)
    errors, _ = mb.check_move(bpy.context, move)
    check(any("outside the motion" in e for e in errors), f"a frame past the block is refused ({errors})")
    mb.place_marker(bpy.context, move, cancel, 20)
    stage_item = elems(move, "stage")[0]
    stage_item.attrs["block"].value = "2"
    errors, _ = mb.check_move(bpy.context, move)
    check(any("empty" in e for e in errors), f"an empty block is refused ({errors})")
    stage_item.attrs["block"].value = "7"
    errors, _ = mb.check_move(bpy.context, move)
    check(any("doesn't exist" in e for e in errors), f"a missing block is refused ({errors})")
    stage_item.attrs["block"].value = "300"
    errors, _ = mb.check_move(bpy.context, move)
    check(any("0-255" in e for e in errors), f"a block past 255 is refused ({errors})")
    stage_item.attrs["block"].value = "0"

    def edit(m, tag, **attrs):
        d = mb.move_doc(m)
        e = d.child(d.root, tag) if tag == "lmt" else mcheck.stages(d)[0]
        for k, v in attrs.items():
            e.remove(k) if v is None else e.set(k, v)
        mb.store_doc(m, d)

    edit(move, "stage", motion="10:0")
    errors, _ = mb.check_move(bpy.context, move)
    check(any("block= and motion= together" in e for e in errors), f"block= with motion= is refused ({errors})")
    edit(move, "stage", block=None)
    errors, _ = mb.check_move(bpy.context, move)
    check(any("runtime bank 10" in e and "block=" in e for e in errors),
          f"motion= in a free bank of a registry LMT is refused, pointing at block= ({errors})")
    edit(move, "stage", motion="6:0")
    errors, _ = mb.check_move(bpy.context, move)
    check(any("runtime bank 6" in e for e in errors), f"Nero's banks 4 / 6-9 are runtime banks too ({errors})")
    edit(move, "stage", motion="3:0")
    errors, _ = mb.check_move(bpy.context, move)
    check(not any("runtime bank" in e for e in errors), f"a vanilla setup bank is fine ({errors})")
    edit(move, "stage", motion="10:0")
    edit(move, "lmt", bank="10")
    errors, _ = mb.check_move(bpy.context, move)
    check(not errors, f"the fixed-bank form (bank=10, motion=10:0) still checks clean ({errors})")
    edit(move, "stage", motion="10:7")
    errors, _ = mb.check_move(bpy.context, move)
    check(any("doesn't exist" in e for e in errors), f"a fixed-bank motion= is looked up in the move's LMT ({errors})")
    edit(move, "stage", motion=None, block="0")

    other = mb.new_move(bpy.context, "other", "pl000", "NEW", None, None)
    od = mb.move_doc(other)
    check(od.root.get("id") == "0x35", f"a second move gets the next free id ({od.root.get('id')})")
    errors, _ = mb.check_move(bpy.context, other)
    check(not any("already holds" in e for e in errors),
          f"two registry LMTs don't clash (the registry places both) ({errors})")
    edit(other, "lmt", bank="10")
    errors, _ = mb.check_move(bpy.context, other)
    check(any("already holds" in e for e in errors), f"two LMTs in one fixed bank are refused ({errors})")
    edit(other, "lmt", bank="9")
    errors, _ = mb.check_move(bpy.context, other)
    check(any("fixed bank is 10-14" in e for e in errors), f"a fixed bank outside 10-14 is refused ({errors})")
    edit(move, "lmt", bank=None)
    scene.albam.movedefs.active = list(scene.albam.movedefs.moves).index(other)
    bpy.ops.albam.movedef_remove()

    # ---- a hand-written file comes back byte for byte, apart from the edit
    src = os.path.join(EXAMPLES, "nero_million_stab.xml")
    original = open(src, encoding="utf-8", newline="").read()
    stab = mb.import_text(bpy.context, original, src)
    check(stab.lmt_group == group.name, f"the import finds its LMT by the <lmt> path ({stab.lmt_group})")
    effect = elems(stab, "effect")[0]
    check(a0.pose_markers.get(effect.marker) is not None and a0.pose_markers[effect.marker].frame == 9,
          "its frames become markers on the block's action")
    text, _ = mb.write_text(bpy.context, stab)
    check(text == original, "written back unchanged, it's byte-identical (comments, wrapped tags)")
    stage_item = elems(stab, "stage")[0]
    stage_item.attrs["watchdog"].v_int = 120
    a0.pose_markers[effect.marker].frame = 11
    text, _ = mb.write_text(bpy.context, stab)
    diff = [(a, b) for a, b in zip(original.splitlines(), text.splitlines()) if a != b]
    check(len(diff) == 2 and 'watchdog="120"' in diff[0][1] and 'frame="11"' in diff[1][1]
          and len(text.splitlines()) == len(original.splitlines()),
          f"an edit changes only its own lines ({diff})")
    move_count = len(scene.albam.movedefs.moves)

    # ---- an overlay from Nero's .ctn: Streak's finish
    scene.albam.rfs.add_root_folder("dmc4", common.NERO)
    finish = make_action(rig, "pl000_04_0x17", 0x17, 70)
    vanilla = make_lmt("pl000_04", os.path.join(common.NERO, "motion", "pl000", "pl000_04.lmt"), [finish])
    overlay = mb.new_move(bpy.context, "streak_cancels", "pl000", "OVERLAY", vanilla, finish)
    od = mb.move_doc(overlay)
    st = mcheck.stages(od)[0]
    check(st.get("motion") == "3:0x17" and od.root.get("overlay") == "true",
          f"an overlay's stage plays the vanilla motion ({st.attrs})")
    overlay.elems[0].attrs["ids"].value = "28 29"
    overlay.active_elem = list(overlay.elems).index(elems(overlay, "stage")[0])
    bpy.ops.albam.movedef_extract_ctn()
    cancels = [(e.attrs["frame"].value, e.attrs["kind"].value, e.attrs["categories"].value)
               for e in elems(overlay, "cancel")]
    check(cancels == [("26", "buffer", "C_NORM0 C_COMMAND C_JUMP C_CHOUHATSU C_GUN"), ("31", "open", "C_JUMP"),
                      ("36", "open", "C_NORM0 C_COMMAND C_CHOUHATSU C_GUN"), ("56", "open", "C_ALL")],
          f"its cancels are the game's script ({cancels})")
    triggers = [(e.attrs["byte"].value, e.attrs["value"].value, e.attrs["frame"].value)
                for e in elems(overlay, "trigger")]
    check(("free1", "2", "20") in triggers and len(triggers) == 7, f"and its triggers ({triggers})")
    check(all(finish.pose_markers.get(e.marker) for e in elems(overlay, "cancel") + elems(overlay, "trigger")),
          "each on a marker of the motion")
    jump = [e for e in elems(overlay, "cancel") if e.attrs["frame"].value == "31"][0]
    finish.pose_markers[jump.marker].frame = 20
    errors, warnings = mb.check_move(bpy.context, overlay)
    check(not errors, f"the overlay checks clean ({errors} {warnings})")
    text, _ = mb.write_text(bpy.context, overlay)
    check('<cancel frame="20" kind="open" categories="C_JUMP"/>' in text, "the moved jump window is written")
    overlay.elems[0].attrs["ids"].value = "0x60"
    errors, _ = mb.check_move(bpy.context, overlay)
    check(any("vanilla id" in e for e in errors), f"an overlay on a non-vanilla id is refused ({errors})")

    # ---- an overlay on a Buster grab: motion bank 15, its script from the grabbed enemy's .ctn bank (em010 = 14)
    from dmc4xml import ctn
    from albam.engines.mtfw.movedef import extract as mextract
    ctn_data = open(CTN, "rb").read()
    grab_slot = next(i for i, s in enumerate(ctn.read(ctn_data).banks[14].slots)
                     if s is not None and mextract.script_elements(ctn_data, 14, i)[0])
    grab_action = make_action(rig, "pl000_em010_00_grab", grab_slot, 400)
    grab = make_lmt("pl000_em010_00", os.path.join(common.NERO, "motion", "pl000", "em010", "pl000_em010_00.lmt"),
                    [grab_action])
    gm = mb.new_move(bpy.context, "grab_cancels", "pl000", "OVERLAY", grab, grab_action)
    gst = mcheck.stages(mb.move_doc(gm))[0]
    check(gst.get("motion") == f"15:0x{grab_slot:X}", f"a grab overlay plays motion bank 15 ({gst.attrs})")
    gm.elems[0].attrs["ids"].value = "28"
    gm.active_elem = list(gm.elems).index(elems(gm, "stage")[0])
    bpy.ops.albam.movedef_extract_ctn(grab="14")
    gm = mb.active_move(bpy.context)
    want, _ = mextract.script_elements(ctn_data, 14, grab_slot)
    got = elems(gm, "cancel") + elems(gm, "trigger")
    check(len(got) == len(want) and got, f"its script comes from em010's .ctn bank 14 ({len(got)} / {len(want)})")
    errors, _ = mb.check_move(bpy.context, gm)
    check(not errors, f"the grab overlay checks clean ({errors})")
    edit(gm, "stage", motion="24:5")
    errors, _ = mb.check_move(bpy.context, gm)
    check(any("motion banks are 0-15" in e for e in errors), f"a .ctn grab bank as motion= is refused ({errors})")
    scene.albam.movedefs.active = list(scene.albam.movedefs.moves).index(gm)
    bpy.ops.albam.movedef_remove()

    # ---- a shell's .atk entry (Nero's Collision\pl000.atk is in Game Files now)
    moves = scene.albam.movedefs.moves
    scene.albam.movedefs.active = next(i for i, m in enumerate(moves) if mb.move_name(m) == "stab")
    move = mb.active_move(bpy.context)        # references to collection items go stale after add()
    st_item = elems(move, "stage")[0]
    move.active_elem = list(move.elems).index(st_item)
    bpy.ops.albam.movedef_add_element(tag="shell")
    shell = elems(move, "shell")[0]
    names = mb.atk_names(bpy.context, r"Collision\pl000")
    check(names is not None and len(names) > 14, f"the .atk codec reads Nero's attack entries ({len(names or [])})")
    move.active_elem = list(move.elems).index(shell)
    bpy.ops.albam.movedef_add_attr(name="entry")
    shell.attrs["entry"].value = "14"
    errors, _ = mb.check_move(bpy.context, move)
    check(not any("shell" in e for e in errors), f"an existing entry passes ({errors})")
    shell.attrs["entry"].value = str(len(names))
    errors, _ = mb.check_move(bpy.context, move)
    check(any("no such entry" in e for e in errors), f"an entry past the file is refused ({errors})")
    check(mb.entry_label(bpy.context, move, shell) == "(no such entry)", "the panel says so next to the entry")

    # ---- <attack>: defined in the file or taken from an .atk entry (by index or name), used by <shell attack=>
    shell.attrs["entry"].value = names[14].lower()
    check(mb.entry_label(bpy.context, move, shell) == f"14 {names[14]}",
          f"entry= takes an entry name, case-insensitive ({mb.entry_label(bpy.context, move, shell)})")
    move.active_elem = 0
    bpy.ops.albam.movedef_add_element(tag="attack")
    attack = elems(move, "attack")[0]
    check(attack.attrs["name"].value == "attack1", f"a new attack gets a free name ({attack.attrs['name'].value})")
    attack.attrs["name"].value = "my_kick"
    move.active_elem = list(move.elems).index(attack)
    bpy.ops.albam.movedef_add_attr(name="entry")
    attack.attrs["entry"].value = names[14]
    bpy.ops.albam.movedef_add_attr(name="damage")
    attack.attrs["damage"].v_float = 150
    shell = elems(move, "shell")[0]
    move.active_elem = list(move.elems).index(shell)
    shell.attrs.remove(shell.attrs.find("entry"))
    bpy.ops.albam.movedef_add_attr(name="attack")
    shell.attrs["attack"].v_enum = "my_kick"
    check(shell.attrs["attack"].value == "my_kick", "a shell picks the file's attack from a dropdown")
    errors, warnings = mb.check_move(bpy.context, move)
    check(not any("attack" in e or "entry" in e for e in errors), f"the attack and its shell check clean ({errors})")
    attack.attrs["entry"].value = "no_such_name"
    errors, _ = mb.check_move(bpy.context, move)
    check(any("no such entry" in e for e in errors), f"an entry name the .atk lacks is refused ({errors})")
    attack.attrs.remove(attack.attrs.find("entry"))
    move.active_elem = list(move.elems).index(attack)
    bpy.ops.albam.movedef_add_attr(name="atk")
    attack.attrs["atk"].value = r"Collision\pl000"
    attack.attrs.remove(attack.attrs.find("damage"))
    _, warnings = mb.check_move(bpy.context, move)
    check(any("entry 0, since entry= isn't given" in w and "No_used" in w for w in warnings),
          f"an attack on Nero's .atk without entry= lands on entry 0, a placeholder: warned ({warnings})")
    bpy.ops.albam.movedef_add_attr(name="damage")
    attack.attrs["damage"].v_float = 150
    _, warnings = mb.check_move(bpy.context, move)
    check(not any("deals no damage" in w for w in warnings), "setting damage= answers it")
    attack.attrs.remove(attack.attrs.find("atk"))
    attack.attrs["name"].value = "a_very_long_attack_name"
    errors, warnings = mb.check_move(bpy.context, move)
    check(any("names no <attack>" in e for e in errors), f"a shell naming no attack is refused ({errors})")
    check(any("15 characters" in w for w in warnings), f"a name over 15 characters is a warning ({warnings})")
    shell.attrs["attack"].value = "a_very_long_attack_name"
    errors, _ = mb.check_move(bpy.context, move)
    check(not errors, f"an attack defined by its values alone needs no .atk entry ({errors})")
    text, _ = mb.write_text(bpy.context, move)
    check('<attack name="a_very_long_attack_name" damage="150"/>' in text and 'attack="a_very_long_attack_name"' in text,
          "the attack and the shell's reference are written")

    # ---- the panel
    layout = Stub()
    scene.albam.movedefs.active = len(scene.albam.movedefs.moves) - 1
    mb.ALBAM_PT_MoveDefs.draw(type("P", (), {"layout": layout})(), bpy.context)
    mb.ALBAM_PT_MoveDefElements.draw(type("P", (), {"layout": layout})(), bpy.context)
    check(any("Write XML" == t for t in layout.texts), f"the panel draws ({layout.texts[:12]})")
    check(move_count == len(scene.albam.movedefs.moves) - 1, "the overlay is one more move in the list")
    tip = mb.attr_tooltip("cancel", "kind")
    check("buffer" in tip and "at once" in tip, f"attributes have tooltips ({tip!r})")
except Exception:
    traceback.print_exc()
    failures.append("exception")

print("FAILURES:", failures)
sys.stdout.flush()
sys.exit(1 if failures else 0)
