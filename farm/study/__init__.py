"""Shared, point-in-time backtest primitives for research studies."""

from .benchmark import Benchmark
from .costs import CostSelection, StudyCostProfile
from .data import Bar, DataDeclaration, LookAheadError, MarketData, PointInTimeView, PriceSource
from .spec import EventStrategy, ExitRule, FillPoint, Order, PortfolioStrategy
from .universe import ListingInterval, Universe

CORE_VERSION = "p18-study-v1"

__all__ = [
    "CORE_VERSION",
    "Bar",
    "Benchmark",
    "CostSelection",
    "DataDeclaration",
    "EventStrategy",
    "ExitRule",
    "FillPoint",
    "LookAheadError",
    "ListingInterval",
    "MarketData",
    "Order",
    "PointInTimeView",
    "PortfolioStrategy",
    "PriceSource",
    "StudyCostProfile",
    "Universe",
]
