"""Shared corpus loader for the plain-Python tests: every unique DX9 .efl under <data>/arctool, parsed."""
import glob
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402

common.plain()
from efl import EffectList, EflError  # noqa: E402


def files():
    """(path, EffectList) for each unique DX9 effect list (Special Edition files are skipped)."""
    seen = set()
    for path in sorted(glob.glob(os.path.join(common.ARCTOOL, "**", "*.efl"), recursive=True)):
        data = open(path, "rb").read()
        digest = hashlib.md5(data).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        try:
            yield path, EffectList.from_bytes(data)
        except EflError:
            pass
