"""high_52wk — monthly book of names trading closest to their 52-week high.

Universe: active, liquid, non-ETF names with at least 252 stored sessions and a
close of at least $3. Signal (one set-based scan): ratio = latest close ÷ the
highest high of the last 252 sessions; names rank by ratio descending, ties
broken by 126-session return. Selection: a holding is kept while its ratio stays
at or above `keep_ratio` and it remains within `keep_rank`; remaining slots are
filled from the top of the candidate list (ratio at or above `min_ratio`) until
`n` names are held. Equal weight `1/n`; unfilled slots stay in cash.
"""
from __future__ import annotations

from datetime import timedelta

from .base import PortfolioView, Strategy, rebalance_orders

RATIO_SQL = """
WITH cand AS (
    SELECT ticker FROM universe WHERE active AND liquid AND NOT etf
), px AS (
    SELECT p.ticker, p.date, p.high, p.close,
           ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) AS rn
    FROM prices p JOIN cand c ON c.ticker = p.ticker
    WHERE p.date <= ? AND p.date > ? AND p.close > 0
)
SELECT ticker,
       MAX(CASE WHEN rn = 1 THEN close END) AS last_close,
       MAX(high) AS hi,
       MAX(CASE WHEN rn = 127 THEN close END) AS ref_close
FROM px WHERE rn <= 252
GROUP BY ticker
HAVING COUNT(*) >= 252 AND MAX(high) > 0
   AND MAX(CASE WHEN rn = 1 THEN close END) >= 3
ORDER BY MAX(CASE WHEN rn = 1 THEN close END) / MAX(high) DESC, ticker
"""


class High52Week(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        rows = con.execute(
            RATIO_SQL, [as_of, as_of - timedelta(days=430)]
        ).fetchall()
        scored = []
        for tk, last_close, hi, ref_close in rows:
            ret126 = (last_close / ref_close - 1) if ref_close else float("-inf")
            scored.append((last_close / hi, ret126, tk))
        scored.sort(key=lambda s: (-s[0], -s[1], s[2]))
        ratios = {tk: r for r, _ret, tk in scored}
        ranks = {tk: i + 1 for i, (_r, _ret, tk) in enumerate(scored)}

        n = p.get("n", 25)
        min_ratio = p.get("min_ratio", 0.85)
        keep_ratio = p.get("keep_ratio", 0.75)
        keep_rank = p.get("keep_rank", 50)
        chosen: list[str] = []
        for tk in sorted(pf.positions, key=lambda t: ranks.get(t, 10**9)):
            if len(chosen) >= n:
                break
            if ratios.get(tk, 0.0) >= keep_ratio and ranks.get(tk, 10**9) <= keep_rank:
                chosen.append(tk)
        for ratio, _ret, tk in scored:
            if len(chosen) >= n:
                break
            if ratio < min_ratio:
                break
            if tk not in chosen:
                chosen.append(tk)

        w = 1.0 / n
        return rebalance_orders(con, pf, as_of, {tk: w for tk in chosen})
