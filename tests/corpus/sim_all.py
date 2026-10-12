"""Simulate every record of every unique DX9 effect for 60 game frames (ended at 40) and evaluate its particles:
the preview's simulation (efl/sim.py) must not raise on any game file."""
import time
import traceback
from collections import Counter

from _corpus import files
from efl.sim import simulate, state_at

start = time.time()
errors, examples, count = Counter(), {}, 0
for path, efl in files():
    for i, record in enumerate(efl.records):
        if record.gen is None:
            continue
        try:
            particles = simulate(record, seed=i, max_frames=60, end_frame=40)
            for p in particles[:30]:
                for frame in range(p.birth, min(p.birth + p.lifetime(), 60), 7):
                    state_at(p, frame)
            count += 1
        except Exception as err:
            key = repr(err)[:80]
            errors[key] += 1
            examples.setdefault(key, (path, i, traceback.format_exc()[-600:]))
print(f"records {count}, errors {sum(errors.values())}, {time.time() - start:.0f} s")
for key, n in errors.most_common(5):
    print(n, key, examples[key][:2])
    print(examples[key][2])
print("FAILURES:", [f"{n} x {key}" for key, n in errors.most_common()])
