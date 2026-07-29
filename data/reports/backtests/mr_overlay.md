# Mean-Reversion Overlay (`mr_overlay`) — historical windows

_strategy `mr_overlay` · cadence daily · generated 2026-07-29 07:56 UTC_

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
| mr_overlay | 2026-01-16→2026-07-16 | +6.59% | +13.74% | +19.23% | +0.77 | +0.59 | −8.96% | −1.12% | +1.88% | −3.86% | 237 |
| mr_overlay | 2025-07-16→2026-07-16 | +9.08% | +9.09% | +16.61% | +0.61 | +0.38 | −8.96% | −3.62% | −36.28% | −12.10% | 479 |
| mr_overlay | 2023-07-17→2026-07-16 | +20.26% | +6.35% | +14.26% | +0.50 | +0.19 | −17.44% | −7.05% | · | · | 1387 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 237 · rejected orders 0 · dividend credits 0 ($0)
- equity $39,000 → $41,569 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 84.8s (screen 4.9s, day-steps 76.1s) · screen rows 85638 · dividend rows in force 1837

| Month | Equity |
|---|---|
| 2026-01 | $39,810 |
| 2026-02 | $42,028 |
| 2026-03 | $41,603 |
| 2026-04 | $41,662 |
| 2026-05 | $41,194 |
| 2026-06 | $41,930 |
| 2026-07 | $41,569 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 479 · rejected orders 0 · dividend credits 0 ($0)
- equity $39,000 → $42,542 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 123.7s (screen 6.4s, day-steps 113.0s) · screen rows 160706 · dividend rows in force 1837

| Month | Equity |
|---|---|
| 2025-07 | $38,967 |
| 2025-08 | $40,253 |
| 2025-09 | $39,829 |
| 2025-10 | $41,392 |
| 2025-11 | $39,894 |
| 2025-12 | $40,910 |
| 2026-01 | $42,196 |
| 2026-02 | $43,011 |
| 2026-03 | $42,576 |
| 2026-04 | $42,637 |
| 2026-05 | $42,158 |
| 2026-06 | $42,911 |
| 2026-07 | $42,542 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 1387 · rejected orders 0 · dividend credits 0 ($0)
- equity $39,000 → $46,900 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 405.7s (screen 9.0s, day-steps 390.3s) · screen rows 396728 · dividend rows in force 1837

| Month | Equity |
|---|---|
| 2024-08 | $39,996 |
| 2024-09 | $41,702 |
| 2024-10 | $43,618 |
| 2024-11 | $45,388 |
| 2024-12 | $45,954 |
| 2025-01 | $47,055 |
| 2025-02 | $45,072 |
| 2025-03 | $41,896 |
| 2025-04 | $41,421 |
| 2025-05 | $42,355 |
| 2025-06 | $43,267 |
| 2025-07 | $42,713 |
| 2025-08 | $44,377 |
| 2025-09 | $43,910 |
| 2025-10 | $45,633 |
| 2025-11 | $43,981 |
| 2025-12 | $45,101 |
| 2026-01 | $46,519 |
| 2026-02 | $47,417 |
| 2026-03 | $46,938 |
| 2026-04 | $47,005 |
| 2026-05 | $46,477 |
| 2026-06 | $47,307 |
| 2026-07 | $46,900 |

_… last 24 of 37 months shown._
