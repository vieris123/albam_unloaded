"""MoveDef move files (one XML per DMC4 player move, run by the dmc4_hook `MoveDef` runner): the element / attribute
table, a reader / writer that keeps everything it doesn't touch, the checks, and the extraction of a vanilla motion's
`.ctn` cancels.

Pure Python with no Blender dependency, so it can be tested outside Blender (tests/corpus/movedef_check.py). Only
relative imports are used inside this package. The format is the dmc4_hook runner's: `Vibed/MoveDef/schema.md`,
section "Implemented" (and `D:/dmc4_hook/src/dev/movedef/XmlMove.cpp`, which parses it); the Blender side is
`engines/mtfw/movedef_blender.py`.
"""
from .schema import ELEMENTS, spec_for, MIN_ID, FREE_BANKS, OWN  # noqa: F401
from .doc import Doc, Elem, parse, write, MoveDefError  # noqa: F401
