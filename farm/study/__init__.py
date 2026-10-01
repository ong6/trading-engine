"""Shared, point-in-time backtest primitives for research studies."""

from .benchmark import Benchmark
from .costs import CostSelection, StudyCostProfile
from .data import Bar, DataDeclaration, LookAheadError, MarketData, PointInTimeView, PriceSource
from .protocol import RunIdentity, Windows
from .spec import EventStrategy, ExitRule, FillPoint, Order, PortfolioStrategy
from .stats import TradeObservation
from .universe import ListingInterval, Universe
from .version import CORE_VERSION

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
    "RunIdentity",
    "StudyCostProfile",
    "TradeObservation",
    "Universe",
    "Windows",
]
