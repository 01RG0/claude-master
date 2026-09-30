# brain/sleep/__init__.py
"""Nightly sleep consolidation worker."""

from brain.sleep.consolidator import SleepConsolidator, SHY_GAMMA

__all__ = ["SleepConsolidator", "SHY_GAMMA"]
