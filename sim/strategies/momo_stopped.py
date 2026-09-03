"""momo_stopped — template_top10_banded selection plus a daily protective stop.

The A/B partner of template_top10_banded: identical weekly selection (top `n` by
RS, a holding kept while its rank is within `band_rank`, equal weight), so any
difference in the forward record is attributable to the stop alone.
Stop (checked every session): sell in full when today's close is below
`stop_frac` × the close on the most recent weekly-signal session — the price the
position was last sized against. If that reference is unavailable the position's
avg_cost stands in; a name stopped today is excluded from the same call's
rebalance so only one order per leg is emitted.
"""
from __future__ import annotations

from .. import calendar
from .base import (
    Order,
    PortfolioView,
    Strategy,
    apply_agent_gate,
    close_on,
    latest_screen_date,
    passing_ranked,
    rank_position,
    rebalance_orders,
)


def _last_week_signal(con, as_of):
    rows = con.execute(
        "SELECT DISTINCT date FROM prices WHERE date <= ? ORDER BY date DESC LIMIT 10",
        [as_of],
    ).fetchall()
    for (d,) in rows:
        if calendar.is_week_signal(con, d):
            return d
    return None


def _avg_cost(con, pf_id: str, ticker: str) -> float | None:
    row = con.execute(
        "SELECT avg_cost FROM sim_positions WHERE portfolio_id = ? AND ticker = ?",
        [pf_id, ticker],
    ).fetchone()
    if row is None or row[0] is None or row[0] <= 0:
        return None
    return float(row[0])


class MomoStopped(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        stop_frac = p.get("stop_frac", 0.85)
        orders: list[Order] = []
        stopped: set[str] = set()

        ref_date = _last_week_signal(con, as_of)
        for tk, qty in pf.positions.items():
            ref = close_on(con, tk, ref_date) if ref_date is not None else None
            if ref is None:
                ref = _avg_cost(con, pf.id, tk)
            close = close_on(con, tk, as_of)
            if ref is None or close is None:
                continue
            if close < stop_frac * ref:
                orders.append(Order(pf.id, tk, "sell", qty, as_of))
                stopped.add(tk)

        if not calendar.is_week_signal(con, as_of):
            return apply_agent_gate(pf, as_of, orders)
        sd = latest_screen_date(con, as_of)
        if sd is None:
            return apply_agent_gate(pf, as_of, orders)
        n = p.get("n", 10)
        band = p.get("band_rank", 20)
        ranks = rank_position(con, sd)
        top = [t for t, _ in passing_ranked(con, sd)[:n]]
        keepers = [t for t in pf.positions if ranks.get(t, 10**9) <= band]
        target_names = list(dict.fromkeys(top + keepers))
        if not target_names:
            targets = {}
        else:
            w = 1.0 / len(target_names)
            targets = {t: w for t in target_names}
        orders += [o for o in rebalance_orders(con, pf, as_of, targets)
                   if o.ticker not in stopped]
        # Agent gate LAST, so it sees the final algo intent. It only ever
        # removes or shrinks BUYs; a book without `agent_gate` is untouched.
        return apply_agent_gate(pf, as_of, orders)
