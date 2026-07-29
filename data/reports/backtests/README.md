# Historical backtests of the league books — IN-SAMPLE-CONTEXT

_78 of 78 planned (book, window) replays complete · generated 2026-07-29 14:04 UTC._

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
| sector_momentum | 2026-01-16→2026-07-16 | +14.85% | +32.23% | +13.71% | +2.14 | +1.88 | −5.75% | −1.41% | +10.08% | +4.40% | 18 |
| spy_benchmark | 2026-01-16→2026-07-16 | +10.45% | +22.20% | +13.82% | +1.54 | +1.28 | −8.76% | −4.87% | +5.67% | +0.00% | 1 |
| mr_overlay_gated | 2026-01-16→2026-07-16 | +9.34% | +19.75% | +18.51% | +1.08 | +0.89 | −8.04% | −1.13% | +4.57% | −1.10% | 221 |
| low_vol | 2026-01-16→2026-07-16 | +7.28% | +15.23% | +9.71% | +1.53 | +1.17 | −5.38% | −4.46% | +2.50% | −3.17% | 93 |
| mr_overlay | 2026-01-16→2026-07-16 | +6.59% | +13.75% | +19.23% | +0.78 | +0.59 | −8.96% | −1.12% | +1.82% | −3.85% | 237 |
| dual_momentum | 2026-01-16→2026-07-16 | +5.43% | +11.27% | +17.48% | +0.71 | +0.50 | −11.42% | −7.82% | +0.66% | −5.01% | 5 |
| ew_benchmark | 2026-01-16→2026-07-16 | +4.77% | +9.86% | +62.38% | +0.47 | +0.41 | −25.54% | −23.53% | +0.00% | −5.67% | 419 |
| dual_momentum_gated | 2026-01-16→2026-07-16 | +1.55% | +3.15% | +15.46% | +0.28 | +0.05 | −11.42% | −7.82% | −3.22% | −8.90% | 5 |
| high_52wk | 2026-01-16→2026-07-16 | +0.92% | +1.87% | +17.77% | +0.19 | −0.00 | −11.96% | −7.88% | −3.85% | −9.52% | 252 |
| template_top5 | 2026-01-16→2026-07-16 | −3.26% | −6.46% | +85.74% | +0.36 | +0.31 | −37.73% | −21.38% | −8.03% | −13.70% | 169 |
| momo_stopped | 2026-01-16→2026-07-16 | −5.99% | −11.72% | +84.17% | +0.28 | +0.24 | −34.12% | −27.94% | −10.76% | −16.43% | 380 |
| template_top10_banded | 2026-01-16→2026-07-16 | −8.13% | −15.73% | +86.89% | +0.25 | +0.21 | −37.23% | −29.22% | −12.90% | −18.58% | 371 |
| turtle_breakout | 2026-01-16→2026-07-16 | −10.28% | −19.65% | +32.45% | −0.52 | −0.63 | −17.20% | −10.72% | −15.05% | −20.72% | 82 |
| template_top10_banded_gated | 2026-01-16→2026-07-16 | −14.26% | −26.68% | +85.00% | +0.07 | +0.03 | −35.32% | −29.23% | −19.03% | −24.70% | 343 |
| template_top5_gated | 2026-01-16→2026-07-16 | −17.09% | −31.49% | +82.80% | −0.04 | −0.09 | −37.73% | −21.39% | −21.86% | −27.54% | 151 |

## Window: 1y

