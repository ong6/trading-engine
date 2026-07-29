# Mean-Reversion Overlay (`mr_overlay`) — historical windows

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
| mr_overlay | 2026-01-16→2026-07-16 | +6.59% | +13.75% | +19.23% | +0.78 | +0.59 | −8.96% | −1.12% | +1.82% | −3.85% | 237 |
| mr_overlay | 2025-07-16→2026-07-16 | +9.09% | +9.10% | +16.61% | +0.61 | +0.38 | −8.96% | −3.62% | −37.03% | −12.09% | 479 |
| mr_overlay | 2023-07-17→2026-07-16 | +21.00% | +6.56% | +14.25% | +0.52 | +0.20 | −17.30% | −6.89% | −39.60% | −49.85% | 1387 |
| mr_overlay | 2021-07-16→2026-07-16 | +3.87% | +0.76% | +13.75% | +0.12 | −0.13 | −23.53% | −9.03% | −59.71% | −79.17% | 2193 |
| mr_overlay | 2011-07-18→2026-07-16 | −0.01% | −0.00% | +12.43% | +0.06 | −0.05 | −37.15% | −11.54% | −1142.24% | −529.47% | 6225 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 237 · rejected orders 0 · dividend credits 1 ($2)
- equity $39,000 → $41,571 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 61.3s (screen 5.4s, day-steps 51.0s) · screen rows 85638 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2026-01 | $39,810 |
| 2026-02 | $42,028 |
| 2026-03 | $41,605 |
| 2026-04 | $41,664 |
| 2026-05 | $41,196 |
| 2026-06 | $41,932 |
| 2026-07 | $41,571 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 479 · rejected orders 0 · dividend credits 2 ($4)
- equity $39,000 → $42,546 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 132.7s (screen 6.3s, day-steps 121.5s) · screen rows 160706 · dividend rows in force 400240

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
| 2026-03 | $42,580 |
| 2026-04 | $42,641 |
| 2026-05 | $42,162 |
| 2026-06 | $42,915 |
| 2026-07 | $42,546 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 1387 · rejected orders 0 · dividend credits 14 ($261)
- equity $39,000 → $47,190 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 399.7s (screen 8.9s, day-steps 383.6s) · screen rows 396728 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $40,012 |
| 2024-09 | $41,718 |
| 2024-10 | $43,635 |
| 2024-11 | $45,406 |
| 2024-12 | $45,984 |
| 2025-01 | $47,086 |
| 2025-02 | $45,102 |
| 2025-03 | $41,993 |
| 2025-04 | $41,557 |
| 2025-05 | $42,546 |
| 2025-06 | $43,530 |
| 2025-07 | $42,973 |
| 2025-08 | $44,647 |
| 2025-09 | $44,177 |
| 2025-10 | $45,910 |
| 2025-11 | $44,251 |
| 2025-12 | $45,377 |
| 2026-01 | $46,804 |
| 2026-02 | $47,708 |
| 2026-03 | $47,228 |
| 2026-04 | $47,295 |
| 2026-05 | $46,764 |
| 2026-06 | $47,600 |
| 2026-07 | $47,190 |

_… last 24 of 37 months shown._

### 5y — 2021-07-16 → 2026-07-16

- sessions 1255 · fills 2193 · rejected orders 0 · dividend credits 26 ($404)
- equity $39,000 → $40,507 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 539.8s (screen 11.1s, day-steps 519.7s) · screen rows 543363 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $34,346 |
| 2024-09 | $35,811 |
| 2024-10 | $37,456 |
| 2024-11 | $38,976 |
| 2024-12 | $39,473 |
| 2025-01 | $40,418 |
| 2025-02 | $38,715 |
| 2025-03 | $36,047 |
| 2025-04 | $35,673 |
| 2025-05 | $36,521 |
| 2025-06 | $37,366 |
| 2025-07 | $36,888 |
| 2025-08 | $38,325 |
| 2025-09 | $37,921 |
| 2025-10 | $39,409 |
| 2025-11 | $37,984 |
| 2025-12 | $38,952 |
| 2026-01 | $40,176 |
| 2026-02 | $40,953 |
| 2026-03 | $40,540 |
| 2026-04 | $40,598 |
| 2026-05 | $40,142 |
| 2026-06 | $40,859 |
| 2026-07 | $40,507 |

_… last 24 of 61 months shown._

### 15y — 2011-07-18 → 2026-07-16

- sessions 3771 · fills 6225 · rejected orders 0 · dividend credits 84 ($1,718)
- equity $39,000 → $38,997 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 2272.0s (screen 20.1s, day-steps 2235.6s) · screen rows 1280417 · dividend rows in force 400240

| Month | Equity |
|---|---|
| 2024-08 | $33,066 |
| 2024-09 | $34,475 |
| 2024-10 | $36,060 |
| 2024-11 | $37,523 |
| 2024-12 | $38,001 |
| 2025-01 | $38,911 |
| 2025-02 | $37,272 |
| 2025-03 | $34,703 |
| 2025-04 | $34,343 |
| 2025-05 | $35,160 |
| 2025-06 | $35,973 |
| 2025-07 | $35,513 |
| 2025-08 | $36,896 |
| 2025-09 | $36,507 |
| 2025-10 | $37,940 |
| 2025-11 | $36,568 |
| 2025-12 | $37,499 |
| 2026-01 | $38,678 |
| 2026-02 | $39,426 |
| 2026-03 | $39,029 |
| 2026-04 | $39,085 |
| 2026-05 | $38,646 |
| 2026-06 | $39,336 |
| 2026-07 | $38,997 |

_… last 24 of 181 months shown._
