# Split restatements re-audit — 2026-09-03

> **Historical snapshot.** This records the re-audit performed on 2026-09-03. See
> [`how-it-works.md`](../how-it-works.md) for current reconciler operation.

Read-only audit of every `split_adjustments` row with `outcome = 'applied'` against (a) the
2026-09-02 adjudicator rule in `engine/actions.py::_adjudicate` and (b) Yahoo's current view
(one `yf.download(period="max", auto_adjust=False)` per ticker, paced 2 s). Nothing was written
to the store. Scratch scripts: `scratchpad/reaudit/{reaudit,scale,recon}.py` (session scratchpad).

**Count:** 29 applied rows, not 31. The BUILDLOG's "applied 31" predates the two JEM rows that
now read `superseded_by_refetch` (JEM 2026-04-13 and 2026-07-14). Other watermarks: 4
`reverted_false_break` (BH, ORCL, NEM, HWKN).

## Headline

**18 of the 29 applied restatements are false — the same defect class as BH/ORCL/NEM/HWKN, one
mechanism.** For every historical split Yahoo serves a split-adjusted, continuous series *except
for the zero-volume bars from the ex-date up to the first traded post-split session*, which sit
on the old scale. Example, TRST 2:1 ex 1986-07-22 (Yahoo close, volume):

```
1986-07-21  11.1671  vol 0
1986-07-22  22.3341  vol 0      <- ex-date, bogus bar on the pre-split scale
1986-07-23  11.4584  vol 257    <- first trade after the split
```

The old ±20% adjudicator saw the drop from the bogus ex-date bar to the first real bar as "the
break" and divided every earlier (already-adjusted) row by the ratio. The store is now on the
wrong scale for the whole pre-break history of these 16 tickers (17 rows; CHCO twice, so its
pre-1987 history is divided by 2.25). The 30-session median check in `repair_restatements.py
--yahoo` reads `before = 1/ratio, after = 1.0` for these names, which is exactly what a
false restatement looks like, so the BUILDLOG's reading of GRC, ERIC, BRO, ODC, TRST, INDB and
UBSI as "Yahoo itself discontinuous" was wrong: Yahoo is discontinuous only for the 1–6 zero-volume
ex-date bars. Verified bar-by-bar for all 17 rows (store, store with the restatement undone, and
Yahoo agree to 4 dp before the ex-date once the restatement is undone).

The 18th (ISSC) has no Yahoo history left to compare (Yahoo returns 16 rows from 2026-07-17), but
the store's internal evidence is the BH pattern: the series is continuous through the ex-date
(2005-07-08, 23.10 -> 23.17 on the undone series) and the "break" 9 sessions later is a −21% day
on 6x volume (23.02 -> 18.20, observed 1.265, inside the old ln 1.2 band, outside the new ln 1.08).

**The new rule would apply none of the 29** when re-run on the pre-restatement series (rebuilt in
memory by undoing each restatement, replayed in ex-date order). Every historical row was bulk-loaded
2026-07-16, i.e. `fetched_at >= ex_date`, so rule 3 returns `skipped_already_adjusted`; the rest
fall to `skipped_sanity` (observed jump outside ±8%) or `skipped_no_break_near_ex` (TJGC, break 6
sessions after ex). That includes the 9 rows that are correct today (BKLC, CLBK, CCHH, EDBL, FTFT,
YHC, IREZ, LMFA, SNEX): those were fixed by Yahoo's later re-serve rather than by the adjudicator,
and rule 3 would have left the break in place. Not a defect of the new rule (it never guesses), but
recent-split handling now depends on the nightly re-fetch, not on the adjudicator.

Two latent single-bar false positives of the new rule on the *current* series (protected only by
the existing `applied` watermark; the nightly never re-adjudicates a watermarked split):
SNEX 2026-07-14 (store 50.33 = Yahoo 75.49 / 1.5, a bar fetched on the ex-date evening, already
adjusted, then divided) and WLFC 2026-07-15 (store 22.99 = Yahoo-at-the-time 68.99 / 3). Both
match `applied_pending` with a ratio-sized one-bar dip inside the near-ex window. A 5d re-fetch
will not reach them; they need a targeted re-fetch or a one-row fix.

