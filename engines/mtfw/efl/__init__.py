"""DMC4 DX9 .efl (effect list) parser and writer.

Pure Python with no Blender or Kaitai dependency, so it can be tested outside Blender
(engines/mtfw/scripts/efl_check.py). Only relative imports are used inside this package.
Layout notes and evidence: Vibed/RE/efl_import_plan.md.
"""
from .model import EffectList, Block, Record, SubBlock, EflError, VERSION_DX9, VERSION_SE  # noqa: F401
