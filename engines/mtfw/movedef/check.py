"""Checks of a MoveDef file before it's written: what the runner would refuse or silently ignore, and what Blender
knows that the runner can't (does the LMT block exist, are the frames inside it). Errors stop the write; warnings
are reported.

    errors, warnings = check(doc, Env(block_length=..., others=[...]))
"""
from .schema import (
    ELEMENTS, MIN_ID, FREE_BANKS, OWN, RUNTIME_BANKS, MAX_MOTION_BANK, GRAB_BANK, MAX_SHELLS, MAX_CANCEL_WORDS,
    CATEGORIES, CONTACT_BYTES, BUTTONS, DIRECTIONS, spec_for)


def parse_int(text, default=None):
    """Decimal or 0x hex, as the runner's strtol(text, 0); `default` when it isn't a number"""
    if text is None:
        return default
    text = text.strip()
    try:
        return int(text, 0)
    except ValueError:
        try:
            return int(text, 10)
        except ValueError:
            return default


def parse_float(text, default=None):
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def parse_motion(text):
    """(bank, slot) of "bank:slot", or None"""
    if not text or ":" not in text:
        return None
    bank, slot = text.split(":", 1)
    bank, slot = parse_int(bank), parse_int(slot)
    if bank is None or slot is None:
        return None
    return bank, slot


class Other:
    """Another move file the runner would load alongside (from the scene or the game folder)"""
    def __init__(self, name, character, ids, overlay, bank=None, lmt_path="", where=""):
        self.name, self.character, self.ids, self.overlay = name, character, ids, overlay
        self.bank, self.lmt_path, self.where = bank, lmt_path, where


class Env:
    """What the checks may ask outside the file. `block_length(bank, slot)` = the block's length in game frames,
    0 when it's empty, None when it doesn't exist or isn't known (`known_banks` lists the banks Blender can answer
    for; OWN = the move's own <lmt>); `others` the other move files; `shared_commands` {character: {names}}."""
    def __init__(self, block_length=None, known_banks=(), others=(), shared_commands=None, atk_names=None,
                 atk_damage=None):
        self.block_length = block_length or (lambda bank, slot: None)
        self.atk_names = atk_names or (lambda path: None)      # [entry names] of an .atk game path, None = unknown
        self.atk_damage = atk_damage or (lambda path: None)    # [entry damage values], the same
        self.known_banks = set(known_banks)
        self.others = list(others)
        self.shared_commands = shared_commands or {}


def summary(doc):
    """Other of this file (name, character, ids, bank) for checking another file against it"""
    root = doc.root
    ids = []
    if root.tag == "move":
        for text in [root.get("id")] + (root.get("ids") or "").replace(",", " ").split():
            value = parse_int(text)
            if value and value not in ids:
                ids.append(value)
    lmt = doc.child(root, "lmt")
    return Other(root.get("name", ""), root.get("character", ""), ids, root.get("overlay") == "true",
                 parse_int(lmt.get("bank")) if lmt is not None else None,
                 lmt.get("path", "") if lmt is not None else "")


def stages(doc):
    holder = doc.child(doc.root, "stages") or doc.root
    return doc.children(holder, "stage")


def stage_motions(doc, stage):
    """[(bank, slot)] the stage plays: every <slot>'s block, else its block=, of the move's own <lmt> (bank OWN), else
    its motion= (a vanilla bank:slot; one in the <lmt>'s fixed bank is OWN too)"""
    lmt = doc.child(doc.root, "lmt")
    slots = doc.children(stage, "slot")
    if slots or stage.has("block"):
        blocks = [parse_int(s.get("block")) for s in slots] if slots else [parse_int(stage.get("block"))]
        return [(OWN, b) for b in blocks if b is not None] if lmt is not None else []
    motion = parse_motion(stage.get("motion"))
    if motion is None:
        return []
    if lmt is not None and motion[0] == parse_int(lmt.get("bank")):
        return [(OWN, motion[1])]
    return [motion]


