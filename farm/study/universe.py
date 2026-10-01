"""Point-in-time eligibility, liquidity, and delisting treatment."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from .data import PointInTimeView, PriceSource

SURVIVOR_WARNING = "SURVIVOR-BIASED SOURCE"


@dataclass(frozen=True)
class ListingInterval:
    ticker: str
    listed_from: date
    listed_through: date | None = None

    def contains(self, session: date) -> bool:
        return self.listed_from <= session and (
            self.listed_through is None or session <= self.listed_through)


@dataclass(frozen=True)
class DelistingExit:
    ticker: str
    session: date
    exit_price: float
    used_fallback: bool
    applied_return: float | None


class Universe:
    def __init__(self, source: PriceSource, listings: tuple[ListingInterval, ...] | None = None,
                 *, delisting_return: float = -0.30):
        if not -1 <= delisting_return <= 0:
            raise ValueError("delisting return must be between -1 and 0")
        self.source = source
        self.listings = listings
        self.delisting_return = delisting_return
        self._by_ticker = {item.ticker: item for item in listings or ()}
        if listings is not None and len(self._by_ticker) != len(listings):
            raise ValueError("one listing interval per ticker is required")

    @property
    def survivor_warning(self) -> str | None:
        status = self.source.declaration.survivor_status
        return None if self.listings is not None and status == "point_in_time" else SURVIVOR_WARNING

    def is_listed(self, ticker: str, session: date) -> bool:
        interval = self._by_ticker.get(ticker)
        return interval.contains(session) if interval else self.listings is None

    @staticmethod
    def mdv60(view: PointInTimeView, ticker: str, session: date) -> float | None:
        rows = view.history(ticker, ("close", "volume"), before=session, limit=60)
        values = [row["close"] * row["volume"] for row in rows
                  if row["close"] is not None and row["volume"] is not None]
        return float(np.median(values)) if values else None

    def eligible(self, view: PointInTimeView, session: date, *, min_mdv60: float = 0,
                 min_price: float = 0) -> list[str]:
        tickers = sorted({bar.ticker for bar in self.source.bars})
        result = []
        for ticker in tickers:
            if not self.is_listed(ticker, session):
                continue
            history = view.history(ticker, ("close",), before=session, limit=1)
            if not history or history[-1]["close"] is None or history[-1]["close"] < min_price:
                continue
            mdv = self.mdv60(view, ticker, session)
            if mdv is not None and mdv >= min_mdv60:
                result.append(ticker)
        return result

    def delisting_exit(self, ticker: str, *, held_on: date,
                       entry_price: float) -> DelistingExit | None:
        interval = self._by_ticker.get(ticker)
        if interval is None or interval.listed_through is None or interval.listed_through < held_on:
            return None
        candidates = [bar for bar in self.source.bars if bar.ticker == ticker
                      and held_on <= bar.session <= interval.listed_through
                      and bar.close is not None and bar.close >= 0]
        if candidates:
            last = candidates[-1]
            return DelistingExit(ticker, last.session, float(last.close), False, None)
        return DelistingExit(ticker, interval.listed_through,
                             entry_price * (1 + self.delisting_return), True,
                             self.delisting_return)