## Table

Ratio: `1:N` = reverse split (`ratio` = 1/N). "New rule" is `_adjudicate` on the pre-restatement
series. Store/Yahoo = median(store close / Yahoo close) over 30 sessions before / after
`break_date`. "Rows off" = |store/yahoo − 1| > 1% over the full common history.

| Ticker | Ex | Ratio | Break | New rule (on pre-restatement series) | Store/Yahoo before | after | Rows >1% off / total | Yahoo across break | Flag |
|---|---|---|---|---|---|---|---|---|---|
| ASTH | 2015-04-27 | 1:10 | 2015-04-29 | skipped_sanity | 10.000 | 1.000 | 1544/4398 | continuous | WRONG |
| AYA | 2018-03-02 | 1:4 | 2018-03-07 | skipped_already_adjusted | 4.000 | 1.000 | 1980/4115 | continuous | WRONG |
| BKLC | 2026-07-20 | 3 | 2026-07-15 | skipped_already_adjusted | 1.000 | 1.000 | 0/1606 | continuous | OK |
| BRO | 1983-03-24 | 1.5 | 1983-03-25 | skipped_already_adjusted | 0.667 | 1.000 | 536/11482 | continuous | WRONG |
| CCHH | 2026-07-13 | 1:10 | 2026-07-13 | skipped_already_adjusted | 1.000 | 1.000 | 0/61 | continuous | OK |
| CHCO | 1987-10-02 | 1.5 | 1987-10-05 | skipped_already_adjusted | 0.444 | 0.667 | 387/9871 | continuous | WRONG |
| CHCO | 1989-01-03 | 1.5 | 1989-01-06 | skipped_already_adjusted | 0.667 | 1.000 | 387/9871 | continuous | WRONG |
| CLBK | 2026-07-21 | 2.2 | 2026-07-16 | skipped_already_adjusted | 1.000 | 1.000 | 0/2103 | continuous | OK |
| CTO | 1992-08-18 | 2 | 1992-08-19 | skipped_already_adjusted | 0.500 | 1.000 | 3142/11711 | continuous | WRONG |
| EDBL | 2026-07-13 | 1:45 | 2026-07-13 | skipped_already_adjusted | 1.000 | 1.000 | 0/61 | continuous | OK |
| ERIC | 1982-10-07 | 1.5 | 1982-10-12 | skipped_already_adjusted | 0.667 | 1.000 | 287/11348 | continuous | WRONG |
| FTFT | 2026-07-13 | 1:4 | 2026-07-13 | skipped_sanity | 1.000 | 1.000 | 0/61 | continuous | OK |
| GRC | 1981-05-06 | 1.5 | 1981-05-07 | skipped_already_adjusted | 0.667 | 1.000 | 288/11710 | continuous | WRONG |
| INDB | 1987-10-01 | 1.5 | 1987-10-07 | skipped_already_adjusted | 0.667 | 1.000 | 354/10153 | continuous | WRONG |
| IPAR | 1990-08-03 | 0.4 (2:5) | 1990-08-08 | skipped_sanity | 2.500 | 1.000 | 634/9716 | continuous | WRONG |
| IREZ | 2026-07-21 | 1:3 | 2026-07-16 | skipped_sanity | 1.000 | 1.000 | 0/155 | continuous | OK |
| ISSC | 2005-07-08 | 1.5 | 2005-07-21 | noop_restated | n/a | 1.000 | 0/15 | no history (16 rows) | WRONG (internal evidence) |
| LMFA | 2026-07-13 | 1:25 | 2026-07-13 | skipped_sanity | n/a | n/a | n/a | no history (7 rows) | OK (store continuous, unverified) |
| ODC | 1983-07-28 | 2 | 1983-08-03 | skipped_already_adjusted | 0.500 | 1.000 | 853/11708 | continuous | WRONG |
| OPAD | 2026-06-09 | 1:10 | 2026-06-05 | skipped_sanity | 10.000 | 1.000 | 34/61 | unadjusted; Yahoo's own break is 06-05 | AMBIGUOUS (store continuous) |
| SKE | 2017-10-20 | 1:10 | 2017-10-25 | skipped_already_adjusted | 10.000 | 1.000 | 3959/6183 | continuous | WRONG |
| SNEX | 2026-07-20 | 1.5 | 2026-07-17 | skipped_already_adjusted | 1.000 | 1.000 | 1/7926 | continuous | OK (1 bad bar 2026-07-14) |
| TECX | 2024-06-21 | 1:12 | 2024-06-24 | skipped_already_adjusted | 12.000 | 1.000 | 1510/2060 | continuous | WRONG |
| TJGC | 2026-05-26 | 1:3 | 2026-06-03 | skipped_no_break_near_ex | 3.000 | 1.000 | 32/61 | continuous | WRONG |
| TMP | 1989-06-02 | 1.5 | 1989-06-05 | skipped_already_adjusted | 0.667 | 1.000 | 761/10141 | continuous | WRONG |
| TRST | 1986-07-22 | 2 | 1986-07-23 | skipped_already_adjusted | 0.500 | 1.000 | 823/10928 | continuous | WRONG |
| UBSI | 1988-02-16 | 2 | 1988-02-17 | skipped_already_adjusted | 0.500 | 1.000 | 178/9886 | continuous | WRONG |
| WLFC | 2026-07-21 | 3 | 2026-07-20 | skipped_already_adjusted | 0.333 | 1.000 | 7504/7536 | unadjusted (break at 07-20) | AMBIGUOUS (store continuous, 1 bad bar 07-15) |
| YHC | 2026-07-13 | 1:100 | 2026-07-13 | skipped_already_adjusted | 1.000 | 1.000 | 0/61 | continuous | OK |

