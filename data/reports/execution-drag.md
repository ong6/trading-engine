# Execution-timing drag — as of 2026-09-06

Signed cost (bp, >0 = adverse) of filling at next-open vs the signal-day close,
over every sim fill on record. See farm/execution_drag.py for method and the
interpretation guard (noise-dominated at small n; read per book).

- Fills: **975**
- Overnight move alone: mean **+2.7 bp** · stdev 359 bp · t = 0.24
- All-in (incl. slippage): mean **+17.4 bp**
- Adverse overnight moves: 483/975

| Book | mean overnight bp | n | t |
|---|---|---|---|
| adaptive_mr | +220.4 | 18 | 1.00 |
| adaptive_mr_frozen | +220.4 | 18 | 1.00 |
| agentic_alloc | -2.1 | 8 | -0.11 |
| agentic_alloc_frozen | -2.1 | 8 | -0.11 |
| discretionary | +99.7 | 1 | 0.00 |
| dual_momentum | -12.4 | 2 | -0.48 |
| dual_momentum_gated | -12.4 | 2 | -0.48 |
| earnings_context_pead | -26.1 | 21 | -0.62 |
| ew_benchmark | +12.6 | 120 | 0.26 |
| ew_trend_gated | -50.3 | 49 | -2.13 |
| ew_voltarget | -50.3 | 49 | -2.13 |
| high_52wk | +20.8 | 54 | 1.94 |
| low_vol | +1.8 | 46 | 0.17 |
| macro_composite | -8.5 | 1 | 0.00 |
| momo_stopped | -67.5 | 66 | -2.19 |
| mr_overlay | +20.3 | 71 | 0.33 |
| mr_overlay_gated | +20.3 | 71 | 0.33 |
| news_gated_momo | -51.7 | 24 | -1.68 |
| pead_ear | +13.7 | 26 | 0.41 |
| sector_momentum | -34.9 | 5 | -0.64 |
| spy_benchmark | +50.7 | 1 | 0.00 |
| stop_tuner_turtle | -18.1 | 10 | -0.63 |
| template_top10_banded | +1.3 | 92 | 0.07 |
| template_top10_banded_gated | +1.3 | 92 | 0.07 |
| template_top5 | +19.9 | 47 | 0.74 |
| template_top5_gated | +19.9 | 47 | 0.74 |
| turtle_breakout | -72.1 | 26 | -1.03 |

_Decision rule (pre-committed 2026-07-29): consider close-execution (MOC-style)
A/B variants only for a book whose drag is adverse with t > 2 at n ≥ 100 own
fills. Mean-reversion books are expected to keep a favorable sign — leave them._
