# Sector ETF Rotation (`sector_momentum`) — historical windows

_strategy `sector_momentum` · cadence monthly · generated 2026-09-07 11:18 UTC_

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
| sector_momentum | `legacy_unclassified` | 2026-01-16→2026-07-16 | +14.85% | +32.23% | +13.71% | +2.14 | +1.88 | −5.75% | −1.41% | · | · | **uncontrolled absolute simulation** | 18 |
| sector_momentum | `legacy_unclassified` | 2025-07-16→2026-07-16 | +24.30% | +24.32% | +13.20% | +1.72 | +1.43 | −7.91% | −1.91% | · | · | **uncontrolled absolute simulation** | 38 |
| sector_momentum | `legacy_unclassified` | 2023-07-17→2026-07-16 | +52.48% | +15.11% | +14.96% | +1.02 | +0.72 | −17.18% | −5.48% | · | · | **uncontrolled absolute simulation** | 117 |
| sector_momentum | `legacy_unclassified` | 2021-07-16→2026-07-16 | +87.21% | +13.36% | +15.77% | +0.88 | +0.66 | −17.19% | −9.61% | · | · | **uncontrolled absolute simulation** | 205 |
| sector_momentum ⚑ | `legacy_unclassified` | 2016-10-07→2026-07-16 | +224.17% | +12.79% | +17.66% | +0.77 | +0.65 | −31.83% | −10.76% | · | · | **uncontrolled absolute simulation** | 403 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 18 · rejected orders 1 · dividend credits 6 ($347)
- equity $39,000 → $44,792 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 8.9s (screen 0.0s, day-steps 4.4s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $39,000 |
| 2026-02 | $42,478 |
| 2026-03 | $41,878 |
| 2026-04 | $42,977 |
| 2026-05 | $44,804 |
| 2026-06 | $45,118 |
| 2026-07 | $44,792 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 38 · rejected orders 1 · dividend credits 12 ($592)
- equity $39,000 → $48,476 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 16.6s (screen 0.0s, day-steps 11.8s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2025-07 | $39,000 |
| 2025-08 | $39,817 |
| 2025-09 | $42,182 |
| 2025-10 | $42,712 |
| 2025-11 | $41,896 |
| 2025-12 | $42,095 |
| 2026-01 | $42,363 |
| 2026-02 | $45,990 |
| 2026-03 | $45,343 |
| 2026-04 | $46,527 |
| 2026-05 | $48,494 |
| 2026-06 | $48,830 |
| 2026-07 | $48,476 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 117 · rejected orders 1 · dividend credits 36 ($2,006)
- equity $39,000 → $59,467 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 40.1s (screen 0.0s, day-steps 32.8s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $44,011 |
| 2024-09 | $45,184 |
| 2024-10 | $44,912 |
| 2024-11 | $48,092 |
| 2024-12 | $47,031 |
| 2025-01 | $49,494 |
| 2025-02 | $48,510 |
| 2025-03 | $47,111 |
| 2025-04 | $44,529 |
| 2025-05 | $46,338 |
| 2025-06 | $47,995 |
| 2025-07 | $48,314 |
| 2025-08 | $48,834 |
| 2025-09 | $51,730 |
| 2025-10 | $52,382 |
| 2025-11 | $51,382 |
| 2025-12 | $51,625 |
| 2026-01 | $51,953 |
| 2026-02 | $56,401 |
| 2026-03 | $55,609 |
| 2026-04 | $57,067 |
| 2026-05 | $59,488 |
| 2026-06 | $59,901 |
| 2026-07 | $59,467 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 205 · rejected orders 1 · dividend credits 58 ($4,368)
- equity $39,000 → $73,011 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 61.0s (screen 0.0s, day-steps 51.9s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $54,048 |
| 2024-09 | $55,488 |
| 2024-10 | $55,155 |
| 2024-11 | $59,059 |
| 2024-12 | $57,756 |
| 2025-01 | $60,779 |
| 2025-02 | $59,571 |
| 2025-03 | $57,853 |
| 2025-04 | $54,682 |
| 2025-05 | $56,901 |
| 2025-06 | $58,939 |
| 2025-07 | $59,333 |
| 2025-08 | $59,970 |
| 2025-09 | $63,527 |
| 2025-10 | $64,328 |
| 2025-11 | $63,100 |
| 2025-12 | $63,399 |
| 2026-01 | $63,801 |
| 2026-02 | $69,264 |
| 2026-03 | $68,290 |
| 2026-04 | $70,073 |
| 2026-05 | $73,048 |
| 2026-06 | $73,553 |
| 2026-07 | $73,011 |

_… last 24 of 61 months shown._

### 15y — 2016-10-07 → 2026-07-16

- sessions 2455 · fills 403 · rejected orders 5 · dividend credits 115 ($11,872)
- equity $39,000 → $126,424 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 158.8s (screen 0.0s, day-steps 145.1s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $93,546 |
| 2024-09 | $96,039 |
| 2024-10 | $95,462 |
| 2024-11 | $102,220 |
| 2024-12 | $99,964 |
| 2025-01 | $105,198 |
| 2025-02 | $103,108 |
| 2025-03 | $100,133 |
| 2025-04 | $94,645 |
| 2025-05 | $98,491 |
| 2025-06 | $102,017 |
| 2025-07 | $102,698 |
| 2025-08 | $103,802 |
| 2025-09 | $109,958 |
| 2025-10 | $111,343 |
| 2025-11 | $109,218 |
| 2025-12 | $109,736 |
| 2026-01 | $110,433 |
| 2026-02 | $119,888 |
| 2026-03 | $118,200 |
| 2026-04 | $121,300 |
| 2026-05 | $126,482 |
| 2026-06 | $127,365 |
| 2026-07 | $126,424 |

_… last 24 of 118 months shown._
