"""Run Albam's test scripts and summarise them.

    python tests/run_tests.py                 # every test
    python tests/run_tests.py keys wait       # tests whose file name contains one of these words
    python tests/run_tests.py -j 3 --blender "C:/Program Files/Blender Foundation/Blender 4.2/blender.exe"

Blender tests (tests/blender/test_*.py) run in headless Blender with factory settings; corpus tests
(tests/corpus/*.py) run in this Python. A test passes when it prints "FAILURES: []" and no "FAIL " line, and exits
with 0. Logs go to <ALBAM_TEST_OUT>/logs (default <temp>/albam_tests/logs). Game data: ALBAM_DMC4_DATA (see
tests/README.md).
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common  # noqa: E402

DEFAULT_BLENDER = os.environ.get("ALBAM_BLENDER", r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe")


def run(test, blender, logs, timeout):
    name = os.path.splitext(os.path.basename(test))[0]
    kind = os.path.basename(os.path.dirname(test))
    if kind == "blender":
        cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", test]
    else:
        cmd = [sys.executable, test]
    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
        output, returncode = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as err:   # the process is killed; a hung Blender shouldn't block the run
        output = (err.stdout or b"").decode("utf-8", "replace") + (err.stderr or b"").decode("utf-8", "replace") \
            if isinstance(err.stdout, bytes) else (err.stdout or "") + (err.stderr or "")
        output += f"\nTIMED OUT after {timeout} s\n"
        returncode = None
    log = os.path.join(logs, f"{kind}_{name}.txt")
    with open(log, "w", encoding="utf-8") as f:
        f.write(output)
    fails = [line for line in output.splitlines() if line.startswith("FAIL ")]
    summary = re.findall(r"^FAILURES: (.*)$", output, re.M)
    ok = returncode == 0 and not fails and summary == ["[]"]
    if returncode is None:
        reason = f"timed out after {timeout} s"
    else:
        reason = "" if ok else (fails[0][5:] if fails else summary[-1] if summary else f"exit code {returncode}, "
                                "no FAILURES line")
    return name, kind, ok, time.time() - start, reason, log


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("words", nargs="*", help="only tests whose file name contains one of these")
    parser.add_argument("-j", "--jobs", type=int, default=4, help="tests run at once (Blender uses ~1 GB each)")
    parser.add_argument("--blender", default=DEFAULT_BLENDER, help="blender executable (or ALBAM_BLENDER)")
    parser.add_argument("--timeout", type=float, default=1800, help="seconds before a test is killed and fails")
    args = parser.parse_args()
    tests = sorted(glob.glob(os.path.join(HERE, "blender", "test_*.py"))) + \
        sorted(glob.glob(os.path.join(HERE, "corpus", "*.py")))
    tests = [t for t in tests if not os.path.basename(t).startswith("_")]
    if args.words:
        tests = [t for t in tests if any(w in os.path.basename(t) for w in args.words)]
    if not tests:
        print("no tests match")
        return 2
    if not os.path.isdir(common.ARCTOOL):
        print(f"game data not found: {common.ARCTOOL} (set ALBAM_DMC4_DATA)")
        return 2
    logs = os.path.join(common.OUT, "logs")
    os.makedirs(logs, exist_ok=True)
    print(f"{len(tests)} tests, {args.jobs} at a time; logs in {logs}", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=max(args.jobs, 1)) as pool:   # results print as each test finishes
        futures = [pool.submit(run, t, args.blender, logs, args.timeout) for t in tests]
        for future in as_completed(futures):
            name, kind, ok, seconds, reason, log = future.result()
            results.append(ok)
            print(f"{'ok  ' if ok else 'FAIL'} {kind}/{name} ({seconds:.0f} s)" + ("" if ok else f": {reason}  [{log}]"),
                  flush=True)
    failed = results.count(False)
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
