"""Live `.sdl` edits, the file side (pure Python, no bpy): what the game-link client needs to patch a scheduler the
game has loaded (dmc4_hook debug server `sdl_layout` / `sdl_patch`, `Vibed\\GameMCP\\tools.md`).

- `layout(data)`: the file's header and track table in the shape `sdl_layout` answers with (offsets file-relative,
  timing / data offsets only for value tracks, types 6-14), so the two can be compared (`differences`): a different
  version of the file in the game must not be patched.
- `ranges(lay)`: the byte ranges the game lets a patch touch: per int / vector / float / bool track (6-9) its timing
  array (4 bytes a key: frame bits 0-23, mode 24-31) and its value array (4 bytes a key for int / float, 16 for a
  vector, 1 for a bool).
- `diff_runs(old, new, ranges)`: the runs where two same-size images differ, cut at range edges, and the differing
  bytes outside every range (those need export + deploy + a room reload instead).
"""
import struct

HEADER = struct.Struct("<4sHHIII")
TRACK = struct.Struct("<BBHIIIII")
PATCHABLE = (6, 7, 8, 9)            # int, vector, float, bool
VALUE_TRACKS = range(6, 15)         # the tracks whose timing / data offsets the game turns into pointers


def _name(data, area, ofs):
    start = area + ofs
    if not 0 <= start < len(data):
        return None
    end = data.find(b"\0", start)
    raw = data[start:end if end >= 0 else len(data)]
    return raw.decode("utf-8", "replace")


def layout(data):
    """The `sdl_layout` view of a file's bytes."""
    data = bytes(data)
    magic, version, count, frames_word, marker, names = HEADER.unpack_from(data, 0)
    if magic != b"SDL\0":
        raise ValueError("not an .sdl file")
    tracks = []
    for i in range(count):
        ttype, prop, keys, parent, name_ofs, dti, timing, values = TRACK.unpack_from(data, HEADER.size + TRACK.size * i)
        value_track = ttype in VALUE_TRACKS
        tracks.append({"index": i, "type": ttype, "prop_type": prop, "keys": keys, "parent": parent,
                       "name": _name(data, names, name_ofs),
                       "timing_offset": timing if value_track else None,
                       "data_offset": values if value_track else None})
    return {"version": version, "track_count": count, "frames_word": frames_word, "marker_track": marker,
            "name_area_offset": names, "size": len(data), "tracks": tracks}


HEAD_FIELDS = ("version", "track_count", "frames_word", "marker_track", "name_area_offset", "size")
TRACK_FIELDS = ("type", "prop_type", "keys", "parent", "name", "timing_offset", "data_offset")


def differences(mine, game, limit=5):
    """Plain-language differences between two layouts (empty = the same file layout)."""
    out = []
    for f in HEAD_FIELDS:
        if f in game and game[f] != mine[f]:
            out.append("%s: %s here, %s in the game" % (f, mine[f], game[f]))
    for a, b in zip(mine["tracks"], game.get("tracks") or []):
        for f in TRACK_FIELDS:
            if f in b and b[f] != a[f]:
                out.append("track %d (%s) %s: %s here, %s in the game" % (a["index"], a["name"], f, a[f], b[f]))
                break
        if len(out) >= limit:
            break
    return out[:limit]


def value_size(ttype, prop):
    if ttype == 7:
        return 16
    if ttype == 9:
        return 1
    return 4


def ranges(lay):
    """[(start, end, track index, what)] the game accepts patches in, sorted."""
    out = []
    for t in lay["tracks"]:
        if t["type"] in PATCHABLE and t["keys"]:
            n = t["keys"]
            out.append((t["timing_offset"], t["timing_offset"] + 4 * n, t["index"], "timing"))
            out.append((t["data_offset"], t["data_offset"] + value_size(t["type"], t["prop_type"]) * n,
                        t["index"], "values"))
    return sorted(out)


def diff_runs(old, new, spans):
    """(runs [(offset, bytes)], bytes outside every span that differ). old / new must be the same size."""
    if len(old) != len(new):
        raise ValueError("sizes differ")
    old, new = memoryview(bytes(old)), memoryview(bytes(new))
    runs, covered = [], 0
    for start, end, _index, _what in spans:
        i = start
        while i < end:
            if old[i] == new[i]:
                i += 1
                continue
            j = i
            while j < end and old[j] != new[j]:
                j += 1
            runs.append((i, bytes(new[i:j])))
            covered += j - i
            i = j
    total = sum(1 for a, b in zip(old, new) if a != b) if covered or old != new else 0
    return runs, total - covered


def full_runs(data, spans):
    """Every span's bytes: makes the game's image equal `data` in all it lets a patch touch."""
    data = bytes(data)
    return [(start, data[start:end]) for start, end, _i, _w in spans if end > start]


def hex_bytes(b):
    return bytes(b).hex()
