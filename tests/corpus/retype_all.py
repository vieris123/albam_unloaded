"""Change Type on a sample of the corpus: 60 random DX9 effects, their first 4 records' particle and move blocks
retyped to every offered type and variant, from a template (the corpus block of that type with the fewest keyframes)
and from defaults. Each result must write, read back, keep the shared fields' keyframes, and simulate."""
import os, random, sys, traceback  # noqa: E401
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402

common.plain()
sys.path.insert(0, os.path.join(common.MTFW, "scripts"))
from efl import EffectList, EflError, schema
from efl.retype import _extension_names, retype, offered_types, variants, variant_of, template_score, RetypeError
from efl.edit import keyframe_props, sub_props, block_props
from efl.sim import simulate
from efl_check import iter_unique_files

files = []
templates = {}   # (slot, type, variant) -> (score, block)
for path, data in iter_unique_files([common.ARCTOOL]):
    try:
        efl = EffectList.from_bytes(data)
    except EflError:
        continue
    files.append((path, efl))
    for r in efl.records:
        for slot in ("ptcl", "move"):
            b = getattr(r, slot)
            if b is None:
                continue
            key = (slot, b.type, variant_of(b))
            s = template_score(b)
            if key not in templates or s < templates[key][0]:
                templates[key] = (s, b)
print("files", len(files), "template keys", len(templates))

rng = random.Random(1)
stats, fails = Counter(), []
sample = rng.sample(files, 60)
for path, efl in sample:
    for ri, r in enumerate(efl.records[:4]):
        for slot in ("ptcl", "move"):
            old = getattr(r, slot)
            if old is None:
                continue
            for t, name in offered_types(slot):
                vs = [v for v, _ in variants(slot, t)] or [None]
                for v in vs:
                    for use_template in (True, False):
                        tpl = templates.get((slot, t, v), (None, None))[1] if use_template else None
                        if use_template and tpl is None:
                            continue
                        try:
                            new, notes = retype(old, t, tpl, v)
                        except RetypeError as e:
                            stats["refused"] += 1
                            if "only be made from an example" not in str(e):
                                fails.append((path, ri, slot, name, v, use_template, str(e)))
                            continue
                        except Exception as e:
                            fails.append((path, ri, slot, name, v, use_template, traceback.format_exc()))
                            continue
                        try:
                            # swap into a copy of the file, write, read back, check and simulate
                            copy = EffectList.from_bytes(efl.to_bytes())
                            rec = copy.records[ri]
                            old_copy = getattr(rec, slot)
                            idx = next(i for i, b in enumerate(copy.blocks) if b is old_copy)
                            copy.blocks[idx] = new
                            setattr(rec, slot, new)
                            again = EffectList.from_bytes(copy.to_bytes())
                            nb = getattr(again.records[ri], slot)
                            assert nb.type == t and nb.struct.name == new.struct.name, (nb.struct.name, new.struct.name)
                            assert variant_of(nb) == v or v is None
                            keyframe_props(nb); sub_props(nb); block_props(nb)
                            # shared fields kept
                            skip_words, skip_bits = _extension_names(nb)
                            for b in nb.struct.bits:
                                ob_ = old.struct.bits_by_name.get(b.name)
                                if b.field in skip_words and b.name not in skip_bits and ob_ and ob_.width == b.width:
                                    assert nb.get(b.name) == old.get(b.name), b.name
                            for f in nb.struct.fields:
                                of = old.struct.by_name.get(f.name)
                                if of and not f.sub and of.type == f.type and f.name not in skip_words:
                                    assert nb.get(f.name) == old.get(f.name), f.name
                            # keyframes kept where the field exists
                            okf, nkf = keyframe_props(old), keyframe_props(nb)
                            for k, p in okf.items():
                                if k in nb.struct.by_name and nb.struct.by_name[k].sub == old.struct.by_name[k].sub:
                                    assert nkf[k]["frames"] == p["frames"], k
                            rec2 = again.records[ri]
                            if rec2.gen is not None and rec2.ptcl is not None:
                                simulate(rec2, seed=ri, max_frames=40)
                            stats["ok_tpl" if use_template else "ok_def"] += 1
                        except Exception:
                            fails.append((path, ri, slot, name, v, use_template, traceback.format_exc()))
print(stats)
print("failures", len(fails))
print(Counter(f[6].strip().splitlines()[-1][:90] for f in fails).most_common(10))
for f in fails[:4]:
    print(f[:6]); print(f[6][-1500:])
print("FAILURES:", [f"{f[0]} record {f[1]} {f[2]} -> {f[3]} {f[4]}" for f in fails[:20]])
