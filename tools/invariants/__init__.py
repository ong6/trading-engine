"""Snapshot invariants: read-only checks of a published snapshot (see ``registry``).

Importing the package registers every invariant in ``registry.INVARIANTS`` in report order.
"""

from . import books, market_data, results  # noqa: F401  (registration side effect)
from .registry import INVARIANTS, evaluate, exit_code, load_baseline

__all__ = ["INVARIANTS", "evaluate", "exit_code", "load_baseline"]