| Book | Span | Total | CAGR | Vol | Sharpe | Sharpe−BIL | Max DD | Worst mo | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ew_benchmark | 2025-07-16→2026-07-16 | +46.12% | +46.16% | +53.32% | +0.98 | +0.91 | −27.50% | −23.55% | +0.00% | +24.94% | 858 |
| template_top5 | 2025-07-16→2026-07-16 | +30.71% | +30.74% | +73.18% | +0.74 | +0.69 | −37.73% | −21.39% | −15.41% | +9.53% | 340 |
| dual_momentum | 2025-07-16→2026-07-16 | +25.48% | +25.50% | +14.61% | +1.63 | +1.37 | −11.42% | −7.83% | −20.64% | +4.30% | 10 |
| sector_momentum | 2025-07-16→2026-07-16 | +24.30% | +24.32% | +13.20% | +1.72 | +1.43 | −7.91% | −1.91% | −21.82% | +3.12% | 38 |
| spy_benchmark | 2025-07-16→2026-07-16 | +21.18% | +21.19% | +12.46% | +1.61 | +1.31 | −8.78% | −4.88% | −24.94% | +0.00% | 1 |
| dual_momentum_gated | 2025-07-16→2026-07-16 | +20.80% | +20.82% | +13.46% | +1.48 | +1.20 | −11.42% | −7.83% | −25.32% | −0.38% | 11 |
| high_52wk | 2025-07-16→2026-07-16 | +20.74% | +20.75% | +15.77% | +1.28 | +1.04 | −11.72% | −7.66% | −25.38% | −0.44% | 538 |
| low_vol | 2025-07-16→2026-07-16 | +13.98% | +13.99% | +8.81% | +1.54 | +1.11 | −5.52% | −4.49% | −32.14% | −7.20% | 189 |
| template_top5_gated | 2025-07-16→2026-07-16 | +12.04% | +12.05% | +71.53% | +0.52 | +0.47 | −37.72% | −21.39% | −34.08% | −9.13% | 322 |
| mr_overlay_gated | 2025-07-16→2026-07-16 | +11.91% | +11.92% | +16.20% | +0.78 | +0.55 | −8.04% | −3.62% | −34.21% | −9.27% | 463 |
| template_top10_banded | 2025-07-16→2026-07-16 | +9.94% | +9.95% | +71.34% | +0.50 | +0.45 | −36.66% | −29.23% | −36.18% | −11.24% | 731 |
| mr_overlay | 2025-07-16→2026-07-16 | +9.09% | +9.10% | +16.61% | +0.61 | +0.38 | −8.96% | −3.62% | −37.03% | −12.09% | 479 |
| momo_stopped | 2025-07-16→2026-07-16 | +7.77% | +7.77% | +68.57% | +0.46 | +0.41 | −33.62% | −27.94% | −38.36% | −13.41% | 748 |
| template_top10_banded_gated | 2025-07-16→2026-07-16 | +2.94% | +2.94% | +70.25% | +0.40 | +0.35 | −35.31% | −29.22% | −43.18% | −18.24% | 705 |
| turtle_breakout | 2025-07-16→2026-07-16 | −15.89% | −15.90% | +29.49% | −0.44 | −0.57 | −25.92% | −11.83% | −62.01% | −37.07% | 162 |

## Window: 3y

| Book | Span | Total | CAGR | Vol | Sharpe | Sharpe−BIL | Max DD | Worst mo | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|
| spy_benchmark | 2023-07-17→2026-07-16 | +70.85% | +19.56% | +14.94% | +1.28 | +0.97 | −18.33% | −5.45% | +10.26% | +0.00% | 1 |
| ew_benchmark | 2023-07-17→2026-07-16 | +60.59% | +17.12% | +41.48% | +0.59 | +0.48 | −33.61% | −23.57% | +0.00% | −10.26% | 2535 |
| dual_momentum | 2023-07-17→2026-07-16 | +60.31% | +17.05% | +15.94% | +1.07 | +0.79 | −18.75% | −7.83% | −0.28% | −10.54% | 26 |
| high_52wk | 2023-07-17→2026-07-16 | +60.05% | +16.99% | +13.80% | +1.21 | +0.88 | −11.71% | −7.64% | −0.55% | −10.80% | 1589 |
| sector_momentum | 2023-07-17→2026-07-16 | +52.48% | +15.11% | +14.96% | +1.02 | +0.72 | −17.18% | −5.48% | −8.11% | −18.37% | 117 |
| low_vol | 2023-07-17→2026-07-16 | +41.07% | +12.16% | +9.80% | +1.23 | +0.77 | −8.22% | −5.69% | −19.53% | −29.78% | 538 |
| dual_momentum_gated | 2023-07-17→2026-07-16 | +36.02% | +10.81% | +12.68% | +0.88 | +0.52 | −11.42% | −7.83% | −24.58% | −34.84% | 24 |
| mr_overlay_gated | 2023-07-17→2026-07-16 | +26.32% | +8.10% | +13.64% | +0.64 | +0.31 | −13.64% | −5.75% | −34.28% | −44.53% | 1313 |
| mr_overlay | 2023-07-17→2026-07-16 | +21.00% | +6.56% | +14.25% | +0.52 | +0.20 | −17.30% | −6.89% | −39.60% | −49.85% | 1387 |
| turtle_breakout | 2023-07-17→2026-07-16 | +1.62% | +0.54% | +27.35% | +0.16 | −0.01 | −30.99% | −11.96% | −58.98% | −69.23% | 482 |
| momo_stopped | 2023-07-17→2026-07-16 | +1.03% | +0.34% | +55.43% | +0.29 | +0.21 | −48.02% | −27.94% | −59.57% | −69.82% | 2286 |
| template_top10_banded | 2023-07-17→2026-07-16 | −1.19% | −0.40% | +57.14% | +0.28 | +0.20 | −47.80% | −29.23% | −61.79% | −72.04% | 2238 |
| template_top10_banded_gated | 2023-07-17→2026-07-16 | −8.84% | −3.04% | +55.93% | +0.23 | +0.15 | −46.37% | −29.22% | −69.43% | −79.69% | 2058 |
| template_top5_gated | 2023-07-17→2026-07-16 | −40.03% | −15.68% | +62.97% | +0.04 | −0.03 | −64.51% | −26.84% | −100.62% | −110.88% | 937 |
| template_top5 | 2023-07-17→2026-07-16 | −51.67% | −21.54% | +65.29% | −0.04 | −0.11 | −76.20% | −26.82% | −112.26% | −122.52% | 1026 |

