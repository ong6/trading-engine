# Charter — `ew_sector_capped`

_Pre-registration, 2026-08-20. The text below preserves the original candidate
hypothesis and gates; the dated outcome addendum records the completed decision._

Status: **completed — rejected and closed 2026-09-07** · Class: `sim/strategies/ew_sector_capped.py` ·
Sweep grid: `sector_cap` · Cadence: **monthly** (matching `ew_benchmark`).

## Outcome addendum — 2026-09-07

The four-cell, 10-fold sweep rejects this candidate under its pre-registered
drawdown gate. The best-returning cell had **+0.72% median excess**, a 90% CI of
**[-1.38%, +2.39%]**, **-0.53% mean excess**, and a **-38.82%** worst drawdown
versus EW's **-37.54%**. It therefore established neither return improvement nor
the required 5-point drawdown relief. The result also retains the disclosed
static-2026-sector look-ahead, so it cannot support promotion. No book was
registered; do not forward-test or tune this grid without point-in-time sectors
and a newly frozen hypothesis.

## LOOK-AHEAD DISCLOSURE — read before any number from this book

**This store has no point-in-time sector history.** `fundamentals` holds five
weekly snapshots, 2026-07-18 through 2026-08-14, and nothing earlier;
`farm/backtest/replay.py` copies the latest snapshot into every scratch store
and restamps it to the window's warmup start. A replay of 2014 therefore
classifies names by their **2026** sector.

That is a static look-ahead. It is the same class of compromise `low_vol`
already carries with its 2026 market-cap floor, and it is disclosed the same
way. Two things make it tolerable and neither makes it disappear:

- Sector membership is close to stationary. A name that migrated sector between
  2014 and 2026 is the exception, unlike a price or an earnings surprise where
  the future value is the whole signal.
- The alternative was to leave the rule untested. A silent non-result is worse
  than a disclosed approximation — that is the standing house position.

**Every result from this book must be quoted with this disclosure attached.**
If point-in-time sector data ever lands in the store, this book must be re-run
before any of its numbers are treated as clean.

Secondary data note: sector coverage on the live screen is **473 of 534
passers (88.6%)**. The uncovered names are mostly ETFs and recent listings.
They are pooled into a single `(unknown)` bucket that is capped like any real
sector — see "Judgment calls" below.

## Hypothesis

The screen is momentum-driven, so its top names cluster hard by sector. On the
2026-08-19 screen, **38 of the top 50 names by RS were Healthcare**. A 50-name
equal-weighted book that is three-quarters one sector is a sector bet wearing a
diversification costume, and a sector de-rating takes most of the book with it.

Forcing spread — at most `max_per_sector` names from any one sector, freed slots
backfilled from the next-ranked passers outside it — should reduce drawdown
through diversification rather than through exposure.

## What changes vs `ew_benchmark`, and only that

Exactly one thing: **which names fill the `cap` slots**. Same screen, same
`cap`, same equal weight, same monthly cadence, and — deliberately — the same
**100% gross exposure at all times**. This book never holds BIL. Keeping gross
pinned is what makes it orthogonal to `ew_gross_voltarget`; a book that drifted
to 80% invested would be testing exposure instead.

## Why this is not the `concentration` sweep

`concentration` varied the total name COUNT (`cap` 10 / 20 / 30 / 50 / 75 /
100) and left sector spread completely alone. Fifty names from one sector and
fifty names from eight are different books with identical `cap`, and nothing in
this repo has yet told them apart. Best cell there was `cap-10` at **-0.39%**
median excess; `cap-50` was the benchmark re-run and scored an exact 0.00%.

## Expectation, including the negative case

**Positive case.** Lower worst-fold drawdown than `ew_benchmark`, most visibly
in folds containing a single-sector unwind (2015-16 energy, 2021-22 tech and
biotech). Some return give-up is expected and is the honest price: the cap
forces the book to drop high-RS names for lower-RS ones, so if RS rank carries
information the book pays for spread out of it.

**Negative case, and it is a real one.** The clustering may BE the edge. If the
screen's return comes from riding whichever sector is in a momentum regime, then
capping sector exposure is capping the signal, and this book will trail
`ew_benchmark` on return without buying much drawdown relief — because a
momentum drawdown is usually a *market* drawdown, and diversifying across
sectors does not help when correlations converge to one, which is exactly when
it is needed. The tightest cells (`max_per_sector = 5`) may also fail to fill
50 slots at all in some months, leaving a smaller book that is more
name-concentrated even as it becomes less sector-concentrated. That trade should
be watched, not assumed away.

**Prior overall:** in line with every other rule tested here — the screen is the
edge and the layer subtracts. This book is worth running because the hypothesis
is mechanically distinct and cheap to test, not because it is expected to win.

## Comparison

Always against **`ew_benchmark`** on identical folds and the identical universe.
Never against SPY. Primary statistic: **median excess validate return** over the
10-fold protocol, with beat-rate and worst-fold drawdown alongside, and the
trial count quoted with every number.

## Kill criterion

Kill (do not promote; if promoted, retire) if **any** of:

1. Over the 10-fold walk-forward no cell improves worst-fold drawdown vs
   `ew_benchmark` by at least **5 percentage points**. Drawdown is the book's
   only claim.
2. Median excess vs `ew_benchmark` is below **-5%** at the best cell. That is
   below the noise floor the other four grids already occupy and would make this
   another confirmation rather than a candidate.
3. Beat rate vs `ew_benchmark` is under **40%** of folds while median excess is
   negative.
4. Any fold returns `status: "inert"`.
5. Point-in-time sector data becomes available and the result does not survive a
   re-run on it. The 2026-snapshot result is provisional by construction.

## Judgment calls, stated so they can be disagreed with

- **Unknown sector is ONE capped bucket, not a per-name exemption.** Pooling all
  unknowns as one sector is wrong; treating each as its own sector is also
  wrong. The difference is that pooling cannot be used to smuggle concentration
  back in and exempting can. This follows `low_vol`'s existing convention.
- **The book stays fully invested even when the cap cannot fill `cap` slots.**
  It equal-weights whatever it selected rather than leaking the shortfall to
  cash, so gross exposure never becomes a hidden second variable.
