---
plan: P2
title: League collapse to ten books
status: approved
opened: 2026-09-18
owner_decision: none
---

## Goal

The paper league carries only books that still answer an open question. Retired books keep
their full history (`active = FALSE`, equity in `league.csv`, walk-forward artifacts intact)
and stop consuming nightly steps, comparisons, and reader attention.

## Why now

The 2026-09-02 evaluation ranked this second of its five actions and it has not happened;
the eleven registered legacy retirement targets remain active. Three pairs are byte-identical
(each regime-gated twin has
the same equity, drawdown and fill count as its ungated book, so the gate has never fired in
two months and the pair is one book counted twice). The own-model backtest grid already showed
no stock-picking book beats equal-weight on any window of three years or more. Fewer books
means fewer comparisons to deflate against and a league table a human can read.

## Scope

Retire (set `active = FALSE`, no deletion, one BUILDLOG line each):

| Book | Reason |
|---|---|
| Template Top 5 (regime-gated) | Identical to its twin; gate never fired |
| Mean-Reversion Overlay (regime-gated) | Same |
| Dual Momentum (regime-gated) | Same |
| Template Top 10 banded (regime-gated) | Same |
| Template Top 10 (banded) | −6.3% with −15.8% drawdown; 15-year replay hit −83% |
| Template Top 5 | −18.6% drawdown in two months; evaluation verdict was drop |
| Turtle Breakout | Evaluation verdict: drop; walk-forward WATCH/REVIEW |
| 52-Week-High Momentum | Same |
| Mean-Reversion Overlay | Same |
| EW Screen — 200d Trend Gated | Same |
| Macro Composite (all-signals) | One fill in six weeks; adds nothing the single-signal books do not |

Keep (10): SPY Buy & Hold, Equal-Weight Benchmark, Sector ETF Rotation (frozen forward),
XS Momentum 12-1 (frozen forward), Momentum Top 10 stop-managed, Dual Momentum, PEAD,
Low-Volatility Defensive, EW Screen Inverse-Vol, Discretionary.

Mechanics: one `sim/league.py` or SQL path that already exists for the archived agentic books
(`active = FALSE`); the nightly league step and reports already filter on `active`. Update
the root README without assuming a final total because newer separately authorized books are
outside this frozen eleven-book set; `league.md` regenerates itself. Walk-forward keeps replaying
retired books only if the Sunday driver selects on `active`; confirm and leave it.

## Not in scope

- Adding any book, including a "cleaner" replacement for a retired one.
- Touching `sector_momentum`, `xs_momentum_12_1`, `spy_benchmark`, or `ew_benchmark`. The
  frozen forward records depend on them.
- Changing any retired book's config before retiring it "to see if it helps".
- Re-running walk-forward or backtests to justify the list. The evidence exists.

## Done when

- The exact eleven listed legacy books are inactive after the next nightly, and the total active
  count is eleven below its pre-P2 value; separately authorized P8/P15/P7 books are unchanged.
- `league.csv` still contains every retired book's history (row count for each retired book
  unchanged before and after).
- `research.active_books` in the metrics snapshot falls by exactly eleven.
- Forward reports for sector and XS unchanged in status, count and hashes.

## Budget

One session, two commits (the retirement, the README count), under 100 lines.

## Risks

A retired book might be referenced by a doc test. Fix the doc, not the retirement. If the
owner wants a different keep list, edit the table above before approving; the plan does not
change once active.
