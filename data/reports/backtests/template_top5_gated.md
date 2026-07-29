# Template Top 5 (regime-gated) (`template_top5_gated`) — historical windows

_strategy `template_top5` · cadence weekly · generated 2026-07-29 14:04 UTC_

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
| template_top5_gated | 2026-01-16→2026-07-16 | −17.09% | −31.49% | +82.80% | −0.04 | −0.09 | −37.73% | −21.39% | −21.86% | −27.54% | 151 |
| template_top5_gated | 2025-07-16→2026-07-16 | +12.04% | +12.05% | +71.53% | +0.52 | +0.47 | −37.72% | −21.39% | −34.08% | −9.13% | 322 |
| template_top5_gated | 2023-07-17→2026-07-16 | −40.03% | −15.68% | +62.97% | +0.04 | −0.03 | −64.51% | −26.84% | −100.62% | −110.88% | 937 |
| template_top5_gated | 2021-07-16→2026-07-16 | −46.01% | −11.60% | +54.64% | +0.05 | −0.02 | −77.90% | −26.83% | −109.58% | −129.05% | 1333 |
| template_top5_gated | 2011-07-18→2026-07-16 | +808.26% | +15.85% | +47.27% | +0.55 | +0.52 | −74.00% | −26.99% | −333.98% | +278.79% | 4022 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 151 · rejected orders 2 · dividend credits 1 ($21)
- equity $39,000 → $32,334 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 17.6s (screen 5.4s, day-steps 7.5s) · screen rows 85638 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $36,593 |
| 2026-02 | $39,683 |
| 2026-03 | $40,502 |
| 2026-04 | $43,728 |
| 2026-05 | $46,116 |
| 2026-06 | $41,131 |
| 2026-07 | $32,334 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 322 · rejected orders 3 · dividend credits 1 ($29)
- equity $39,000 → $43,697 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 25.6s (screen 6.5s, day-steps 14.1s) · screen rows 160706 · dividend rows in force 400240

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
| 2026-03 | $54,736 |
| 2026-04 | $59,095 |
| 2026-05 | $62,323 |
| 2026-06 | $55,584 |
| 2026-07 | $43,697 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 937 · rejected orders 6 · dividend credits 1 ($16)
- equity $39,000 → $23,389 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 57.6s (screen 8.7s, day-steps 41.7s) · screen rows 396728 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $31,112 |
| 2024-09 | $29,820 |
| 2024-10 | $29,892 |
| 2024-11 | $29,607 |
| 2024-12 | $26,931 |
| 2025-01 | $23,947 |
| 2025-02 | $19,594 |
| 2025-03 | $18,210 |
| 2025-04 | $18,210 |
| 2025-05 | $16,631 |
| 2025-06 | $20,275 |
| 2025-07 | $17,880 |
| 2025-08 | $19,060 |
| 2025-09 | $20,394 |
| 2025-10 | $25,941 |
| 2025-11 | $25,083 |
| 2025-12 | $23,678 |
| 2026-01 | $26,469 |
| 2026-02 | $28,704 |
| 2026-03 | $29,296 |
| 2026-04 | $31,628 |
| 2026-05 | $33,352 |
| 2026-06 | $29,751 |
| 2026-07 | $23,389 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 1333 · rejected orders 7 · dividend credits 10 ($1,258)
- equity $39,000 → $21,056 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 83.5s (screen 11.1s, day-steps 63.5s) · screen rows 543363 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $27,999 |
| 2024-09 | $26,836 |
| 2024-10 | $26,901 |
| 2024-11 | $26,648 |
| 2024-12 | $24,227 |
| 2025-01 | $21,543 |
| 2025-02 | $17,623 |
| 2025-03 | $16,378 |
| 2025-04 | $16,378 |
| 2025-05 | $14,958 |
| 2025-06 | $18,240 |
| 2025-07 | $16,085 |
| 2025-08 | $17,147 |
| 2025-09 | $18,337 |
| 2025-10 | $23,330 |
| 2025-11 | $22,558 |
| 2025-12 | $21,305 |
| 2026-01 | $23,816 |
| 2026-02 | $25,836 |
| 2026-03 | $26,369 |
| 2026-04 | $28,468 |
| 2026-05 | $30,024 |
| 2026-06 | $26,783 |
| 2026-07 | $21,056 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 4022 · rejected orders 164 · dividend credits 37 ($20,670)
- equity $39,000 → $354,220 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 285.1s (screen 20.3s, day-steps 249.6s) · screen rows 1280417 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $436,360 |
| 2024-09 | $419,609 |
| 2024-10 | $440,361 |
| 2024-11 | $436,175 |
| 2024-12 | $396,456 |
| 2025-01 | $342,056 |
| 2025-02 | $293,522 |
| 2025-03 | $272,757 |
| 2025-04 | $272,757 |
| 2025-05 | $249,105 |
| 2025-06 | $303,633 |
| 2025-07 | $267,757 |
| 2025-08 | $285,554 |
| 2025-09 | $305,351 |
| 2025-10 | $388,780 |
| 2025-11 | $364,548 |
| 2025-12 | $343,859 |
| 2026-01 | $384,471 |
| 2026-02 | $413,965 |
| 2026-03 | $422,463 |
| 2026-04 | $456,088 |
| 2026-05 | $484,403 |
| 2026-06 | $422,137 |
| 2026-07 | $354,220 |

_… last 24 of 181 months shown._
