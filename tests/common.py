"""Shared setup for Albam's test scripts.

Blender tests (tests/blender/test_*.py) run inside headless Blender (`run_tests.py` starts them); corpus tests
(tests/corpus/*.py) run in plain Python. Both find the game data through ALBAM_DMC4_DATA (default
E:\\DMC mod stuffs, the folder holding `arctool`) and write their output under ALBAM_TEST_OUT (default
<temp>/albam_tests). The data is only read, never written.
"""
import os
import shutil
import sys
import tempfile

TESTS = os.path.dirname(os.path.abspath(__file__))
ALBAM = os.path.dirname(TESTS)                 # the add-on package folder
ADDONS = os.path.dirname(ALBAM)                # the folder holding the `albam` package
MTFW = os.path.join(ALBAM, "engines", "mtfw")  # `efl` imports from here in plain Python
DATA = os.environ.get("ALBAM_DMC4_DATA", r"E:\DMC mod stuffs")
ARCTOOL = os.path.join(DATA, "arctool")
NERO = os.path.join(ARCTOOL, "uPlayerNero-vanilla")
MODS = os.environ.get("ALBAM_DMC4_MODS", r"D:\DMC4 mods")   # mod packs (DanteJDC's ec002_00v0 for a few tests)
OUT = os.environ.get("ALBAM_TEST_OUT") or os.path.join(tempfile.gettempdir(), "albam_tests")


def skip_unless(*paths):
    """End the test as skipped (the runner reports it, not as a failure) when a data file it needs is missing."""
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        print("SKIPPED: missing " + ", ".join(missing))
        print("FAILURES: []")
        sys.stdout.flush()
        sys.exit(0)


def out_dir(name):
    """An empty folder under OUT for a test's files."""
    path = os.path.join(OUT, name)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    return path


def register():
    """Import and register the add-on (Blender tests)."""
    if ADDONS not in sys.path:
        sys.path.insert(0, ADDONS)
    import albam
    albam.register()
    return albam


def plain():
    """Make the pure-Python EFL modules importable as `efl` (corpus tests)."""
    if MTFW not in sys.path:
        sys.path.insert(0, MTFW)
