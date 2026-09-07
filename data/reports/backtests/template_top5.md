# Template Top 5 (`template_top5`) — historical windows

_strategy `template_top5` · cadence weekly · generated 2026-09-07 11:18 UTC_

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
| template_top5 | `legacy_unclassified` | 2026-01-16→2026-07-16 | −3.26% | −6.46% | +85.74% | +0.36 | +0.31 | −37.73% | −21.38% | · | · | **uncontrolled absolute simulation** | 169 |
| template_top5 | `legacy_unclassified` | 2025-07-16→2026-07-16 | +30.71% | +30.74% | +73.18% | +0.74 | +0.69 | −37.73% | −21.39% | · | · | **uncontrolled absolute simulation** | 340 |
| template_top5 | `legacy_unclassified` | 2023-07-17→2026-07-16 | −51.67% | −21.54% | +65.29% | −0.04 | −0.11 | −76.20% | −26.82% | · | · | **uncontrolled absolute simulation** | 1026 |
| template_top5 | `legacy_unclassified` | 2021-07-16→2026-07-16 | −51.28% | −13.40% | +59.53% | +0.06 | −0.00 | −83.39% | −26.84% | · | · | **uncontrolled absolute simulation** | 1711 |
| template_top5 | `legacy_unclassified` | 2011-07-18→2026-07-16 | +271.99% | +9.16% | +52.29% | +0.43 | +0.40 | −83.31% | −26.89% | · | · | **uncontrolled absolute simulation** | 4987 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 169 · rejected orders 2 · dividend credits 1 ($25)
- equity $39,000 → $37,730 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 17.6s (screen 5.3s, day-steps 7.5s) · screen rows 85638 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $36,593 |
| 2026-02 | $39,683 |
| 2026-03 | $39,372 |
| 2026-04 | $51,023 |
| 2026-05 | $53,811 |
| 2026-06 | $47,993 |
| 2026-07 | $37,730 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 340 · rejected orders 3 · dividend credits 1 ($34)
- equity $39,000 → $50,978 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 23.0s (screen 6.4s, day-steps 11.8s) · screen rows 160706 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2025-07 | $33,430 |
| 2025-08 | $35,650 |
| 2025-09 | $38,124 |
| 2025-10 | $48,526 |
| 2025-11 | $46,912 |
| 2025-12 | $44,254 |
| 2026-01 | $49,468 |
| 2026-02 | $53,634 |
| 2026-03 | $53,200 |
| 2026-04 | $68,942 |
| 2026-05 | $72,706 |
| 2026-06 | $64,846 |
| 2026-07 | $50,978 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 1026 · rejected orders 7 · dividend credits 1 ($13)
- equity $39,000 → $18,849 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 53.3s (screen 9.1s, day-steps 37.1s) · screen rows 396728 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $29,449 |
| 2024-09 | $28,226 |
| 2024-10 | $28,294 |
| 2024-11 | $28,035 |
| 2024-12 | $25,529 |
| 2025-01 | $22,692 |
| 2025-02 | $18,560 |
| 2025-03 | $14,684 |
| 2025-04 | $11,600 |
| 2025-05 | $11,474 |
| 2025-06 | $13,990 |
| 2025-07 | $12,338 |
| 2025-08 | $13,153 |
| 2025-09 | $14,075 |
| 2025-10 | $17,910 |
| 2025-11 | $17,315 |
| 2025-12 | $16,347 |
| 2026-01 | $18,275 |
| 2026-02 | $19,825 |
| 2026-03 | $19,670 |
| 2026-04 | $25,490 |
| 2026-05 | $26,885 |
| 2026-06 | $23,973 |
| 2026-07 | $18,849 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 1711 · rejected orders 11 · dividend credits 13 ($1,474)
- equity $39,000 → $19,001 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 85.9s (screen 11.0s, day-steps 65.9s) · screen rows 543363 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $29,627 |
| 2024-09 | $28,396 |
| 2024-10 | $28,465 |
| 2024-11 | $28,198 |
| 2024-12 | $25,681 |
| 2025-01 | $22,835 |
| 2025-02 | $18,682 |
| 2025-03 | $14,793 |
| 2025-04 | $11,695 |
| 2025-05 | $11,571 |
| 2025-06 | $14,108 |
| 2025-07 | $12,442 |
| 2025-08 | $13,264 |
| 2025-09 | $14,192 |
| 2025-10 | $18,052 |
| 2025-11 | $17,452 |
| 2025-12 | $16,479 |
| 2026-01 | $18,419 |
| 2026-02 | $19,983 |
| 2026-03 | $19,827 |
| 2026-04 | $25,692 |
| 2026-05 | $27,099 |
| 2026-06 | $24,170 |
| 2026-07 | $19,001 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 4987 · rejected orders 86 · dividend credits 46 ($16,639)
- equity $39,000 → $145,077 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 309.2s (screen 20.6s, day-steps 272.3s) · screen rows 1280417 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $227,168 |
| 2024-09 | $217,740 |
| 2024-10 | $218,275 |
| 2024-11 | $216,175 |
| 2024-12 | $196,537 |
| 2025-01 | $174,740 |
| 2025-02 | $142,912 |
| 2025-03 | $113,162 |
| 2025-04 | $89,441 |
| 2025-05 | $88,477 |
| 2025-06 | $107,845 |
| 2025-07 | $95,103 |
| 2025-08 | $101,423 |
| 2025-09 | $108,461 |
| 2025-10 | $138,078 |
| 2025-11 | $133,491 |
| 2025-12 | $125,933 |
| 2026-01 | $140,800 |
| 2026-02 | $152,653 |
| 2026-03 | $151,397 |
| 2026-04 | $196,197 |
| 2026-05 | $206,925 |
| 2026-06 | $184,549 |
| 2026-07 | $145,077 |

_… last 24 of 181 months shown._
