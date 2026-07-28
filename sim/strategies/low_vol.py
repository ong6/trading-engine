"""low_vol — monthly defensive book of the lowest-realized-volatility large caps.

Universe: the latest fundamentals snapshot at or before as_of, market cap at or
above `cap_floor`, quote_type EQUITY, still active and liquid in `universe`.
Signal: stddev of daily log returns over the last `vol_lookback` sessions
(names with fewer than 200 usable returns are skipped), ranked ascending in one
set-based scan. Selection: a current holding is kept while it stays within
`keep_rank`, remaining slots go to the lowest-vol names, at most `sector_cap` per
fundamentals sector (an unknown sector is its own bucket), until `n` names are
held. Equal weight `1/n`; unfilled slots stay in cash.
"""
from __future__ import annotations

from datetime import timedelta

from .base import PortfolioView, Strategy, rebalance_orders

VOL_SQL = """
WITH cand AS (
    SELECT f.ticker, f.sector
    FROM fundamentals f
    JOIN universe u ON u.ticker = f.ticker
    WHERE f.as_of = (SELECT MAX(as_of) FROM fundamentals WHERE as_of <= ?)
      AND f.market_cap >= ? AND f.quote_type = 'EQUITY'
      AND u.active AND u.liquid
), px AS (
    SELECT p.ticker, p.date, p.close,
           ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) AS rn
    FROM prices p JOIN cand c ON c.ticker = p.ticker
    WHERE p.date <= ? AND p.date > ? AND p.close > 0
), rets AS (
    SELECT ticker, LN(close / LAG(close) OVER (PARTITION BY ticker ORDER BY date)) AS r
    FROM px WHERE rn <= ?
)
SELECT r.ticker, c.sector, STDDEV_SAMP(r.r) AS vol
FROM rets r JOIN cand c ON c.ticker = r.ticker
WHERE r.r IS NOT NULL
GROUP BY r.ticker, c.sector
HAVING COUNT(*) >= 200 AND STDDEV_SAMP(r.r) IS NOT NULL
ORDER BY vol, r.ticker
"""


class LowVol(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        lookback = p.get("vol_lookback", 252)
        rows = con.execute(VOL_SQL, [
            as_of, p.get("cap_floor", 5e9), as_of,
            as_of - timedelta(days=int(lookback * 1.7)), lookback,
        ]).fetchall()
        if not rows:
            return []
        order = [r[0] for r in rows]
        sectors = {r[0]: (r[1] or "unknown") for r in rows}
        ranks = {tk: i + 1 for i, tk in enumerate(order)}

        n = p.get("n", 30)
        keep_rank = p.get("keep_rank", 60)
        sector_cap = p.get("sector_cap", 5)
        chosen: list[str] = []
        used: dict[str, int] = {}

        def take(tk: str) -> None:
            sec = sectors[tk]
            if used.get(sec, 0) >= sector_cap:
                return
            used[sec] = used.get(sec, 0) + 1
            chosen.append(tk)

        for tk in sorted(pf.positions, key=lambda t: ranks.get(t, 10**9)):
            if len(chosen) >= n:
                break
            if ranks.get(tk, 10**9) <= keep_rank:
                take(tk)
        for tk in order:
            if len(chosen) >= n:
                break
            if tk not in chosen:
                take(tk)

        w = 1.0 / n
        return rebalance_orders(con, pf, as_of, {tk: w for tk in chosen})
