"""DMC4 DX9 attack data (`.atk` = rAttackStatusData, `ATK\\0`): byte-exact reader and writer, plain Python. One
`kAttackStatus` per entry: what a hit does (damage, levels, hit stop, reactions, hit mark / sound, style points, DT
gain, flags, knock direction, element). The game's loader (0x464930) keeps the file in memory and uses each 0x58-byte
entry in place; its writer (0x464A90) writes the header and `memcpy`s the entries (Vibed/RE/resource_loaders_writers.md).
A hitbox group takes entry k of the character's `.atk` (`collision/pl000.atk` ...) through the `.rCollisionIdxData`
rows; dmc4_hook's MoveDef `<shell atk= entry=>` copies one into its capsule.

- header 8: `ATK\\0`, u16 version (0 in all 61 DX9 files), u16 entry count. Special Edition files are version 8 with
  0x6C-byte entries (another layout) and are refused.
- entry 0x58 (`kAttackStatus`, dmc4_hook sdk/uCollisionMgr.hpp): char mAsName[16]; s32 mAttackID; f32 mDamageValue;
  s32 mAttackLv, mAttackLvI, mAttackLvB, mRangeType, mHitStopTimer, mDamageType, mDamageTypeI, mDamageTypeB,
  mHitmarkAngle, mHitSE; f32 mStylishPoint, mStylishTimer, mDTAdd; s32 mAttackFlag, mBlownAngleType, mElementType.
- anything after the last entry is kept as `trailer`.

Values are kept as the raw 32-bit words (floats too, so NaN payloads survive); the field properties convert. The
name keeps its 16 raw bytes (bytes after the terminating NUL are kept until the name is assigned).

    a = atk.read(data); data == atk.write(a)
    e = a.entries[14]; e.name, e.damage, e.blown_angle_type
    a.entries.append(atk.Entry(name="my_kick", damage=120.0, attack_lv=2))
"""
import struct

MAGIC = b"ATK\0"
HEADER = struct.Struct("<4sHH")
ENTRY = struct.Struct("<16s18I")
ENTRY_SIZE = ENTRY.size            # 0x58

# (name, kind) of the 18 words after the name, in file order; kind f = f32, i = s32
FIELDS = (
    ("attack_id", "i"), ("damage", "f"), ("attack_lv", "i"), ("attack_lv_i", "i"), ("attack_lv_b", "i"),
    ("range_type", "i"), ("hit_stop", "i"), ("damage_type", "i"), ("damage_type_i", "i"), ("damage_type_b", "i"),
    ("hitmark_angle", "i"), ("hit_se", "i"), ("stylish_point", "f"), ("stylish_timer", "f"), ("dt_add", "f"),
    ("attack_flag", "i"), ("blown_angle_type", "i"), ("element", "i"),
)
GAME_NAMES = {   # the kAttackStatus member of each field
    "attack_id": "mAttackID", "damage": "mDamageValue", "attack_lv": "mAttackLv", "attack_lv_i": "mAttackLvI",
    "attack_lv_b": "mAttackLvB", "range_type": "mRangeType", "hit_stop": "mHitStopTimer",
    "damage_type": "mDamageType", "damage_type_i": "mDamageTypeI", "damage_type_b": "mDamageTypeB",
    "hitmark_angle": "mHitmarkAngle", "hit_se": "mHitSE", "stylish_point": "mStylishPoint",
    "stylish_timer": "mStylishTimer", "dt_add": "mDTAdd", "attack_flag": "mAttackFlag",
    "blown_angle_type": "mBlownAngleType", "element": "mElementType",
}


class AtkError(ValueError):
    pass


def _word_of(kind, value):
    if kind == "f":
        return struct.unpack("<I", struct.pack("<f", value))[0]
    return value & 0xFFFFFFFF


def _value_of(kind, word):
    if kind == "f":
        return struct.unpack("<f", struct.pack("<I", word))[0]
    return word - 0x100000000 if word & 0x80000000 else word


def _field(index, kind):
    return property(lambda self: _value_of(kind, self.words[index]),
                    lambda self, v: self.words.__setitem__(index, _word_of(kind, v)))


class Entry:
    """One kAttackStatus. Keyword arguments set fields by name (see FIELDS); the rest are 0"""
    __slots__ = ("name_raw", "words")

    def __init__(self, name="", **fields):
        self.words = [0] * len(FIELDS)
        self.name_raw = b"\0" * 16
        self.name = name
        for key, value in fields.items():
            if key not in _INDEX:
                raise AtkError(f"no field {key!r} (fields: {', '.join(n for n, _ in FIELDS)})")
            setattr(self, key, value)

    @property
    def name(self):
        return self.name_raw.split(b"\0", 1)[0].decode("latin-1")

    @name.setter
    def name(self, value):
        raw = value.encode("latin-1")
        if len(raw) > 15:
            raise AtkError(f"name {value!r} is longer than 15 characters")
        self.name_raw = raw.ljust(16, b"\0")

    def fields(self):
        """{field name: value} in file order"""
        return {n: getattr(self, n) for n, _ in FIELDS}

    def copy(self):
        e = Entry.__new__(Entry)
        e.name_raw, e.words = self.name_raw, list(self.words)
        return e

    def __repr__(self):
        return f"Entry({self.name!r}, " + ", ".join(f"{k}={v!r}" for k, v in self.fields().items()) + ")"


_INDEX = {}
for _i, (_n, _k) in enumerate(FIELDS):
    setattr(Entry, _n, _field(_i, _k))
    _INDEX[_n] = _i


class Atk:
    def __init__(self, entries=None, unk=0, trailer=b""):
        self.entries = entries if entries is not None else []
        self.unk, self.trailer = unk, trailer

    def find(self, name):
        """Index of the first entry with that name, or -1"""
        return next((i for i, e in enumerate(self.entries) if e.name == name), -1)


def read(data):
    if len(data) < HEADER.size:
        raise AtkError("file too short for the header")
    magic, unk, count = HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise AtkError(f"not an .atk file (magic {magic!r})")
    if unk != 0:
        raise AtkError(f"version {unk}: not a DX9 .atk (Special Edition files are version 8, with 0x6C-byte entries)")
    end = HEADER.size + count * ENTRY_SIZE
    if end > len(data):
        raise AtkError(f"{count} entries need {end} bytes, the file has {len(data)}")
    entries = []
    for i in range(count):
        values = ENTRY.unpack_from(data, HEADER.size + i * ENTRY_SIZE)
        e = Entry.__new__(Entry)
        e.name_raw, e.words = values[0], list(values[1:])
        entries.append(e)
    return Atk(entries, unk, bytes(data[end:]))


def write(atk):
    if len(atk.entries) > 0xFFFF:
        raise AtkError(f"{len(atk.entries)} entries, 65535 at most")
    out = [HEADER.pack(MAGIC, atk.unk, len(atk.entries))]
    out += [ENTRY.pack(e.name_raw, *e.words) for e in atk.entries]
    out.append(atk.trailer)
    return b"".join(out)
