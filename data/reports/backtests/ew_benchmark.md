# Equal-Weight Benchmark (`ew_benchmark`) — historical windows

_strategy `ew_benchmark` · cadence monthly · generated 2026-07-29 14:04 UTC_

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


| Book | Span | Total | CAGR | Vol | Sharpe | Sharpe−BIL | Max DD | Worst mo | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ew_benchmark | 2026-01-16→2026-07-16 | +4.77% | +9.86% | +62.38% | +0.47 | +0.41 | −25.54% | −23.53% | +0.00% | −5.67% | 419 |
| ew_benchmark | 2025-07-16→2026-07-16 | +46.12% | +46.16% | +53.32% | +0.98 | +0.91 | −27.50% | −23.55% | +0.00% | +24.94% | 858 |
| ew_benchmark | 2023-07-17→2026-07-16 | +60.59% | +17.12% | +41.48% | +0.59 | +0.48 | −33.61% | −23.57% | +0.00% | −10.26% | 2535 |
| ew_benchmark | 2021-07-16→2026-07-16 | +63.57% | +10.34% | +37.76% | +0.45 | +0.36 | −34.36% | −23.56% | +0.00% | −19.46% | 4164 |
| ew_benchmark | 2011-07-18→2026-07-16 | +1142.23% | +18.30% | +31.25% | +0.70 | +0.65 | −37.48% | −23.60% | +0.00% | +612.77% | 12422 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 419 · rejected orders 0 · dividend credits 16 ($27)
- equity $39,000 → $40,861 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 29.2s (screen 5.4s, day-steps 19.2s) · screen rows 85638 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $39,000 |
| 2026-02 | $40,196 |
| 2026-03 | $34,944 |
| 2026-04 | $43,392 |
| 2026-05 | $52,800 |
| 2026-06 | $53,437 |
| 2026-07 | $40,861 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 858 · rejected orders 2 · dividend credits 29 ($302)
- equity $39,000 → $56,988 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 47.7s (screen 6.6s, day-steps 36.1s) · screen rows 160706 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2025-07 | $39,000 |
| 2025-08 | $41,686 |
| 2025-09 | $48,877 |
| 2025-10 | $54,173 |
| 2025-11 | $48,629 |
| 2025-12 | $48,456 |
| 2026-01 | $54,982 |
| 2026-02 | $56,121 |
| 2026-03 | $48,770 |
| 2026-04 | $60,544 |
| 2026-05 | $73,656 |
| 2026-06 | $74,545 |
| 2026-07 | $56,988 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 2535 · rejected orders 2 · dividend credits 113 ($834)
- equity $39,000 → $62,632 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 133.1s (screen 8.9s, day-steps 116.9s) · screen rows 396728 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $39,554 |
| 2024-09 | $40,985 |
| 2024-10 | $42,150 |
| 2024-11 | $49,818 |
| 2024-12 | $44,215 |
| 2025-01 | $45,080 |
| 2025-02 | $41,669 |
| 2025-03 | $38,616 |
| 2025-04 | $38,407 |
| 2025-05 | $39,836 |
| 2025-06 | $42,863 |
| 2025-07 | $44,395 |
| 2025-08 | $45,861 |
| 2025-09 | $53,694 |
| 2025-10 | $59,526 |
| 2025-11 | $53,454 |
| 2025-12 | $53,263 |
| 2026-01 | $60,450 |
| 2026-02 | $61,704 |
| 2026-03 | $53,623 |
| 2026-04 | $66,566 |
| 2026-05 | $80,983 |
| 2026-06 | $81,948 |
| 2026-07 | $62,632 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 4164 · rejected orders 5 · dividend credits 285 ($2,158)
- equity $39,000 → $63,793 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 172.3s (screen 11.2s, day-steps 152.2s) · screen rows 543363 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $40,283 |
| 2024-09 | $41,740 |
| 2024-10 | $42,926 |
| 2024-11 | $50,736 |
| 2024-12 | $45,030 |
| 2025-01 | $45,911 |
| 2025-02 | $42,439 |
| 2025-03 | $39,330 |
| 2025-04 | $39,119 |
| 2025-05 | $40,571 |
| 2025-06 | $43,653 |
| 2025-07 | $45,214 |
| 2025-08 | $46,707 |
| 2025-09 | $54,684 |
| 2025-10 | $60,623 |
| 2025-11 | $54,439 |
| 2025-12 | $54,244 |
| 2026-01 | $61,551 |
| 2026-02 | $62,828 |
| 2026-03 | $54,612 |
| 2026-04 | $67,794 |
| 2026-05 | $82,477 |
| 2026-06 | $83,460 |
| 2026-07 | $63,793 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 12422 · rejected orders 25 · dividend credits 913 ($21,673)
- equity $39,000 → $484,471 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 669.5s (screen 20.0s, day-steps 632.0s) · screen rows 1280417 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $306,246 |
| 2024-09 | $317,316 |
| 2024-10 | $326,361 |
| 2024-11 | $385,716 |
| 2024-12 | $342,329 |
| 2025-01 | $348,887 |
| 2025-02 | $322,520 |
| 2025-03 | $299,028 |
| 2025-04 | $297,348 |
| 2025-05 | $308,075 |
| 2025-06 | $331,355 |
| 2025-07 | $343,260 |
| 2025-08 | $354,492 |
| 2025-09 | $415,158 |
| 2025-10 | $460,320 |
| 2025-11 | $413,324 |
| 2025-12 | $411,895 |
| 2026-01 | $467,449 |
| 2026-02 | $477,203 |
| 2026-03 | $415,004 |
| 2026-04 | $515,181 |
| 2026-05 | $626,759 |
| 2026-06 | $634,088 |
| 2026-07 | $484,471 |

_… last 24 of 181 months shown._
