# Mean-Reversion Overlay (regime-gated) (`mr_overlay_gated`) — historical windows

_strategy `mr_overlay` · cadence daily · generated 2026-07-29 14:04 UTC_

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
| mr_overlay_gated | 2026-01-16→2026-07-16 | +9.34% | +19.75% | +18.51% | +1.08 | +0.89 | −8.04% | −1.13% | +4.57% | −1.10% | 221 |
| mr_overlay_gated | 2025-07-16→2026-07-16 | +11.91% | +11.92% | +16.20% | +0.78 | +0.55 | −8.04% | −3.62% | −34.21% | −9.27% | 463 |
| mr_overlay_gated | 2023-07-17→2026-07-16 | +26.32% | +8.10% | +13.64% | +0.64 | +0.31 | −13.64% | −5.75% | −34.28% | −44.53% | 1313 |
| mr_overlay_gated | 2021-07-16→2026-07-16 | +14.08% | +2.67% | +11.97% | +0.28 | −0.01 | −19.55% | −5.75% | −49.49% | −68.96% | 1773 |
| mr_overlay_gated | 2011-07-18→2026-07-16 | +7.46% | +0.48% | +11.25% | +0.10 | −0.03 | −32.98% | −11.54% | −1134.78% | −522.01% | 5413 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 221 · rejected orders 0 · dividend credits 1 ($2)
- equity $39,000 → $42,644 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 57.5s (screen 5.3s, day-steps 47.6s) · screen rows 85638 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $39,810 |
| 2026-02 | $42,028 |
| 2026-03 | $42,446 |
| 2026-04 | $42,741 |
| 2026-05 | $42,260 |
| 2026-06 | $43,014 |
| 2026-07 | $42,644 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 463 · rejected orders 0 · dividend credits 2 ($4)
- equity $39,000 → $43,644 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 125.8s (screen 6.3s, day-steps 114.5s) · screen rows 160706 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2025-07 | $38,967 |
| 2025-08 | $40,253 |
| 2025-09 | $39,829 |
| 2025-10 | $41,392 |
| 2025-11 | $39,896 |
| 2025-12 | $40,912 |
| 2026-01 | $42,198 |
| 2026-02 | $43,013 |
| 2026-03 | $43,441 |
| 2026-04 | $43,743 |
| 2026-05 | $43,250 |
| 2026-06 | $44,023 |
| 2026-07 | $43,644 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 1313 · rejected orders 0 · dividend credits 10 ($126)
- equity $39,000 → $49,264 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 382.3s (screen 8.8s, day-steps 366.2s) · screen rows 396728 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $40,159 |
| 2024-09 | $41,871 |
| 2024-10 | $43,795 |
| 2024-11 | $45,572 |
| 2024-12 | $46,153 |
| 2025-01 | $47,259 |
| 2025-02 | $45,267 |
| 2025-03 | $42,662 |
| 2025-04 | $42,662 |
| 2025-05 | $43,793 |
| 2025-06 | $44,764 |
| 2025-07 | $43,733 |
| 2025-08 | $45,437 |
| 2025-09 | $44,958 |
| 2025-10 | $46,722 |
| 2025-11 | $45,033 |
| 2025-12 | $46,180 |
| 2026-01 | $47,631 |
| 2026-02 | $48,552 |
| 2026-03 | $49,035 |
| 2026-04 | $49,376 |
| 2026-05 | $48,820 |
| 2026-06 | $49,692 |
| 2026-07 | $49,264 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 1773 · rejected orders 0 · dividend credits 16 ($205)
- equity $39,000 → $44,491 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 476.1s (screen 11.2s, day-steps 455.5s) · screen rows 543363 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $36,268 |
| 2024-09 | $37,814 |
| 2024-10 | $39,552 |
| 2024-11 | $41,157 |
| 2024-12 | $41,681 |
| 2025-01 | $42,680 |
| 2025-02 | $40,882 |
| 2025-03 | $38,529 |
| 2025-04 | $38,529 |
| 2025-05 | $39,550 |
| 2025-06 | $40,427 |
| 2025-07 | $39,496 |
| 2025-08 | $41,034 |
| 2025-09 | $40,602 |
| 2025-10 | $42,195 |
| 2025-11 | $40,670 |
| 2025-12 | $41,705 |
| 2026-01 | $43,017 |
| 2026-02 | $43,848 |
| 2026-03 | $44,284 |
| 2026-04 | $44,592 |
| 2026-05 | $44,090 |
| 2026-06 | $44,877 |
| 2026-07 | $44,491 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 5413 · rejected orders 0 · dividend credits 74 ($1,470)
- equity $39,000 → $41,908 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 1530.2s (screen 20.2s, day-steps 1494.0s) · screen rows 1280417 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $34,162 |
| 2024-09 | $35,619 |
| 2024-10 | $37,255 |
| 2024-11 | $38,767 |
| 2024-12 | $39,261 |
| 2025-01 | $40,202 |
| 2025-02 | $38,508 |
| 2025-03 | $36,292 |
| 2025-04 | $36,292 |
| 2025-05 | $37,254 |
| 2025-06 | $38,079 |
| 2025-07 | $37,203 |
| 2025-08 | $38,652 |
| 2025-09 | $38,245 |
| 2025-10 | $39,745 |
| 2025-11 | $38,309 |
| 2025-12 | $39,284 |
| 2026-01 | $40,519 |
| 2026-02 | $41,302 |
| 2026-03 | $41,713 |
| 2026-04 | $42,003 |
| 2026-05 | $41,530 |
| 2026-06 | $42,271 |
| 2026-07 | $41,908 |

_… last 24 of 181 months shown._
