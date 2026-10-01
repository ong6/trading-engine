"""Shared, point-in-time backtest primitives for research studies."""

from .data import Bar, DataDeclaration, LookAheadError, MarketData, PointInTimeView, PriceSource
from .spec import EventStrategy, ExitRule, FillPoint, Order, PortfolioStrategy

CORE_VERSION = "p18-study-v1"

__all__ = [
    "CORE_VERSION",
    "Bar",
    "DataDeclaration",
    "EventStrategy",
    "ExitRule",
    "FillPoint",
    "LookAheadError",
    "MarketData",
    "Order",
    "PointInTimeView",
    "PortfolioStrategy",
    "PriceSource",
]
