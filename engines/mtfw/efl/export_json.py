"""EFL -> JSON-ready dicts for inspection and diffing. Evidence tiers live in schema_dict()."""
from __future__ import annotations

from . import schema


def _sub_dict(sub):
    out = {"field": sub.field.name, "kind": sub.kind, "offset": sub.offset, "max_size": sub.end - sub.offset}
    if sub.kind == "kf":
        out["value_type"] = sub.value_type
        out["header"] = sub.header()
        out["raw"] = bytes(sub.data[4:]).hex()
    else:
        out["fields"] = sub.fields()
    return out


def _nonzero_gaps(block):
    out = []
    for start, end in block.struct.gaps():
        raw = bytes(block.data[start:min(end, len(block.data))])
        if any(raw):
            out.append({"offset": start, "raw": raw.hex()})
    return out


def block_dict(block):
    if block is None:
        return None
    return {
        "type": block.type,
        "type_name": block.type_name,
        "struct": block.struct.name,
        "source_offset": block.offset,
        "size": len(block.data),
        "fields": block.fields(),
        "bits": block.bits(),
        "subblocks": [_sub_dict(s) for s in block.subblocks()],
        "unknown_nonzero": _nonzero_gaps(block),
    }


def to_dict(efl):
    return {
        "header": {"version": efl.version, "base_fps": efl.base_fps, "header_unk": efl.header_unk,
                   "record_count": len(efl.records)},
        "records": [{slot: block_dict(block) for slot, block in rec.blocks()} for rec in efl.records],
        "unit_gen": block_dict(efl.unit_gen),
        "unit_move": block_dict(efl.unit_move),
    }


def schema_dict():
    """Every struct with field offsets, types and evidence tiers."""
    out = {}
    for st in schema.all_structs():
        out[st.name] = {
            "size": st.size, "size_tier": st.size_tier,
            "fields": [{"offset": f.offset, "name": f.name, "type": f.type, "tier": f.tier, "note": f.note,
                        **({"sub": f.sub} if f.sub else {})} for f in st.fields],
            "bits": [{"name": b.name, "field": b.field, "shift": b.shift, "width": b.width, "tier": b.tier}
                     for b in st.bits],
        }
    return out
