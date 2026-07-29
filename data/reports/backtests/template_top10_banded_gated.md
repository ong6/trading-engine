# Template Top 10 banded (regime-gated) (`template_top10_banded_gated`) — historical windows

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
| template_top10_banded_gated | 2026-01-16→2026-07-16 | −14.26% | −26.68% | +85.00% | +0.07 | +0.03 | −35.32% | −29.23% | −19.03% | −24.70% | 343 |
| template_top10_banded_gated | 2025-07-16→2026-07-16 | +2.94% | +2.94% | +70.25% | +0.40 | +0.35 | −35.31% | −29.22% | −43.18% | −18.24% | 705 |
| template_top10_banded_gated | 2023-07-17→2026-07-16 | −8.84% | −3.04% | +55.93% | +0.23 | +0.15 | −46.37% | −29.22% | −69.43% | −79.69% | 2058 |
| template_top10_banded_gated | 2021-07-16→2026-07-16 | +3.40% | +0.67% | +47.29% | +0.25 | +0.18 | −51.63% | −29.22% | −60.18% | −79.64% | 2924 |
| template_top10_banded_gated | 2011-07-18→2026-07-16 | +828.24% | +16.02% | +39.12% | +0.58 | +0.54 | −51.71% | −29.23% | −313.99% | +298.78% | 9400 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 343 · rejected orders 5 · dividend credits 4 ($25)
- equity $39,000 → $33,440 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 21.3s (screen 5.5s, day-steps 11.3s) · screen rows 85638 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $37,668 |
| 2026-02 | $41,546 |
| 2026-03 | $32,400 |
| 2026-04 | $36,515 |
| 2026-05 | $45,511 |
| 2026-06 | $47,249 |
| 2026-07 | $33,440 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 705 · rejected orders 6 · dividend credits 4 ($30)
- equity $39,000 → $40,147 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 32.9s (screen 6.8s, day-steps 21.1s) · screen rows 160706 · dividend rows in force 400240

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
| 2026-03 | $38,752 |
| 2026-04 | $43,844 |
| 2026-05 | $54,638 |
| 2026-06 | $56,721 |
| 2026-07 | $40,147 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 2058 · rejected orders 14 · dividend credits 8 ($57)
- equity $39,000 → $35,553 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 79.9s (screen 8.8s, day-steps 63.8s) · screen rows 396728 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $32,804 |
| 2024-09 | $37,127 |
| 2024-10 | $41,981 |
| 2024-11 | $49,808 |
| 2024-12 | $43,663 |
| 2025-01 | $39,586 |
| 2025-02 | $36,772 |
| 2025-03 | $33,423 |
| 2025-04 | $30,334 |
| 2025-05 | $29,920 |
| 2025-06 | $35,108 |
| 2025-07 | $30,709 |
| 2025-08 | $29,946 |
| 2025-09 | $34,722 |
| 2025-10 | $39,579 |
| 2025-11 | $32,513 |
| 2025-12 | $33,605 |
| 2026-01 | $39,832 |
| 2026-02 | $43,938 |
| 2026-03 | $34,226 |
| 2026-04 | $38,830 |
| 2026-05 | $48,392 |
| 2026-06 | $50,233 |
| 2026-07 | $35,553 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 2924 · rejected orders 19 · dividend credits 25 ($1,122)
- equity $39,000 → $40,324 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 107.2s (screen 11.1s, day-steps 86.9s) · screen rows 543363 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $37,323 |
| 2024-09 | $42,244 |
| 2024-10 | $47,765 |
| 2024-11 | $56,662 |
| 2024-12 | $49,670 |
| 2025-01 | $45,031 |
| 2025-02 | $41,839 |
| 2025-03 | $38,027 |
| 2025-04 | $34,513 |
| 2025-05 | $34,042 |
| 2025-06 | $39,945 |
| 2025-07 | $34,938 |
| 2025-08 | $34,069 |
| 2025-09 | $39,502 |
| 2025-10 | $45,047 |
| 2025-11 | $36,973 |
| 2025-12 | $38,205 |
| 2026-01 | $45,286 |
| 2026-02 | $49,954 |
| 2026-03 | $38,927 |
| 2026-04 | $44,036 |
| 2026-05 | $54,881 |
| 2026-06 | $56,973 |
| 2026-07 | $40,324 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 9400 · rejected orders 62 · dividend credits 102 ($13,449)
- equity $39,000 → $362,015 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 405.6s (screen 20.1s, day-steps 369.1s) · screen rows 1280417 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $333,575 |
| 2024-09 | $377,651 |
| 2024-10 | $427,081 |
| 2024-11 | $506,513 |
| 2024-12 | $444,002 |
| 2025-01 | $402,411 |
| 2025-02 | $373,974 |
| 2025-03 | $339,919 |
| 2025-04 | $308,501 |
| 2025-05 | $304,288 |
| 2025-06 | $357,174 |
| 2025-07 | $312,475 |
| 2025-08 | $304,718 |
| 2025-09 | $353,407 |
| 2025-10 | $402,855 |
| 2025-11 | $330,781 |
| 2025-12 | $341,764 |
| 2026-01 | $405,150 |
| 2026-02 | $446,838 |
| 2026-03 | $347,882 |
| 2026-04 | $394,965 |
| 2026-05 | $492,735 |
| 2026-06 | $511,510 |
| 2026-07 | $362,015 |

_… last 24 of 181 months shown._