## Window: 5y

| Book | Span | Total | CAGR | Vol | Sharpe | Sharpe−BIL | Max DD | Worst mo | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sector_momentum | 2021-07-16→2026-07-16 | +87.21% | +13.36% | +15.77% | +0.88 | +0.66 | −17.19% | −9.61% | +23.64% | +4.17% | 205 |
| spy_benchmark | 2021-07-16→2026-07-16 | +83.04% | +12.85% | +16.54% | +0.82 | +0.61 | −24.02% | −8.97% | +19.46% | +0.00% | 1 |
| ew_benchmark | 2021-07-16→2026-07-16 | +63.57% | +10.34% | +37.76% | +0.45 | +0.36 | −34.36% | −23.56% | +0.00% | −19.46% | 4164 |
| dual_momentum | 2021-07-16→2026-07-16 | +50.57% | +8.53% | +14.79% | +0.63 | +0.40 | −23.12% | −8.75% | −13.00% | −32.47% | 32 |
| low_vol | 2021-07-16→2026-07-16 | +46.22% | +7.90% | +10.59% | +0.77 | +0.45 | −16.35% | −7.78% | −17.36% | −36.82% | 904 |
| high_52wk | 2021-07-16→2026-07-16 | +42.41% | +7.33% | +15.67% | +0.53 | +0.31 | −30.92% | −7.66% | −21.16% | −40.63% | 2591 |
| dual_momentum_gated | 2021-07-16→2026-07-16 | +21.07% | +3.90% | +11.72% | +0.39 | +0.09 | −27.13% | −9.18% | −42.50% | −61.97% | 32 |
| mr_overlay_gated | 2021-07-16→2026-07-16 | +14.08% | +2.67% | +11.97% | +0.28 | −0.01 | −19.55% | −5.75% | −49.49% | −68.96% | 1773 |
| momo_stopped | 2021-07-16→2026-07-16 | +13.54% | +2.57% | +49.27% | +0.30 | +0.23 | −51.77% | −27.94% | −50.03% | −69.49% | 3819 |
| template_top10_banded | 2021-07-16→2026-07-16 | +8.91% | +1.72% | +50.68% | +0.29 | +0.22 | −52.75% | −29.22% | −54.67% | −74.13% | 3761 |
| mr_overlay | 2021-07-16→2026-07-16 | +3.87% | +0.76% | +13.75% | +0.12 | −0.13 | −23.53% | −9.03% | −59.71% | −79.17% | 2193 |
| template_top10_banded_gated | 2021-07-16→2026-07-16 | +3.40% | +0.67% | +47.29% | +0.25 | +0.18 | −51.63% | −29.22% | −60.18% | −79.64% | 2924 |
| turtle_breakout | 2021-07-16→2026-07-16 | −17.60% | −3.80% | +23.78% | −0.04 | −0.19 | −41.29% | −13.44% | −81.17% | −100.64% | 690 |
| template_top5_gated | 2021-07-16→2026-07-16 | −46.01% | −11.60% | +54.64% | +0.05 | −0.02 | −77.90% | −26.83% | −109.58% | −129.05% | 1333 |
| template_top5 | 2021-07-16→2026-07-16 | −51.28% | −13.40% | +59.53% | +0.06 | −0.00 | −83.39% | −26.84% | −114.85% | −134.32% | 1711 |