def frame_elements(doc, stage):
    """(element, attribute name) of every motion frame inside `stage` (its cancel_frame included)"""
    out = []
    if stage.has("cancel_frame"):
        out.append((stage, "cancel_frame"))
    for e in doc.descendants(stage):
        spec = ELEMENTS.get(e.key)
        if spec is not None and spec.frame and e.has(spec.frame):
            out.append((e, spec.frame))
    return out


def check(doc, env=None):
    env = env or Env()
    errors, warnings = [], []
    root = doc.root
    if root.tag == "commands":
        if root.get("character") not in MIN_ID:
            errors.append("<commands character=> must be pl000 or pl006")
        _check_commands(doc, doc.children(root, "command"), errors, warnings)
        _unknown(doc, warnings)
        return errors, warnings

    name, character = root.get("name", ""), root.get("character", "")
    me = summary(doc)
    if not name:
        errors.append("the move has no name")
    if character not in MIN_ID:
        errors.append(f"character is '{character}': pl000 (Nero) or pl006 (Dante)")
    overlay = me.overlay or doc.child(root, "routine") is not None
    if not me.ids:
        errors.append("the move has no id")
    elif character in MIN_ID:
        first = MIN_ID[character]
        for value in me.ids:
            if overlay and value >= first:
                errors.append(f"an overlay names a vanilla id: {value:#x} is not below {first:#x}")
            elif not overlay and value < first:
                errors.append(f"id {value:#x} is below the first free id {first:#x} of {character}")
    for other in env.others:
        if other.name and other.name == name:
            errors.append(f"another move is named '{name}' ({other.where})")
        if other.character == character and not overlay and not other.overlay and set(other.ids) & set(me.ids):
            errors.append(f"id {me.ids[0]:#x} is also {other.name}'s ({other.where})")

    lmt = doc.child(root, "lmt")
    bank = None
    if lmt is not None:
        bank = parse_int(lmt.get("bank"))
        if lmt.has("bank") and bank not in FREE_BANKS:
            errors.append(f"<lmt bank={lmt.get('bank')!r}>: a fixed bank is 10-14 (or leave bank= out: the motion "
                          f"registry places the LMT)")
        if not lmt.get("path"):
            errors.append("<lmt> has no path")
        for other in env.others:
            if bank is not None and other.character == character and other.bank == bank and other.lmt_path and \
                    other.lmt_path.lower() != (lmt.get("path") or "").lower():
                errors.append(f"bank {bank} already holds {other.lmt_path} for {other.name} ({other.where}): one "
                              f"bank per LMT per character, pick another free bank or share that file")

    table = doc.child(root, "table")
    commands = doc.children(root, "command")
    _check_commands(doc, commands, errors, warnings)
    if table is not None:
        if overlay:
            warnings.append("an overlay's <table> is ignored (it has no row)")
        words = 0
        for f in doc.children(table, "follows"):
            if not f.get("move"):
                errors.append("<follows> needs move=")
            elif parse_int(f.get("move")) is None and not _move_exists(env, f.get("move"), character, doc):
                warnings.append(f"<follows move='{f.get('move')}'>: no such move in the scene or the movedef folder")
            if f.get("window") and f.get("window") not in CATEGORIES:
                errors.append(f"<follows window='{f.get('window')}'>: unknown category")
            words += 2 if f.get("window") else 1
        for w in doc.children(table, "window"):
            if w.get("category") not in CATEGORIES:
                errors.append(f"<window category='{w.get('category')}'>: unknown category")
            words += 1
        if words > MAX_CANCEL_WORDS:
            errors.append(f"the row needs {words} cancel words, {MAX_CANCEL_WORDS} at most (a <follows> with a "
                          f"window takes two)")
        inp = doc.child(table, "input")
        if inp is not None:
            command = inp.get("command", "")
            own = {c.get("name") for c in commands}
            shared = env.shared_commands.get(character, set())
            if parse_int(command) is None and command not in own and command not in shared:
                errors.append(f"<input command='{command}'>: no <command> of that name (in this file or a "
                              f"shared one), and not a CMD_ID number")
    elif not overlay and not stages(doc):
        errors.append("a move needs a <table> row or a <stage>")

    attack_names = set()
    for a in doc.children(root, "attack"):
        label = f"<attack name='{a.get('name', '')}'>"
        if not a.get("name"):
            errors.append("an <attack> has no name")
        elif a.get("name") in attack_names:
            errors.append(f"two attacks are named '{a.get('name')}'")
        elif len(a.get("name")) > 15:
            warnings.append(f"{label}: the game cuts the name to 15 characters ({a.get('name')[:15]})")
        attack_names.add(a.get("name"))
        if a.has("atk") or a.has("entry"):
            _check_entry(env, a, a.get("atk") or "Collision\\" + character, label, errors, warnings)

    all_stages = stages(doc)
    if len(all_stages) > 1:
        warnings.append(f"{len(all_stages)} stages: the runner runs the first one only (chain files instead)")
    for stage in all_stages:
        _check_stage(doc, stage, lmt, bank, character, env, overlay, errors, warnings)
    _unknown(doc, warnings)
    return errors, warnings


