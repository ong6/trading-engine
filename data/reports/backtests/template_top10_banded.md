# Template Top 10 (banded) (`template_top10_banded`) — historical windows

_strategy `template_top10_banded` · cadence weekly · generated 2026-07-29 14:04 UTC_

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
| template_top10_banded | 2026-01-16→2026-07-16 | −8.13% | −15.73% | +86.89% | +0.25 | +0.21 | −37.23% | −29.22% | −12.90% | −18.58% | 371 |
| template_top10_banded | 2025-07-16→2026-07-16 | +9.94% | +9.95% | +71.34% | +0.50 | +0.45 | −36.66% | −29.23% | −36.18% | −11.24% | 731 |
| template_top10_banded | 2023-07-17→2026-07-16 | −1.19% | −0.40% | +57.14% | +0.28 | +0.20 | −47.80% | −29.23% | −61.79% | −72.04% | 2238 |
| template_top10_banded | 2021-07-16→2026-07-16 | +8.91% | +1.72% | +50.68% | +0.29 | +0.22 | −52.75% | −29.22% | −54.67% | −74.13% | 3761 |
| template_top10_banded | 2011-07-18→2026-07-16 | +620.86% | +14.08% | +41.82% | +0.53 | +0.49 | −52.85% | −29.23% | −521.38% | +91.39% | 11298 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 371 · rejected orders 4 · dividend credits 4 ($26)
- equity $39,000 → $35,829 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 18.2s (screen 5.3s, day-steps 8.3s) · screen rows 85638 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $37,668 |
| 2026-02 | $41,546 |
| 2026-03 | $31,199 |
| 2026-04 | $39,407 |
| 2026-05 | $48,772 |
| 2026-06 | $50,624 |
| 2026-07 | $35,829 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 731 · rejected orders 9 · dividend credits 4 ($31)
- equity $39,000 → $42,876 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 33.9s (screen 6.5s, day-steps 22.4s) · screen rows 160706 · dividend rows in force 400240

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
| 2026-03 | $37,347 |
| 2026-04 | $47,171 |
| 2026-05 | $58,372 |
| 2026-06 | $60,582 |
| 2026-07 | $42,876 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 2238 · rejected orders 18 · dividend credits 10 ($88)
- equity $39,000 → $38,535 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 84.4s (screen 8.8s, day-steps 68.4s) · screen rows 396728 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $33,687 |
| 2024-09 | $38,126 |
| 2024-10 | $43,111 |
| 2024-11 | $51,148 |
| 2024-12 | $44,838 |
| 2025-01 | $40,650 |
| 2025-02 | $37,761 |
| 2025-03 | $32,498 |
| 2025-04 | $28,686 |
| 2025-05 | $30,553 |
| 2025-06 | $35,728 |
| 2025-07 | $31,249 |
| 2025-08 | $30,472 |
| 2025-09 | $35,334 |
| 2025-10 | $40,260 |
| 2025-11 | $33,045 |
| 2025-12 | $34,157 |
| 2026-01 | $40,485 |
| 2026-02 | $44,658 |
| 2026-03 | $33,561 |
| 2026-04 | $42,393 |
| 2026-05 | $52,457 |
| 2026-06 | $54,448 |
| 2026-07 | $38,535 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 3761 · rejected orders 25 · dividend credits 40 ($1,673)
- equity $39,000 → $42,473 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 117.6s (screen 11.1s, day-steps 97.5s) · screen rows 543363 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $37,155 |
| 2024-09 | $42,050 |
| 2024-10 | $47,550 |
| 2024-11 | $56,404 |
| 2024-12 | $49,446 |
| 2025-01 | $44,827 |
| 2025-02 | $41,640 |
| 2025-03 | $35,844 |
| 2025-04 | $31,617 |
| 2025-05 | $33,670 |
| 2025-06 | $39,376 |
| 2025-07 | $34,443 |
| 2025-08 | $33,587 |
| 2025-09 | $38,952 |
| 2025-10 | $44,404 |
| 2025-11 | $36,445 |
| 2025-12 | $37,659 |
| 2026-01 | $44,640 |
| 2026-02 | $49,240 |
| 2026-03 | $36,990 |
| 2026-04 | $46,722 |
| 2026-05 | $57,813 |
| 2026-06 | $60,008 |
| 2026-07 | $42,473 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 11298 · rejected orders 83 · dividend credits 127 ($13,775)
- equity $39,000 → $281,134 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 469.0s (screen 20.4s, day-steps 432.5s) · screen rows 1280417 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $244,910 |
| 2024-09 | $277,270 |
| 2024-10 | $313,562 |
| 2024-11 | $371,895 |
| 2024-12 | $326,000 |
| 2025-01 | $295,463 |
| 2025-02 | $274,582 |
| 2025-03 | $236,458 |
| 2025-04 | $208,664 |
| 2025-05 | $222,182 |
| 2025-06 | $259,925 |
| 2025-07 | $227,402 |
| 2025-08 | $221,756 |
| 2025-09 | $257,185 |
| 2025-10 | $293,181 |
| 2025-11 | $240,728 |
| 2025-12 | $248,732 |
| 2026-01 | $294,867 |
| 2026-02 | $325,209 |
| 2026-03 | $244,336 |
| 2026-04 | $308,516 |
| 2026-05 | $382,643 |
| 2026-06 | $397,225 |
| 2026-07 | $281,134 |

_… last 24 of 181 months shown._
