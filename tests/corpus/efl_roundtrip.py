"""The corpus round-trip and invariant check (engines/mtfw/scripts/efl_check.py): every unique DX9 .efl must parse
and write back byte-identical, with no check issues."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402

script = os.path.join(common.MTFW, "scripts", "efl_check.py")
proc = subprocess.run([sys.executable, script, common.DATA], capture_output=True, text=True, errors="replace")
output = proc.stdout + proc.stderr
print(output[-3000:])
failures = []
counts = re.search(r"dx9: (\d+), round-trip ok: (\d+)", output)
if counts is None:
    failures.append(f"no summary line (exit code {proc.returncode})")
elif counts.group(1) != counts.group(2) or counts.group(1) == "0":
    failures.append(f"round-trip ok {counts.group(2)} of {counts.group(1)} files")
if "no check issues" not in output:
    failures.append("check issues reported")
print("FAILURES:", failures)
