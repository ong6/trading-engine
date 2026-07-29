# Equal-Weight Benchmark (`ew_benchmark`) — historical windows

_strategy `ew_benchmark` · cadence monthly · generated 2026-07-29 07:56 UTC_

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
| ew_benchmark | 2026-01-16→2026-07-16 | +4.70% | +9.72% | +62.38% | +0.46 | +0.41 | −25.57% | −23.55% | +0.00% | −5.74% | 419 |
| ew_benchmark | 2025-07-16→2026-07-16 | +45.36% | +45.40% | +53.33% | +0.97 | +0.90 | −27.50% | −23.57% | +0.00% | +24.18% | 857 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 419 · rejected orders 0 · dividend credits 0 ($0)
- equity $39,000 → $40,834 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 37.8s (screen 4.9s, day-steps 29.1s) · screen rows 85638 · dividend rows in force 1837

| Month | Equity |
|---|---|
| 2026-01 | $39,000 |
| 2026-02 | $40,196 |
| 2026-03 | $34,934 |
| 2026-04 | $43,380 |
| 2026-05 | $52,785 |
| 2026-06 | $53,415 |
| 2026-07 | $40,834 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 857 · rejected orders 1 · dividend credits 0 ($0)
- equity $39,000 → $56,692 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 48.0s (screen 6.3s, day-steps 37.3s) · screen rows 160706 · dividend rows in force 1837

| Month | Equity |
|---|---|
| 2025-07 | $39,000 |
| 2025-08 | $41,686 |
| 2025-09 | $48,875 |
| 2025-10 | $54,171 |
| 2025-11 | $48,627 |
| 2025-12 | $48,191 |
| 2026-01 | $54,683 |
| 2026-02 | $55,827 |
| 2026-03 | $48,537 |
| 2026-04 | $60,254 |
| 2026-05 | $73,304 |
| 2026-06 | $74,179 |
| 2026-07 | $56,692 |
