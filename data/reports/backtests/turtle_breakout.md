# Turtle Breakout (ATR-stopped) (`turtle_breakout`) — historical windows

_strategy `turtle_breakout` · cadence daily · generated 2026-09-07 11:18 UTC_

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
| turtle_breakout | `legacy_unclassified` | 2026-01-16→2026-07-16 | −10.28% | −19.65% | +32.45% | −0.52 | −0.63 | −17.20% | −10.72% | · | · | **uncontrolled absolute simulation** | 82 |
| turtle_breakout | `legacy_unclassified` | 2025-07-16→2026-07-16 | −15.89% | −15.90% | +29.49% | −0.44 | −0.57 | −25.92% | −11.83% | · | · | **uncontrolled absolute simulation** | 162 |
| turtle_breakout | `legacy_unclassified` | 2023-07-17→2026-07-16 | +1.62% | +0.54% | +27.35% | +0.16 | −0.01 | −30.99% | −11.96% | · | · | **uncontrolled absolute simulation** | 482 |
| turtle_breakout | `legacy_unclassified` | 2021-07-16→2026-07-16 | −17.60% | −3.80% | +23.78% | −0.04 | −0.19 | −41.29% | −13.44% | · | · | **uncontrolled absolute simulation** | 690 |
| turtle_breakout | `legacy_unclassified` | 2011-07-18→2026-07-16 | +120.50% | +5.41% | +23.41% | +0.34 | +0.28 | −42.98% | −15.71% | · | · | **uncontrolled absolute simulation** | 1934 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 82 · rejected orders 0 · dividend credits 2 ($5)
- equity $39,000 → $34,992 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 32.8s (screen 5.4s, day-steps 22.9s) · screen rows 85638 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $39,599 |
| 2026-02 | $40,874 |
| 2026-03 | $37,748 |
| 2026-04 | $38,882 |
| 2026-05 | $41,392 |
| 2026-06 | $39,194 |
| 2026-07 | $34,992 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 162 · rejected orders 0 · dividend credits 3 ($9)
- equity $39,000 → $32,803 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 52.1s (screen 6.7s, day-steps 40.5s) · screen rows 160706 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2025-07 | $37,242 |
| 2025-08 | $36,377 |
| 2025-09 | $35,967 |
| 2025-10 | $36,640 |
| 2025-11 | $35,763 |
| 2025-12 | $36,832 |
| 2026-01 | $38,508 |
| 2026-02 | $41,186 |
| 2026-03 | $36,314 |
| 2026-04 | $36,912 |
| 2026-05 | $38,867 |
| 2026-06 | $36,863 |
| 2026-07 | $32,803 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 482 · rejected orders 0 · dividend credits 20 ($328)
- equity $39,000 → $39,631 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 134.9s (screen 8.8s, day-steps 118.7s) · screen rows 396728 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $45,980 |
| 2024-09 | $45,879 |
| 2024-10 | $49,180 |
| 2024-11 | $54,193 |
| 2024-12 | $51,417 |
| 2025-01 | $48,579 |
| 2025-02 | $43,758 |
| 2025-03 | $39,489 |
| 2025-04 | $37,552 |
| 2025-05 | $39,347 |
| 2025-06 | $42,517 |
| 2025-07 | $40,632 |
| 2025-08 | $40,793 |
| 2025-09 | $41,825 |
| 2025-10 | $44,277 |
| 2025-11 | $43,153 |
| 2025-12 | $44,511 |
| 2026-01 | $46,528 |
| 2026-02 | $49,749 |
| 2026-03 | $43,869 |
| 2026-04 | $44,590 |
| 2026-05 | $46,949 |
| 2026-06 | $44,537 |
| 2026-07 | $39,631 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 690 · rejected orders 8 · dividend credits 39 ($1,247)
- equity $39,000 → $32,136 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 176.5s (screen 10.9s, day-steps 156.3s) · screen rows 543363 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $37,272 |
| 2024-09 | $37,193 |
| 2024-10 | $39,870 |
| 2024-11 | $43,953 |
| 2024-12 | $41,692 |
| 2025-01 | $39,391 |
| 2025-02 | $35,482 |
| 2025-03 | $32,020 |
| 2025-04 | $30,449 |
| 2025-05 | $31,905 |
| 2025-06 | $34,476 |
| 2025-07 | $32,947 |
| 2025-08 | $33,078 |
| 2025-09 | $33,914 |
| 2025-10 | $35,903 |
| 2025-11 | $34,991 |
| 2025-12 | $36,092 |
| 2026-01 | $37,728 |
| 2026-02 | $40,340 |
| 2026-03 | $35,572 |
| 2026-04 | $36,156 |
| 2026-05 | $38,069 |
| 2026-06 | $36,113 |
| 2026-07 | $32,136 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 1934 · rejected orders 32 · dividend credits 154 ($7,916)
- equity $39,000 → $85,995 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 712.5s (screen 20.3s, day-steps 675.9s) · screen rows 1280417 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $99,739 |
| 2024-09 | $99,528 |
| 2024-10 | $106,692 |
| 2024-11 | $117,617 |
| 2024-12 | $111,568 |
| 2025-01 | $105,409 |
| 2025-02 | $94,949 |
| 2025-03 | $85,686 |
| 2025-04 | $81,482 |
| 2025-05 | $85,378 |
| 2025-06 | $92,256 |
| 2025-07 | $88,166 |
| 2025-08 | $88,516 |
| 2025-09 | $90,755 |
| 2025-10 | $96,075 |
| 2025-11 | $93,635 |
| 2025-12 | $96,583 |
| 2026-01 | $100,959 |
| 2026-02 | $107,949 |
| 2026-03 | $95,189 |
| 2026-04 | $96,753 |
| 2026-05 | $101,872 |
| 2026-06 | $96,638 |
| 2026-07 | $85,995 |

_… last 24 of 181 months shown._
