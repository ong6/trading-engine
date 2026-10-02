"""Shared, point-in-time backtest primitives for research studies."""

from .benchmark import Benchmark
from .costs import CostSelection, StudyCostProfile
from .data import (
    Bar,
    DataDeclaration,
    DerivedInput,
    LookAheadError,
    MarketData,
    PointInTimeView,
    PriceSource,
)
from .protocol import RunIdentity, Windows
from .report import CrossCheckTrade
from .run import RunBatch, StudyJob, run_simulate_jobs
from .simulate import PortfolioLedger, TradeLedger, simulate_events, simulate_portfolio
from .spec import EventStrategy, ExitRule, FillPoint, Order, PortfolioStrategy
from .stats import TradeObservation
from .universe import ListingInterval, Universe
from .version import CORE_VERSION

__all__ = [
    "CORE_VERSION",
    "Bar",
    "Benchmark",
    "CostSelection",
    "CrossCheckTrade",
    "DataDeclaration",
    "DerivedInput",
    "EventStrategy",
    "ExitRule",
    "FillPoint",
    "LookAheadError",
    "ListingInterval",
    "MarketData",
    "Order",
    "PointInTimeView",
    "PortfolioStrategy",
    "PortfolioLedger",
    "PriceSource",
    "RunIdentity",
    "RunBatch",
    "StudyCostProfile",
    "StudyJob",
    "TradeObservation",
    "Universe",
    "Windows",
    "TradeLedger",
    "run_simulate_jobs",
    "simulate_events",
    "simulate_portfolio",
]