def _move_exists(env, name, character, doc):
    name = name[5:] if name.startswith("move:") else name
    if name == doc.root.get("name"):
        return True
    return any(o.name == name and o.character == character for o in env.others)


def _check_commands(doc, commands, errors, warnings):
    names = set()
    for c in commands:
        label = c.get("name", "")
        if not label:
            errors.append("a <command> has no name")
        elif label in names:
            errors.append(f"two commands are named '{label}'")
        names.add(label)
        steps = [s for s in doc.children(c) if s.tag in ("btn", "lever")]
        if not steps:
            errors.append(f"command '{label}' has no <btn> / <lever> step")
        for s in steps:
            if s.tag == "btn" and s.get("id") not in BUTTONS and parse_int(s.get("id")) is None:
                errors.append(f"command '{label}': <btn id='{s.get('id')}'> is not {', '.join(BUTTONS)} or a number")


def _check_stage(doc, stage, lmt, bank, character, env, overlay, errors, warnings):
    label = f"stage '{stage.get('name', '')}'"
    slots = doc.children(stage, "slot")
    seen = set()
    for slot in slots:
        if slot.get("dir") not in DIRECTIONS:
            errors.append(f"{label}: <slot dir='{slot.get('dir')}'> is not {', '.join(DIRECTIONS)}")
        if slot.get("dir") in seen:
            errors.append(f"{label}: two slots for {slot.get('dir')}")
        seen.add(slot.get("dir"))
        if parse_int(slot.get("block")) is None:
            errors.append(f"{label}: <slot dir='{slot.get('dir')}'> has no block")
    own_lmt = lmt is not None and bool(lmt.get("path"))
    if slots and not own_lmt:
        errors.append(f"{label}: <slot>s play blocks of the move's own LMT, and the move has no <lmt path=>")
    block = stage.has("block")
    if block:
        value = parse_int(stage.get("block"))
        if value is None or not 0 <= value <= 255:
            errors.append(f"{label}: block='{stage.get('block')}' is not a block number 0-255")
        if not own_lmt:
            errors.append(f"{label}: block= plays a block of the move's own LMT, and the move has no <lmt path=>")
        if stage.has("motion"):
            errors.append(f"{label}: block= and motion= together: block= is the move's own LMT, motion= a vanilla "
                          f"motion; keep one")
        if slots:
            warnings.append(f"{label}: block= is for a stage without <slot>s (the slots pick the block)")
    for attr in ("motion", "ctn"):
        if stage.has(attr) and parse_motion(stage.get(attr)) is None:
            errors.append(f"{label}: {attr}='{stage.get(attr)}' is not bank:slot")
    motion = parse_motion(stage.get("motion"))
    if motion is not None and not 0 <= motion[0] <= MAX_MOTION_BANK:
        errors.append(f"{label}: motion={stage.get('motion')}: motion banks are 0-{MAX_MOTION_BANK}; a grab plays "
                      f"from bank {GRAB_BANK} (its script's .ctn bank 10-29 isn't a motion bank)")
    if not slots and not block and motion is None and not overlay:
        errors.append(f"{label}: no block=, motion= or <slot>s")
    script = doc.children(stage, "cancel") + doc.children(stage, "trigger")
    if overlay:
        if script and motion is None:
            errors.append(f"{label}: an overlay's <cancel> / <trigger>s change a vanilla motion's script: the stage "
                          f"needs motion=\"bank:block\" of that motion")
        if not script and not any(e.tag in ("next", "effect", "se", "kill_effect", "finish_effect")
                                  for e in doc.children(stage)):
            warnings.append(f"{label}: the overlay does nothing (no <next>, effect / sound or <cancel> / <trigger>)")
        if doc.children(stage, "cancel") and stage.has("cancel_frame"):
            warnings.append(f"{label}: an overlay's <cancel>s replace all the motion's windows; cancel_frame adds one "
                            f"that opens everything")
    # (an overlay may name a vanilla motion there: Nero's Buster grabs play banks 10-29)
    runtime = set().union(*(RUNTIME_BANKS.get(c, FREE_BANKS) for c in (character or "").split()))
    if motion is not None and motion[0] in runtime and motion[0] != bank and not overlay:
        errors.append(f"{label}: motion={stage.get('motion')} names runtime bank {motion[0]}, whose blocks are the "
                      f"motion registry's: play the move's own LMT with block=")
    if (slots or block or (motion and motion[0] in FREE_BANKS)) and not stage.has("ctn") and not overlay:
        warnings.append(f"{label}: a motion in a runtime bank has no .ctn script of its own; borrow one with ctn= "
                        f"(the runner synthesises the cancels on top)")

    lengths = []
    for b, s in stage_motions(doc, stage):
        if b not in env.known_banks:
            continue
        length = env.block_length(b, s)
        where = "the move's LMT" if b == OWN else f"bank {b}"
        if length is None:
            errors.append(f"{label}: block {s} doesn't exist in {where}")
        elif length <= 0:
            errors.append(f"{label}: block {s} of {where} is empty (no keys: the game soft-locks on it)")
        else:
            lengths.append(length)
    end = min(lengths) if lengths else None
    for e, attr in frame_elements(doc, stage):
        frame = parse_float(e.get(attr))
        if frame is None:
            errors.append(f"{label}: <{e.tag} {attr}='{e.get(attr)}'> is not a number")
        elif frame < 0 or (end is not None and frame >= end):
            span = f"0-{end - 1}" if end is not None else "0 and up"
            message = f"{label}: <{e.tag}> at frame {frame:g} is outside the motion (frames {span})"
            if e.tag == "next" and frame >= 0:
                warnings.append(message + ": it never fires (a looping block wraps first); use on=\"motion_end\", a "
                                "frame inside the block, or ticks= for a time limit")
            else:
                errors.append(message)

    for c in doc.children(stage, "cancel"):
        for cat in (c.get("categories") or c.get("category") or "").replace(",", " ").split():
            if cat not in CATEGORIES:
                errors.append(f"{label}: unknown cancel category '{cat}'")
        if c.get("kind") not in (None, "open", "close", "buffer", "reserve", "open_alt"):
            errors.append(f"{label}: <cancel kind='{c.get('kind')}'> is not open, buffer or close")
    for t in doc.children(stage, "trigger"):
        if (t.get("byte") or "free0").lower() not in [b.lower() for b in CONTACT_BYTES] + ["cam", "pad"]:
            errors.append(f"{label}: <trigger byte='{t.get('byte')}'> is not {', '.join(CONTACT_BYTES)}")
    for e in doc.children(stage, "effect"):
        if parse_int(e.get("list"), -1) < 0 and not e.get("efl"):
            errors.append(f"{label}: an <effect> needs list= + index=, or efl=")
        if e.get("joint", "self") not in ("self", "weapon"):
            errors.append(f"{label}: <effect joint='{e.get('joint')}'>: the runner knows self and weapon")
    for e in doc.children(stage, "kill_effect") + doc.children(stage, "finish_effect"):
        if parse_int(e.get("id"), -1) < 0:
            errors.append(f"{label}: <{e.tag}> needs the id of an <effect id=>")
    launch = doc.child(stage, "launch")
    shells = doc.children(stage, "shell") + (doc.children(launch, "shell") if launch is not None else [])
    if len(shells) > MAX_SHELLS:
        errors.append(f"{label}: {len(shells)} shells, {MAX_SHELLS} at most")
    attacks = {a.get("name") for a in doc.children(doc.root, "attack")}
    for shell in shells:
        if shell.get("attack"):
            if shell.get("attack") not in attacks:
                errors.append(f"{label}: <shell attack='{shell.get('attack')}'> names no <attack> of this file (the "
                              f"runner drops the shell)")
            if shell.has("atk") or shell.has("entry"):
                warnings.append(f"{label}: a <shell> with attack= ignores its own atk= / entry=")
            continue
        _check_entry(env, shell, shell.get("atk") or "Collision\\" + character, f"{label}: <shell>", errors,
                     warnings)
    for n in doc.children(stage, "next"):
        to = n.get("to", "")
        if not to:
            errors.append(f"{label}: a <next> has no to=")
        elif to != "exit" and not _move_exists(env, to, character, doc):
            warnings.append(f"{label}: <next to='{to}'>: no such move of {character} in the scene or the movedef "
                            f"folder")
        if n.has("ticks") and parse_int(n.get("ticks"), -1) < 0:
            errors.append(f"{label}: <next ticks='{n.get('ticks')}'> must be a number of ticks, 0 or more")
        if not any(n.has(a) for a in ("on", "frame", "byte", "button", "ticks")):
            errors.append(f"{label}: <next to='{to}'> has no condition and never fires")