Notes per flag:

- **WRONG (17 rows + ISSC).** Yahoo is continuous across the break by a 10-session median on each
  side (skipping the two sessions nearest the ex/break); the store's pre-break rows are at
  1/ratio of Yahoo. CHCO "before" reads 0.444 because both false restatements stack. TJGC is the
  same pattern with a six-session run of zero-volume old-scale bars (05-26..06-02).
- **AMBIGUOUS (2).** Yahoo currently serves WLFC and OPAD *unadjusted* before their break dates
  (WLFC 216.98 vs store 72.33 on 07-14; OPAD 0.74 vs store 7.40 on 06-04), and Yahoo's own scale
  break sits one to two sessions before Yahoo's split date. The store is continuous on the
  post-split scale, so the restatement itself looks right; do not revert. WLFC's 07-15 bar
  (22.99, should be 68.99) is a Yahoo flip-flop divided a second time.
- **OK (9).** Store = Yahoo over the full history. The July-13 batch (CCHH, EDBL, FTFT, YHC, LMFA)
  and BKLC/CLBK/IREZ were bulk-loaded half-adjusted on 07-16 and Yahoo has since re-served them on
  one scale; the restatement matches. SNEX is on one scale except the single 07-14 bar.

## Books exposure

Of the WRONG/AMBIGUOUS names only two have ever traded:

- **AYA** (WRONG): 3 fills, all 2026-09-01 buys at 26.60, and 3 open positions (`ew_benchmark`,
  `ew_trend_gated`, `ew_voltarget`, qty 25–29). Fills are post-break, so a revert does not change
  fill prices; `repair_restatements.py` will still rebuild the books because fills exist.
- **ODC** (WRONG): 4 fills (`mr_overlay`, `mr_overlay_gated`; buy 2026-07-20, sell 2026-07-22),
  no open position. Post-break; books rebuild only.

No fills or positions for the other 14 WRONG tickers, ISSC, WLFC or OPAD. Backtest exposure is
larger than book exposure: pre-break history for these 16 names (roughly 15k rows) is on the wrong
scale, though only TJGC (2026), TECX (2024), AYA (2018) and SKE (2017) fall inside the 2014+
walk-forward windows the BUILDLOG cares about; the rest predate 1993.

## Proposed reverts (NOT run)

Each inverts exactly one restatement (`date < break_date`: prices × ratio, volume ÷ ratio),
flips the watermark to `reverted_false_break`, appends an `audit_log` row. Dry-run first (drop
`--apply`), then on a copy (`--db`), then live. Not while the nightly or a queue job is running.
Ratios must match the watermark to 1e-9, hence the long fractions.

