# SPY Buy & Hold (`spy_benchmark`) — historical windows

_strategy `spy_benchmark` · cadence once · generated 2026-07-29 14:04 UTC_

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
| spy_benchmark | 2026-01-16→2026-07-16 | +10.45% | +22.20% | +13.82% | +1.54 | +1.28 | −8.76% | −4.87% | +5.67% | +0.00% | 1 |
| spy_benchmark | 2025-07-16→2026-07-16 | +21.18% | +21.19% | +12.46% | +1.61 | +1.31 | −8.78% | −4.88% | −24.94% | +0.00% | 1 |
| spy_benchmark | 2023-07-17→2026-07-16 | +70.85% | +19.56% | +14.94% | +1.28 | +0.97 | −18.33% | −5.45% | +10.26% | +0.00% | 1 |
| spy_benchmark | 2021-07-16→2026-07-16 | +83.04% | +12.85% | +16.54% | +0.82 | +0.61 | −24.02% | −8.97% | +19.46% | +0.00% | 1 |
| spy_benchmark | 2011-07-18→2026-07-16 | +529.47% | +13.05% | +15.67% | +0.86 | +0.77 | −30.43% | −11.16% | −612.77% | +0.00% | 1 |
| spy_benchmark | 1994-01-27→2026-07-16 | +1690.70% | +9.29% | +15.95% | +0.64 | +0.52 | −47.31% | −13.52% | · | +0.00% | 1 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 1 · rejected orders 0 · dividend credits 2 ($209)
- equity $39,000 → $43,074 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 7.7s (screen 0.0s, day-steps 3.3s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $39,552 |
| 2026-02 | $39,215 |
| 2026-03 | $37,306 |
| 2026-04 | $41,159 |
| 2026-05 | $43,291 |
| 2026-06 | $42,851 |
| 2026-07 | $43,074 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 1 · rejected orders 0 · dividend credits 4 ($467)
- equity $39,000 → $47,260 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 12.6s (screen 0.0s, day-steps 7.7s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2025-07 | $39,437 |
| 2025-08 | $40,242 |
| 2025-09 | $41,665 |
| 2025-10 | $42,650 |
| 2025-11 | $42,732 |
| 2025-12 | $42,765 |
| 2026-01 | $43,388 |
| 2026-02 | $43,017 |
| 2026-03 | $40,918 |
| 2026-04 | $45,154 |
| 2026-05 | $47,499 |
| 2026-06 | $47,015 |
| 2026-07 | $47,260 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 1 · rejected orders 0 · dividend credits 12 ($1,852)
- equity $39,000 → $66,632 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 29.2s (screen 0.0s, day-steps 22.0s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $49,283 |
| 2024-09 | $50,300 |
| 2024-10 | $49,860 |
| 2024-11 | $52,776 |
| 2024-12 | $51,529 |
| 2025-01 | $52,883 |
| 2025-02 | $52,225 |
| 2025-03 | $49,379 |
| 2025-04 | $48,962 |
| 2025-05 | $51,959 |
| 2025-06 | $54,558 |
| 2025-07 | $55,782 |
| 2025-08 | $56,898 |
| 2025-09 | $58,872 |
| 2025-10 | $60,238 |
| 2025-11 | $60,352 |
| 2025-12 | $60,397 |
| 2026-01 | $61,262 |
| 2026-02 | $60,747 |
| 2026-03 | $57,836 |
| 2026-04 | $63,711 |
| 2026-05 | $66,964 |
| 2026-06 | $66,293 |
| 2026-07 | $66,632 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 1 · rejected orders 0 · dividend credits 20 ($3,080)
- equity $39,000 → $71,384 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 47.2s (screen 0.0s, day-steps 38.1s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $53,144 |
| 2024-09 | $54,213 |
| 2024-10 | $53,750 |
| 2024-11 | $56,816 |
| 2024-12 | $55,505 |
| 2025-01 | $56,928 |
| 2025-02 | $56,237 |
| 2025-03 | $53,245 |
| 2025-04 | $52,806 |
| 2025-05 | $55,957 |
| 2025-06 | $58,690 |
| 2025-07 | $59,977 |
| 2025-08 | $61,149 |
| 2025-09 | $63,225 |
| 2025-10 | $64,661 |
| 2025-11 | $64,781 |
| 2025-12 | $64,829 |
| 2026-01 | $65,737 |
| 2026-02 | $65,197 |
| 2026-03 | $62,136 |
| 2026-04 | $68,313 |
| 2026-05 | $71,733 |
| 2026-06 | $71,027 |
| 2026-07 | $71,384 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 1 · rejected orders 0 · dividend credits 60 ($23,194)
- equity $39,000 → $245,492 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 165.3s (screen 0.0s, day-steps 148.9s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $185,779 |
| 2024-09 | $189,279 |
| 2024-10 | $187,764 |
| 2024-11 | $197,801 |
| 2024-12 | $193,508 |
| 2025-01 | $198,167 |
| 2025-02 | $195,905 |
| 2025-03 | $186,110 |
| 2025-04 | $184,674 |
| 2025-05 | $194,990 |
| 2025-06 | $203,935 |
| 2025-07 | $208,147 |
| 2025-08 | $211,986 |
| 2025-09 | $218,783 |
| 2025-10 | $223,483 |
| 2025-11 | $223,877 |
| 2025-12 | $224,032 |
| 2026-01 | $227,006 |
| 2026-02 | $225,236 |
| 2026-03 | $215,216 |
| 2026-04 | $235,439 |
| 2026-05 | $246,633 |
| 2026-06 | $244,323 |
| 2026-07 | $245,492 |

_… last 24 of 181 months shown._

### max — 1994-01-27 → 2026-07-16

- sessions 8170 · fills 1 · rejected orders 0 · dividend credits 131 ($89,495)
- equity $39,000 → $698,374 · Sharpe-excess computed over 59% of the window (BIL's first bar is 2007-05-30)
- replay runtime 419.9s (screen 0.0s, day-steps 397.3s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $534,768 |
| 2024-09 | $544,359 |
| 2024-10 | $540,207 |
| 2024-11 | $567,708 |
| 2024-12 | $555,945 |
| 2025-01 | $568,710 |
| 2025-02 | $562,514 |
| 2025-03 | $535,675 |
| 2025-04 | $531,741 |
| 2025-05 | $560,005 |
| 2025-06 | $584,514 |
| 2025-07 | $596,055 |
| 2025-08 | $606,573 |
| 2025-09 | $625,195 |
| 2025-10 | $638,073 |
| 2025-11 | $639,152 |
| 2025-12 | $639,576 |
| 2026-01 | $647,727 |
| 2026-02 | $642,877 |
| 2026-03 | $615,422 |
| 2026-04 | $670,829 |
| 2026-05 | $701,502 |
| 2026-06 | $695,171 |
| 2026-07 | $698,374 |

_… last 24 of 391 months shown._
