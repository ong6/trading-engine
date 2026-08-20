"""Strategy registry: maps a config's `strategy` name to its Strategy class."""
from __future__ import annotations

from .base import Order, PortfolioView, Strategy
from .discretionary import Discretionary
from .dual_momentum import DualMomentum
from .ew_benchmark import EwBenchmark
from .ew_dd_throttle import EwDdThrottle
from .ew_gross_voltarget import EwGrossVolTarget
from .ew_sector_capped import EwSectorCapped
from .ew_trend_gated import EwTrendGated
from .ew_voltarget import EwVolTarget
from .high_52wk import High52Week
from .low_vol import LowVol
from .macro_composite import MacroComposite
from .momo_stopped import MomoStopped
from .mr_overlay import MrOverlay
from .pead_ear import PeadEar
from .sector_momentum import SectorMomentum
from .sleeve_alloc import SleeveAlloc
from .spy_benchmark import SpyBenchmark
from .template_top10_banded import TemplateTop10Banded
from .template_top5 import TemplateTop5
from .turtle_breakout import TurtleBreakout

REGISTRY: dict[str, type[Strategy]] = {
    "discretionary": Discretionary,
    "template_top5": TemplateTop5,
    "template_top10_banded": TemplateTop10Banded,
    "dual_momentum": DualMomentum,
    "mr_overlay": MrOverlay,
    "ew_benchmark": EwBenchmark,
    "ew_voltarget": EwVolTarget,
    "ew_trend_gated": EwTrendGated,
    # Three 2026-08-20 drawdown candidates. They are WALK-FORWARD
    # CANDIDATES, not league books: registering a class here does not
    # create a `portfolios` row, and a candidate becomes a book only when
    # a human pre-registers it in configs.py with an expectation and a
    # kill criterion. Charters live in docs/charters/.
    "ew_gross_voltarget": EwGrossVolTarget,
    "ew_sector_capped": EwSectorCapped,
    "ew_dd_throttle": EwDdThrottle,
    "spy_benchmark": SpyBenchmark,
    "turtle_breakout": TurtleBreakout,
    "momo_stopped": MomoStopped,
    "sector_momentum": SectorMomentum,
    "low_vol": LowVol,
    "macro_composite": MacroComposite,
    "high_52wk": High52Week,
    "pead_ear": PeadEar,
    "sleeve_alloc": SleeveAlloc,
}


def get_strategy(name: str) -> Strategy:
    return REGISTRY[name]()


__all__ = ["Order", "PortfolioView", "Strategy", "REGISTRY", "get_strategy"]
