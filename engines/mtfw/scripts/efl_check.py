"""Round-trip and validate DMC4 DX9 .efl files with the albam efl parser. Plain Python, no Blender.

usage: python engines/mtfw/scripts/efl_check.py [root ...] [--json-dir DIR] [--limit N] [--coverage]

For every unique DX9 file under the roots: parse, write back and require identical bytes, then run
the structural checks. --coverage adds field-usage and keyframe-fit statistics (RE leads).
--json-dir dumps each file as JSON plus schema.json. Exits 1 if any file fails to parse or round-trip.
"""
import argparse
import hashlib
import json
import os
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

# the efl package only uses relative imports, so it can be imported without albam (and bpy)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from efl import EffectList, EflError, VERSION_DX9  # noqa: E402
from efl.check import check, Coverage  # noqa: E402
from efl.export_json import to_dict, schema_dict  # noqa: E402

DEFAULT_ROOT = r"E:\DMC mod stuffs"


def iter_unique_files(roots):
    seen = set()
    for root in roots:
        for dirpath, _, filenames in os.walk(root):
            for fn in sorted(filenames):
                if fn.lower().endswith(".efl"):
                    path = os.path.join(dirpath, fn)
                    with open(path, "rb") as f:
                        data = f.read()
                    digest = hashlib.sha1(data).digest()
                    if digest not in seen:
                        seen.add(digest)
                        yield path, data


def first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


def print_coverage(cov):
    print("\n== fields never non-zero (candidates for unused) ==")
    for name in sorted(cov.blocks):
        never = [f for f in _struct_fields(name) if not cov.nonzero[name][f]]
        if never:
            print(f"  {name} ({cov.blocks[name]} blocks): {', '.join(never)}")
    print("\n== unknown gaps with data (RE leads) ==")
    for name in sorted(cov.gap_nonzero):
        for (start, end), n in sorted(cov.gap_nonzero[name].items()):
            print(f"  {name} {start:#x}..{end:#x}: non-zero in {n}/{cov.blocks[name]}")
    print("\n== keyframe blocks: fit of the assumed key type (padded to 16), and which key types fit exactly ==")
    for key in sorted(cov.sub_seen):
        if key in cov.kf_headers:
            fit = dict(cov.kf_fit.get(key, {})) or "-"
            matches = dict(cov.kf_size_match[key].most_common()) or "-"
            heads = dict(cov.kf_headers[key].most_common(3))
            print(f"  {key[0]}.{key[1]}: n={cov.sub_seen[key]} fit={fit} fits={matches} "
                  f"(single,fixangle,inp)={heads}")
        else:
            print(f"  {key[0]}.{key[1]}: n={cov.sub_seen[key]}")


_STRUCT_FIELDS = None


def _struct_fields(name):
    global _STRUCT_FIELDS
    if _STRUCT_FIELDS is None:
        from efl import schema
        _STRUCT_FIELDS = {st.name: [f.name for f in st.fields] for st in schema.all_structs()}
    return _STRUCT_FIELDS.get(name, [])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roots", nargs="*", default=[DEFAULT_ROOT])
    ap.add_argument("--json-dir")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--coverage", action="store_true")
    args = ap.parse_args()

    if args.json_dir:
        os.makedirs(args.json_dir, exist_ok=True)
        with open(os.path.join(args.json_dir, "schema.json"), "w") as f:
            json.dump(schema_dict(), f, indent=1)

    stats = Counter()
    failures = []
    issues = defaultdict(list)
    cov = Coverage() if args.coverage else None
    for path, data in iter_unique_files(args.roots):
        if data[:4] == b"EFL\0" and struct.unpack_from("<I", data, 4)[0] != VERSION_DX9:
            stats["skipped (not DX9)"] += 1
            continue
        if args.limit and stats["dx9"] >= args.limit:
            break
        stats["dx9"] += 1
        try:
            efl = EffectList.from_file(path)
            out = efl.to_bytes()
        except EflError as e:
            failures.append((path, f"parse/write: {e}"))
            continue
        if out != data:
            failures.append((path, f"round-trip differs at byte {first_diff(out, data):#x} "
                                   f"(sizes {len(out):#x} vs {len(data):#x})"))
            continue
        stats["round-trip ok"] += 1
        stats["records"] += len(efl.records)
        for code, where, detail in check(efl):
            issues[code].append((path, where, detail))
        if cov:
            cov.add(efl)
        if args.json_dir:
            rel = os.path.relpath(path, args.roots[0]).replace(os.sep, "__")
            with open(os.path.join(args.json_dir, rel + ".json"), "w") as f:
                json.dump(to_dict(efl), f, indent=1)

    print(", ".join(f"{k}: {v}" for k, v in stats.items()))
    for path, msg in failures[:20]:
        print(f"FAIL {path}: {msg}")
    if len(failures) > 20:
        print(f"... {len(failures) - 20} more failures")
    print(f"\n== check issues ({sum(len(v) for v in issues.values())}) ==" if issues else "\nno check issues")
    for code, rows in sorted(issues.items(), key=lambda kv: -len(kv[1])):
        by_where = Counter(where.split(":", 1)[-1].split(".", 1)[-1] if "." in where else where
                           for _, where, _ in rows)
        print(f"  {code}: {len(rows)}  top: {dict(by_where.most_common(4))}")
        for path, where, detail in rows[:2]:
            print(f"      e.g. {os.path.basename(path)} {where} {detail}")
    if cov:
        print_coverage(cov)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
