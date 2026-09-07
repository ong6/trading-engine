# Dual Momentum (GEM) (`dual_momentum`) — historical windows

_strategy `dual_momentum` · cadence monthly · generated 2026-09-07 11:18 UTC_

**Evidence and assumptions.** `legacy_unclassified`; starting capital $0; execution profile `legacy_unstamped`; data snapshot `legacy_unstamped`.

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
9. **Costs are the league's own named execution profile**, serialized in every
   result: t+1-open fills, explicit spread/adverse/impact/fee assumptions, a
   profile-defined median-dollar-volume ceiling, no same-bar fills and no
   fabricated bars. `baseline_v1` is the historical
   `max(half_spread, 5) + 5` bp-per-side model.


| Book | Evidence class | Span | Total | CAGR | Vol | Sharpe | Sharpe−BIL | Max DD | Worst mo | vs EW | vs SPY | Comparison | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dual_momentum | `legacy_unclassified` | 2026-01-16→2026-07-16 | +5.43% | +11.27% | +17.48% | +0.71 | +0.50 | −11.42% | −7.82% | · | · | **uncontrolled absolute simulation** | 5 |
| dual_momentum | `legacy_unclassified` | 2025-07-16→2026-07-16 | +25.48% | +25.50% | +14.61% | +1.63 | +1.37 | −11.42% | −7.83% | · | · | **uncontrolled absolute simulation** | 10 |
| dual_momentum | `legacy_unclassified` | 2023-07-17→2026-07-16 | +60.31% | +17.05% | +15.94% | +1.07 | +0.79 | −18.75% | −7.83% | · | · | **uncontrolled absolute simulation** | 26 |
| dual_momentum | `legacy_unclassified` | 2021-07-16→2026-07-16 | +50.57% | +8.53% | +14.79% | +0.63 | +0.40 | −23.12% | −8.75% | · | · | **uncontrolled absolute simulation** | 32 |
| dual_momentum | `legacy_unclassified` | 2011-07-18→2026-07-16 | +213.45% | +7.92% | +15.89% | +0.56 | +0.47 | −33.68% | −12.52% | · | · | **uncontrolled absolute simulation** | 91 |
| dual_momentum | `legacy_unclassified` | 2008-05-29→2026-07-16 | +251.69% | +7.18% | +15.55% | +0.53 | +0.44 | −33.65% | −12.51% | · | · | **uncontrolled absolute simulation** | 107 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 5 · rejected orders 0 · dividend credits 1 ($104)
- equity $39,000 → $41,120 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 8.9s (screen 0.0s, day-steps 4.4s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $39,000 |
| 2026-02 | $40,698 |
| 2026-03 | $37,514 |
| 2026-04 | $39,517 |
| 2026-05 | $41,329 |
| 2026-06 | $40,903 |
| 2026-07 | $41,120 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 10 · rejected orders 0 · dividend credits 3 ($1,018)
- equity $39,000 → $48,936 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 12.8s (screen 0.0s, day-steps 7.9s) · screen rows 0 · dividend rows in force 400240

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
| 2026-04 | $47,004 |
| 2026-05 | $49,186 |
| 2026-06 | $48,679 |
| 2026-07 | $48,936 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 26 · rejected orders 7 · dividend credits 10 ($3,053)
- equity $39,000 → $62,522 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 33.3s (screen 0.0s, day-steps 26.1s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $47,694 |
| 2024-09 | $48,695 |
| 2024-10 | $48,262 |
| 2024-11 | $51,131 |
| 2024-12 | $49,904 |
| 2025-01 | $51,236 |
| 2025-02 | $50,590 |
| 2025-03 | $47,772 |
| 2025-04 | $47,359 |
| 2025-05 | $49,901 |
| 2025-06 | $51,080 |
| 2025-07 | $50,013 |
| 2025-08 | $51,260 |
| 2025-09 | $53,087 |
| 2025-10 | $54,353 |
| 2025-11 | $54,894 |
| 2025-12 | $56,375 |
| 2026-01 | $59,127 |
| 2026-02 | $61,850 |
| 2026-03 | $57,010 |
| 2026-04 | $60,054 |
| 2026-05 | $62,841 |
| 2026-06 | $62,193 |
| 2026-07 | $62,522 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 32 · rejected orders 14 · dividend credits 13 ($3,257)
- equity $39,000 → $58,722 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 50.3s (screen 0.0s, day-steps 41.3s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $44,797 |
| 2024-09 | $45,738 |
| 2024-10 | $45,331 |
| 2024-11 | $48,026 |
| 2024-12 | $46,873 |
| 2025-01 | $48,124 |
| 2025-02 | $47,517 |
| 2025-03 | $44,871 |
| 2025-04 | $44,482 |
| 2025-05 | $46,870 |
| 2025-06 | $47,976 |
| 2025-07 | $46,974 |
| 2025-08 | $48,145 |
| 2025-09 | $49,861 |
| 2025-10 | $51,050 |
| 2025-11 | $51,559 |
| 2025-12 | $52,950 |
| 2026-01 | $55,533 |
| 2026-02 | $58,088 |
| 2026-03 | $53,542 |
| 2026-04 | $56,403 |
| 2026-05 | $59,022 |
| 2026-06 | $58,413 |
| 2026-07 | $58,722 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 91 · rejected orders 41 · dividend credits 50 ($17,824)
- equity $39,000 → $122,244 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 184.8s (screen 0.0s, day-steps 168.4s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $93,254 |
| 2024-09 | $95,211 |
| 2024-10 | $94,364 |
| 2024-11 | $99,974 |
| 2024-12 | $97,575 |
| 2025-01 | $100,191 |
| 2025-02 | $98,919 |
| 2025-03 | $93,411 |
| 2025-04 | $92,602 |
| 2025-05 | $97,574 |
| 2025-06 | $99,878 |
| 2025-07 | $97,793 |
| 2025-08 | $100,231 |
| 2025-09 | $103,803 |
| 2025-10 | $106,279 |
| 2025-11 | $107,337 |
| 2025-12 | $110,233 |
| 2026-01 | $115,616 |
| 2026-02 | $120,941 |
| 2026-03 | $111,473 |
| 2026-04 | $117,429 |
| 2026-05 | $122,868 |
| 2026-06 | $121,600 |
| 2026-07 | $122,244 |

_… last 24 of 181 months shown._

### max — 2008-05-29 → 2026-07-16

- sessions 4561 · fills 107 · rejected orders 54 · dividend credits 56 ($21,968)
- equity $39,000 → $137,158 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 214.8s (screen 0.0s, day-steps 196.8s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $104,629 |
| 2024-09 | $106,826 |
| 2024-10 | $105,876 |
| 2024-11 | $112,170 |
| 2024-12 | $109,478 |
| 2025-01 | $112,411 |
| 2025-02 | $110,986 |
| 2025-03 | $104,804 |
| 2025-04 | $103,896 |
| 2025-05 | $109,475 |
| 2025-06 | $112,059 |
| 2025-07 | $109,719 |
| 2025-08 | $112,455 |
| 2025-09 | $116,463 |
| 2025-10 | $119,240 |
| 2025-11 | $120,427 |
| 2025-12 | $123,676 |
| 2026-01 | $129,715 |
| 2026-02 | $135,687 |
| 2026-03 | $125,068 |
| 2026-04 | $131,748 |
| 2026-05 | $137,859 |
| 2026-06 | $136,436 |
| 2026-07 | $137,158 |

_… last 24 of 219 months shown._
