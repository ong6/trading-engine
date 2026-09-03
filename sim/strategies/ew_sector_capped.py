"""ew_sector_capped — the ew_benchmark basket, equal-weighted, with at most
`max_per_sector` names from any one sector.

**LOOK-AHEAD DISCLOSURE, READ THIS FIRST.** This store has NO point-in-time
sector history. `fundamentals` holds five weekly snapshots (2026-07-18 →
2026-08-14) and nothing before that, and `farm/backtest/replay.py` copies the
LATEST snapshot into every scratch store and restamps it to the window's warmup
start. So a replay of 2014 classifies names by their **2026** sector. That is a
static look-ahead, exactly the one `low_vol`'s market-cap floor already carries
and that every farm report discloses. It is materially milder than a look-ahead
on a price or an earnings number — GICS-style sector membership is close to
stationary and a name that changed sector between 2014 and 2026 is the
exception — but it is a look-ahead, it is not fixable with the data on disk,
and any result from this book must be quoted with it attached. The alternative
was to leave the rule untested, which is a silent non-result rather than a
disclosed approximation.

WHY THIS BOOK EXISTS (pre-registered 2026-08-20). `ew_benchmark` is the bar
nothing clears — 30 genuine sweep trials over 10 folds and the best median
excess anywhere is +0.02% — and its one real weakness is a -36.5% to -37.5%
worst-fold drawdown. The screen is momentum-driven, so its top names cluster
hard: on the 2026-08-19 screen, **38 of the top 50 by RS were Healthcare**. A
book like that is a sector bet wearing a diversification costume, and a sector
that de-rates takes three quarters of the book with it.

This attacks the drawdown through DIVERSIFICATION rather than exposure, which
makes it orthogonal to both of its siblings: `ew_gross_voltarget` varies gross
exposure at flat relative weights, and the `concentration` sweep varied total
name COUNT (cap 10…100) while leaving the sector spread entirely alone. Holding
50 names from one sector and 50 names from eight are different books with the
same `cap`, and nothing in this repo has yet told them apart.

THE RULE. Walk the passing names in RS order, best first. Take a name if its
sector is still under `max_per_sector`, otherwise skip it and keep walking —
i.e. an over-cap sector keeps its HIGHEST-RS names and the freed slots backfill
from the next-ranked passers outside it. Stop at `cap` names. Equal weight
1/len(chosen), fully invested.

GUARDS — which are correctness and which are optimisation:

  * The book stays at **100% gross** even when the cap cannot fill `cap` slots
    (few enough sectors among the passers that max_per_sector x n_sectors <
    cap). It equal-weights whatever it did select rather than leaking the
    shortfall to cash. CORRECTNESS, and specifically isolation: a book that
    drifted to 80% invested would be testing exposure, which is
    `ew_gross_voltarget`'s question, and the spread between the two would stop
    being attributable to either rule.
  * An unknown sector is ONE bucket, capped like any other, not a per-name
    exemption. Coverage on the live screen is 473 of 534 passers (88.6%);
    the missing names are mostly ETFs and recent listings. Calling them all one
    sector is wrong, and calling each of them its own sector is also wrong —
    the difference is that the first cannot be used to smuggle concentration
    back in, and the second can. This follows `low_vol`'s existing convention
    ("an unknown sector is its own bucket"). CORRECTNESS-LEANING JUDGMENT CALL,
    stated so a reader can disagree with it.
  * `max_per_sector` (default 10) is the OPTIMISATION axis and the only thing
    the grid varies.

AN EMPTY SECTOR MAP RAISES. If `fundamentals` carries no sector for any name at
all, this book cannot apply its cap and would silently degenerate into a
byte-identical copy of `ew_benchmark` — a plausible-looking row that tests
nothing. That is the exact failure this codebase has hit four times, so it
fails loudly instead.
"""
from __future__ import annotations

from .base import (
    PortfolioView,
    Strategy,
    latest_screen_date,
    passing_ranked,
    rebalance_orders,
)

# The latest fundamentals snapshot at or before as_of. In a replay that snapshot
# has been restamped to the warmup start (see the look-ahead disclosure above),
# so this resolves at every historical date to the same 2026 sector map.
SECTOR_SQL = """
SELECT ticker, sector FROM fundamentals
WHERE as_of = (SELECT MAX(as_of) FROM fundamentals WHERE as_of <= ?)
"""

UNKNOWN = "(unknown)"


class EwSectorCapped(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        cap = int(p.get("cap", 50))
        max_per_sector = int(p.get("max_per_sector", 10))

        if max_per_sector < 1:
            raise ValueError(
                f"ew_sector_capped config is infeasible: max_per_sector="
                f"{max_per_sector} admits no name from any sector, so the book "
                f"would hold nothing forever")
        if cap < 1:
            raise ValueError(
                f"ew_sector_capped config is infeasible: cap={cap}")

        sd = latest_screen_date(con, as_of)
        if sd is None:
            return []
        ranked = [t for t, _ in passing_ranked(con, sd)]
        if not ranked:
            return []

        rows = con.execute(SECTOR_SQL, [as_of]).fetchall()
        sectors = {tk: (sec or UNKNOWN) for tk, sec in rows}
        if not any(sec for sec in sectors.values() if sec != UNKNOWN):
            # No sector data at all: the cap is unenforceable and this book
            # would be an unlabelled duplicate of ew_benchmark.
            raise ValueError(
                "ew_sector_capped cannot run: the fundamentals snapshot at or "
                f"before {as_of} carries no sector for any name, so the "
                "per-sector cap is unenforceable and the book would silently "
                "be ew_benchmark")

        chosen: list[str] = []
        used: dict[str, int] = {}
        for tk in ranked:
            if len(chosen) >= cap:
                break
            sec = sectors.get(tk, UNKNOWN)
            if used.get(sec, 0) >= max_per_sector:
                continue
            used[sec] = used.get(sec, 0) + 1
            chosen.append(tk)
        if not chosen:
            return []

        # Fully invested over whatever the cap admitted — see the guard note.
        w = 1.0 / len(chosen)
        return rebalance_orders(con, pf, as_of, {t: w for t in chosen})
