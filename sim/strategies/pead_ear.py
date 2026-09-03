"""pead_ear — daily post-earnings-announcement-drift sleeve.

Entry: a name whose earnings landed today or the previous session (known only
from earnings_calendar rows with as_of <= the decision date), whose abnormal
return — its one-day return less SPY's over the same session — is at least
`min_ear`, on volume of at least `vol_mult` × its prior 20-session average, priced
at $3 or more and still active and liquid. Each entry takes `weight` of equity,
up to `max_concurrent` open names.
Exit: `max_hold` sessions after the entry fill, or a close below `stop_frac` ×
the position's avg_cost.
"""
from __future__ import annotations

from datetime import timedelta

from .. import calendar
from ..portfolio import position_open_since
from .base import (
    MIN_ORDER_USD,
    Order,
    PortfolioView,
    Strategy,
    apply_agent_gate,
    close_on,
)

REACTION_SQL = """
WITH ev AS (
    SELECT DISTINCT ticker FROM earnings_calendar
    WHERE as_of <= ? AND earnings_date IN (?, ?)
), today AS (
    SELECT p.ticker, p.close, p.volume FROM prices p
    JOIN ev ON ev.ticker = p.ticker WHERE p.date = ?
), prev AS (
    SELECT p.ticker, p.close FROM prices p
    JOIN ev ON ev.ticker = p.ticker WHERE p.date = ?
), avgvol AS (
    SELECT ticker, AVG(volume) AS av FROM (
        SELECT p.ticker, p.volume,
               ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) AS rn
        FROM prices p JOIN ev ON ev.ticker = p.ticker
        WHERE p.date < ? AND p.date > ?
    ) WHERE rn <= 20 GROUP BY ticker HAVING COUNT(*) = 20
)
SELECT t.ticker, t.close / v.close - 1 AS ret
FROM today t
JOIN prev v ON v.ticker = t.ticker
JOIN avgvol a ON a.ticker = t.ticker
JOIN universe u ON u.ticker = t.ticker
WHERE u.active AND u.liquid AND t.close >= 3 AND v.close > 0
  AND t.volume >= ? * a.av
  AND (t.close / v.close - 1) - ? >= ?
ORDER BY ret DESC, t.ticker
"""


class PeadEar(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        stop_frac = p.get("stop_frac", 0.92)
        max_hold = p.get("max_hold", 45)
        orders: list[Order] = []

        for tk, qty in pf.positions.items():
            since = position_open_since(con, pf.id, tk)
            exit_now = (since is not None
                        and calendar.trading_days_between(con, since, as_of) >= max_hold)
            if not exit_now:
                row = con.execute(
                    "SELECT avg_cost FROM sim_positions "
                    "WHERE portfolio_id = ? AND ticker = ?", [pf.id, tk],
                ).fetchone()
                cost = None if row is None or not row[0] else float(row[0])
                close = close_on(con, tk, as_of)
                exit_now = (cost is not None and close is not None
                            and close < stop_frac * cost)
            if exit_now:
                orders.append(Order(pf.id, tk, "sell", qty, as_of))

        slots = p.get("max_concurrent", 10) - len(pf.positions)
        if slots <= 0:
            return apply_agent_gate(pf, as_of, orders)
        sessions = [r[0] for r in con.execute(
            "SELECT DISTINCT date FROM prices WHERE date <= ? ORDER BY date DESC LIMIT 2",
            [as_of],
        ).fetchall()]
        if len(sessions) < 2:
            return apply_agent_gate(pf, as_of, orders)
        day, prev_day = sessions
        spy_now, spy_prev = close_on(con, "SPY", day), close_on(con, "SPY", prev_day)
        if spy_now is None or spy_prev is None or spy_prev <= 0:
            return apply_agent_gate(pf, as_of, orders)

        weight = p.get("weight", 0.04)
        rows = con.execute(REACTION_SQL, [
            as_of, day, prev_day, day, prev_day, day, day - timedelta(days=60),
            p.get("vol_mult", 2.0), spy_now / spy_prev - 1, p.get("min_ear", 0.05),
        ]).fetchall()
        for tk, _ret in rows:
            if slots <= 0:
                break
            if tk in pf.positions:
                continue
            price = close_on(con, tk, as_of)
            if not price:
                continue
            qty = weight * pf.equity / price
            if qty * price < MIN_ORDER_USD:
                continue
            orders.append(Order(pf.id, tk, "buy", qty, as_of))
            slots -= 1
        # Agent gate LAST, so it sees the final algo intent. It only ever
        # removes or shrinks BUYs; a book without `agent_gate` is untouched.
        return apply_agent_gate(pf, as_of, orders)
