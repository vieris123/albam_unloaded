"""A vanilla motion's `.ctn` script (dmc4xml `ctn`) as MoveDef <cancel> / <trigger> elements: the starting point for
an overlay that changes the motion's windows (the runner replaces every cancel command of the motion with the file's
<cancel>s, and every set-0 command with its <trigger>s, so within a kind the file lists them all).

Mapping (`Vibed/MoveDef/schema.md`, "Synthesised scripts on vanilla motions"): a contact-set-1 command at frame f
gives one <cancel frame=f kind= categories=> per kind it uses (0x10 open, 0x20 close, 0x30 buffer; byte k's low
nibble n picks `CANCEL_TABLES[k][n]`); a set-0 command one <trigger frame=f byte= value=> per non-zero byte.
"""

KINDS = {0x10: "open", 0x20: "close", 0x30: "buffer"}
TRIGGER_BYTES = ("atck", "free2", "camVib", "free1", "free0", "padVib")   # contact set 0, byte order


def _fmt(frame):
    return str(int(frame)) if float(frame).is_integer() else f"{frame:g}"


def script_elements(data, bank, slot):
    """([(tag, [(name, value)])], notes) of the script for (bank, slot) in the .ctn bytes `data`. Raises
    ValueError when the file has no script there."""
    from dmc4xml import ctn
    table = ctn.read(data)
    script = table.script(bank, slot)
    if script is None:
        raise ValueError(f"the .ctn has no script for bank {bank} slot {slot:#x} (the game hangs on that motion)")
    out, notes = [], []
    for frame, cmd in ctn.events(script):
        if isinstance(cmd, ctn.Loop):
            notes.append(f"the script loops (at frame {_fmt(frame or 0)}): the runner can't change a looping "
                         f"script and plays it unchanged")
            continue
        if isinstance(cmd, ctn.Clear):
            notes.append(f"a clear of contact set {cmd.idx} at frame {_fmt(frame or 0)} has no MoveDef element "
                         f"(the game's stays)")
            continue
        if isinstance(cmd, ctn.Wait):
            continue
        if not isinstance(cmd, ctn.Contact):
            continue
        if frame is None:
            notes.append("a command at the motion's end has no frame; left out")
            continue
        if cmd.idx == 1:
            by_kind = {}
            for k, b in enumerate(cmd.info):
                if not b:
                    continue
                tables = ctn.CANCEL_TABLES[k] if k < len(ctn.CANCEL_TABLES) else ()
                n = b & 0xF
                if n >= len(tables) or (b & 0xF0) not in KINDS:
                    notes.append(f"cancel byte {k} = {b:#04x} at frame {_fmt(frame)} isn't a known window; left out")
                    continue
                by_kind.setdefault(KINDS[b & 0xF0], []).append(ctn.CANCEL_NAMES[tables[n]])
            for kind, cats in by_kind.items():
                out.append((frame, "cancel", [("frame", _fmt(frame)), ("kind", kind), ("categories", " ".join(cats))]))
        elif cmd.idx == 0:
            for name, value in zip(TRIGGER_BYTES, cmd.info):
                if value:
                    out.append((frame, "trigger", [("byte", name), ("value", str(value)), ("frame", _fmt(frame))]))
        else:
            notes.append(f"contact set {cmd.idx} at frame {_fmt(frame)} has no MoveDef element; left out")
    out.sort(key=lambda t: (t[0], t[1] != "trigger"))
    return [(tag, attrs) for _, tag, attrs in out], notes
