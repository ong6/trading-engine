"""Shared trade, calendar-session, fold, risk, and capacity statistics."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

import numpy as np

from farm.stats import equity, inference
from farm.walkforward.monthly import block_bootstrap_ci


@dataclass(frozen=True)
class TradeObservation:
    entry_session: date
    net_return: float
    notional: float
    mdv60: float | None
    auction_volume: float | None = None


def _t_stat(values: np.ndarray) -> tuple[float, float, float]:
    mean = float(values.mean()) if len(values) else float("nan")
    se = float(values.std(ddof=1) / math.sqrt(len(values))) if len(values) > 1 else float("nan")
    return mean, se, mean / se if se > 0 else float("nan")


def clustered_trade_stats(trades: Iterable[TradeObservation]) -> dict:
    observations = tuple(trades)
    values = np.asarray([trade.net_return for trade in observations], dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("trade returns must be finite")
    mean = float(values.mean()) if len(values) else float("nan")
    groups: dict[date, float] = {}
    for trade in observations:
        groups[trade.entry_session] = groups.get(trade.entry_session, 0.0) + trade.net_return - mean
    count = len(groups)
    se = (math.sqrt(count / (count - 1) * sum(value * value for value in groups.values())
                    / len(values) ** 2)
          if len(values) > 1 and count > 1 else float("nan"))
    return {"n": len(values), "entry_session_clusters": count, "mean": mean, "se": se,
            "one_sided_t": mean / se if se > 0 else float("nan")}


def event_capital(max_concurrent_slots: int, slot_notional: float) -> float:
    capital = max_concurrent_slots * slot_notional
    if max_concurrent_slots < 1 or not math.isfinite(capital) or capital <= 0:
        raise ValueError("event capital inputs must be positive")
    return float(capital)


def calendar_day_series(sessions: Iterable[date], pnl_by_session: Mapping[date, float], *,
                        capital: float) -> np.ndarray:
    days = tuple(sessions)
    if list(days) != sorted(set(days)) or capital <= 0 or not math.isfinite(capital):
        raise ValueError("calendar sessions must be sorted and capital positive")
    unknown = set(pnl_by_session) - set(days)
    if unknown:
        raise ValueError(f"PnL outside the calendar window: {sorted(unknown)}")
    values = np.asarray([pnl_by_session.get(day, 0.0) / capital for day in days], dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("calendar returns must be finite")
    return values


def calendar_statistics(dates: list[date], returns: Iterable[float], *, census_n: int,
                        periods_per_year: int = 252, gross_exposure: Iterable[float] | None = None,
                        traded_notional: float = 0.0, capital: float = 1.0,
                        bootstrap_seed: int = inference.BOOTSTRAP_SEED,
                        bootstrap_draws: int = inference.BOOTSTRAP_DRAWS,
                        bootstrap_mean_block: float = 4.0) -> dict:
    values = np.asarray(tuple(returns), dtype=float)
    if len(dates) != len(values) or not np.all(np.isfinite(values)):
        raise ValueError("calendar dates and returns must be finite and aligned")
    if type(census_n) is not int or census_n < 1:
        raise ValueError("census_n must be a positive integer")
    mean, se, t_stat = _t_stat(values)
    std = float(values.std(ddof=1)) if len(values) > 1 else float("nan")
    sharpe = mean / std * math.sqrt(periods_per_year) if std > 0 else float("nan")
    dsr, per_period_sharpe, sr0 = inference.deflated_sharpe(values, census_n)
    curve = np.cumprod(1 + values)
    exposures = np.asarray(tuple(gross_exposure), dtype=float) if gross_exposure is not None else None
    if exposures is not None and (exposures.shape != values.shape or not np.all(np.isfinite(exposures))):
        raise ValueError("gross exposure must be finite and calendar-aligned")
    ci = block_bootstrap_ci(values, stat="mean", seed=bootstrap_seed,
                            n_boot=bootstrap_draws, mean_block=bootstrap_mean_block)
    return {
        "n_sessions": len(values), "mean": mean, "se": se, "one_sided_t": t_stat,
        "sharpe_annual": sharpe, "deflated_sharpe": dsr, "sharpe_per_session": per_period_sharpe,
        "sr0": sr0, "census_n": census_n, "stationary_bootstrap_ci": ci,
        "max_drawdown": equity.max_drawdown(curve),
        "worst_month": equity.worst_month(dates, curve),
        "exposure": float(exposures.mean() / capital) if exposures is not None and len(values) else None,
        "turnover": float(traded_notional / capital),
    }


def fold_statistics(dates: list[date], returns: Iterable[float], folds: Iterable[object]) -> dict:
    values = np.asarray(tuple(returns), dtype=float)
    if len(dates) != len(values):
        raise ValueError("fold dates and returns must be aligned")
    rows = []
    for fold in folds:
        sample = values[[fold.split_date < day <= fold.validate_end for day in dates]]
        mean, se, t_stat = _t_stat(sample)
        rows.append({"fold": fold.index, "start": fold.split_date.isoformat(),
                     "end": fold.validate_end.isoformat(), "n": len(sample),
                     "mean": mean, "se": se, "one_sided_t": t_stat,
                     "positive": bool(mean > 0)})
    return {"folds": rows, "positive_folds": sum(row["positive"] for row in rows),
            "recency": rows[-3:]}


def capacity_statistics(trades: Iterable[TradeObservation]) -> dict:
    rows, mdv, auction = [], [], []
    for trade in trades:
        mdv_share = trade.notional / trade.mdv60 if trade.mdv60 and trade.mdv60 > 0 else None
        auction_share = (trade.notional / trade.auction_volume
                         if trade.auction_volume and trade.auction_volume > 0 else None)
        rows.append({"notional": trade.notional, "mdv60_share": mdv_share,
                     "auction_volume_share": auction_share})
        if mdv_share is not None:
            mdv.append(mdv_share)
        if auction_share is not None:
            auction.append(auction_share)
    return {"orders": rows, "max_mdv60_share": max(mdv, default=None),
            "max_auction_volume_share": max(auction, default=None)}
