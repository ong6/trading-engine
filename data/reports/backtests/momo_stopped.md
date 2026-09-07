# Momentum Top 10 (stop-managed) (`momo_stopped`) — historical windows

_strategy `momo_stopped` · cadence daily · generated 2026-09-07 11:18 UTC_

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
| momo_stopped | `legacy_unclassified` | 2026-01-16→2026-07-16 | −5.99% | −11.72% | +84.17% | +0.28 | +0.24 | −34.12% | −27.94% | · | · | **uncontrolled absolute simulation** | 380 |
| momo_stopped | `legacy_unclassified` | 2025-07-16→2026-07-16 | +7.77% | +7.77% | +68.57% | +0.46 | +0.41 | −33.62% | −27.94% | · | · | **uncontrolled absolute simulation** | 748 |
| momo_stopped | `legacy_unclassified` | 2023-07-17→2026-07-16 | +1.03% | +0.34% | +55.43% | +0.29 | +0.21 | −48.02% | −27.94% | · | · | **uncontrolled absolute simulation** | 2286 |
| momo_stopped | `legacy_unclassified` | 2021-07-16→2026-07-16 | +13.54% | +2.57% | +49.27% | +0.30 | +0.23 | −51.77% | −27.94% | · | · | **uncontrolled absolute simulation** | 3819 |
| momo_stopped | `legacy_unclassified` | 2011-07-18→2026-07-16 | +673.03% | +14.61% | +40.84% | +0.54 | +0.50 | −51.86% | −28.29% | · | · | **uncontrolled absolute simulation** | 11391 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 380 · rejected orders 7 · dividend credits 4 ($26)
- equity $39,000 → $36,664 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 33.8s (screen 5.3s, day-steps 23.8s) · screen rows 85638 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $37,726 |
| 2026-02 | $41,287 |
| 2026-03 | $32,749 |
| 2026-04 | $40,486 |
| 2026-05 | $48,447 |
| 2026-06 | $50,883 |
| 2026-07 | $36,664 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 748 · rejected orders 10 · dividend credits 4 ($30)
- equity $39,000 → $42,029 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 54.4s (screen 6.6s, day-steps 42.8s) · screen rows 160706 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2025-07 | $35,036 |
| 2025-08 | $34,022 |
| 2025-09 | $38,438 |
| 2025-10 | $42,122 |
| 2025-11 | $35,633 |
| 2025-12 | $36,614 |
| 2026-01 | $43,246 |
| 2026-02 | $47,337 |
| 2026-03 | $37,526 |
| 2026-04 | $46,408 |
| 2026-05 | $55,529 |
| 2026-06 | $58,325 |
| 2026-07 | $42,029 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 2286 · rejected orders 21 · dividend credits 10 ($91)
- equity $39,000 → $39,402 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 150.6s (screen 8.7s, day-steps 134.7s) · screen rows 396728 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $34,307 |
| 2024-09 | $38,913 |
| 2024-10 | $43,710 |
| 2024-11 | $52,819 |
| 2024-12 | $45,403 |
| 2025-01 | $41,109 |
| 2025-02 | $38,985 |
| 2025-03 | $33,388 |
| 2025-04 | $29,546 |
| 2025-05 | $31,636 |
| 2025-06 | $37,237 |
| 2025-07 | $32,778 |
| 2025-08 | $31,914 |
| 2025-09 | $36,048 |
| 2025-10 | $39,509 |
| 2025-11 | $33,412 |
| 2025-12 | $34,355 |
| 2026-01 | $40,581 |
| 2026-02 | $44,421 |
| 2026-03 | $35,225 |
| 2026-04 | $43,508 |
| 2026-05 | $52,060 |
| 2026-06 | $54,682 |
| 2026-07 | $39,402 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 3819 · rejected orders 29 · dividend credits 40 ($1,707)
- equity $39,000 → $44,282 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 303.6s (screen 11.0s, day-steps 283.4s) · screen rows 543363 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $38,565 |
| 2024-09 | $43,741 |
| 2024-10 | $49,134 |
| 2024-11 | $59,379 |
| 2024-12 | $51,043 |
| 2025-01 | $46,215 |
| 2025-02 | $43,827 |
| 2025-03 | $37,535 |
| 2025-04 | $33,203 |
| 2025-05 | $35,544 |
| 2025-06 | $41,836 |
| 2025-07 | $36,826 |
| 2025-08 | $35,861 |
| 2025-09 | $40,518 |
| 2025-10 | $44,403 |
| 2025-11 | $37,564 |
| 2025-12 | $38,603 |
| 2026-01 | $45,595 |
| 2026-02 | $49,907 |
| 2026-03 | $39,559 |
| 2026-04 | $48,889 |
| 2026-05 | $58,504 |
| 2026-06 | $61,454 |
| 2026-07 | $44,282 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 11391 · rejected orders 84 · dividend credits 127 ($14,492)
- equity $39,000 → $301,482 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 927.8s (screen 20.0s, day-steps 890.6s) · screen rows 1280417 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $262,778 |
| 2024-09 | $298,150 |
| 2024-10 | $334,955 |
| 2024-11 | $404,701 |
| 2024-12 | $347,863 |
| 2025-01 | $314,960 |
| 2025-02 | $298,702 |
| 2025-03 | $255,915 |
| 2025-04 | $226,407 |
| 2025-05 | $242,236 |
| 2025-06 | $285,127 |
| 2025-07 | $251,020 |
| 2025-08 | $244,414 |
| 2025-09 | $276,154 |
| 2025-10 | $302,643 |
| 2025-11 | $256,062 |
| 2025-12 | $263,034 |
| 2026-01 | $310,709 |
| 2026-02 | $340,034 |
| 2026-03 | $269,655 |
| 2026-04 | $333,556 |
| 2026-05 | $399,534 |
| 2026-06 | $420,422 |
| 2026-07 | $301,482 |

_… last 24 of 181 months shown._