## Window: 15y

| Book | Span | Total | CAGR | Vol | Sharpe | Sharpe−BIL | Max DD | Worst mo | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ew_benchmark | 2011-07-18→2026-07-16 | +1142.23% | +18.30% | +31.25% | +0.70 | +0.65 | −37.48% | −23.60% | +0.00% | +612.77% | 12422 |
| template_top10_banded_gated | 2011-07-18→2026-07-16 | +828.24% | +16.02% | +39.12% | +0.58 | +0.54 | −51.71% | −29.23% | −313.99% | +298.78% | 9400 |
| template_top5_gated | 2011-07-18→2026-07-16 | +808.26% | +15.85% | +47.27% | +0.55 | +0.52 | −74.00% | −26.99% | −333.98% | +278.79% | 4022 |
| momo_stopped | 2011-07-18→2026-07-16 | +673.03% | +14.61% | +40.84% | +0.54 | +0.50 | −51.86% | −28.29% | −469.20% | +143.56% | 11391 |
| template_top10_banded | 2011-07-18→2026-07-16 | +620.86% | +14.08% | +41.82% | +0.53 | +0.49 | −52.85% | −29.23% | −521.38% | +91.39% | 11298 |
| spy_benchmark | 2011-07-18→2026-07-16 | +529.47% | +13.05% | +15.67% | +0.86 | +0.77 | −30.43% | −11.16% | −612.77% | +0.00% | 1 |
| low_vol | 2011-07-18→2026-07-16 | +403.79% | +11.39% | +12.10% | +0.95 | +0.83 | −35.65% | −16.06% | −738.44% | −125.67% | 3801 |
| template_top5 | 2011-07-18→2026-07-16 | +271.99% | +9.16% | +52.29% | +0.43 | +0.40 | −83.31% | −26.89% | −870.24% | −257.48% | 4987 |
| sector_momentum ⚑ | 2016-10-07→2026-07-16 | +224.17% | +12.79% | +17.66% | +0.77 | +0.65 | −31.83% | −10.76% | −918.07% | −305.30% | 403 |
| dual_momentum | 2011-07-18→2026-07-16 | +213.45% | +7.92% | +15.89% | +0.56 | +0.47 | −33.68% | −12.52% | −928.79% | −316.02% | 91 |
| dual_momentum_gated | 2011-07-18→2026-07-16 | +189.75% | +7.35% | +12.26% | +0.64 | +0.52 | −27.11% | −9.16% | −952.48% | −339.71% | 89 |
| high_52wk | 2011-07-18→2026-07-16 | +171.91% | +6.90% | +15.00% | +0.52 | +0.42 | −30.05% | −12.33% | −970.32% | −357.56% | 7440 |
| turtle_breakout | 2011-07-18→2026-07-16 | +120.50% | +5.41% | +23.41% | +0.34 | +0.28 | −42.98% | −15.71% | −1021.73% | −408.97% | 1934 |
| mr_overlay_gated | 2011-07-18→2026-07-16 | +7.46% | +0.48% | +11.25% | +0.10 | −0.03 | −32.98% | −11.54% | −1134.78% | −522.01% | 5413 |
| mr_overlay | 2011-07-18→2026-07-16 | −0.01% | −0.00% | +12.43% | +0.06 | −0.05 | −37.15% | −11.54% | −1142.24% | −529.47% | 6225 |

## Window: max

| Book | Span | Total | CAGR | Vol | Sharpe | Sharpe−BIL | Max DD | Worst mo | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|
| spy_benchmark | 1994-01-27→2026-07-16 | +1690.70% | +9.29% | +15.95% | +0.64 | +0.52 | −47.31% | −13.52% | · | +0.00% | 1 |
| dual_momentum | 2008-05-29→2026-07-16 | +251.69% | +7.18% | +15.55% | +0.53 | +0.44 | −33.65% | −12.51% | · | −1439.02% | 107 |
| dual_momentum_gated | 2008-05-29→2026-07-16 | +202.65% | +6.30% | +12.25% | +0.56 | +0.46 | −27.13% | −9.20% | · | −1488.05% | 104 |
