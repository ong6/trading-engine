# Dual Momentum (regime-gated) (`dual_momentum_gated`) — historical windows

_strategy `dual_momentum` · cadence monthly · generated 2026-07-29 14:04 UTC_

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
| dual_momentum_gated | 2026-01-16→2026-07-16 | +1.55% | +3.15% | +15.46% | +0.28 | +0.05 | −11.42% | −7.82% | −3.22% | −8.90% | 5 |
| dual_momentum_gated | 2025-07-16→2026-07-16 | +20.80% | +20.82% | +13.46% | +1.48 | +1.20 | −11.42% | −7.83% | −25.32% | −0.38% | 11 |
| dual_momentum_gated | 2023-07-17→2026-07-16 | +36.02% | +10.81% | +12.68% | +0.88 | +0.52 | −11.42% | −7.83% | −24.58% | −34.84% | 24 |
| dual_momentum_gated | 2021-07-16→2026-07-16 | +21.07% | +3.90% | +11.72% | +0.39 | +0.09 | −27.13% | −9.18% | −42.50% | −61.97% | 32 |
| dual_momentum_gated | 2011-07-18→2026-07-16 | +189.75% | +7.35% | +12.26% | +0.64 | +0.52 | −27.11% | −9.16% | −952.48% | −339.71% | 89 |
| dual_momentum_gated | 2008-05-29→2026-07-16 | +202.65% | +6.30% | +12.25% | +0.56 | +0.46 | −27.13% | −9.20% | · | −1488.05% | 104 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 5 · rejected orders 0 · dividend credits 1 ($100)
- equity $39,000 → $39,605 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 9.1s (screen 0.0s, day-steps 4.5s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $39,000 |
| 2026-02 | $40,698 |
| 2026-03 | $37,514 |
| 2026-04 | $38,012 |
| 2026-05 | $39,807 |
| 2026-06 | $39,396 |
| 2026-07 | $39,605 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 11 · rejected orders 0 · dividend credits 3 ($1,013)
- equity $39,000 → $47,112 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 13.4s (screen 0.0s, day-steps 8.2s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2025-07 | $39,000 |
| 2025-08 | $40,118 |
| 2025-09 | $41,550 |
| 2025-10 | $42,541 |
| 2025-11 | $42,964 |
| 2025-12 | $44,123 |
| 2026-01 | $46,278 |
| 2026-02 | $48,409 |
| 2026-03 | $44,620 |
| 2026-04 | $45,213 |
| 2026-05 | $47,353 |
| 2026-06 | $46,864 |
| 2026-07 | $47,112 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 24 · rejected orders 7 · dividend credits 10 ($2,727)
- equity $39,000 → $53,046 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 34.5s (screen 0.0s, day-steps 27.4s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $44,217 |
| 2024-09 | $45,145 |
| 2024-10 | $44,743 |
| 2024-11 | $47,403 |
| 2024-12 | $46,266 |
| 2025-01 | $47,500 |
| 2025-02 | $46,902 |
| 2025-03 | $44,290 |
| 2025-04 | $44,092 |
| 2025-05 | $44,092 |
| 2025-06 | $45,008 |
| 2025-07 | $44,068 |
| 2025-08 | $45,167 |
| 2025-09 | $46,777 |
| 2025-10 | $47,892 |
| 2025-11 | $48,369 |
| 2025-12 | $49,674 |
| 2026-01 | $52,100 |
| 2026-02 | $54,499 |
| 2026-03 | $50,233 |
| 2026-04 | $50,901 |
| 2026-05 | $53,317 |
| 2026-06 | $52,767 |
| 2026-07 | $53,046 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 32 · rejected orders 11 · dividend credits 12 ($2,696)
- equity $39,000 → $47,217 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 50.2s (screen 0.0s, day-steps 41.2s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $39,368 |
| 2024-09 | $40,195 |
| 2024-10 | $39,837 |
| 2024-11 | $42,205 |
| 2024-12 | $41,192 |
| 2025-01 | $42,292 |
| 2025-02 | $41,758 |
| 2025-03 | $39,433 |
| 2025-04 | $39,257 |
| 2025-05 | $39,257 |
| 2025-06 | $40,071 |
| 2025-07 | $39,235 |
| 2025-08 | $40,213 |
| 2025-09 | $41,646 |
| 2025-10 | $42,639 |
| 2025-11 | $43,064 |
| 2025-12 | $44,226 |
| 2026-01 | $46,385 |
| 2026-02 | $48,522 |
| 2026-03 | $44,723 |
| 2026-04 | $45,318 |
| 2026-05 | $47,458 |
| 2026-06 | $46,968 |
| 2026-07 | $47,217 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 89 · rejected orders 45 · dividend credits 43 ($15,457)
- equity $39,000 → $113,004 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 183.7s (screen 0.0s, day-steps 166.6s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $94,165 |
| 2024-09 | $96,142 |
| 2024-10 | $95,287 |
| 2024-11 | $100,952 |
| 2024-12 | $98,529 |
| 2025-01 | $101,170 |
| 2025-02 | $99,886 |
| 2025-03 | $94,324 |
| 2025-04 | $93,905 |
| 2025-05 | $93,905 |
| 2025-06 | $95,855 |
| 2025-07 | $93,853 |
| 2025-08 | $96,193 |
| 2025-09 | $99,622 |
| 2025-10 | $101,997 |
| 2025-11 | $103,012 |
| 2025-12 | $105,792 |
| 2026-01 | $110,958 |
| 2026-02 | $116,067 |
| 2026-03 | $106,982 |
| 2026-04 | $108,405 |
| 2026-05 | $113,581 |
| 2026-06 | $112,409 |
| 2026-07 | $113,004 |

_… last 24 of 181 months shown._

### max — 2008-05-29 → 2026-07-16

- sessions 4561 · fills 104 · rejected orders 41 · dividend credits 47 ($17,659)
- equity $39,000 → $118,034 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 206.0s (screen 0.0s, day-steps 187.6s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $98,379 |
| 2024-09 | $100,444 |
| 2024-10 | $99,551 |
| 2024-11 | $105,469 |
| 2024-12 | $102,938 |
| 2025-01 | $105,697 |
| 2025-02 | $104,356 |
| 2025-03 | $98,544 |
| 2025-04 | $98,105 |
| 2025-05 | $98,105 |
| 2025-06 | $100,142 |
| 2025-07 | $98,051 |
| 2025-08 | $100,495 |
| 2025-09 | $104,077 |
| 2025-10 | $106,559 |
| 2025-11 | $107,620 |
| 2025-12 | $110,524 |
| 2026-01 | $115,921 |
| 2026-02 | $121,260 |
| 2026-03 | $111,767 |
| 2026-04 | $113,253 |
| 2026-05 | $118,637 |
| 2026-06 | $117,413 |
| 2026-07 | $118,034 |

_… last 24 of 219 months shown._
