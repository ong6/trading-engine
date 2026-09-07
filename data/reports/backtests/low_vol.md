# Low-Volatility Defensive (`low_vol`) — historical windows

_strategy `low_vol` · cadence monthly · generated 2026-09-07 11:18 UTC_

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
| low_vol | `legacy_unclassified` | 2026-01-16→2026-07-16 | +7.28% | +15.23% | +9.71% | +1.53 | +1.17 | −5.38% | −4.46% | · | · | **uncontrolled absolute simulation** | 93 |
| low_vol | `legacy_unclassified` | 2025-07-16→2026-07-16 | +13.98% | +13.99% | +8.81% | +1.54 | +1.11 | −5.52% | −4.49% | · | · | **uncontrolled absolute simulation** | 189 |
| low_vol | `legacy_unclassified` | 2023-07-17→2026-07-16 | +41.07% | +12.16% | +9.80% | +1.23 | +0.77 | −8.22% | −5.69% | · | · | **uncontrolled absolute simulation** | 538 |
| low_vol | `legacy_unclassified` | 2021-07-16→2026-07-16 | +46.22% | +7.90% | +10.59% | +0.77 | +0.45 | −16.35% | −7.78% | · | · | **uncontrolled absolute simulation** | 904 |
| low_vol | `legacy_unclassified` | 2011-07-18→2026-07-16 | +403.79% | +11.39% | +12.10% | +0.95 | +0.83 | −35.65% | −16.06% | · | · | **uncontrolled absolute simulation** | 3801 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 93 · rejected orders 3 · dividend credits 66 ($769)
- equity $39,000 → $41,838 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 16.4s (screen 0.0s, day-steps 11.9s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $39,000 |
| 2026-02 | $41,541 |
| 2026-03 | $39,688 |
| 2026-04 | $40,789 |
| 2026-05 | $40,035 |
| 2026-06 | $40,802 |
| 2026-07 | $41,838 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 189 · rejected orders 1 · dividend credits 131 ($1,427)
- equity $39,000 → $44,452 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 27.9s (screen 0.0s, day-steps 23.0s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2025-07 | $39,000 |
| 2025-08 | $39,982 |
| 2025-09 | $40,206 |
| 2025-10 | $39,036 |
| 2025-11 | $40,036 |
| 2025-12 | $39,981 |
| 2026-01 | $41,176 |
| 2026-02 | $44,073 |
| 2026-03 | $42,094 |
| 2026-04 | $43,500 |
| 2026-05 | $42,551 |
| 2026-06 | $43,372 |
| 2026-07 | $44,452 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 538 · rejected orders 15 · dividend credits 349 ($4,472)
- equity $39,000 → $55,016 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 80.7s (screen 0.0s, day-steps 73.4s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $44,915 |
| 2024-09 | $45,279 |
| 2024-10 | $45,116 |
| 2024-11 | $47,896 |
| 2024-12 | $45,171 |
| 2025-01 | $46,753 |
| 2025-02 | $49,100 |
| 2025-03 | $49,739 |
| 2025-04 | $49,935 |
| 2025-05 | $50,223 |
| 2025-06 | $49,743 |
| 2025-07 | $49,468 |
| 2025-08 | $50,961 |
| 2025-09 | $51,060 |
| 2025-10 | $49,383 |
| 2025-11 | $50,746 |
| 2025-12 | $50,339 |
| 2026-01 | $51,702 |
| 2026-02 | $55,324 |
| 2026-03 | $52,794 |
| 2026-04 | $53,999 |
| 2026-05 | $52,782 |
| 2026-06 | $53,783 |
| 2026-07 | $55,016 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 904 · rejected orders 20 · dividend credits 552 ($7,383)
- equity $39,000 → $57,024 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 103.5s (screen 0.0s, day-steps 94.5s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $46,843 |
| 2024-09 | $47,209 |
| 2024-10 | $46,928 |
| 2024-11 | $49,810 |
| 2024-12 | $46,979 |
| 2025-01 | $48,621 |
| 2025-02 | $50,957 |
| 2025-03 | $51,626 |
| 2025-04 | $51,741 |
| 2025-05 | $52,047 |
| 2025-06 | $51,553 |
| 2025-07 | $51,268 |
| 2025-08 | $52,810 |
| 2025-09 | $52,911 |
| 2025-10 | $51,162 |
| 2025-11 | $52,574 |
| 2025-12 | $52,153 |
| 2026-01 | $53,565 |
| 2026-02 | $57,318 |
| 2026-03 | $54,708 |
| 2026-04 | $55,964 |
| 2026-05 | $54,702 |
| 2026-06 | $55,747 |
| 2026-07 | $57,024 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 3801 · rejected orders 107 · dividend credits 1598 ($49,001)
- equity $39,000 → $196,479 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 434.8s (screen 0.0s, day-steps 418.3s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $161,553 |
| 2024-09 | $162,818 |
| 2024-10 | $161,823 |
| 2024-11 | $171,788 |
| 2024-12 | $162,012 |
| 2025-01 | $167,693 |
| 2025-02 | $175,736 |
| 2025-03 | $178,050 |
| 2025-04 | $178,410 |
| 2025-05 | $179,475 |
| 2025-06 | $177,785 |
| 2025-07 | $176,794 |
| 2025-08 | $182,123 |
| 2025-09 | $182,475 |
| 2025-10 | $176,426 |
| 2025-11 | $181,268 |
| 2025-12 | $179,791 |
| 2026-01 | $184,685 |
| 2026-02 | $197,680 |
| 2026-03 | $188,578 |
| 2026-04 | $192,878 |
| 2026-05 | $188,501 |
| 2026-06 | $192,045 |
| 2026-07 | $196,479 |

_… last 24 of 181 months shown._
