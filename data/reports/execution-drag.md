# Execution-timing drag — as of 2026-07-29

Signed cost (bp, >0 = adverse) of filling at next-open vs the signal-day close,
over every sim fill on record. See farm/execution_drag.py for method and the
interpretation guard (noise-dominated at small n; read per book).

- Fills: **124**
- Overnight move alone: mean **+7.7 bp** · stdev 136 bp · t = 0.63
- All-in (incl. slippage): mean **+22.9 bp**
- Adverse overnight moves: 66/124

| Book | mean overnight bp | n | t |
|---|---|---|---|
| discretionary | +99.7 | 1 | 0.00 |
| mr_overlay | -21.3 | 25 | -0.80 |
| mr_overlay_gated | -21.3 | 25 | -0.80 |
| spy_benchmark | +50.7 | 1 | 0.00 |
| template_top10_banded | +23.5 | 23 | 0.83 |
| template_top10_banded_gated | +23.5 | 23 | 0.83 |
| template_top5 | +30.3 | 13 | 0.74 |
| template_top5_gated | +30.3 | 13 | 0.74 |

_Decision rule (pre-committed 2026-07-29): consider close-execution (MOC-style)
A/B variants only for a book whose drag is adverse with t > 2 at n ≥ 100 own
fills. Mean-reversion books are expected to keep a favorable sign — leave them._
