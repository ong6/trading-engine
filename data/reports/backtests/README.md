# Historical backtests of the league books — IN-SAMPLE-CONTEXT

_17 of 78 planned (book, window) replays complete · generated 2026-07-29 07:41 UTC._

Every book below is replayed by its OWN live strategy code through the real `sim/league.py` day-step: real orders, real t+1-open fills with the league's slippage and liquidity guards, real dividend crediting. Nothing is reimplemented for the backtest, and no bar is ever invented.

## Disclosures — read before any number below

1. **Survivor universe.** `prices` holds only tickers listed TODAY, so every
   name that was delisted, acquired or bankrupted inside a window is absent
   entirely. The house lesson prices this at roughly **+7pp/yr of fake return**
   for a screen-driven book. That is WHY the primary comparison here is
   **vs EW (same universe, same screen)** — the bias is largely common to both
   sides of that difference. Absolute CAGR is context, not evidence.
   Two measurements of the size of the problem, both taken while building this:
   (i) re-screening **2026-07-15** today drops 6 names that were in the live
   universe that day — SBIL, NSA, NOWL, AVNS, TMHC, CCRN — the survivor filter
   visibly at work over *two weeks*; (ii) the screen's eligible universe in
   **July 2011** is **1,237 names against 3,873 today**, and every one of those
   1,237 is a name that was still listed in 2026. The 2011 cross-section is not
   the 2011 market; it is the part of the 2011 market that survived.
2. **In-sample context, not out-of-sample evidence.** These configs are the
   league's pre-registered books, replayed as written — one variant per book, no
   sweep, nothing fitted here. But they were chosen by a human who has seen this
   market, so the whole table is labelled **IN-SAMPLE-CONTEXT**. *The league's
   live forward record is the only out-of-sample evidence*, exactly as the E1
   report says.
3. **`low_vol` uses TODAY'S fundamentals snapshot.** No historical market caps
   exist (first snapshot 2026-07-18), so the "$5B+" filter is the current cap
   list restamped to the window start — a static-cap look-ahead, disclosed.
4. **`pead_ear` is absent, not zero.** `earnings_calendar` only spans
   2026-04→2026-10, so its entry signal cannot be computed historically. Its
   forward record is the only record it has. Nothing was faked to fill the row.
5. **`discretionary` is absent** — it is a human book with no code to replay.
6. **Post-calendar-fix semantics throughout.** `momo_stopped` / `mr_overlay` /
   `turtle_breakout` run the current (post calendar-fix) code, so `mr_overlay`
   holds up to its full 10-session time stop here, unlike its pre-fix live record.
7. **Dividends depend on `corporate_actions` completeness** — the row count in
   force for each replay is recorded in its result JSON (`corporate_actions_
   dividend_rows`). A thin actions table degrades a total return toward a price
   return, which is the conservative direction, never an invented distribution.
8. **Windows end 2026-07-16**, the session before league inception. Nothing
   after that date is read, so the farm and the live forward record do not
   overlap.
9. **Costs are the league's own**: t+1-open fills, `max(half_spread, 5) + 5` bp
   per side, the 1%-of-median-dollar-volume liquidity guard, no same-bar fills,
   no fabricated bars.


⚑ = window clamped to the earliest date the book's inputs exist (e.g. `dual_momentum` cannot start before BIL + 252 sessions).

## Window: 6mo

| Book | Span | Total | CAGR | Vol | Sharpe | Sharpe−BIL | Max DD | Worst mo | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sector_momentum | 2026-01-16→2026-07-16 | +14.85% | +32.23% | +13.71% | 2.14 | 1.88 | −5.75% | −1.41% | +10.15% | +4.40% | 18 |
| spy_benchmark | 2026-01-16→2026-07-16 | +10.45% | +22.20% | +13.82% | 1.54 | 1.28 | −8.76% | −4.87% | +5.74% | +0.00% | 1 |
| mr_overlay_gated | 2026-01-16→2026-07-16 | +9.34% | +19.74% | +18.51% | 1.08 | 0.89 | −8.04% | −1.13% | +4.64% | −1.11% | 221 |
| mr_overlay | 2026-01-16→2026-07-16 | +6.59% | +13.74% | +19.23% | 0.77 | 0.59 | −8.96% | −1.12% | +1.88% | −3.86% | 237 |
| dual_momentum | 2026-01-16→2026-07-16 | +5.43% | +11.27% | +17.48% | 0.71 | 0.50 | −11.42% | −7.82% | +0.73% | −5.01% | 5 |
| low_vol | 2026-01-16→2026-07-16 | +5.32% | +11.02% | +9.73% | 1.14 | 0.78 | −5.63% | −4.74% | +0.61% | −5.13% | 96 |
| ew_benchmark | 2026-01-16→2026-07-16 | +4.70% | +9.72% | +62.38% | 0.46 | 0.41 | −25.57% | −23.55% | +0.00% | −5.74% | 419 |
| dual_momentum_gated | 2026-01-16→2026-07-16 | +1.55% | +3.15% | +15.46% | 0.28 | 0.05 | −11.42% | −7.82% | −3.15% | −8.90% | 5 |
| high_52wk | 2026-01-16→2026-07-16 | −0.41% | −0.82% | +17.80% | 0.04 | -0.16 | −12.19% | −8.20% | −5.11% | −10.85% | 252 |
| template_top5 | 2026-01-16→2026-07-16 | −3.32% | −6.58% | +85.75% | 0.35 | 0.31 | −37.76% | −21.38% | −8.02% | −13.76% | 169 |
| momo_stopped | 2026-01-16→2026-07-16 | −6.05% | −11.84% | +84.18% | 0.28 | 0.24 | −34.15% | −27.95% | −10.75% | −16.50% | 380 |
| template_top10_banded | 2026-01-16→2026-07-16 | −8.22% | −15.89% | +86.90% | 0.24 | 0.20 | −37.25% | −29.23% | −12.92% | −18.66% | 371 |
| turtle_breakout | 2026-01-16→2026-07-16 | −10.29% | −19.68% | +32.45% | -0.52 | -0.63 | −17.21% | −10.72% | −14.99% | −20.73% | 82 |
| template_top10_banded_gated | 2026-01-16→2026-07-16 | −14.31% | −26.78% | +85.01% | 0.07 | 0.02 | −35.34% | −29.23% | −19.02% | −24.76% | 343 |
| template_top5_gated | 2026-01-16→2026-07-16 | −17.14% | −31.58% | +82.82% | -0.05 | -0.09 | −37.76% | −21.39% | −21.85% | −27.59% | 151 |

## Window: 1y

| Book | Span | Total | CAGR | Vol | Sharpe | Sharpe−BIL | Max DD | Worst mo | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2025-07-16→2026-07-16 | +30.63% | +30.66% | +73.19% | 0.74 | 0.68 | −37.76% | −21.39% | · | +9.45% | 340 |
| spy_benchmark | 2025-07-16→2026-07-16 | +21.18% | +21.19% | +12.46% | 1.61 | 1.31 | −8.78% | −4.88% | · | +0.00% | 1 |

_pending: template_top10_banded, dual_momentum, mr_overlay, template_top5_gated, template_top10_banded_gated, dual_momentum_gated, mr_overlay_gated, ew_benchmark, turtle_breakout, momo_stopped, sector_momentum, low_vol, high_52wk_
