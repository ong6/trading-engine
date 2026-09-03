"""sleeve_alloc — a four-sleeve allocator whose SLEEVE WEIGHTS are the only knob.

The point of this book is to separate *what to own* from *how much of each kind
to own*. The sleeve CONTENTS are algorithmic and frozen; only the four weights
move, and in the AI book they are moved by a weekly agent session inside the
charter's bounds (each sleeve 0–40%, weights summing to 1.00). The frozen twin
runs the same code with permanently equal weights, so the twin isolates the
allocator decision and nothing else.

Sleeves (weekly rebalance, all long-only, all from names the store already
prices — nothing here ever invents an instrument):

  trend      top `trend_n` of the 11 SPDR sector ETFs by mean 3/6/12-month TOTAL
             return, equal weight inside the sleeve. A slot whose ETF has a
             non-positive 12-month total return sits in cash (same convention as
             the live `sector_momentum` book).
  mr         SPY, held only while SPY's RSI(2) is below `mr_rsi_max` at the
             weekly signal — a genuine index-level mean-reversion timing rule.
             Otherwise the sleeve sits in cash.
  defensive  equal weight XLU / XLP / XLV (the classic low-beta sectors).
  cash       BIL. Held as a real instrument rather than as idle cash so the
             sleeve earns its coupon through the league's dividend crediting —
             idle cash in this engine earns 0% by design, which would make a
             "cash sleeve" a silent drag rather than a decision.

Any ticker appearing in more than one sleeve accumulates weight (e.g. XLU can be
both a trend pick and a defensive holding); the book never double-counts it as
two positions.
"""
from __future__ import annotations

from .base import (
    Order,
    PortfolioView,
    Strategy,
    close_on,
    rebalance_orders,
    recent_closes,
    rsi_wilder,
    total_return,
)

SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB",
           "XLRE", "XLC"]
DEFENSIVE = ["XLU", "XLP", "XLV"]
CASH_PROXY = "BIL"
MR_TICKER = "SPY"

SLEEVES = ("trend", "mr", "defensive", "cash")


def sleeve_weights(params: dict) -> dict[str, float]:
    """The four weights as the config carries them, defaulting to equal.

    Read defensively: a config that somehow lost a key must degrade to the
    equal-weight default rather than silently allocating 0% to a sleeve.
    """
    w = params.get("sleeve_weights") or {}
    return {s: float(w.get(s, 0.25)) for s in SLEEVES}


def _trend_picks(con, as_of, n: int) -> list[str | None]:
    """`n` slots, best-scoring sector ETFs first; None = that slot sits in cash.

    Scored on the mean of the 3/6/12-month TOTAL returns (price + dividends),
    because these are distributing ETFs and a price-only ranking is materially
    wrong for them. An ETF with no full 12-month history is not scored — it is
    absent, never imputed.
    """
    scored: list[tuple[float, str]] = []
    for tk in SECTORS:
        rets = [total_return(con, tk, as_of, lb) for lb in (63, 126, 252)]
        if any(r is None for r in rets):
            continue
        scored.append((sum(rets) / len(rets), tk))
    scored.sort(key=lambda x: (-x[0], x[1]))

    picks: list[str | None] = []
    for _score, tk in scored[:n]:
        r12 = total_return(con, tk, as_of, 252)
        picks.append(tk if (r12 is not None and r12 > 0) else None)
    while len(picks) < n:
        picks.append(None)      # not enough scoreable ETFs → those slots are cash
    return picks


class SleeveAlloc(Strategy):
    cadence = "weekly"

    def generate_orders(self, con, pf: PortfolioView, as_of) -> list[Order]:
        p = pf.params
        w = sleeve_weights(p)
        trend_n = int(p.get("trend_n", 3))
        targets: dict[str, float] = {}

        def add(ticker: str, weight: float) -> None:
            if weight > 0:
                targets[ticker] = targets.get(ticker, 0.0) + weight

        # --- trend sleeve -------------------------------------------------- #
        if w["trend"] > 0 and trend_n > 0:
            slot = w["trend"] / trend_n
            for tk in _trend_picks(con, as_of, trend_n):
                if tk is not None:
                    add(tk, slot)          # a None slot is left uninvested

        # --- mean-reversion sleeve ----------------------------------------- #
        if w["mr"] > 0:
            closes = recent_closes(con, MR_TICKER, as_of, 30)
            rsi = rsi_wilder(closes, 2) if len(closes) > 2 else None
            # Unknown RSI → sleeve sits in cash. Never enter on missing data.
            if rsi is not None and rsi < float(p.get("mr_rsi_max", 30.0)):
                add(MR_TICKER, w["mr"])

        # --- defensive sleeve ---------------------------------------------- #
        if w["defensive"] > 0:
            slot = w["defensive"] / len(DEFENSIVE)
            for tk in DEFENSIVE:
                add(tk, slot)

        # --- cash sleeve ---------------------------------------------------- #
        if w["cash"] > 0 and close_on(con, CASH_PROXY, as_of) is not None:
            add(CASH_PROXY, w["cash"])

        return rebalance_orders(con, pf, as_of, targets)
