# 52-Week-High Momentum (`high_52wk`) — historical windows

_strategy `high_52wk` · cadence monthly · generated 2026-07-29 14:04 UTC_

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
| high_52wk | 2026-01-16→2026-07-16 | +0.92% | +1.87% | +17.77% | +0.19 | −0.00 | −11.96% | −7.88% | −3.85% | −9.52% | 252 |
| high_52wk | 2025-07-16→2026-07-16 | +20.74% | +20.75% | +15.77% | +1.28 | +1.04 | −11.72% | −7.66% | −25.38% | −0.44% | 538 |
| high_52wk | 2023-07-17→2026-07-16 | +60.05% | +16.99% | +13.80% | +1.21 | +0.88 | −11.71% | −7.64% | −0.55% | −10.80% | 1589 |
| high_52wk | 2021-07-16→2026-07-16 | +42.41% | +7.33% | +15.67% | +0.53 | +0.31 | −30.92% | −7.66% | −21.16% | −40.63% | 2591 |
| high_52wk | 2011-07-18→2026-07-16 | +171.91% | +6.90% | +15.00% | +0.52 | +0.42 | −30.05% | −12.33% | −970.32% | −357.56% | 7440 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 252 · rejected orders 0 · dividend credits 40 ($534)
- equity $39,000 → $39,361 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 13.7s (screen 0.0s, day-steps 9.2s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $39,000 |
| 2026-02 | $42,046 |
| 2026-03 | $38,732 |
| 2026-04 | $40,023 |
| 2026-05 | $40,679 |
| 2026-06 | $41,077 |
| 2026-07 | $39,361 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 538 · rejected orders 0 · dividend credits 71 ($1,126)
- equity $39,000 → $47,088 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 30.2s (screen 0.0s, day-steps 25.3s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2025-07 | $39,000 |
| 2025-08 | $40,024 |
| 2025-09 | $43,345 |
| 2025-10 | $42,782 |
| 2025-11 | $43,423 |
| 2025-12 | $43,751 |
| 2026-01 | $46,522 |
| 2026-02 | $50,183 |
| 2026-03 | $46,340 |
| 2026-04 | $47,884 |
| 2026-05 | $48,670 |
| 2026-06 | $49,141 |
| 2026-07 | $47,088 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 1589 · rejected orders 23 · dividend credits 233 ($3,871)
- equity $39,000 → $62,419 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 84.0s (screen 0.0s, day-steps 76.7s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $44,332 |
| 2024-09 | $45,352 |
| 2024-10 | $45,067 |
| 2024-11 | $48,967 |
| 2024-12 | $48,411 |
| 2025-01 | $50,048 |
| 2025-02 | $49,750 |
| 2025-03 | $50,028 |
| 2025-04 | $49,890 |
| 2025-05 | $50,897 |
| 2025-06 | $52,129 |
| 2025-07 | $52,029 |
| 2025-08 | $53,052 |
| 2025-09 | $57,452 |
| 2025-10 | $56,706 |
| 2025-11 | $57,555 |
| 2025-12 | $57,991 |
| 2026-01 | $61,664 |
| 2026-02 | $66,516 |
| 2026-03 | $61,433 |
| 2026-04 | $63,480 |
| 2026-05 | $64,517 |
| 2026-06 | $65,140 |
| 2026-07 | $62,419 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 2591 · rejected orders 73 · dividend credits 391 ($4,894)
- equity $39,000 → $55,539 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 113.7s (screen 0.0s, day-steps 104.6s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $38,280 |
| 2024-09 | $39,160 |
| 2024-10 | $38,912 |
| 2024-11 | $42,282 |
| 2024-12 | $41,800 |
| 2025-01 | $43,209 |
| 2025-02 | $42,960 |
| 2025-03 | $43,199 |
| 2025-04 | $43,075 |
| 2025-05 | $43,944 |
| 2025-06 | $45,010 |
| 2025-07 | $44,928 |
| 2025-08 | $45,811 |
| 2025-09 | $49,604 |
| 2025-10 | $48,961 |
| 2025-11 | $49,691 |
| 2025-12 | $50,068 |
| 2026-01 | $53,245 |
| 2026-02 | $57,434 |
| 2026-03 | $53,037 |
| 2026-04 | $54,815 |
| 2026-05 | $57,491 |
| 2026-06 | $57,963 |
| 2026-07 | $55,539 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 7440 · rejected orders 470 · dividend credits 1209 ($21,897)
- equity $39,000 → $106,044 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 436.6s (screen 0.0s, day-steps 420.4s) · screen rows 0 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $75,927 |
| 2024-09 | $77,181 |
| 2024-10 | $76,671 |
| 2024-11 | $83,307 |
| 2024-12 | $82,358 |
| 2025-01 | $85,140 |
| 2025-02 | $84,636 |
| 2025-03 | $85,109 |
| 2025-04 | $84,881 |
| 2025-05 | $86,597 |
| 2025-06 | $88,692 |
| 2025-07 | $88,521 |
| 2025-08 | $90,262 |
| 2025-09 | $97,516 |
| 2025-10 | $96,322 |
| 2025-11 | $97,765 |
| 2025-12 | $98,506 |
| 2026-01 | $104,745 |
| 2026-02 | $112,988 |
| 2026-03 | $104,354 |
| 2026-04 | $107,832 |
| 2026-05 | $109,598 |
| 2026-06 | $110,670 |
| 2026-07 | $106,044 |

_… last 24 of 181 months shown._
