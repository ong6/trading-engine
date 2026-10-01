"""Seeded price-only market and registered known-answer proving ground."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import NormalDist

import numpy as np

from .benchmark import Benchmark, compare
from .costs import calculate
from .data import Bar, LookAheadError, MarketData, PriceSource
from .report import CrossCheckTrade, price_cross_check
from .stats import TradeObservation, clustered_trade_stats
from .universe import ListingInterval, Universe

POWER_SEEDS = tuple(range(10_000, 10_050))
SIZE_SEEDS = tuple(range(20_000, 20_200))
GAP_FADE_TRUE_RETURN = 0.0035
RETURN_VOLATILITY = 0.015
SAMPLE_TRADES = 256
ONE_SIDED_5PCT_T = NormalDist().inv_cdf(0.95)


@dataclass(frozen=True)
class SyntheticMarket:
    data: MarketData
    listings: tuple[ListingInterval, ...]
    volume_tiers: dict[str, str]
    gap_fade_ticker: str
    momentum_tickers: tuple[str, str]
    noise_ticker: str
    zero_delisting_ticker: str
    gap_fade_truth: float = GAP_FADE_TRUE_RETURN
    secondary_open_bias: float = 0.01


def _sessions(start: date, count: int) -> list[date]:
    days = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _fat_tail(rng: np.random.Generator, scale: float) -> float:
    return float(rng.standard_t(5) * scale / math.sqrt(5 / 3))


def generate_market(seed: int, *, session_count: int = 520,
                    secondary_open_bias: float = 0.01) -> SyntheticMarket:
    """Create tiered prices with gaps, momentum, noise, and two delistings."""
    if session_count < 40:
        raise ValueError("synthetic market needs at least 40 sessions")
    rng = np.random.default_rng(seed)
    sessions = _sessions(date(2014, 1, 2), session_count)
    dollar_volume = {"SPY": 80_000_000, "GAP": 15_000_000, "MOM_UP": 60_000_000,
                     "MOM_DOWN": 8_000_000, "NOISE": 2_000_000,
                     "ZERO": 6_000_000, "DROP": 25_000_000}
    tiers = {ticker: ("high" if value >= 50_000_000 else
                       "mid" if value >= 5_000_000 else "low")
             for ticker, value in dollar_volume.items()}
    prices = {ticker: 50.0 for ticker in dollar_volume}
    primary, secondary = [], []
    delist_index = session_count // 2
    names = tuple(dollar_volume)
    for index, session in enumerate(sessions):
        for name_index, ticker in enumerate(names):
            if ticker in {"ZERO", "DROP"} and index > delist_index:
                continue
            if ticker == "DROP" and index == delist_index:
                continue
            gap = _fat_tail(rng, 0.006)
            intraday = _fat_tail(rng, 0.012)
            if ticker == "GAP" and index % 4 == 0:
                gap = -0.02 - abs(_fat_tail(rng, 0.003))
                intraday += GAP_FADE_TRUE_RETURN
            elif ticker == "MOM_UP":
                intraday += 0.0005
            elif ticker == "MOM_DOWN":
                intraday -= 0.0005
            elif ticker == "SPY":
                intraday += 0.0002
            open_px = max(0.01, prices[ticker] * (1 + gap))
            close = max(0.01, open_px * (1 + intraday))
            if ticker == "ZERO" and index == delist_index:
                close = 0.0
            high, low = max(open_px, close) * 1.002, min(open_px, close) * 0.998
            volume = dollar_volume[ticker] / max(close, 1.0)
            bar = Bar(ticker, session, open_px, high, low, close, volume,
                      auction_volume=volume * 0.08)
            primary.append(bar)
            if (index + name_index) % 37:
                secondary.append(Bar(
                    ticker, session, open_px * (1 + secondary_open_bias), high, low,
                    close, volume, auction_volume=volume * 0.08))
            prices[ticker] = max(close, 0.01)
    primary_source = PriceSource.declared(source="synthetic-primary", bars=primary)
    secondary_source = PriceSource.declared(source="synthetic-independent", bars=secondary)
    listings = tuple(
        ListingInterval(ticker, sessions[0], sessions[delist_index]
                        if ticker in {"ZERO", "DROP"} else None)
        for ticker in names)
    return SyntheticMarket(MarketData(primary_source, secondary_source), listings, tiers, "GAP",
                           ("MOM_UP", "MOM_DOWN"), "NOISE", "ZERO",
                           secondary_open_bias=secondary_open_bias)


def cross_sectional_momentum_weights(source: PriceSource, session: date, *,
                                     lookback: int = 20) -> dict[str, float]:
    scores = []
    for ticker in sorted({bar.ticker for bar in source.bars if bar.ticker.startswith("MOM_")}):
        bars = [bar for bar in source.bars if bar.ticker == ticker and bar.session <= session
                and bar.close is not None and bar.close > 0]
        if len(bars) >= lookback:
            scores.append((bars[-1].close / bars[-lookback].close - 1, ticker))
    if len(scores) < 2:
        return {}
    scores.sort()
    return {scores[-1][1]: 0.5, scores[0][1]: -0.5}


def _sample(seed: int, edge: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.standard_t(5, SAMPLE_TRADES) * RETURN_VOLATILITY / math.sqrt(5 / 3)
    return noise + edge


def _trade_stats(values: np.ndarray) -> dict:
    start = date(2020, 1, 1)
    return clustered_trade_stats(
        TradeObservation(start + timedelta(days=index), float(value), 10_000, 15_000_000)
        for index, value in enumerate(values))


def binomial_99_band(n: int, probability: float) -> tuple[int, int]:
    probabilities = [math.comb(n, k) * probability ** k * (1 - probability) ** (n - k)
                     for k in range(n + 1)]
    cumulative, lower, upper = 0.0, 0, n
    for k, mass in enumerate(probabilities):
        cumulative += mass
        if cumulative >= 0.005 and lower == 0:
            lower = k
        if cumulative >= 0.995:
            upper = k
            break
    return lower, upper


def power_result() -> dict:
    rows = [_trade_stats(_sample(seed, GAP_FADE_TRUE_RETURN)) for seed in POWER_SEEDS]
    pooled = np.concatenate([_sample(seed, GAP_FADE_TRUE_RETURN) for seed in POWER_SEEDS])
    estimate = float(pooled.mean())
    se = float(pooled.std(ddof=1) / math.sqrt(len(pooled)))
    detections = sum(row["one_sided_t"] >= 2 for row in rows)
    return {"seeds": len(rows), "detections": detections, "rate": detections / len(rows),
            "truth": GAP_FADE_TRUE_RETURN, "estimate": estimate, "se": se,
            "within_two_se": abs(estimate - GAP_FADE_TRUE_RETURN) <= 2 * se}


def size_result() -> dict:
    rejections = sum(_trade_stats(_sample(seed, 0))["one_sided_t"] >= ONE_SIDED_5PCT_T
                     for seed in SIZE_SEEDS)
    lower, upper = binomial_99_band(len(SIZE_SEEDS), 0.05)
    return {"seeds": len(SIZE_SEEDS), "rejections": rejections,
            "rate": rejections / len(SIZE_SEEDS), "band": [lower, upper],
            "inside_band": lower <= rejections <= upper}


def _lookahead_canary() -> bool:
    market = generate_market(1, session_count=40)
    session = market.data.primary.sessions[5]
    try:
        market.data.view(session, "at_open", session).value("NOISE", "close")
    except LookAheadError:
        return True
    return False


def _survivor_canary() -> dict:
    start, end = date(2020, 1, 2), date(2020, 1, 3)
    source = PriceSource.declared(source="survivor-canary", bars=[
        Bar("LIVE", start, 100, 100, 100, 100, 1_000),
        Bar("LIVE", end, 100, 100, 100, 100, 1_000),
        Bar("ZERO", start, 100, 100, 100, 100, 1_000),
        Bar("ZERO", end, 100, 100, 0, 0, 1_000)])
    universe = Universe(source, (ListingInterval("LIVE", start),
                                  ListingInterval("ZERO", start, end)))
    zero = universe.delisting_exit("ZERO", held_on=start, entry_price=100)
    with_delisted = ((zero.exit_price / 100 - 1) + 0.0) / 2
    without_delisted = 0.0
    return {"with_delisted": with_delisted, "without_delisted": without_delisted,
            "inflation": without_delisted - with_delisted,
            "passes": zero.exit_price == 0 and without_delisted > with_delisted}


def _cost_canary() -> dict:
    half = _sample(30_000, 0)[:128]
    gross = np.concatenate((half, -half))
    per_side = calculate("baseline_v1", side="buy", notional=10_000, fill_price=100,
                         mdv60=50_000_000).total / 10_000
    expected = 2 * per_side
    net = gross - expected
    stats = _trade_stats(net)
    return {"mean_net": stats["mean"], "expected_cost": expected, "se": stats["se"],
            "passes": abs(stats["mean"] + expected) <= stats["se"]}


def _benchmark_canary() -> dict:
    cost = 0.002
    result = compare(np.asarray([0.01 - cost]), np.asarray([0.01]),
                     Benchmark("ticker", "SYN"))
    return {"excess": result.excess_return, "expected": -cost,
            "passes": math.isclose(result.excess_return, -cost, abs_tol=1e-15)}


def _secondary_canary() -> dict:
    market = generate_market(4, session_count=45)
    sessions = market.data.primary.sessions
    covered = CrossCheckTrade("SPY", "long", sessions[1], "open", sessions[2], "close")
    missing_index = next(index for index, day in enumerate(sessions)
                         if market.data.secondary.get("SPY", day) is None and index > 0)
    uncovered = CrossCheckTrade("SPY", "long", sessions[missing_index - 1], "open",
                                sessions[missing_index], "close")
    result = price_cross_check(market.data, (covered, uncovered),
                               hard_max_date=sessions[-1])
    expected = 1 / (1 + market.secondary_open_bias) - 1
    observed = result["fill_field_distributions"]["open"]["mean"]
    return {"open_ratio_mean": observed, "expected": expected,
            "uncovered_trades": result["uncovered_trades"],
            "recomputed_result": result["per_trade"][0]["secondary_result"],
            "passes": observed < 0 and math.isclose(observed, expected, abs_tol=1e-12)
            and result["uncovered_trades"] == 1}


def run_proving_ground() -> dict:
    return {"power": power_result(), "size": size_result(),
            "canaries": {"lookahead": {"passes": _lookahead_canary()},
                         "survivor": _survivor_canary(), "cost": _cost_canary(),
                         "benchmark": _benchmark_canary(), "secondary": _secondary_canary()}}
