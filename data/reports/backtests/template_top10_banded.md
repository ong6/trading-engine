# Template Top 10 (banded) (`template_top10_banded`) — historical windows

_strategy `template_top10_banded` · cadence weekly · generated 2026-07-29 07:56 UTC_

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
| template_top10_banded | 2026-01-16→2026-07-16 | −8.22% | −15.89% | +86.90% | +0.24 | +0.20 | −37.25% | −29.23% | −12.92% | −18.66% | 371 |
| template_top10_banded | 2025-07-16→2026-07-16 | +9.88% | +9.88% | +71.34% | +0.50 | +0.44 | −36.68% | −29.22% | −35.49% | −11.30% | 732 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 371 · rejected orders 4 · dividend credits 0 ($0)
- equity $39,000 → $35,796 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 20.4s (screen 5.2s, day-steps 11.3s) · screen rows 85638 · dividend rows in force 1837

| Month | Equity |
|---|---|
| 2026-01 | $37,668 |
| 2026-02 | $41,546 |
| 2026-03 | $31,188 |
| 2026-04 | $39,394 |
| 2026-05 | $48,748 |
| 2026-06 | $50,578 |
| 2026-07 | $35,796 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 732 · rejected orders 8 · dividend credits 0 ($0)
- equity $39,000 → $42,851 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 30.2s (screen 6.1s, day-steps 19.8s) · screen rows 160706 · dividend rows in force 1837

| Month | Equity |
|---|---|
| 2025-07 | $34,739 |
| 2025-08 | $33,915 |
| 2025-09 | $39,327 |
| 2025-10 | $44,847 |
| 2025-11 | $36,807 |
| 2025-12 | $38,033 |
| 2026-01 | $45,083 |
| 2026-02 | $49,730 |
| 2026-03 | $37,334 |
| 2026-04 | $47,155 |
| 2026-05 | $58,352 |
| 2026-06 | $60,543 |
| 2026-07 | $42,851 |
