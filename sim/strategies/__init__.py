"""Strategy registry: maps a config's `strategy` name to its Strategy class."""
from __future__ import annotations

from .base import Order, PortfolioView, Strategy
from .dual_momentum import DualMomentum
from .ew_benchmark import EwBenchmark
from .mr_overlay import MrOverlay
from .spy_benchmark import SpyBenchmark
from .template_top10_banded import TemplateTop10Banded
from .template_top5 import TemplateTop5

REGISTRY: dict[str, type[Strategy]] = {
    "template_top5": TemplateTop5,
    "template_top10_banded": TemplateTop10Banded,
    "dual_momentum": DualMomentum,
    "mr_overlay": MrOverlay,
    "ew_benchmark": EwBenchmark,
    "spy_benchmark": SpyBenchmark,
}


def get_strategy(name: str) -> Strategy:
    return REGISTRY[name]()


__all__ = ["Order", "PortfolioView", "Strategy", "REGISTRY", "get_strategy"]
