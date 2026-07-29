# Turtle Breakout (ATR-stopped) (`turtle_breakout`) — historical windows

_strategy `turtle_breakout` · cadence daily · generated 2026-07-29 07:55 UTC_

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
| turtle_breakout | 2026-01-16→2026-07-16 | −10.29% | −19.68% | +32.45% | −0.52 | −0.63 | −17.21% | −10.72% | −14.99% | −20.73% | 82 |
| turtle_breakout | 2025-07-16→2026-07-16 | −15.91% | −15.92% | +29.49% | −0.44 | −0.57 | −25.94% | −11.84% | −61.27% | −37.09% | 162 |
| turtle_breakout | 2023-07-17→2026-07-16 | +0.86% | +0.29% | +27.36% | +0.15 | −0.02 | −31.17% | −11.96% | · | · | 482 |

## Equity-curve detail

### 6mo — 2026-01-16 → 2026-07-16

- sessions 124 · fills 82 · rejected orders 0 · dividend credits 0 ($0)
- equity $39,000 → $34,987 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 23.2s (screen 5.1s, day-steps 14.2s) · screen rows 85638 · dividend rows in force 1837

| Month | Equity |
|---|---|
| 2026-01 | $39,599 |
| 2026-02 | $40,874 |
| 2026-03 | $37,748 |
| 2026-04 | $38,882 |
| 2026-05 | $41,392 |
| 2026-06 | $39,189 |
| 2026-07 | $34,987 |

### 1y — 2025-07-16 → 2026-07-16

- sessions 252 · fills 162 · rejected orders 0 · dividend credits 0 ($0)
- equity $39,000 → $32,795 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 38.6s (screen 6.2s, day-steps 28.3s) · screen rows 160706 · dividend rows in force 1837

| Month | Equity |
|---|---|
| 2025-07 | $37,242 |
| 2025-08 | $36,377 |
| 2025-09 | $35,967 |
| 2025-10 | $36,640 |
| 2025-11 | $35,763 |
| 2025-12 | $36,832 |
| 2026-01 | $38,508 |
| 2026-02 | $41,186 |
| 2026-03 | $36,310 |
| 2026-04 | $36,908 |
| 2026-05 | $38,862 |
| 2026-06 | $36,854 |
| 2026-07 | $32,795 |

### 3y — 2023-07-17 → 2026-07-16

- sessions 753 · fills 482 · rejected orders 0 · dividend credits 0 ($0)
- equity $39,000 → $39,334 · Sharpe-excess computed over 100% of the window (BIL's first bar is 2007-05-30)
- replay runtime 130.7s (screen 10.0s, day-steps 114.1s) · screen rows 396728 · dividend rows in force 1837

| Month | Equity |
|---|---|
| 2024-08 | $45,776 |
| 2024-09 | $45,676 |
| 2024-10 | $48,963 |
| 2024-11 | $53,943 |
| 2024-12 | $51,163 |
| 2025-01 | $48,332 |
| 2025-02 | $43,535 |
| 2025-03 | $39,206 |
| 2025-04 | $37,280 |
| 2025-05 | $39,062 |
| 2025-06 | $42,209 |
| 2025-07 | $40,338 |
| 2025-08 | $40,498 |
| 2025-09 | $41,522 |
| 2025-10 | $43,956 |
| 2025-11 | $42,840 |
| 2025-12 | $44,189 |
| 2026-01 | $46,191 |
| 2026-02 | $49,389 |
| 2026-03 | $43,546 |
| 2026-04 | $44,261 |
| 2026-05 | $46,603 |
| 2026-06 | $44,203 |
| 2026-07 | $39,334 |

_… last 24 of 37 months shown._
