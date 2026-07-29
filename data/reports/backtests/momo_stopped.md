# Momentum Top 10 (stop-managed) (`momo_stopped`) — historical windows

_strategy `momo_stopped` · cadence daily · generated 2026-07-29 07:55 UTC_

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
| momo_stopped | 2026-01-16→2026-07-16 | −6.05% | −11.84% | +84.18% | +0.28 | +0.24 | −34.15% | −27.95% | −10.75% | −16.50% | 380 |
| momo_stopped | 2025-07-16→2026-07-16 | +7.69% | +7.70% | +68.58% | +0.46 | +0.40 | −33.64% | −27.94% | −37.67% | −13.48% | 748 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 380 · rejected orders 7 · dividend credits 0 ($0)
- equity $39,000 → $36,640 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 32.1s (screen 5.0s, day-steps 23.3s) · screen rows 85638 · dividend rows in force 1837

| Month | Equity |
|---|---|
| 2026-01 | $37,726 |
| 2026-02 | $41,287 |
| 2026-03 | $32,738 |
| 2026-04 | $40,473 |
| 2026-05 | $48,431 |
| 2026-06 | $50,850 |
| 2026-07 | $36,640 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 748 · rejected orders 10 · dividend credits 0 ($0)
- equity $39,000 → $42,001 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 51.3s (screen 6.3s, day-steps 40.6s) · screen rows 160706 · dividend rows in force 1837

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
| 2026-03 | $37,513 |
| 2026-04 | $46,392 |
| 2026-05 | $55,511 |
| 2026-06 | $58,287 |
| 2026-07 | $42,001 |