def resolve_entry(names, text):
    """Index of an entry= (an index, or an entry name: case-insensitive, 15 characters) in an .atk's entry names, or
    None when there's no such entry"""
    text = (text or "0").strip()
    if text[:1].isdigit() or text[:1] == "-":
        index = parse_int(text)
        return index if index is not None and 0 <= index < len(names) else None
    want = text[:15].lower()
    return next((i for i, name in enumerate(names) if name.lower() == want), None)


def _check_entry(env, elem, path, label, errors, warnings):
    names = env.atk_names(path)
    if names is None:
        return
    index = resolve_entry(names, elem.get("entry"))
    if index is None:
        errors.append(f"{label} entry='{elem.get('entry', '0')}': {path}.atk has no such entry (entries 0-"
                      f"{len(names) - 1}, by index or name)")
        return
    damages = env.atk_damage(path)
    if damages is not None and damages[index] == 0 and parse_float(elem.get("damage"), -1.0) < 0:
        which = "entry 0, since entry= isn't given" if not elem.has("entry") else f"entry {index}"
        warnings.append(f"{label}: {path}.atk {which} ('{names[index]}') deals no damage (a placeholder or a "
                        f"hit-check entry); set damage= or pick another entry")


def _unknown(doc, warnings):
    """Elements / attributes the runner doesn't read (inside elements it does)"""
    seen, known = set(), set()
    for e in doc.elems:
        parent = doc.by_uid(e.parent)
        if parent is not None and parent.uid not in known:
            continue
        spec = spec_for(e.tag, parent.key if parent is not None else None)
        if spec is None:
            note = f"<{e.tag}> in <{parent.tag}>" if parent is not None else f"<{e.tag}>"
        else:
            known.add(e.uid)
            extra = [k for k, _ in e.attrs if k not in spec.attrs and not (e.tag == "cancel" and k in ("from", "category"))]
            if not extra:
                continue
            note = f"<{e.tag} {' '.join(k + '=' for k in extra)}>"
        if note not in seen:
            warnings.append(f"{note}: the runner doesn't read it (kept in the file)")
            seen.add(note)