```
.venv/bin/python engine/repair_restatements.py --target ASTH:2015-04-29:0.1 --yahoo
.venv/bin/python engine/repair_restatements.py --target AYA:2018-03-07:0.25 --yahoo
.venv/bin/python engine/repair_restatements.py --target BRO:1983-03-25:1.5 --yahoo
.venv/bin/python engine/repair_restatements.py --target CHCO:1989-01-06:1.5 --target CHCO:1987-10-05:1.5 --yahoo
.venv/bin/python engine/repair_restatements.py --target CTO:1992-08-19:2.0 --yahoo
.venv/bin/python engine/repair_restatements.py --target ERIC:1982-10-12:1.5 --yahoo
.venv/bin/python engine/repair_restatements.py --target GRC:1981-05-07:1.5 --yahoo
.venv/bin/python engine/repair_restatements.py --target INDB:1987-10-07:1.5 --yahoo
.venv/bin/python engine/repair_restatements.py --target IPAR:1990-08-08:0.4 --yahoo
.venv/bin/python engine/repair_restatements.py --target ODC:1983-08-03:2.0 --yahoo
.venv/bin/python engine/repair_restatements.py --target SKE:2017-10-25:0.1 --yahoo
.venv/bin/python engine/repair_restatements.py --target TECX:2024-06-24:0.08333333333333333 --yahoo
.venv/bin/python engine/repair_restatements.py --target TJGC:2026-06-03:0.3333333333333333 --yahoo
.venv/bin/python engine/repair_restatements.py --target TMP:1989-06-05:1.5 --yahoo
.venv/bin/python engine/repair_restatements.py --target TRST:1986-07-23:2.0 --yahoo
.venv/bin/python engine/repair_restatements.py --target UBSI:1988-02-17:2.0 --yahoo
.venv/bin/python engine/repair_restatements.py --target ISSC:2005-07-21:1.5            # no Yahoo history; --yahoo would report n/a
```

Add `--apply` to write. The two CHCO targets commute (both multiply disjoint-or-nested prefixes),
so order does not matter. Caveats:

1. The revert restores the zero-volume ex-date bars to their old-scale Yahoo values (e.g. TRST
   1986-07-22 back to 22.33), so a one-to-six-bar spike remains in the store, as it does in Yahoo.
   The tripwire (`TRIPWIRE_MOVE` 0.40) will see these as unexplained moves only if it scans that
   far back. A follow-up could null the close on zero-volume bars whose neighbours agree.
2. `--yahoo` after the revert should read before ≈ 1.000, after ≈ 1.000, rows off ≈ 0 for all
   16 Yahoo-backed names; the audit-log `reason` string still says "ordinary price move inside
   the old ±20% tolerance", which is inexact here (it was a bogus ex-date bar). Cosmetic.
3. WLFC 2026-07-15 and SNEX 2026-07-14 are single-bar fixes, not restatement reverts: re-fetch
   those dates (or set close/open/high/low × 3 and × 1.5 respectively) and leave the watermarks.

## Method

- `_adjudicate` imported from `engine/actions.py` and run against an in-memory DuckDB holding
  one ticker's `(ticker, date, close, fetched_at)` with each applied restatement undone
  (`close × ratio for date < break_date`, newest first), then replayed in ex-date order so the
  second CHCO split saw the first one applied, as the reconciler did.
- Yahoo: `yfinance 
  .download(tk, period="max", auto_adjust=False, threads=False, timeout=30)`, 2 s between names.
  Yahoo returned no usable history for ISSC (16 rows since 2026-07-17) and LMFA (7 rows).
- Yahoo continuity: median Yahoo close over 10 sessions ending 2 before `min(ex, break)` vs 10
  sessions starting 2 after `max(ex, break)`; within ±25% (log) of 1 = continuous, of the ratio =
  unadjusted. Single-bar `prev/cur` at the break is what misleads: it reads ≈ ratio for all 17
  WRONG names because of the bogus ex-date bar.
